"""Offline native factory tests; request fixtures track the provider's API v2 contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kobotoolbox_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-kobo-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/kobotoolbox/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="kobo-test", node_type="automation-kobotoolbox", node_data={
        "config": config, "credentials": {"credential_type": "kobotoolbox_api_token", "api_token": TOKEN, **credential},
    })


def transport(monkeypatch, status, response=None, **headers):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, **({"json": response} if response is not None else {}), headers=headers)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_one_request_per_operation_exact_wire_contract(monkeypatch, case):
    requests = transport(monkeypatch, case.get("status", 200), case.get("response"))
    out = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "kf.kobotoolbox.org"
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert dict(request.url.params) == case.get("params", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    if case.get("status") == 204:
        assert out["deleted"] and out["http_status"] == 204
    else:
        assert out["data"] == case["response"]
    if case["config"]["operation"] == "list_projects":
        assert out["next_start"] == 101 and out["items"][0]["name"] == "Field survey"
    assert TOKEN not in str(out)


@pytest.mark.asyncio
async def test_eu_identity_and_redaction(monkeypatch):
    requests = transport(monkeypatch, 200, {"username": "field-team", "echo": TOKEN, "token": TOKEN})
    out = await node({"operation": "get_account"}, server="https://eu.kobotoolbox.org").execute({})
    assert requests[0].url.host == "eu.kobotoolbox.org"
    assert out["data"] == {"username": "field-team", "echo": "[redacted]"}
    assert native.KobotoolboxNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_and_redirects_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, status, {"detail": "Invalid token."}, Location="https://example.org/")
    out = await node({"operation": "get_account"}).execute({})
    assert out == {"status": "error", "http_status": status, "error": "Invalid token."}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unexpected_json_and_list_shape_fail(monkeypatch):
    transport(monkeypatch, 200, {"detail": "Not a results page"})
    with pytest.raises(ValueError, match="results page"):
        await node({"operation": "list_projects"}).execute({})
    transport(monkeypatch, 200, {"errors": ["bad"]})
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project_id": "../me"},
    {"operation": "get_submission", "project_id": "a123", "submission_id": "1/other"},
    {"operation": "list_projects", "limit": 0},
    {"operation": "set_deployment_active", "project_id": "a123"},
    {"operation": "set_validation_status", "project_id": "a123", "submission_id": "123", "validation_status": "invented"},
])
def test_required_fields_and_path_boundaries(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_credential_defaults_and_server_boundary():
    cred = native.KobotoolboxAPITokenCredential(api_token=TOKEN)
    assert cred.credential_type == "kobotoolbox_api_token"
    for server in ["https://evil.example.org", "https://kf.kobotoolbox.org.evil.org", "http://kf.kobotoolbox.org"]:
        with pytest.raises(ValidationError):
            native.KobotoolboxAPITokenCredential(api_token=TOKEN, server=server)
    assert set(native.ROUTES) == {case["config"]["operation"] for case in CASES}


SUBMISSION = json.loads((Path(__file__).parent / "fixtures/kobotoolbox/submission_created.json").read_text())["body"]
TRIGGER = {"operation": "on_new_submission", "project_id": "a4etXeWtqcoodSxLV8a6Uq"}


@pytest.mark.asyncio
async def test_rest_service_registration_and_cleanup(monkeypatch):
    credential = {"api_token": TOKEN, "server": "https://eu.kobotoolbox.org"}
    requests = transport(monkeypatch, 201, {"uid": "hZzzeedWxQoFHgibsTCysv"})
    registered = await native.KobotoolboxNode._register_external_webhook(
        webhook_url="https://test.hooks.example.test/hook", credential=credential, config=TRIGGER, node_id="test")
    assert registered == {"external_webhook_id": TRIGGER["project_id"] + ":hZzzeedWxQoFHgibsTCysv"}
    assert requests[0].method == "POST"
    assert requests[0].url == "https://eu.kobotoolbox.org/api/v2/assets/a4etXeWtqcoodSxLV8a6Uq/hooks/"
    assert json.loads(requests[0].content) == {
        "name": "NoClick test", "endpoint": "https://test.hooks.example.test/hook", "active": True,
        "export_type": "json", "auth_level": "no_auth", "email_notification": False,
    }
    assert requests[0].headers["Authorization"] == "Token " + TOKEN
    requests = transport(monkeypatch, 204)
    await native.KobotoolboxNode._unregister_external_webhook(
        credential=credential, config={**TRIGGER, **registered, "project_id": "aDifferentProject"}, node_id="test")
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/api/v2/assets/a4etXeWtqcoodSxLV8a6Uq/hooks/hZzzeedWxQoFHgibsTCysv/"
    assert native.KobotoolboxNode.registration_fingerprint_fields(TRIGGER) == {"project_id": TRIGGER["project_id"]}
    config = native.OnNewSubmission(**TRIGGER, **registered)
    assert config.model_dump()["external_webhook_id"] == registered["external_webhook_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_registration_rejection_raises_without_token(monkeypatch, status):
    transport(monkeypatch, status, {"detail": TOKEN})
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await native.KobotoolboxNode._register_external_webhook(
            webhook_url="https://test.hooks.example.test/hook", credential={"api_token": TOKEN}, config=TRIGGER, node_id="test")
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_documented_submission_delivery_and_manual_run():
    cls = native.KobotoolboxNode
    assert cls.verify_webhook_signature(json.dumps(SUBMISSION).encode(), {}, TRIGGER)
    assert cls.filter_trigger_payload(SUBMISSION, TRIGGER)
    assert not cls.filter_trigger_payload({"detail": "Not found"}, TRIGGER)
    payload = {**SUBMISSION, "_webhook": {"headers": {"test": "transport-only"}}}
    output = cls.resolve_trigger_payload(payload, TRIGGER)
    assert output["data"] == SUBMISSION
    assert output["project_id"] == TRIGGER["project_id"]
    event = cls.resolve_agent_event(output)
    assert "94571949" in event["text"]
    assert "An anonymous respondent" in event["text"]
    assert "submit_an_image" in event["text"] and "image-8_58_16.jpg" in event["text"]
    assert "set_validation_status" in event["text"] and TRIGGER["project_id"] in event["text"]
    assert event["conversation_key"] == TRIGGER["project_id"] + ":94571949"
    assert "transport-only" not in event["text"]
    trigger = node(dict(TRIGGER))
    assert (await trigger.execute({"other_step": {"secret": "do not copy"}}))["status"] == "no_event"
    trigger.node_data["config"]["_triggerPayload"] = payload
    assert await trigger.execute({}) == output


@pytest.mark.asyncio
async def test_cleanup_already_removed_is_idempotent_and_uid_required(monkeypatch):
    transport(monkeypatch, 404, {"detail": "Not found."})
    await native.KobotoolboxNode._unregister_external_webhook(
        credential={"api_token": TOKEN}, config={**TRIGGER, "external_webhook_id": TRIGGER["project_id"] + ":h123"}, node_id="test")
    transport(monkeypatch, 201, {})
    with pytest.raises(ValueError, match="REST service UID"):
        await native.KobotoolboxNode._register_external_webhook(
            webhook_url="https://test.hooks.example.test/hook", credential={"api_token": TOKEN}, config=TRIGGER, node_id="test")

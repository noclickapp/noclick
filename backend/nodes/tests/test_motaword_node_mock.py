"""Request mapping and callback lifecycle against MotaWord's published contract."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.motaword_node import MotaWordNode, MotaWordAccessTokenCredential, MotaWordNodeConfig, ROUTES
from nodes.core.binary_output import BinaryOutput

CREDENTIAL = {"credential_type": "motaword_access_token", "access_token": "test-access"}


def node(config):
    return MotaWordNode(node_id="motaword-test", node_type="automation-motaword", node_data={},
        config=MotaWordNode.parse_config({"config": config, "credentials": CREDENTIAL}),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


CASES = [
    ("get_account", {}, "GET", "/me", None),
    ("list_languages", {}, "GET", "/languages", None),
    ("list_formats", {}, "GET", "/formats", None),
    ("list_projects", {"page": 2, "status": "completed"}, "GET", "/projects", None),
    ("get_project", {"project_id": 74}, "GET", "/projects/74", None),
    ("create_project", {"source_language": "en", "target_languages": ["fr"], "custom": {"order": "123"}}, "POST", "/projects", {"source_language": "en", "target_languages": ["fr"], "custom": {"order": "123"}}),
    ("update_project", {"project_id": 74, "notes": "Keep product names"}, "PUT", "/projects/74", {"notes": "Keep product names"}),
    ("launch_project", {"project_id": 74, "payment_method": "app", "card_id": 5}, "POST", "/projects/74/launch", {"payment_method": "app", "card_id": 5}),
    ("cancel_project", {"project_id": 74, "reason": "Duplicate"}, "POST", "/projects/74/cancel", {"reason": "Duplicate"}),
    ("get_progress", {"project_id": 74}, "GET", "/projects/74/progress", None),
    ("get_invoice", {"project_id": 74}, "GET", "/projects/74/invoice", None),
    ("list_documents", {"search": "contract"}, "GET", "/documents", None),
    ("get_document", {"document_id": "d/1"}, "GET", "/documents/d%2F1", None),
    ("list_project_documents", {"project_id": 74}, "GET", "/projects/74/documents", None),
    ("add_linked_document", {"project_id": 74, "source": "dropbox", "url": "https://example.com/source.docx", "name": "source.docx"}, "POST", "/projects/74/documents", {"source-links[]": [{"source": "dropbox", "url": "https://example.com/source.docx", "name": "source.docx"}]}),
    ("list_project_glossaries", {"project_id": 74}, "GET", "/projects/74/glossaries", None),
    ("list_project_style_guides", {"project_id": 74}, "GET", "/projects/74/styleguides", None),
    ("list_activities", {"project_id": 74}, "GET", "/projects/74/activities", None),
    ("add_activity", {"project_id": 74, "info": "Keep product names"}, "POST", "/projects/74/activities", {"info": "Keep product names"}),
    ("list_project_strings", {"project_id": 74}, "GET", "/projects/74/strings", None),
    ("package_translations", {"project_id": 74}, "POST", "/projects/74/package", None),
    ("check_package", {"project_id": 74, "key": "pack-1"}, "GET", "/projects/74/package/check", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,config,method,path,body", CASES)
async def test_motaword_requests(name, config, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.motaword.com" + path).mock(return_value=
            httpx.Response(200, content=b"translated file", headers={"content-type": "application/octet-stream"}) if name == "package_translations" else httpx.Response(200, json={"id": 74}))
        result = await node({"operation": name, **config}).execute({})
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-access"
    if name == "package_translations":
        assert isinstance(result["data"], BinaryOutput)
        assert result["data"].data == b"translated file"
        assert request.url.params["async"] == "0"
    else:
        assert result["data"] == {"id": 74}
    if body is not None:
        assert json.loads(request.content) == body
    if name == "list_projects":
        assert request.url.params["status[]"] == "completed"
        assert request.url.params["page"] == "2"
    if name == "list_documents":
        assert request.url.params["order_by"] == "updated_at"
    if name == "check_package":
        assert request.url.params["key"] == "pack-1"


def test_motaword_routes_all_exercised_and_manual_credential():
    assert set(ROUTES) == {c[0] for c in CASES}
    credential = MotaWordAccessTokenCredential(access_token="  actual-token  ")
    assert credential.credential_type == "motaword_access_token"
    assert credential.access_token == "actual-token"
    for bad in ["Bearer token", "https://example.com/key", "<token>", ""]:
        with pytest.raises((ValidationError, ValueError)):
            MotaWordAccessTokenCredential(access_token=bad)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Token expired"}), (302, {}), (200, None)])
async def test_motaword_errors_and_redirects(status, body):
    with respx.mock:
        respx.get("https://api.motaword.com/me").mock(return_value=httpx.Response(status, json=body) if body is not None else httpx.Response(status, text="not JSON"))
        with pytest.raises(ValueError, match="MotaWord"):
            await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_motaword_callback_lifecycle_and_ownership(monkeypatch):
    request = AsyncMock(side_effect=[{}, {"callback_url": "https://test.hooks.example.test/hook"}])
    monkeypatch.setattr(MotaWordNode, "_request", request)
    config = {"operation": "on_project_status", "project_id": 74, "webhook_url": "https://test.hooks.example.test/hook"}
    result = await MotaWordNode._register_external_webhook(webhook_url=config["webhook_url"], credential=CREDENTIAL, config=config, node_id="n")
    assert result == {"external_webhook_id": "74"}
    assert request.call_args.kwargs["body"] == {"callback_url": config["webhook_url"]}
    request.reset_mock(side_effect=True)
    request.side_effect = [{"callback_url": "https://other.example/hook"}]
    with pytest.raises(ValueError, match="different callback"):
        await MotaWordNode._register_external_webhook(webhook_url=config["webhook_url"], credential=CREDENTIAL, config=config, node_id="n")
    assert request.call_count == 1
    request.reset_mock(side_effect=True)
    request.side_effect = [{"callback_url": config["webhook_url"]}, {}]
    config.update(result)
    await MotaWordNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="n")
    assert request.call_args.args[1:3] == ("DELETE", "/projects/74/webhooks")
    request.reset_mock(side_effect=True)
    request.side_effect = [{"callback_url": "https://other.example/hook"}]
    await MotaWordNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="n")
    assert request.call_count == 1


@pytest.mark.parametrize("action", ["translated", "proofread", "completed"])
def test_motaword_documented_event(action):
    example = json.loads((Path(__file__).parent / "fixtures/motaword/project-translated.json").read_text())
    payload = example["body"]
    # The provider's action table documents all three values for this payload.
    payload["action"] = action
    assert MotaWordNode.filter_trigger_payload(payload, {"project_id": 1})
    assert not MotaWordNode.filter_trigger_payload(payload, {"project_id": 2})
    event = MotaWordNode.resolve_agent_event(payload)
    assert f"project 1 {action}" in event["text"]
    assert event["conversation_key"] == "1"
    assert "project_id=1" in event["text"]
    assert MotaWordNode.verify_webhook_signature(json.dumps(payload).encode(), {}, {})


@pytest.mark.asyncio
async def test_motaword_manual_trigger_has_no_event():
    result = await node({"operation": "on_project_status", "project_id": 1}).execute({})
    assert result["status"] == "no_event"

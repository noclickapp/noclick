"""Pipeless published examples exercised through the native node factory."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import pipeless_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/pipeless/contract.json").read_text()
)
TOKEN = "pipeless-unit-secret-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(
        node_id="pipeless-test",
        node_type="automation-pipeless",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "pipeless_api_key",
                "app_id": "123",
                "api_key": TOKEN,
                **credential,
            },
        },
    )


def transport(monkeypatch, status, payload):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, json=payload, headers={"Location": "https://example.test"}
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_request_and_response_examples(monkeypatch, operation):
    example = EXAMPLES[operation]
    status = 202 if example["method"] in ("POST", "DELETE") else 200
    body = example["response"] if example["response"] is not None else {}
    requests = transport(monkeypatch, status, body)
    result = await node(example["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.host == "api.pipeless.io"
    assert request.url.path == example["path"].replace("{app_id}", "123")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    # JSON on GET is intentional, matching the published provider contract.
    assert json.loads(request.content) == {
        k: v for k, v in example["config"].items() if k != "operation"
    }
    if status == 202:
        assert result["accepted"] is True and result["completed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_no_redirect_or_retry_and_secret_redacted(
    monkeypatch, status
):
    requests = transport(monkeypatch, status, {"errors": ["Rejected " + TOKEN]})
    result = await node({"operation": "get_recent_events"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and "Rejected" in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_contains_recognizable_app_events(monkeypatch):
    body = EXAMPLES["get_recent_events"]["response"]
    transport(monkeypatch, 200, body)
    result = await node({"operation": "get_recent_events"}).execute({})
    assert result["items"][0]["name"] == "Tim interestedIn photography"
    transport(monkeypatch, 200, [])
    assert (await node({"operation": "get_recent_events"}).execute({}))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, [1], [{"event": None}], {"errors": ["not accepted"]}]
)
async def test_malformed_or_error_evidence_never_proves_connection(
    monkeypatch, payload
):
    transport(monkeypatch, 200, payload)
    try:
        result = await node({"operation": "get_recent_events"}).execute({})
    except ValueError:
        return
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "changes",
    [
        {"app_id": "../other"},
        {"app_id": "https://pipeless.io/apps/123"},
        {"api_key": "Bearer pasted"},
        {"api_key": "https://example.test"},
    ],
)
def test_credential_shape_refuses_url_and_header_injection(changes):
    with pytest.raises(ValidationError):
        native.PipelessAPIKeyCredential(
            app_id=changes.get("app_id", "123"), api_key=changes.get("api_key", TOKEN)
        )


def test_manual_credential_defaults_type_and_requires_both_person_fields():
    credential = native.PipelessAPIKeyCredential(app_id="123", api_key=TOKEN)
    assert credential.credential_type == "pipeless_api_key"
    for missing in ("app_id", "api_key"):
        with pytest.raises(ValidationError):
            native.PipelessAPIKeyCredential.model_validate(
                {k: v for k, v in credential.model_dump().items() if k != missing}
            )


@pytest.mark.asyncio
async def test_batch_limit_rejected_before_network(monkeypatch):
    calls = transport(monkeypatch, 202, {})
    event = EXAMPLES["create_event"]["config"]["event"]
    with pytest.raises(ValueError, match="1 and 10"):
        await node(
            {"operation": "create_events_batch", "events": [event] * 11}
        ).execute({})
    assert calls == []


def test_nested_required_fields_enums_and_ids_validated():
    for value in [
        {"id": "x"},
        {"id": "", "type": "user"},
        {"id": "x", "type": "invented"},
    ]:
        with pytest.raises(ValueError):
            node({"operation": "get_object", "object": value})


@pytest.mark.asyncio
async def test_saved_workflow_metadata_is_not_sent_to_provider(monkeypatch):
    calls = transport(monkeypatch, 200, [])
    result = await node(
        {
            "operation": "get_recent_events",
            "credentialIds": {"pipeless_api_key": "saved-id"},
            "label": "Read app activity",
        }
    ).execute({})
    assert result["status"] == "success"
    assert json.loads(calls[0].content) == {}

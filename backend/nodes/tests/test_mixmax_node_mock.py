"""HTTP-boundary tests for Mixmax's published v1 contract."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import mixmax_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mixmax-test", node_type="automation-mixmax",
        node_data={"config": config, "credentials": {"credential_type": "mixmax_api_token", "api_token": "synthetic-mixmax-token"}})


def mock(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={} if body is None else body) if status != 204 else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_routes_and_auth(monkeypatch, operation):
    routes = json.loads((Path(__file__).parent / "fixtures/mixmax/routes.json").read_text())
    cfg = {"operation": operation}
    if "{id}" in routes[operation][1]:
        cfg["id"] = "a1CmUkqZJ8nuyj8qr"
    if operation == "add_sequence_recipients":
        cfg["recipients"] = [{"email": "alice@example.com", "scheduledAt": False}]
    if operation == "cancel_sequence_recipients":
        cfg["emails"] = ["alice@example.com"]
    if operation in {"add_unsubscribe", "remove_unsubscribe"}:
        cfg["email"] = "alice@example.com"
    if operation == "update_sequence_folder":
        cfg["name"] = "Outbound 2026"
    requests = mock(monkeypatch, body={"_id": "6392065b944b186e1b84a82c"} if operation == "get_current_user" else {})
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    req = requests[0]
    assert req.method == routes[operation][0]
    assert req.url.path == routes[operation][1].replace("{id}", "a1CmUkqZJ8nuyj8qr")
    assert req.url.host == "api.mixmax.com"
    assert req.headers["X-API-Token"] == "synthetic-mixmax-token"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_message_body_and_cursor_preserved(monkeypatch):
    requests = mock(monkeypatch, body={"_id": "draft"})
    await node({"operation": "create_draft", "to": [{"email": "alice@example.com"}],
        "subject": "Quarterly review", "body": "<p>Hello</p>", "trackingEnabled": False}).execute({})
    assert json.loads(requests[0].content) == {"to": [{"email": "alice@example.com"}],
        "subject": "Quarterly review", "body": "<p>Hello</p>", "trackingEnabled": False}
    page = {"results": [], "hasNext": True, "next": "cursor+/"}
    requests = mock(monkeypatch, body=page)
    result = await node({"operation": "list_messages", "next": "cursor+/", "limit": 12}).execute({})
    assert result["data"] == page
    assert dict(requests[0].url.params) == {"next": "cursor+/", "limit": "12"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204])
async def test_acknowledgements_do_not_claim_delivery(monkeypatch, status):
    mock(monkeypatch, status=status)
    result = await node({"operation": "send_draft", "id": "draft"}).execute({})
    assert result["http_status"] == status
    assert "delivered" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_http_failures_do_not_echo_secret(monkeypatch, status):
    mock(monkeypatch, status=status, body={"message": "synthetic-mixmax-token"})
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert "synthetic-mixmax-token" not in str(exc.value)


def test_manual_credential_defaults_and_unsafe_ids():
    assert native.MixmaxAPITokenCredential(api_token="valid-token").credential_type == "mixmax_api_token"
    with pytest.raises(ValidationError):
        native.MixmaxGetMessageConfig(id="../users/me")
    with pytest.raises(ValidationError):
        native.MixmaxCancelSequenceRecipientsConfig(id="sequence", emails=[])


@pytest.mark.asyncio
async def test_identity_requires_documented_user_id(monkeypatch):
    mock(monkeypatch, body={})
    with pytest.raises(ValueError, match="authenticated user ID"):
        await node({"operation": "get_current_user"}).execute({})
    assert native.MixmaxNode.connection_evidence.identity_keys == ("_id",)

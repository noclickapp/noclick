"""Classic v2 contract examples exercised through the real node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import mailerlite_classic_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/mailerlite-classic"
ROUTES = json.loads((FIXTURES / "operations.json").read_text())
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
TOKEN = "test-mailerlite-classic-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}


def node(config, creds=None):
    return NodeFactory.create_node(node_id="classic-test", node_type="automation-mailerlite-classic",
        node_data={"config": config, "credentials": credential() if creds is None else creds})


def mock_http(monkeypatch, body=None, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config(operation):
    result = {"operation": operation}
    if "{identifier}" in ROUTES[operation]["path"]:
        result["identifier"] = "demo+tag@mailerlite.com"
    if "{subscriber_identifier}" in ROUTES[operation]["path"]:
        result["subscriber_identifier"] = "demo+tag@mailerlite.com"
    if "{id}" in ROUTES[operation]["path"]:
        result["id"] = 3640549
    if operation in {"create_subscriber", "add_group_subscriber"}:
        result.update(email="demo@mailerlite.com", fields={"company": "MailerLite"})
    if operation in {"create_group", "rename_group", "update_subscriber"}:
        result["name"] = "Demo Group"
    if operation in {"create_field", "update_field"}:
        result["title"] = "Favourite Color"
    if operation == "search_subscribers":
        result["query"] = "demo+tag"
    if operation == "assign_subscriber_groups":
        result["groups"] = [3640549]
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_mailerlite_classic_documented_wire_contract(monkeypatch, operation):
    route = ROUTES[operation]
    status = 204 if route["kind"] == "empty" else 201 if operation == "create_group" else 200
    requests = mock_http(monkeypatch, RESPONSES.get(operation), status)
    cfg = config(operation)
    result = await node(cfg).run({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == route["method"]
    assert request.url.host == "api.mailerlite.com"
    assert request.url.path == "/api/v2" + route["path"].format(**{**cfg, "status": "sent"})
    assert request.headers["X-MailerLite-ApiKey"] == TOKEN
    assert TOKEN not in str(result)
    parsed = node(cfg).config.config.model_dump(exclude_none=True)
    assert dict(request.url.params) == {k: str(parsed[k]).lower() if isinstance(parsed[k], bool) else str(parsed[k]) for k in route["query"] if k in parsed}
    if route["body"]:
        assert json.loads(request.content) == {k: parsed[k] for k in route["body"] if k in parsed}
    else:
        assert not request.content
    if "identifier" in cfg or "subscriber_identifier" in cfg:
        assert b"%2B" in request.url.raw_path and b"%40" in request.url.raw_path
    if operation == "get_account":
        assert result["data"]["email"] == "dummy@mailerlite.com"


@pytest.mark.asyncio
async def test_mailerlite_classic_pages_and_explicit_consent_flags(monkeypatch):
    requests = mock_http(monkeypatch, [{"id": 1}])
    result = await node({"operation": "list_subscribers", "limit": 1, "offset": 7}).execute({})
    assert result["has_more"] and result["next_offset"] == 8
    mock_http(monkeypatch, [])
    result = await node({"operation": "list_subscribers", "limit": 1, "offset": 8}).execute({})
    assert not result["has_more"] and result["next_offset"] is None
    requests = mock_http(monkeypatch, RESPONSES["add_group_subscriber"])
    await node({"operation": "add_group_subscriber", "id": 1, "email": "demo@mailerlite.com", "autoresponders": False}).execute({})
    body = json.loads(requests[0].content)
    assert body["resubscribe"] is False and body["autoresponders"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_mailerlite_classic_errors_are_not_success_and_never_leak_key(monkeypatch, status):
    requests = mock_http(monkeypatch, {"error": {"message": "Unauthorized " + TOKEN}}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Unauthorized" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("get_account", {}), ("list_groups", {}),
    ("get_subscriber", []), ("delete_group", {"success": False}),
    ("assign_subscriber_groups", {"success": False}), ("list_groups", {"error": {"message": "Denied"}})])
async def test_mailerlite_classic_unconfirmed_or_malformed_responses(monkeypatch, operation, body):
    mock_http(monkeypatch, body)
    assert (await node(config(operation)).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_mailerlite_classic_response_redaction_and_transport_failure(monkeypatch):
    mock_http(monkeypatch, {"id": 1, "name": TOKEN, "fields": [{"value": TOKEN}]})
    assert TOKEN not in str(await node(config("get_subscriber")).execute({}))
    def fail(**kwargs):
        raise httpx.ConnectError("headers=" + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", fail)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("node_type", ["automation-mailerlite-classic"])
def test_mailerlite_classic_discovery_manual_credentials_and_schema(node_type):
    assert NODE_REGISTRY[node_type] is native.MailerLiteClassicNode
    assert native.MailerLiteClassicAPIKeyCredential(api_key="  " + TOKEN + "  ").credential_type == native.CREDENTIAL_TYPE
    assert native.MailerLiteClassicNode.connection_evidence.operation == "list_groups"
    assert native.MailerLiteClassicNode.connection_evidence.identity_operation == "get_account"
    for cfg in [{"operation": "update_subscriber", "identifier": "1"},
                {"operation": "get_subscriber", "identifier": "../groups"},
                {"operation": "get_group", "id": 0}, {"operation": "list_groups", "limit": 101},
                {"operation": "create_subscriber", "email": "invalid"}]:
        with pytest.raises(ValueError):
            native.MailerLiteClassicNode.parse_config({"config": cfg, "credentials": credential()})
    with pytest.raises(ValidationError):
        native.MailerLiteClassicAPIKeyCredential.model_validate({**credential(), "credential_type": "other"})
    for value in ["https://example.test/key", "<token>", "Bearer abc"]:
        with pytest.raises(ValueError):
            native.MailerLiteClassicAPIKeyCredential(api_key=value)

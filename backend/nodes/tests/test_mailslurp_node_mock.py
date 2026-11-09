"""Synthetic single-request wire regressions; no live account or delivery."""
import httpx
import pytest
from nodes import mailslurp_node as native
from nodes.core.registry import NodeFactory

ID = "00000000-0000-4000-8000-000000000001"
KEY = "synthetic-mailslurp-key"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mailslurp-test", node_type="automation-mailslurp",
        node_data={"config": config, "credentials": {"credential_type": "mailslurp_api_key", "api_key": KEY}})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_wire_contract(monkeypatch, operation):
    method, path, query, body_fields = native.ROUTES[operation]
    config = {"operation": operation}
    for name in ("inboxId", "emailId", "contactId", "id"):
        if "{" + name + "}" in path:
            config[name] = ID
    if operation == "send_email":
        config.update(to=["recipient@example.com"], subject="Test", body="Hello", isHTML=False)
    if operation == "reply_to_email":
        config.update(body="Reply", isHTML=False)
    if operation == "create_contact":
        config.update(emailAddresses=["recipient@example.com"], firstName="Example")
    if operation == "update_inbox":
        config.update(name="Renamed", favourite=False)
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(204) if method == "DELETE" or operation == "send_email" else httpx.Response(200, json={"id": ID})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(seen) == 1
    request = seen[0]
    assert request.method == method and request.url.host == "api.mailslurp.com"
    assert request.url.path == path.replace("{inboxId}", ID).replace("{emailId}", ID).replace("{contactId}", ID).replace("{id}", ID)
    assert request.headers["x-api-key"] == KEY
    if body_fields:
        import json
        assert json.loads(request.content) == {k: v for k, v in config.items() if k in body_fields}
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_rejection_redacts_key_and_does_not_retry(monkeypatch):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(401, text="Invalid key " + KEY)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match="HTTP 401") as error:
        await node({"operation": "get_account"}).execute({})
    assert KEY not in str(error.value) and len(seen) == 1


def test_invalid_id_and_credential():
    with pytest.raises(ValueError):
        native.MailslurpGetInboxConfig(inboxId="../other")
    with pytest.raises(ValueError):
        native.MailslurpAPIKeyCredential(api_key="bad\nheader")
    assert native.MailslurpAPIKeyCredential(api_key=KEY).credential_type == "mailslurp_api_key"

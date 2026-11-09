"""Native Vibe request, evidence, errors, OAuth identity and refresh tests."""
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import vibe_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.vibe_oauth import OAUTH_PROVIDER

TOKEN = "vibe-synthetic-test-token"
CASES = json.loads((Path(__file__).parent / "fixtures/vibe/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="vibe-test", node_type="automation-vibe",
        node_data={"config": config, "credentials": credential or {"credential_type": "vibe_oauth", "access_token": TOKEN}})


def transport(monkeypatch, body, status=200, raw=None):
    seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(status, content=raw) if raw is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_vibe_published_requests(monkeypatch, case):
    seen = transport(monkeypatch, case["response"], case["status"], raw=b"" if case["status"] == 204 else None)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success", result
    assert len(seen) == 1
    req = seen[0]
    assert req.method == case["method"] and req.url.host == "api.vibe.co"
    assert req.url.path == case["path"]
    query = {k: req.url.params.get_list(k) if isinstance(v, list) else req.url.params[k] for k,v in case["query"].items()}
    assert query == case["query"] and set(req.url.params) == set(case["query"])
    assert (json.loads(req.content) if req.content else None) == case["body"]
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["X-Vibe-Revision"] == "2026-06-01"
    assert TOKEN not in str(result)
    if case["method"] != "GET":
        assert result["acknowledged"] and result["state_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_vibe_failure_preserves_provider_message_and_redacts(monkeypatch, status):
    seen = transport(monkeypatch, {"error": {"message": "Rejected " + TOKEN}}, status)
    result = await node({"operation": "list_accounts"}).execute({})
    assert len(seen) == 1 and result["status"] == "error"
    assert result["http_status"] == status and result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": {"message":"Denied"}}, [None], [{"id":1}], "html"])
async def test_vibe_invalid_evidence_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation":"list_accounts"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_vibe_empty_accounts_and_one_page(monkeypatch):
    transport(monkeypatch, [])
    result = await node({"operation":"list_accounts"}).execute({})
    assert result["items"] == [] and result["complete"]
    seen = transport(monkeypatch, {"data":[],"total":100,"limit":20,"offset":20})
    result = await node({"operation":"list_campaigns", "offset":20}).execute({})
    assert len(seen) == 1 and result["pagination"]["total"] == 100


@pytest.mark.asyncio
async def test_vibe_oauth_identity_revision_header(monkeypatch):
    seen=[]
    def reply(request):
        seen.append(request)
        return httpx.Response(200, json=[{"id":1,"name":"Acme Account"}])
    @asynccontextmanager
    async def client(self, template):
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), follow_redirects=False) as c:
            yield c
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", client)
    assert await OAUTH_PROVIDER.account_name(TOKEN) == "Acme Account"
    assert seen[0].url == "https://api.vibe.co/accounts"
    assert seen[0].headers["X-Vibe-Revision"] == "2026-06-01"
    assert OAUTH_PROVIDER.pkce and OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.token_auth == "basic"


@pytest.mark.asyncio
async def test_vibe_refresh_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes.oauth import vibe_oauth
    calls=[]
    async def fresh(**kwargs):
        calls.append(kwargs)
        kwargs["credential"].update(access_token="new-vibe-token", refresh_token="new-refresh-token", expires_at="2030-01-01T00:00:00Z")
        return "new-vibe-token"
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", fresh)
    seen=transport(monkeypatch, [])
    n=node({"operation":"list_accounts"},{"credential_type":"vibe_oauth","access_token":TOKEN,"refresh_token":"old-refresh-token","expires_at":"2020-01-01T00:00:00Z"})
    await n.execute({})
    assert calls[0]["provider"] == "vibe" and calls[0]["refresh"] == vibe_oauth.refresh_access_token
    assert seen[0].headers["Authorization"] == "Bearer new-vibe-token"
    assert n.config.credentials.refresh_token == "new-refresh-token"


def test_vibe_manual_credential_default_and_required_fields():
    c=native.VibeOAuthCredential(access_token=TOKEN)
    assert c.credential_type == "vibe_oauth"
    assert {k for k,v in type(c).model_fields.items() if v.is_required()} == {"access_token"}


@pytest.mark.parametrize("token", ["Bearer token", "https://example.com/token", "<token>", "bad\r\nheader"])
def test_vibe_refuses_bad_tokens(token):
    with pytest.raises(ValueError):
        native.VibeOAuthCredential(access_token=token)


@pytest.mark.asyncio
async def test_vibe_explicit_null_clears_strategy_end(monkeypatch):
    seen = transport(monkeypatch, {"id": "b5101c24-e32a-4a53-a9f0-6ea38eca1a52"})
    await node({"operation":"update_strategy", "strategy_id":"b5101c24-e32a-4a53-a9f0-6ea38eca1a52", "ends_at":None}).execute({})
    assert json.loads(seen[0].content) == {"ends_at":None}

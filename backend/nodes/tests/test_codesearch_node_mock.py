"""Exercise the native Debian Code Search node against its published response fields.

HTTP is mocked; no provider account or live API key is used by these regressions.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import codesearch_node as native
from nodes.core.registry import NodeFactory

ROW = json.loads((Path(__file__).parent / "fixtures/codesearch/published-schema-examples.json").read_text())["search_result"]
KEY = "synthetic-dcs-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation="search_code", **config):
    return NodeFactory.create_node(node_id="codesearch-test", node_type="automation-codesearch",
        node_data={"config": {"operation": operation, "query": "who knows...", **config},
                   "credentials": {"credential_type": "codesearch_api_key", "api_key": KEY}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,body", [
    ("search_code", "search", [ROW]),
    ("search_per_package", "searchperpackage", [{"package": ROW["package"], "results": [ROW]}]),
])
@pytest.mark.parametrize("mode", ["literal", "regexp"])
async def test_published_routes_auth_params_and_response(monkeypatch, operation, path, body, mode):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node(operation, query="xcb_create_window package:i3-wm", match_mode=mode).execute({})
    assert result == {"status": "success", "operation": operation, "data": body, "identity_verified": False}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET" and str(req.url).startswith(native.BASE_URL + "/" + path + "?")
    assert req.headers["x-dcs-apikey"] == KEY
    assert dict(req.url.params) == {"query": "xcb_create_window package:i3-wm", "match_mode": mode}
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_empty_and_optional_context_results(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json=[]))
    assert (await node().execute({}))["data"] == []
    minimal = {k: ROW[k] for k in ("context", "line", "package", "path")}
    transport(monkeypatch, lambda req: httpx.Response(200, json=[minimal]))
    assert (await node().execute({}))["data"] == [minimal]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 403, 429, 500])
async def test_http_failures_are_not_success_or_identity(monkeypatch, status):
    transport(monkeypatch, lambda req: httpx.Response(status, text="request refused " + KEY))
    result = await node().execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "bad"}, [None], [{"package": "p"}], [{**ROW, "line": "1313"}]])
async def test_malformed_response_is_not_success(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    assert (await node().execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_timeout_invalid_json_and_missing_key(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout("timeout " + KEY, request=req)
    transport(monkeypatch, timeout)
    assert KEY not in str(await node().execute({}))
    transport(monkeypatch, lambda req: httpx.Response(200, text="not JSON"))
    assert (await node().execute({}))["status"] == "error"
    without = NodeFactory.create_node(node_id="no-key", node_type="automation-codesearch", node_data={"config": {"operation": "search_code", "query": "who knows..."}})
    with pytest.raises(ValueError, match="API key"):
        await without.execute({})


@pytest.mark.parametrize("key", ["", "https://example.com/key", "<token>", "key with spaces", "abc\r\ndef", "nonasciié"])
def test_bad_pasted_keys_are_rejected(key):
    with pytest.raises(ValidationError):
        native.CodesearchAPIKeyCredential(api_key=key)


def test_manual_key_default_and_reachability_evidence():
    value = native.CodesearchAPIKeyCredential(api_key="  " + KEY + "\n")
    assert value.credential_type == "codesearch_api_key" and value.api_key == KEY
    assert native.CodesearchNode.connection_evidence.proves == "reachability"
    assert native.CodesearchNode.validate_config({"config": {"operation": "search_code", "query": "who knows..."}, "credentials": value.model_dump()})["valid"]
    assert not native.CodesearchNode.validate_config({"config": {"operation": "search_code", "query": "who knows...", "match_mode": "invalid"}})["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,reachable", [(200, [], True), (403, None, False), (500, None, None)])
async def test_connection_probe_uses_declared_read_and_never_claims_account(monkeypatch, status, body, reachable):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as runner
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json=body) if status == 200 else httpx.Response(status))
    async def run(**kwargs):
        assert kwargs["operation"] == "search_code"
        assert kwargs["arguments"] == {"query": "who knows...", "match_mode": "literal"}
        return await node(kwargs["operation"], **kwargs["arguments"]).execute({})
    monkeypatch.setattr(runner, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-codesearch", user_id="test-user",
        credential_data={"credential_type": "codesearch_api_key", "api_key": KEY})
    assert evidence.reachable is reachable
    assert len(requests) == 1

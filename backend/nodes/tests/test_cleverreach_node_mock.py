"""CleverReach HTTP boundary regressions; no live account or provider writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import cleverreach_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cleverreach-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="cleverreach-test", node_type="automation-cleverreach",
        node_data={"config": config, "credentials": {
            "credential_type": native.TOKEN_TYPE, "access_token": TOKEN, **credentials}})


def transport(monkeypatch, payload=None, status=200, handler=None):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_cleverreach_connection_evidence_lists_account_groups(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/cleverreach/groups.json").read_text())
    requests = transport(monkeypatch, payload)
    out = await node({"operation": "list_groups", "search": "Justice League", "page": 2}).execute({})
    assert out["data"] == payload and out["status"] == "success"
    assert str(requests[0].url).startswith(native.BASE + "/groups?")
    assert dict(requests[0].url.params) == {"page": "2", "pagesize": "50", "search": "Justice League"}
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(out)
    assert native.CleverreachNode.connection_evidence.operation == "list_groups"


CASES = [
    ({"operation": "get_group", "group_id": "1966"}, "GET", "/groups/1966"),
    ({"operation": "create_group", "name": "Justice League"}, "POST", "/groups"),
    ({"operation": "update_group", "group_id": "1966", "name": "Justice League"}, "PUT", "/groups/1966"),
    ({"operation": "delete_group", "group_id": "1966"}, "DELETE", "/groups/1966"),
    ({"operation": "get_group_stats", "group_id": "1966"}, "GET", "/groups/1966/stats"),
    ({"operation": "list_receivers", "group_id": "1966"}, "GET", "/groups/1966/receivers"),
    ({"operation": "get_group_receiver", "group_id": "1966", "receiver_id": "123"}, "GET", "/groups/1966/receivers/123"),
    ({"operation": "create_receiver", "group_id": "1966", "email": "bruce@gotham.com"}, "POST", "/groups/1966/receivers"),
    ({"operation": "update_receiver", "group_id": "1966", "receiver_id": "123", "source": "Batcave Computer"}, "PUT", "/groups/1966/receivers/123"),
    ({"operation": "delete_receiver", "group_id": "1966", "receiver_id": "123"}, "DELETE", "/groups/1966/receivers/123"),
    ({"operation": "deactivate_receiver", "group_id": "1966", "receiver_id": "123"}, "PUT", "/groups/1966/receivers/123/deactivate"),
    ({"operation": "get_receiver", "receiver_id": "123"}, "GET", "/receivers/123"),
    ({"operation": "get_receiver_tags", "receiver_id": "123"}, "GET", "/receivers/123/tags"),
    ({"operation": "add_receiver_tags", "receiver_id": "123", "tags": ["hero"]}, "POST", "/receivers/123/tags"),
    ({"operation": "get_receiver_groups", "receiver_id": "123"}, "GET", "/receivers/123/groups"),
    ({"operation": "list_tags"}, "GET", "/tags"),
    ({"operation": "list_mailings"}, "GET", "/mailings"),
    ({"operation": "get_mailing", "mailing_id": "456"}, "GET", "/mailings/456"),
    ({"operation": "list_reports"}, "GET", "/reports"),
    ({"operation": "get_report", "report_id": "456"}, "GET", "/reports/456"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES)
async def test_cleverreach_each_operation_is_one_exact_request(monkeypatch, config, method, path):
    requests = transport(monkeypatch, {"id": "123"})
    out = await node(config).execute({})
    assert len(requests) == 1 and requests[0].method == method
    assert requests[0].url.path == "/v3" + path
    assert out["data"] == {"id": "123"}
    if method != "GET":
        assert out["write_acknowledged"] and out["readback_verified"] is False


@pytest.mark.asyncio
async def test_cleverreach_receiver_body_uses_official_unwrapped_example(monkeypatch):
    requests = transport(monkeypatch, {"id": "123", "email": "bruce@gotham.com"})
    cfg = {"operation": "create_receiver", "group_id": "1966", "email": "bruce@gotham.com",
        "source": "Batcave Computer", "global_attributes": {"firstname": "Bruce", "lastname": "Wayne"}}
    await node(cfg).execute({})
    assert json.loads(requests[0].content) == {k: v for k, v in cfg.items() if k not in {"operation", "group_id"}}
    assert dict(requests[0].url.params) == {"check_blacklist": "true"}
    assert "postdata" not in json.loads(requests[0].content)
    await node({"operation": "update_receiver", "group_id": "1966", "receiver_id": "123", "source": "Batcave Computer"}).execute({})
    assert json.loads(requests[1].content) == {"source": "Batcave Computer"}


@pytest.mark.asyncio
async def test_cleverreach_email_is_one_encoded_path_segment_and_tags_have_context(monkeypatch):
    requests = transport(monkeypatch, ["hero"])
    await node({"operation": "add_receiver_tags", "receiver_id": "bruce+news@gotham.com", "group_id": "1966", "tags": ["hero"]}).execute({})
    assert requests[0].url.raw_path == b"/v3/receivers/bruce%2Bnews%40gotham.com/tags"
    assert json.loads(requests[0].content) == {"tags": ["hero"], "group_id": "1966"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_cleverreach_errors_preserve_provider_text_without_secret(monkeypatch, status):
    transport(monkeypatch, {"error": "Token refused " + TOKEN}, status)
    out = await node({"operation": "list_groups"}).execute({})
    assert out["status"] == "error" and out["http_status"] == status
    assert out["message"] == "Token refused [redacted]"


@pytest.mark.asyncio
async def test_cleverreach_errors_inside_success_response_are_not_proof(monkeypatch):
    transport(monkeypatch, {"success": False, "message": "invalid access token"})
    assert (await node({"operation": "list_groups"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_cleverreach_full_page_is_hint_not_total(monkeypatch):
    transport(monkeypatch, [{"id": "123"}])
    out = await node({"operation": "list_receivers", "group_id": "1966", "pagesize": 1, "page": 3}).execute({})
    assert out["pagination"] == {"page": 3, "page_size": 1, "next_page": 4, "complete": False}


@pytest.mark.asyncio
async def test_cleverreach_html_redirects_malformed_json_and_uncertain_write(monkeypatch):
    for response in [httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}),
                     httpx.Response(200, content=b"{", headers={"content-type": "application/json"})]:
        transport(monkeypatch, handler=lambda request: response)
        with pytest.raises(ValueError):
            await node({"operation": "list_groups"}).execute({})
    def timeout(request):
        raise httpx.ReadTimeout("uncertain " + TOKEN, request=request)
    requests = transport(monkeypatch, handler=timeout)
    with pytest.raises(ValueError, match="Inspect write results") as exc:
        await node({"operation": "create_group", "name": "Justice League"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1
    transport(monkeypatch, handler=lambda request: httpx.Response(302, headers={"location": "https://example.test"}))
    assert (await node({"operation": "list_groups"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("value", ["https://example.test/token", "<token>", "Bearer abc", "abc\nxyz", "é", "abc\x00"])
def test_cleverreach_bad_credentials(value):
    with pytest.raises(ValidationError):
        native.CleverreachAccessTokenCredential(access_token=value)


@pytest.mark.parametrize("identifier", ["../123", "a/b", "https://bad.test", "x?query=1", "x#frag"])
def test_cleverreach_path_injection_is_rejected(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_group", "group_id": identifier})


@pytest.mark.asyncio
async def test_cleverreach_false_acknowledgement_is_failure(monkeypatch):
    transport(monkeypatch, False)
    out = await node({"operation": "delete_group", "group_id": "1966"}).execute({})
    assert out["status"] == "error" and "write_acknowledged" not in out

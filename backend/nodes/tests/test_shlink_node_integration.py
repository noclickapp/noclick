"""Shlink factory, evidence, routing and dependent-selector fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.shlink_node import ShlinkNode, _credential

TYPE = "automation-shlink"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "shlink_api_key", "api_key": "synthetic-shlink-secret", "instance_url": "https://shlink.example.test"}
PARENTS, DARGS = {"domain": "DEFAULT"}, {"domain": "DEFAULT", "short_code": "fixture-code"}
ROOT, SHORT, DETAIL = "/rest/v3/domains", "/rest/v3/short-urls", "/rest/v3/short-urls/fixture-code"
DOMAINS = [{"domain": "PRIVATE-default.example.test", "isDefault": True, "redirects": {"baseUrlRedirect": "https://PRIVATE.test"}}, {"domain": "private.example.test", "isDefault": False, "redirects": {}}]
DCAT = {"domains": {"data": DOMAINS, "defaultRedirects": {"PRIVATE": "https://PRIVATE.test"}}}
ROW = {"shortCode": "fixture-code", "domain": None, "dateCreated": "2026-01-01T00:00:00Z", "visitsSummary": {"total": 7, "nonBots": 5, "bots": 2}, "meta": {"validSince": None, "validUntil": "2027-01-01T00:00:00Z", "maxVisits": 12.5}, "crawlable": False, "forwardQuery": True, "hasRedirectRules": False, "title": "PRIVATE title", "tags": ["PRIVATE tag"], "longUrl": "https://PRIVATE.test/?token=PRIVATE", "shortUrl": "https://PRIVATE.test/fixture-code", "redirects": "PRIVATE", "visits": [{"ip": "PRIVATE"}]}
def page(rows, number=1, pages=1): return {"data": deepcopy(rows), "pagination": {"currentPage": number, "pagesCount": pages, "itemsPerPage": 10, "itemsInCurrentPage": len(rows), "totalItems": max(len(rows), 10 if pages > 1 else len(rows))}}
ROWS = {ROOT: DCAT, "/rest/v3/tags": {"tags": page(["PRIVATE tag"])}, SHORT: {"shortUrls": page([ROW])}, DETAIL: ROW}

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "shlink.example.test"
        assert request.headers["X-Api-Key"] == RAW["api_key"] and request.headers["Accept"] == "application/json"
        assert "Authorization" not in request.headers and RAW["api_key"] not in str(request.url) and not request.content
        assert request.url.path in ROWS and "shorten" not in request.url.path and "/track" not in request.url.path
        params = dict(request.url.params)
        if request.url.path == ROOT: assert not params
        elif request.url.path == SHORT: assert set(params) == {"page", "itemsPerPage", "domain"}
        elif request.url.path == DETAIL: assert set(params) <= {"domain"} and params.get("domain") != "DEFAULT"
        else: assert set(params) == {"page", "itemsPerPage"}
        reply = replies.get(request.url.path, (200, deepcopy(ROWS[request.url.path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload = reply
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Link": '<https://PRIVATE.test/?key=PRIVATE>; rel="next"'})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.shlink_node.guarded_async_client", client)
    return calls, replies

async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_domains", {}), ("list_tags", {}), ("list_short_urls", PARENTS), ("get_short_url", DARGS)])
async def test_actual_four_native_reads_envelopes_auth_and_private_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"] and not result["principal_identity_proven"] and not result["instance_ownership_proven"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"]
    output = json.dumps(result)
    for private in ("PRIVATE", "fixture-code", "longUrl", "shortUrl", RAW["api_key"]): assert private not in output
    if operation in {"list_short_urls", "get_short_url"}:
        row = result["data"][0] if isinstance(result["data"], list) else result["data"]
        assert row["meta"]["maxVisits"] == 12.5 and row["meta"]["validSince"] is None and row["visitsSummary"]["bots"] == 2
    if operation == "get_short_url": assert not dict(next(r for r in transport[0] if r.url.path == DETAIL).url.params)

@pytest.mark.asyncio
async def test_actual_custom_domain_default_witness_names_and_config_lens(transport):
    calls, replies = transport
    replies[SHORT] = (200, {"shortUrls": page([{**ROW, "domain": "private.example.test"}])}); replies[DETAIL] = (200, {**ROW, "domain": "private.example.test"})
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_short_url", "domain": "private.example.test", "short_code": "fixture-code", "include_names": True, "label": "Saved canvas", "disabled": False}}, user_id=USER)
    result = await node.execute({})
    assert result["data"]["shortCode"] == "fixture-code" and result["data"]["domain"] == "private.example.test" and "longUrl" not in result["data"]
    assert dict(next(r for r in calls if r.url.path == DETAIL).url.params) == {"domain": "private.example.test"}
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; calls.clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not calls
    replies.clear(); replies[ROOT] = (200, {"domains": {"data": [{**d, "isDefault": True} for d in DOMAINS]}})
    assert (await run("get_short_url", **DARGS))["status"] == "error" and not any(r.url.path == DETAIL for r in calls)

@pytest.mark.asyncio
async def test_empty_catalog_is_reachability_only_and_pickers_are_private(transport):
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True and ShlinkNode.connection_evidence.proves == "reachability" and not evidence.account_label and "PRIVATE" not in json.dumps(asdict(evidence))
    assert [r["value"] for r in (await ShlinkNode.load_field_options("domain", RAW))["options"]] == ["DEFAULT"]
    named = await ShlinkNode.load_field_options("domain", RAW, context={"include_names": True})
    assert [r["value"] for r in named["options"]] == ["DEFAULT", "private.example.test"]
    calls, replies = transport; calls.clear()
    assert (await ShlinkNode.load_field_options("short_code", RAW, context=PARENTS))["options"] == [] and not calls
    with pytest.raises(ValueError): await ShlinkNode.load_field_options("short_code", RAW, context={"include_names": True})
    options = await ShlinkNode.load_field_options("short_code", RAW, context={**PARENTS, "include_names": True})
    assert options["options"][0]["metadata"]["domain"] == "DEFAULT"
    replies[ROOT] = (200, {"domains": {"data": []}})
    assert (await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)).reachable is True
    assert (await run("get_short_url", **DARGS))["status"] == "error"

@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"domain": "private.example.test"}, {"shortCode": "different-code"}, {"shortCode": "shorten"}, {"visitsSummary": {"total": True, "nonBots": 0, "bots": 0}}, {"meta": {"validSince": None, "validUntil": None, "maxVisits": True}}])
async def test_exact_detail_parent_code_and_number_contract_no_fallback(transport, patch):
    transport[1][DETAIL] = (200, {**ROW, **patch})
    assert (await run("get_short_url", **DARGS))["status"] == "error"

@pytest.mark.asyncio
async def test_current_parent_and_short_code_catalog_races_discard_payload(transport):
    calls, replies = transport
    replies[SHORT] = lambda r: (200, {"shortUrls": page([])} if sum(c.url.path == SHORT for c in calls) > 1 else ROWS[SHORT])
    assert (await run("get_short_url", **DARGS))["status"] == "error"
    replies.clear(); calls.clear()
    replies[ROOT] = lambda r: (200, {"domains": {"data": []}} if sum(c.url.path == ROOT for c in calls) > 1 else DCAT)
    assert (await run("get_short_url", **DARGS))["status"] == "error"

@pytest.mark.asyncio
async def test_optional_pagination_numeric_continuation_and_local_truncation(transport):
    transport[1][SHORT] = (200, {"shortUrls": {"data": [ROW]}})
    result = await run("list_short_urls", **PARENTS)
    assert result["pagination"] == {} and result["has_more"] is None and result["pagination_complete"] is None and result["next_page_token"] is None
    transport[1][SHORT] = (200, {"shortUrls": page([ROW], pages=2)})
    assert (await run("list_short_urls", **PARENTS))["next_page_token"] == "2"
    rows = [{**ROW, "shortCode": f"code-{i}"} for i in range(11)]
    transport[1][SHORT] = (200, {"shortUrls": page(rows)})
    result = await run("list_short_urls", **PARENTS)
    assert result["local_truncated"] and result["has_more"] is None and len(result["data"]) == 10
    for token in ("https://PRIVATE.test", "02", "10001", True):
        with pytest.raises(ValueError): await ShlinkNode.load_field_options("short_code", RAW, context={**PARENTS, "include_names": True}, page_token=token)

@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 404, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1)])
async def test_private_error_contract_no_retry_or_link_following(transport, reply):
    calls, replies = transport; replies[ROOT] = reply if isinstance(reply, Exception) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_domains")
    assert result["status"] == "error" and len(calls) == 1 and "PRIVATE" not in json.dumps(result)

def test_raw_family_bound_origin_and_closed_four_operation_schema():
    for patch in ({"credential_type": "foreign"}, {"api_key": "Bearer token"}, {"instance_url": "https://127.0.0.1"}, {"instance_url": "https://shlink.example.test/rest/v3"}, {"refresh_token": "PRIVATE"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = ShlinkNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_domains", "list_tags", "list_short_urls", "get_short_url"}
    for field in ("url", "longUrl", "shortUrl", "redirects", "headers", "visits", "api_key"): assert field not in schema["$defs"]["ShlinkShortUrlConfig"]["properties"]


@pytest.fixture
def documented_short_urls():
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures/shlink/documented_short_urls.json").read_text())


def test_documented_short_url_records_parse_without_redirect_targets(documented_short_urls):
    from nodes.shlink_node import _short_url
    rows = documented_short_urls["list"]["shortUrls"]["data"]
    for row in [*rows, documented_short_urls["detail"]]:
        projected, anchor = _short_url(row, row["domain"], True)
        assert anchor == (row["domain"], row["shortCode"])
        assert projected["visitsSummary"] == row["visitsSummary"]
        assert projected["meta"] == row["meta"]
        assert projected["dateCreated"] == row["dateCreated"]
        assert projected["title"] == row["title"]
        assert "longUrl" not in projected and "shortUrl" not in projected


def test_documented_list_example_contradicts_filter_and_page_count(documented_short_urls):
    from nodes.shlink_node import _paging, _short_url, ShlinkShortUrlsConfig
    envelope = documented_short_urls["list"]["shortUrls"]
    rows = envelope["data"]
    # The provider documents domain=DEFAULT as default-domain-only, but its
    # generic list example includes a custom-domain row as well.
    assert {row["domain"] for row in rows} == {None, "example.com"}
    with pytest.raises(ValueError, match="returned domain differs"):
        _short_url(rows[-1], None, False)
    # Preserve the example verbatim: its pagination claims ten current items
    # while its actual data array contains three. Do not relax this invariant.
    config = ShlinkShortUrlsConfig(domain="DEFAULT", page=5, items_per_page=10)
    assert len(rows) == 3 and envelope["pagination"]["itemsInCurrentPage"] == 10
    with pytest.raises(ValueError, match="page count differs"):
        _paging(envelope["pagination"], len(rows), len(rows), config)

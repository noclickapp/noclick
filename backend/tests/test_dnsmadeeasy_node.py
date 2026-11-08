"""UNRUN actual native factory/run/collector/picker and signed transport fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.dnsmadeeasy_node import DNSMadeEasyNode, _credential, _signed_headers

TYPE = "automation-dnsmadeeasy"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
DOMAIN = 1119443
RAW = {"credential_type": "dnsmadeeasy_api_key", "api_key": "synthetic-dnsme-key", "api_secret": "synthetic-dnsme-secret", "environment": "production", "domain_id": DOMAIN}
PARENTS = {"domain_id": DOMAIN}
DOMAIN_ROW = {"id": DOMAIN, "name": "PRIVATE-example.org", "created": 1450000000, "nameServers": [{"ipv4": "192.0.2.1"}], "activeThirdParties": ["PRIVATE"], "processMulti": True}
RECORD_ROW = {"id": 66813434, "type": "TXT", "ttl": 1800, "name": "PRIVATE-record-name", "value": "PRIVATE-TXT-secret", "source": 1, "sourceId": 999, "dynamicDns": True, "monitor": True, "failed": False}
def wrapped(rows, page=0): return {"data": rows, "page": page, "totalPages": 8, "totalRecords": 999}
ROWS = {"dns/managed/": wrapped([DOMAIN_ROW]), f"dns/managed/{DOMAIN}": DOMAIN_ROW, f"dns/managed/{DOMAIN}/records": wrapped([RECORD_ROW])}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.dnsmadeeasy.com" and request.url.scheme == "https"
        assert request.headers["x-dnsme-apiKey"] == RAW["api_key"] and request.headers["Accept"] == "application/json"
        date = request.headers["x-dnsme-requestDate"]
        assert parsedate_to_datetime(date).utcoffset().total_seconds() == 0 and date.endswith(" GMT")
        assert request.headers["x-dnsme-hmac"] == hmac.new(RAW["api_secret"].encode(), date.encode("ascii"), hashlib.sha1).hexdigest()
        assert "Authorization" not in request.headers and not request.content
        assert all(RAW[field] not in str(request.url) for field in ("api_key", "api_secret"))
        path = request.url.path.removeprefix("/V2.0/")
        assert path in ROWS
        if path.endswith("/records"): assert set(request.url.params) <= {"rows", "page", "type"}
        else: assert not request.url.params
        reply = replies.get(path, (200, deepcopy(ROWS[path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload, *extra = reply
        headers = {"Content-Type": "application/json", "Link": '<https://PRIVATE.test>; rel="next"'}
        if extra: headers.update(extra[0])
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.dnsmadeeasy_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


def test_known_exact_http_date_hex_signature_not_base64_or_basic():
    headers = _signed_headers(_credential(RAW), datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert headers == {"x-dnsme-apiKey": RAW["api_key"], "x-dnsme-requestDate": "Thu, 01 Jan 2026 00:00:00 GMT", "x-dnsme-hmac": "547cfb429d985cf095a44ba2c1ca391d0f9f079f", "Accept": "application/json", "Content-Type": "application/json"}
    assert _signed_headers(_credential(RAW), datetime(2026, 1, 2, tzinfo=timezone.utc))["x-dnsme-hmac"] != headers["x-dnsme-hmac"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_domains", {}), ("get_domain", PARENTS), ("list_records", PARENTS)])
async def test_three_actual_native_operations_parent_headers_and_private_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"] and not result["principal_identity_proven"] and not result["account_ownership_proven"]
    rendered = json.dumps(result)
    assert all(value not in rendered for value in ("PRIVATE", "192.0.2.1", "nameServers", "sourceId", "created", "dynamicDns", RAW["api_key"], RAW["api_secret"]))
    if operation != "get_domain":
        assert result["provider_page"] == 0 and result["provider_total_pages"] == 8 and result["provider_total_records"] == 999
        assert result["provider_count_scope"] == "unspecified" and result["returned_count"] == 1
        assert result["next_page"] is None and result["has_more"] is None and result["pagination_complete"] is None


@pytest.mark.asyncio
async def test_real_factory_config_lens_raw_witness_collector_and_bound_picker(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_domain", **PARENTS, "label": "Saved canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"] == {"resource_type": "managed_domain", "id": DOMAIN}
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and DNSMadeEasyNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))
    picker = await DNSMadeEasyNode.load_field_options("domain_id", RAW)
    assert picker["options"][0]["value"] == str(DOMAIN) and picker["options"][0]["label"] == str(DOMAIN)
    assert picker["next_page_token"] is None and picker["has_more"] is None
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; transport[0].clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]


@pytest.mark.asyncio
async def test_explicit_record_page_type_names_and_no_catalog_input_paging(transport):
    calls, replies = transport
    replies[f"dns/managed/{DOMAIN}/records"] = (200, wrapped([RECORD_ROW], page=2))
    result = await run("list_records", **PARENTS, rows=1, page=2, record_type="TXT", include_names=True)
    assert result["data"][0]["name"] == RECORD_ROW["name"] and result["data"][0]["ttl"] == 1800
    request = next(r for r in calls if r.url.path.endswith("/records"))
    assert dict(request.url.params) == {"rows": "1", "page": "2", "type": "TXT"}
    calls.clear()
    for kwargs in ({"page_token": "1"}, {"context": {"domain_id": DOMAIN + 1}}, {"context": {"include_names": "true"}}):
        with pytest.raises(ValueError): await DNSMadeEasyNode.load_field_options("domain_id", RAW, **kwargs)
    assert not calls


@pytest.mark.asyncio
async def test_empty_crossed_and_changed_current_domain_cannot_prove_access(transport):
    calls, replies = transport
    replies["dns/managed/"] = (200, wrapped([]))
    assert (await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)).reachable is None
    replies.clear(); calls.clear()
    assert (await run("get_domain", domain_id=DOMAIN + 1))["status"] == "error" and not calls
    replies[f"dns/managed/{DOMAIN}"] = (200, {**DOMAIN_ROW, "id": DOMAIN + 1})
    assert (await run("get_domain", **PARENTS))["status"] == "error"
    replies.clear(); calls.clear()
    def moved(request): return 200, wrapped([] if sum(r.url.path.endswith("/managed/") for r in calls) >= 2 else [DOMAIN_ROW])
    replies["dns/managed/"] = moved
    assert (await run("get_domain", **PARENTS))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"ttl": True}, {"ttl": None}, {"type": "UNPUBLISHED"}, {"id": True}])
async def test_record_optional_present_scalars_are_typed(transport, patch):
    transport[1][f"dns/managed/{DOMAIN}/records"] = (200, wrapped([{**RECORD_ROW, **patch}]))
    assert (await run("list_records", **PARENTS))["status"] == "error"


@pytest.mark.asyncio
async def test_absent_ttl_and_apex_empty_name_preserved(transport):
    row = deepcopy(RECORD_ROW); row.pop("ttl"); row["name"] = ""
    transport[1][f"dns/managed/{DOMAIN}/records"] = (200, wrapped([row]))
    result = await run("list_records", **PARENTS, include_names=True)
    assert "ttl" not in result["data"][0] and result["data"][0]["name"] == ""


@pytest.mark.asyncio
async def test_explicit_sandbox_uses_separate_fixture_keys_and_never_falls_back(monkeypatch):
    calls = []
    sandbox = {**RAW, "api_key": "separate-sandbox-fixture-key", "api_secret": "separate-sandbox-fixture-secret", "environment": "sandbox"}
    def handle(request):
        calls.append(request)
        assert request.url.host == "api.sandbox.dnsmadeeasy.com"
        assert request.headers["x-dnsme-apiKey"] == sandbox["api_key"]
        date = request.headers["x-dnsme-requestDate"]
        assert request.headers["x-dnsme-hmac"] == hmac.new(sandbox["api_secret"].encode(), date.encode("ascii"), hashlib.sha1).hexdigest()
        return httpx.Response(403, json={"error": "PRIVATE"})
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.dnsmadeeasy_node.guarded_async_client", client)
    result = await run_node_operation(node_type=TYPE, operation="list_domains", arguments={}, credential_data=sandbox, user_id=USER)
    assert result["status"] == "error" and len(calls) == 1


@pytest.mark.asyncio
async def test_actual_native_requests_sign_fresh_dates_and_refuse_crossed_page(transport, monkeypatch):
    class Clock:
        tick = 0
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            cls.tick += 1
            return datetime(2026, 1, 1, 0, 0, cls.tick, tzinfo=timezone.utc)
    monkeypatch.setattr("nodes.dnsmadeeasy_node.datetime", Clock)
    assert (await run("get_domain", **PARENTS))["status"] == "success"
    dates = [r.headers["x-dnsme-requestDate"] for r in transport[0]]
    assert len(set(dates)) == len(dates) == Clock.tick
    transport[1][f"dns/managed/{DOMAIN}/records"] = (200, wrapped([RECORD_ROW], page=1))
    assert (await run("list_records", **PARENTS, page=0))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [403, 429, 204, {}, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1), (200, {**wrapped([DOMAIN_ROW]), "page": True}), (200, {**wrapped([DOMAIN_ROW]), "totalRecords": "3"}), (200, wrapped([DOMAIN_ROW]), {"Content-Type": "text/plain"})])
async def test_unknown_errors_bounded_envelope_no_fallback_retry(transport, reply):
    calls, replies = transport
    replies["dns/managed/"] = reply if isinstance(reply, (Exception, tuple)) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_domains")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)
    if reply == 403: assert "credentials or request date" in result["error"]


def test_raw_family_explicit_environment_and_closed_schema():
    for patch in ({"credential_type": "foreign"}, {"environment": "other"}, {"api_key": "Bearer secret"}, {"host": "evil.test"}, {"access_token": "secret"}, {"token_version": True}, {"domain_id": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    raw = deepcopy(RAW); raw.pop("environment")
    with pytest.raises(ValueError): _credential(raw)
    schema = DNSMadeEasyNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_domains", "get_domain", "list_records"}
    assert "page" not in schema["$defs"]["DNSMadeEasyDomainsConfig"]["properties"]
    assert "environment" in schema["$defs"]["DNSMadeEasyAPIKeyCredential"]["required"]


def test_required_domain_picker_uses_central_sole_option_autofill():
    schema = DNSMadeEasyNode.get_config_schema()
    for name in ("DNSMadeEasyDomainConfig", "DNSMadeEasyRecordsConfig"):
        field = schema["$defs"][name]["properties"]["domain_id"]
        assert field["x-dynamic-options"]["auto_select_sole_option"] is True

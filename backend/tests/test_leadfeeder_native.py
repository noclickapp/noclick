"""Leadfeeder staging dispatcher and v1 wire fixtures."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.leadfeeder_node import FAMILY, LeadfeederNode, LeadfeederNodeConfig, _Client
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation
CID, USER, ORG = ("00000000-0000-4000-8000-00000000000" + n for n in ("1", "2", "3"))

NODE = "automation-leadfeeder"
CREDENTIAL = {"credential_type": FAMILY, "api_key": "fixture-leadfeeder-personal-key"}
ACCOUNT = "account-1"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(requests=[], overrides={}, callback=None, status=200, error="invalid_api_key",
        cursor=None, page_count=1, total_count=1, scope="company", company_id="company-1", changed=False,
        previous_ids=[], masked=False, accounts=[{"type": "account_summary", "id": ACCOUNT,
            "attributes": {"name": "Fixture account"}, "relationships": {}}], failure=None)

    def row(kind, ident):
        value = {"type": kind, "id": ident, "attributes": {"name": "Fixture", "created_at": "2026-01-01T00:00:00Z"},
                 "relationships": {"created_by": {"id": "private-person", "type": "user"}},
                 "private_url": "https://private.example.test/?token=PRIVATE_TOKEN"}
        attrs = value["attributes"]
        attrs.update(emails=["PRIVATE_EMAIL"], phones=["PRIVATE_PHONE"], notifications=["PRIVATE_NOTIFICATION"],
                     configuration={"prompt": "PRIVATE_PROMPT"}, revenue="PRIVATE_FINANCE", ip="PRIVATE_IP")
        if kind in {"company", "company_summary", "masked_company_summary"}:
            attrs.update(meta={"has_updated_id": state.changed, "do_not_contact": False}, employee_range="1-10")
            if kind == "company": attrs["previous_ids"] = state.previous_ids
        if kind in {"list", "custom_field"}: attrs["scope"] = state.scope
        if kind == "custom_field": attrs.update(type="text", read_only=False, source="user")
        if kind == "campaign": attrs["status"] = "draft"
        if kind in {"country", "company_industry"}: attrs["code"] = "DE" if kind == "country" else "62.01"
        if kind == "company_location":
            value.pop("attributes")
            value["relationships"] = {"company": {"id": "company-1", "type": "company"},
                "location": {"type": "location", "id": "PRIVATE_LOCATION", "attributes": {"ip": "PRIVATE_IP"}}}
        return value

    async def respond(request):
        state.requests.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.leadfeeder.com"
        assert request.headers["X-Api-Key"] == CREDENTIAL["api_key"] and request.headers["Accept"] == "application/json"
        assert "Authorization" not in request.headers and CREDENTIAL["api_key"] not in str(request.url)
        assert request.method == ("POST" if request.url.path == "/v1/companies/search" else "GET")
        assert "include" not in request.url.params
        if state.callback: state.callback(request)
        if state.failure: raise state.failure(request)
        path = request.url.path
        if state.status != 200:
            return httpx.Response(state.status, json={"errors": [{"code": state.error, "title": CREDENTIAL["api_key"]}]})
        if path in state.overrides:
            return httpx.Response(200, json=deepcopy(state.overrides[path]))
        meta = {"request_id": "fixture-request"}
        if path == "/v1/accounts":
            data = deepcopy(state.accounts)
            if "account_id" in request.url.params:
                assert request.url.params["account_id"] == ACCOUNT
                data[0]["type"] = "account"
                data[0]["attributes"]["credits"] = {"available": 100, "remaining": 90, "used": 10, "next_reset_on": "2026-11-01"}
        else:
            assert request.url.params["account_id"] == ACCOUNT
            types = {"campaigns": "campaign", "lists": "list", "tags": "tag", "custom-fields": "custom_field",
                "countries": "country", "industries": "company_industry", "custom-feeds": "custom_feed",
                "custom-feeds-folders": "custom_feed_folder", "companies": "company_location"}
            last = path.split("/")[-1]
            if path == "/v1/companies/search":
                data = [row("masked_company_summary" if state.masked else "company_summary", "company-1")]
                meta.update(credits={"charged": 0}, pagination={"total_count": state.total_count, "next_cursor": state.cursor})
                assert set(json.loads(request.content)) <= {"search_terms", "locations", "employee_ranges"}
            elif path.startswith("/v1/companies/"):
                data = row("company", state.company_id)
                meta["credits"] = {"charged": 1}
            elif last == "items":
                data = [{"type": "company", "id": "company-1"}]
                meta["pagination"] = {"total_count": state.total_count, "next_cursor": state.cursor}
            elif last in types:
                data = [row(types[last], {"lists": "company_list-1", "campaigns": "campaign-1", "custom-feeds": "feed-1",
                    "countries": "DE", "industries": "nace_62.01"}.get(last, "resource-1"))]
                if "page[num]" in request.url.params:
                    meta["pagination"] = {"total_count": state.total_count, "page_count": state.page_count,
                        "page_num": int(request.url.params["page[num]"])}
            else:
                parent = path.split("/")[-2]
                data = row(types[parent], last)
        return httpx.Response(200, json={"data": data, "meta": meta})

    original = httpx.AsyncClient
    def transport(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", transport)
    state.transport = transport
    return state


async def run(op, args=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {},
        user_id=USER, organization_id=ORG, **kwargs)


OPERATIONS = [
    ("list_accounts", {}), ("get_account", {}), ("search_companies", {"search_terms": ["Fixture"]}),
    ("get_company", {"company_id": "company-1", "acknowledge_credit_use": True}),
    ("list_visitor_companies", {"start_date": "2026-01-01", "end_date": "2026-01-31", "custom_feed_id": "feed-1"}),
    ("list_custom_feeds", {}), ("get_custom_feed", {"custom_feed_id": "feed-1"}), ("list_feed_folders", {}),
    ("list_campaigns", {}), ("get_campaign", {"campaign_id": "campaign-1"}), ("list_company_lists", {}),
    ("get_company_list", {"list_id": "company_list-1"}), ("list_company_list_members", {"list_id": "company_list-1"}),
    ("list_tags", {}), ("list_company_fields", {}), ("list_countries", {}), ("list_industries", {}),
]


def arguments(op, args):
    return args if op == "list_accounts" else {"account_id": ACCOUNT, **args}


def test_real_declaration_schema_discriminator_and_scoped_fields():
    from coder.workflow.operation_catalog import get_operations_for_node_type
    assert {op.name for op in get_operations_for_node_type(NODE)} == {op for op, _ in OPERATIONS}
    schema = LeadfeederNode.get_config_schema()
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == {op for op, _ in OPERATIONS}
    assert schema["$defs"]["GetCompany"]["properties"]["company_id"]["x-dynamic-options"]["depends_on"] == "account_id"
    for op, args in OPERATIONS:
        assert LeadfeederNodeConfig.model_validate({"config": {"operation": op, **arguments(op, args)}}).config.operation == op
    with pytest.raises(ValidationError):
        LeadfeederNodeConfig.model_validate({"config": {"operation": "get_account", "account_id": True}})


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", OPERATIONS)
async def test_actual_factory_dispatcher_all_operations_current_header_and_projection(api, op, args):
    assert NODE_REGISTRY[NODE] is LeadfeederNode
    result = await run(op, arguments(op, args), credential_data=CREDENTIAL)
    assert result["status"] == "success" and result["account_verified"] is True
    assert api.requests[0].url.path == "/v1/accounts"
    assert all(marker not in repr(result) for marker in ("PRIVATE_", "emails", "phones", "notifications", "configuration", "revenue", CREDENTIAL["api_key"]))
    if op != "list_accounts": assert api.requests[-1].url.path == "/v1/accounts"


@pytest.mark.asyncio
async def test_credit_acknowledgment_and_credential_account_binding_refuse_before_http(api):
    with pytest.raises(ValueError, match="credit use"):
        await run("get_company", {"account_id": ACCOUNT, "company_id": "company-1"}, credential_data=CREDENTIAL)
    with pytest.raises(ValueError, match="account binding"):
        await run("list_tags", {"account_id": "other-account"}, credential_data={**CREDENTIAL, "account_id": ACCOUNT})
    assert api.requests == []


@pytest.mark.asyncio
async def test_exact_read_post_cursor_and_numbered_paging_roundtrip(api):
    api.cursor, api.total_count = "opaque+/next=", 2
    args = {"account_id": ACCOUNT, "search_terms": ["Fixture"], "page_size": 1}
    first = await run("search_companies", args, credential_data=CREDENTIAL)
    token = first["data"]["next_page_token"]
    api.cursor = None
    await run("search_companies", {**args, "page_token": token}, credential_data=CREDENTIAL)
    request = [r for r in api.requests if r.method == "POST"][-1]
    assert request.url.params["page[cursor]"] == "opaque+/next=" and request.url.params["page[size]"] == "1"
    assert json.loads(request.content) == {"search_terms": ["Fixture"]}
    api.page_count = 2
    first = await run("list_tags", {"account_id": ACCOUNT, "page_size": 1}, credential_data=CREDENTIAL)
    await run("list_tags", {"account_id": ACCOUNT, "page_size": 1, "page_token": first["data"]["next_page_token"]}, credential_data=CREDENTIAL)
    assert [r for r in api.requests if r.url.path == "/v1/tags"][-1].url.params["page[num]"] == "2"


@pytest.mark.asyncio
async def test_page_tokens_bind_parent_filters_resource_and_key(api):
    api.cursor, api.total_count = "next", 2
    base = {"account_id": ACCOUNT, "search_terms": ["Fixture"]}
    first = await run("search_companies", base, credential_data=CREDENTIAL)
    token = first["data"]["next_page_token"]
    with pytest.raises(ValueError, match="page token"):
        await run("search_companies", {**base, "search_terms": ["Other"], "page_token": token}, credential_data=CREDENTIAL)
    with pytest.raises(ValueError, match="page token"):
        await run("list_company_list_members", {"account_id": ACCOUNT, "list_id": "company_list-1", "page_token": token}, credential_data=CREDENTIAL)
    assert sum(r.method == "POST" for r in api.requests) == 1
    client = _Client({**CREDENTIAL, "api_key": "other-fixture-key"})
    client.witness = _Client(CREDENTIAL).witness
    with pytest.raises(ValueError, match="page token"):
        client.page_token({}, token=token)


@pytest.mark.asyncio
async def test_company_scope_preflight_and_changed_id_history(api):
    api.scope = "contact"
    with pytest.raises(ValueError, match="company-scoped"):
        await run("list_company_list_members", {"account_id": ACCOUNT, "list_id": "company_list-1"}, credential_data=CREDENTIAL)
    assert not any(r.url.path.endswith("/items") for r in api.requests)
    api.company_id = "current-company"
    args = {"account_id": ACCOUNT, "company_id": "company-1", "acknowledge_credit_use": True}
    with pytest.raises(ValueError, match="ID-change"):
        await run("get_company", args, credential_data=CREDENTIAL)
    api.changed = True
    with pytest.raises(ValueError, match="history"):
        await run("get_company", args, credential_data=CREDENTIAL)
    api.previous_ids = ["company-1"]
    result = await run("get_company", args, credential_data=CREDENTIAL)
    assert result["data"]["requested_company_id"] == "company-1" and result["data"]["id"] == "current-company"
    assert result["data"]["id_changed"] is True and result["data"]["credits_charged"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": []}, {"data": [], "meta": {}}, {"data": {}, "meta": {"request_id": "ok"}},
    {"data": [{"id": "", "type": "account_summary", "attributes": {"name": "Fixture"}}], "meta": {"request_id": "ok"}},
    {"data": [{"id": ACCOUNT, "type": "account_summary", "attributes": {"name": {"token": "PRIVATE_"}}}], "meta": {"request_id": "ok"}}])
async def test_malformed_account_envelopes_never_prove_access(api, payload):
    api.overrides["/v1/accounts"] = payload
    with pytest.raises(ValueError): await run("list_accounts", credential_data=CREDENTIAL)


@pytest.mark.asyncio
async def test_empty_accounts_and_masked_search_are_honest(api):
    api.accounts = []
    result = await run("list_accounts", credential_data=CREDENTIAL)
    assert result["account_verified"] is False and result["data"]["account_verified"] is False
    api.accounts = [{"type": "account_summary", "id": ACCOUNT, "attributes": {"name": "Fixture account"}}]
    api.masked = True
    result = await run("search_companies", {"account_id": ACCOUNT, "search_terms": ["Fixture"]}, credential_data=CREDENTIAL)
    assert result["data"]["items"][0]["masked"] is True and "entitled" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("pagination", [{}, {"page_num": 1, "page_count": True, "total_count": 1},
    {"page_num": 2, "page_count": 2, "total_count": 1}, {"page_num": 1, "page_count": 1, "total_count": False},
    {"page_num": 1, "page_count": 0, "total_count": 1}])
async def test_malformed_numbered_meta_fails_closed(api, pagination):
    api.overrides["/v1/tags"] = {"data": [{"id": "tag-1", "type": "tag", "attributes": {"name": "Fixture"}}],
        "meta": {"request_id": "ok", "pagination": pagination}}
    with pytest.raises(ValueError): await run("list_tags", {"account_id": ACCOUNT}, credential_data=CREDENTIAL)


@pytest.mark.asyncio
async def test_search_coverage_without_optional_cursor_and_paid_pickers_never_run(api):
    api.total_count = 3
    result = await run("search_companies", {"account_id": ACCOUNT, "search_terms": ["Fixture"]}, credential_data=CREDENTIAL)
    assert result["data"]["coverage_limited"] is True and result["data"]["next_page_token"] is None
    result = await LeadfeederNode.load_field_options("company_id", CREDENTIAL, {"account_id": ACCOUNT}, search="Fixture")
    assert result["options"] == [{"value": "company-1", "label": "Fixture"}]
    assert all(r.url.path in {"/v1/accounts", "/v1/companies/search"} for r in api.requests)


@pytest.mark.asyncio
async def test_wrong_raw_provider_transport_and_mid_read_witness_never_deliver(api):
    with pytest.raises(ValueError): await run("list_accounts", credential_data={**CREDENTIAL, "credential_type": "other_key"})
    assert api.requests == []
    api.failure = lambda request: httpx.ReadTimeout(CREDENTIAL["api_key"], request=request)
    with pytest.raises(ValueError) as caught: await run("list_accounts", credential_data=CREDENTIAL)
    assert CREDENTIAL["api_key"] not in str(caught.value) and caught.value.__cause__ is None
    api.failure = None
    def change(request):
        if request.url.path == "/v1/tags": api.accounts[0]["attributes"]["name"] = "Changed"
    api.callback = change
    with pytest.raises(ValueError, match="witness changed"):
        await run("list_tags", {"account_id": ACCOUNT}, credential_data=CREDENTIAL)


@pytest.mark.asyncio
async def test_actual_http_trace_adapter_keeps_key_body_query_and_headers_private(api, monkeypatch):
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from utils.outbound_trace_privacy import OutboundTraceProvider
    from tests.test_outbound_trace_privacy import RecordingSampler, StartObserver
    sampler, observer, exporter = RecordingSampler(), StartObserver(), InMemorySpanExporter()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(observer)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = HTTPXClientInstrumentor()
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST", ".*")
    def traced(**kwargs):
        client = api.transport(**kwargs)
        instrumentor.instrument_client(client, tracer_provider=OutboundTraceProvider(provider))
        return client
    monkeypatch.setattr(httpx, "AsyncClient", traced)
    try:
        await run("search_companies", {"account_id": ACCOUNT, "search_terms": ["PRIVATE_SEARCH"]}, credential_data=CREDENTIAL)
        spans = exporter.get_finished_spans()
        assert spans
        data = repr(sampler.observed) + repr(observer.observed) + repr([span.to_json() for span in spans])
        assert all(value not in data for value in (CREDENTIAL["api_key"], "PRIVATE_SEARCH", ACCOUNT))
    finally:
        provider.shutdown()


@pytest.mark.asyncio
async def test_direct_config_credentials_execute_real_account_request(api):
    config = LeadfeederNodeConfig.model_validate({
        "config": {"operation": "list_accounts"}, "credentials": CREDENTIAL,
    })
    node = LeadfeederNode(node_id="direct", node_type=NODE, node_data={}, config=config, sio=MagicMock())
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["items"] == [{"id": ACCOUNT, "type": "account_summary", "name": "Fixture account"}]
    assert [request.url.path for request in api.requests] == ["/v1/accounts"]


@pytest.mark.asyncio
async def test_config_credentials_do_not_replace_missing_saved_authority(api):
    config = LeadfeederNodeConfig.model_validate({
        "config": {"operation": "list_accounts"}, "credentials": CREDENTIAL,
    })
    node = LeadfeederNode(node_id="saved", node_type=NODE,
        node_data={"credential_id": CID}, config=config, sio=MagicMock())
    with pytest.raises(ValueError):
        await node.execute({})
    assert api.requests == []


@pytest.mark.asyncio
async def test_documented_summary_and_filtered_account_responses(monkeypatch):
    """The same route has two documented, query-dependent representations."""
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/leadfeeder/accounts.json").read_text())
    requests = []
    def respond(request):
        requests.append(request)
        body = examples["detail"] if request.url.params.get("account_id") == "123456" else examples["summary"]
        return httpx.Response(200, json=body)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = await run("get_account", {"account_id": "123456"}, credential_data=CREDENTIAL)
    assert result["data"]["id"] == "123456"
    assert result["data"]["credits"] == {"available": 1000, "remaining": 800, "used": 200, "next_reset_on": "2026-10-01"}
    assert [dict(request.url.params) for request in requests] == [{}, {"account_id": "123456"}, {}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,valid", [(200, "none", True), (401, "invalid_api_key", False),
    (403, "invalid_api_key", False), (403, "access_denied", None), (429, "rate_limit", None), (503, "temporary", None)])
async def test_staging_credential_access_hook(api, status, code, valid):
    api.status, api.error = status, code
    result = await LeadfeederNode.validate_credential_access(CREDENTIAL)
    assert result["valid"] is valid and CREDENTIAL["api_key"] not in repr(result)

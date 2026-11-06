"""UNRUN native PredictLeads factory, wire, paging and privacy regressions.

Only the HTTPS boundary is synthetic. Actual factory/config/dispatcher and
connection collection are exercised after an explicit future test grant.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from nodes import predictleads_node as p
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
COMPANY = "00000000-0000-4000-8000-000000000010"
SECOND = "00000000-0000-4000-8000-000000000011"
ITEM = "00000000-0000-4000-8000-000000000012"
TECH = "00000000-0000-4000-8000-000000000013"
STAMP = "2026-10-01T12:30:00Z"


def blob(**changes):
    return {"credential_type": p.FAMILY, "api_key": "synthetic-issued-api-key", "api_token": "synthetic-issued-api-token",
        "allowed_companies_json": '["fixture.example", "second.example"]', "allow_credit_reads": True, **changes}


def subscription(status="active"):
    return {"data": [{"id": ITEM, "type": "api_subscription", "attributes": {"status": status,
        "monthly_credits_quota": 100, "monthly_credits_used": 3}}], "meta": {"schema_version": "3.0"}}


def company():
    return {"data": [{"id": COMPANY, "type": "company", "attributes": {"domain": "fixture.example",
        "company_name": "Fixture Company", "ticker": None, "contact": "SYNTHETIC_PRIVATE_PERSON"},
        "relationships": {}}], "included": [], "meta": {"schema_version": "3.0", "record_state": "active"}}


def link(uid=COMPANY, kind="company"): return {"data": {"id": uid, "type": kind}}


def job(uid=ITEM):
    return {"id": uid, "type": "job_opening", "attributes": {"normalized_title": "Engineer", "translated_title": None,
        "url": "https://external.example.test/job", "first_seen_at": STAMP, "last_seen_at": STAMP,
        "status": None, "categories": ["engineering"], "language": "en", "location": None,
        "recruiter_data": {"name": "SYNTHETIC_PRIVATE_PERSON"}, "description": "SYNTHETIC_PRIVATE_BODY"},
        "relationships": {"company": link()}}


def news(linked=True):
    return {"id": ITEM, "type": "news_event", "attributes": {"category": "launches", "found_at": STAMP,
        "first_seen_at": STAMP, "confidence": 0.5, "planning": False, "contact": "SYNTHETIC_PRIVATE_PERSON",
        "summary": "SYNTHETIC_PRIVATE_SUMMARY"}, "relationships": {"company1": link()} if linked else {"most_relevant_source": {"data": None}}}


def technology():
    return {"id": ITEM, "type": "technology_detection", "attributes": {"first_seen_at": STAMP, "last_seen_at": STAMP,
        "score": 0.7, "behind_firewall": False, "source_count": 1, "department_onet_codes": ["15-1252.00"]},
        "relationships": {"company": link(), "technology": link(TECH, "technology")}}


def dataset(rows, count=None, included=None):
    return {"data": rows, "included": included or [], "meta": {"count": len(rows) if count is None else count,
        "schema_version": "3.0", "record_state": "active"}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype, headers=None):
            self.status_code, self.headers = status, {"content-type": ctype, **(headers or {})}
            self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self):
            yield self.payload
            if state.after_body: state.after_body()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected request beyond the fixture"
            item = state.queue.pop(0)
            if isinstance(item, BaseException): raise item
            return Response(*item) if isinstance(item, tuple) else Response(item, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(args, data=None):
    node = NodeFactory.create_node("fixture-node", p.NODE_TYPE, {"config": args, "credentials": data or blob()}, user_id=USER)
    assert node.config.config.operation == args["operation"]
    return await node.execute({"company": "injected.example", "operation": "follow_company"})


@pytest.mark.asyncio
async def test_preparsed_credentials_execute_documented_subscription_without_raw_node_data(wire):
    # ApiSubscription.example from https://docs.predictleads.com/schemas/open_api_schema.json
    wire.queue = [{"data": [{"id": "ea20b0c1-3427-4004-91e6-59a27be0c9ed", "type": "api_subscription",
        "attributes": {"status": "active", "display_name": "HubSpot enrichment",
            "monthly_credits_quota": 100, "monthly_credits_used": 42}}],
        "included": [], "meta": {"schema_version": "3.1"}}]
    config = p.PredictLeadsNodeConfig.model_validate({"config": {"operation": "check_connection"}, "credentials": blob()})
    node = p.PredictLeadsNode(node_id="fixture", node_type=p.NODE_TYPE, node_data={}, config=config, sio=None)
    result = await node.execute({})
    assert result["witness_verified"] is True
    assert result["data"][0]["attributes"]["monthly_credits_used"] == 42
    assert wire.calls[0][2]["headers"]["X-Api-Key"] == blob()["api_key"]
    # Explicit removal must not resurrect a credential from the parsed config.
    node.node_data["credentials"] = None
    with pytest.raises(ValueError, match="Connect a native"):
        await node.execute({})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_real_registered_factory_dispatcher_execute_inputs_config_and_header_transport(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.PredictLeadsNode
    wire.queue = [company()]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="get_company", arguments={"operation": "follow_company", "company": "fixture.example"}, user_id=USER, credential_data=blob())
    assert result["data"][0]["id"] == COMPANY and result["identity_verified"] is False
    method, url, args = wire.calls[0]
    assert (method, url) == ("GET", p.ROOT + "/companies/fixture.example")
    assert args["headers"]["X-Api-Key"] == blob()["api_key"] and args["headers"]["X-Api-Token"] == blob()["api_token"]
    assert args["params"] is None and "json" not in args and "Authorization" not in args["headers"]
    assert blob()["api_key"] not in url and blob()["api_token"] not in url
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_subscription_zero_credit_actual_connect_collector_has_no_account_claim(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [subscription(), {"data": []}]
    positive = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(allow_credit_reads=False), user_id=USER)
    assert positive.ok and positive.evidence.reachable is True and positive.evidence.proves == "reachability"
    assert positive.evidence.account_label is None
    empty = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert empty.evidence.reachable is None and empty.verified_metadata() == {}
    assert all(call[1] == p.ROOT + "/api_subscription" for call in wire.calls)


@pytest.mark.asyncio
async def test_saved_local_picker_spends_no_credits_and_ignores_caller_scope(wire):
    result = await p.PredictLeadsNode.load_field_options("company", blob(allow_credit_reads=False), context={"company": "injected.example"}, search="SECOND")
    assert result == {"options": [{"value": "second.example", "label": "second.example"}], "has_more": False, "next_page_token": None}
    with pytest.raises(ValueError): await p.PredictLeadsNode.load_field_options("company", blob(), page_token="invented")
    assert not wire.calls


@pytest.mark.asyncio
async def test_bound_paging_repeats_filters_and_reports_cap_then_complete(wire):
    wire.queue = [company(), dataset([job()], count=2), dataset([job(SECOND)], count=2)]
    result = await execute({"operation": "list_job_openings", "company": "fixture.example", "page": 1, "limit": 1,
        "max_pages": 2, "categories": ["engineering"], "active_only": True, "first_seen_at_from": "2026-10-01", "location": "United States"})
    assert result["meta"] == {"count": 2, "start_page": 1, "pages_read": 2, "has_more": False, "next_page": None, "complete_from_first_page": True}
    assert result["documented_credits"] == 3 and "SYNTHETIC_PRIVATE" not in json.dumps(result)
    for page, call in enumerate(wire.calls[1:], 1):
        assert call[2]["params"] == {"page": page, "limit": 1, "categories": "engineering", "active_only": "true", "first_seen_at_from": "2026-10-01", "location": "United States"}
    wire.queue = [company(), dataset([job()], count=2)]
    capped = await execute({"operation": "list_job_openings", "company": "fixture.example", "limit": 1})
    assert capped["meta"]["has_more"] and capped["meta"]["next_page"] == 2 and not capped["meta"]["complete_from_first_page"]
    wire.queue = [company(), dataset([job()], count=2)]
    later = await execute({"operation": "list_job_openings", "company": "fixture.example", "page": 2, "limit": 1})
    assert later["meta"]["has_more"] is False and later["meta"]["complete_from_first_page"] is False


@pytest.mark.asyncio
async def test_technology_typed_included_and_news_unknown_ancestry_are_honest(wire):
    wire.queue = [company(), dataset([technology()], included=[{"id": TECH, "type": "technology", "attributes": {"name": "Fixture", "secret": "SYNTHETIC_PRIVATE"}}]), company(), dataset([news(False)])]
    tech = await execute({"operation": "list_technology_detections", "company": "fixture.example"})
    assert tech["included"] == [{"id": TECH, "type": "technology", "attributes": {"name": "Fixture"}}]
    assert tech["data"][0]["company_link_verified"] is True
    unresolved = await execute({"operation": "list_news_events", "company": "fixture.example"})
    assert unresolved["unresolved_company_link_count"] == 1 and unresolved["data"][0]["company_link_verified"] is False
    assert "SYNTHETIC_PRIVATE" not in json.dumps(tech) + json.dumps(unresolved)
    assert len(wire.calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing-count", "bool-count", "foreign-company", "missing-company", "bad-type", "missing-included", "private-error"])
async def test_jsonapi_shape_and_membership_errors_do_not_become_empty_success(wire, change):
    response = dataset([job()])
    if change == "missing-count": response["meta"].pop("count")
    if change == "bool-count": response["meta"]["count"] = True
    if change == "foreign-company": response["data"][0]["relationships"]["company"] = link(SECOND)
    if change == "missing-company": response["data"][0]["relationships"] = {}
    if change == "bad-type": response["data"][0]["type"] = "person"
    if change == "missing-included": response.pop("included")
    if change == "private-error": response = {"errors": [{"detail": "SYNTHETIC_PRIVATE"}]}
    wire.queue = [company(), response]
    with pytest.raises(RuntimeError) as caught: await execute({"operation": "list_job_openings", "company": "fixture.example"})
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [dataset([job()], count=2), dataset([], count=2), dataset([job(SECOND)], count=3)])
async def test_duplicate_short_and_changing_count_walks_fail(wire, second):
    wire.queue = [company(), dataset([job()], count=2), second]
    with pytest.raises(RuntimeError): await execute({"operation": "list_job_openings", "company": "fixture.example", "limit": 1, "max_pages": 2})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(402, "credit quota"), (403, "rate limit"), (401, "refused"), (404, "refused")])
async def test_distinct_safe_provider_refusals_without_retries(wire, status, reason):
    wire.queue = [({"errors": [{"detail": "SYNTHETIC_PRIVATE"}]}, status, "application/json")]
    with pytest.raises(ValueError, match=reason) as caught: await execute({"operation": "check_connection"})
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,ctype", [(202, "application/json"), (204, "application/json"), (302, "application/json"), (500, "text/html"), (200, "text/html")])
async def test_noncompletion_is_not_success(wire, status, ctype):
    wire.queue = [({}, status, ctype)]
    with pytest.raises(RuntimeError): await execute({"operation": "check_connection"})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_429_delay_transport_and_paid_grants_are_safe(wire):
    wire.queue = [({}, 429, "application/json", {"retry-after": "17"}), httpx.ReadTimeout("SYNTHETIC_PRIVATE")]
    with pytest.raises(RuntimeError, match="17 seconds"): await execute({"operation": "check_connection"})
    with pytest.raises(RuntimeError, match="transport") as caught: await execute({"operation": "check_connection"})
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    with pytest.raises(ValueError, match="credit-consuming"): await execute({"operation": "get_company", "company": "fixture.example"}, blob(allow_credit_reads=False))
    with pytest.raises(ValueError, match="outside"): await execute({"operation": "get_company", "company": "unapproved.example"})
    assert len(wire.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [subscription("disabled"), subscription("disabled_due_to_error"),
    b'{"data":[],"data":[]}', b'{"data":NaN}', b'{"data":' + b' ' * 2_000_000])
async def test_disabled_malformed_and_oversized_subscription_cannot_verify_access(wire, payload):
    wire.queue = [payload]
    with pytest.raises((ValueError, RuntimeError)): await execute({"operation": "check_connection"})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_company_uuid_witness_and_domain_mismatch_do_not_follow_redirects(wire):
    wire.queue = [company(), company()]
    positive = await execute({"operation": "get_company", "company": COMPANY}, blob(allowed_companies_json=json.dumps([COMPANY])))
    assert positive["data"][0]["id"] == COMPANY
    with pytest.raises(RuntimeError, match="does not match"):
        await execute({"operation": "get_company", "company": "second.example"})
    assert len(wire.calls) == 2


@pytest.mark.parametrize("bad", [None, "", "predictleads_oauth", False])
def test_original_family_rejected_before_default_erasure(bad):
    data = {"config": {"operation": "check_connection"}, "credentials": blob(credential_type=bad)}
    assert p.PredictLeadsNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError): p.PredictLeadsNode.parse_config(data)


def test_actual_schema_masked_header_pair_exact_operations_and_input_bounds():
    schema = p.PredictLeadsNode.get_config_schema()
    model = schema["$defs"]["PredictLeadsAPIKeyTokenCredential"]
    assert model["title"] == "PredictLeads API Key and Token" and "x-credential-type" not in model
    assert model["properties"]["api_key"]["ui:widget"] == model["properties"]["api_token"]["ui:widget"] == "password"
    assert model["properties"]["allow_credit_reads"]["default"] is False
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS)
    assert p.PredictLeadsNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for args in ({"company": "https://fixture.example/escape"}, {"company": "fixture.example", "limit": 1001}, {"company": "fixture.example", "page": True}, {"company": "fixture.example", "first_seen_at_from": 1728000000}):
        with pytest.raises(ValueError): p.ListJobOpenings(**args)

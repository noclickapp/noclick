"""PassKit Membership fixed-route and streaming-response contract tests; no live account."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import passkit_membership_node as native
from nodes.core.registry import NodeFactory


TOKEN = "synthetic-passkit-membership-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region="eu"):
    result = NodeFactory.create_node(node_id="passkit-test", node_type=native.PassKitMembershipNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "passkit_membership_api_token", "api_token": TOKEN, "region": region}})
    result.emit = AsyncMock()
    return result


def transport(monkeypatch, *, body=None, text=None, status=200):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=text, json=body) if text is None else httpx.Response(status, text=text)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    return calls


CASES = [
    ({"operation": "list_programs"}, "POST", "/members/programs/list", {"limit": 25, "offset": 0}),
    ({"operation": "get_program", "program_id": "p1"}, "GET", "/members/program/p1", None),
    ({"operation": "get_enrolment_url", "program_id": "p1"}, "GET", "/members/enrol/url/program/p1", None),
    ({"operation": "list_tiers", "program_id": "p1"}, "POST", "/members/tiers/list", {"programId": "p1", "filters": {"limit": 25, "offset": 0}}),
    ({"operation": "get_tier", "program_id": "p1", "tier_id": "gold"}, "GET", "/members/tier/p1/gold", None),
    ({"operation": "list_members", "program_id": "p1"}, "POST", "/members/member/list/p1", {"filters": {"limit": 25, "offset": 0}}),
    ({"operation": "count_members", "program_id": "p1"}, "POST", "/members/count/p1", {"filters": {"limit": 25, "offset": 0}}),
    ({"operation": "get_member", "member_id": "m1"}, "GET", "/members/member/id/m1", None),
    ({"operation": "get_member_by_external_id", "program_id": "p1", "external_id": "a/b +?"}, "GET", "/members/member/externalId/p1/a%2Fb%20%2B%3F", None),
    ({"operation": "enrol_member", "program_id": "p1", "tier_id": "gold", "external_id": "external1", "forename": "Ada", "opt_out": False}, "POST", "/members/member", {"programId": "p1", "tierId": "gold", "externalId": "external1", "person": {"forename": "Ada"}, "optOut": False}),
    ({"operation": "update_member", "member_id": "m1", "program_id": "p1", "tier_id": "gold", "meta_data": {"city": "London"}}, "PUT", "/members/member", {"id": "m1", "programId": "p1", "tierId": "gold", "metaData": {"city": "London"}, "operation": "OPERATION_PATCH"}),
    ({"operation": "delete_member", "member_id": "m1", "program_id": "p1", "tier_id": "gold"}, "DELETE", "/members/member", {"id": "m1", "programId": "p1", "tierId": "gold"}),
    ({"operation": "update_person", "member_id": "m1", "email_address": "ada@example.com"}, "PATCH", "/members/member/person", {"id": "m1", "person": {"emailAddress": "ada@example.com"}}),
    ({"operation": "earn_points", "member_id": "m1", "points": 2.5}, "PUT", "/members/member/points/earn", {"id": "m1", "points": 2.5}),
    ({"operation": "burn_points", "member_id": "m1", "points": 2.5}, "PUT", "/members/member/points/burn", {"id": "m1", "points": 2.5}),
    ({"operation": "set_points", "member_id": "m1", "points": 0}, "PUT", "/members/member/points/set", {"id": "m1", "points": 0, "resetPoints": True}),
    ({"operation": "change_tier", "member_id": "m1", "tier_id": "gold"}, "PUT", "/members/member/tier", {"memberId": "m1", "tierId": "gold"}),
    ({"operation": "update_expiry", "member_id": "m1", "expiry_date": "2027-01-01T00:00:00Z"}, "PUT", "/members/member/updateExpiry", {"id": "m1", "expiryDate": "2027-01-01T00:00:00Z"}),
    ({"operation": "check_in", "member_id": "m1", "notes": "Arrival", "external_event_id": "evt1"}, "POST", "/members/member/checkIn", {"memberId": "m1", "notes": "Arrival", "externalEventId": "evt1"}),
    ({"operation": "check_out", "member_id": "m1"}, "POST", "/members/member/checkOut", {"memberId": "m1"}),
]


@pytest.mark.parametrize("config,method,path,body", CASES)
@pytest.mark.asyncio
async def test_passkit_membership_exact_wire_requests(monkeypatch, config, method, path, body):
    listing = config["operation"] in {"list_programs", "list_tiers", "list_members"}
    calls = transport(monkeypatch, body={"result": {"id": "p1", "name": "Loyalty"}} if listing else {"id": "m1"})
    output = await node(config).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.raw_path.decode() == path
    assert request.url.host == "api.pub1.passkit.io"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert json.loads(request.content) == body if body is not None else request.content == b""
    assert output["data"] == ([{"id": "p1", "name": "Loyalty"}] if listing else {"id": "m1"})


@pytest.mark.asyncio
async def test_passkit_membership_us_stream_and_pagination(monkeypatch):
    calls = transport(monkeypatch, text='{"result":{"id":"a","name":"A"}}\n{"result":{"id":"b","name":"B"}}\n')
    output = await node({"operation": "list_programs", "limit": 2, "offset": 4}, "us").execute({})
    assert calls[0].url.host == "api.pub2.passkit.io"
    assert [x["id"] for x in output["data"]] == ["a", "b"]
    assert output["next_offset"] == 6


@pytest.mark.asyncio
async def test_passkit_membership_empty_page_and_last_page(monkeypatch):
    transport(monkeypatch, text="")
    assert (await node({"operation": "list_programs"}).execute({}))["next_offset"] is None


@pytest.mark.parametrize("text", ['{"result":{"id":"a"}}\n{"error":{"code":7,"message":"denied"}}', '{}', '<html>gateway</html>', '{"result":[]}'])
@pytest.mark.asyncio
async def test_passkit_membership_rejects_incomplete_or_failed_streams(monkeypatch, text):
    transport(monkeypatch, text=text)
    current = node({"operation": "list_programs"})
    with pytest.raises(ValueError):
        await current.execute({})
    current.emit.assert_not_awaited()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
@pytest.mark.asyncio
async def test_passkit_membership_rejections_redact_token_without_retry(monkeypatch, status):
    calls = transport(monkeypatch, text="rejected " + TOKEN, status=status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_program", "program_id": "p1"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(calls) == 1


def test_passkit_membership_filter_mapping_and_input_validation():
    op = native.ListMembers(program_id="p1", filter_field="tierId", filter_value="gold", order_by="created", order_asc=False)
    body = native.request_for(op)[2]
    assert body["filters"]["filterGroups"] == [{"condition": "AND", "fieldFilters": [{"filterField": "tierId", "filterValue": "gold", "filterOperator": "eq"}]}]
    assert body["filters"]["orderAsc"] is False
    with pytest.raises(ValueError):
        native.request_for(native.ListPrograms(filter_field="name"))
    for config in [{"operation": "earn_points", "member_id": "m1", "points": -1},
                   {"operation": "get_program", "program_id": "../a"},
                   {"operation": "get_member_by_external_id", "program_id": "p1", "external_id": ".."},
                   {"operation": "list_programs", "limit": 1001},
                   {"operation": "update_expiry", "member_id": "m1", "expiry_date": "2027-01-01"}]:
        with pytest.raises(ValidationError):
            TypeAdapter(native.Operation).validate_python(config)


def test_passkit_membership_credential_defaults_and_token_validation():
    assert native.PassKitMembershipTokenCredential(api_token=TOKEN).credential_type == "passkit_membership_api_token"
    for token in ["Bearer " + TOKEN, "https://example.com/token", "<token>"]:
        with pytest.raises(ValidationError):
            native.PassKitMembershipTokenCredential(api_token=token)
    with pytest.raises(ValidationError):
        native.PassKitMembershipTokenCredential(api_token=TOKEN, region="https://evil.example")

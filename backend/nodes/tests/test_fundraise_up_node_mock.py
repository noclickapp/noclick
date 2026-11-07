"""Fundraise Up wire and schema regressions using synthetic HTTP only."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import fundraise_up_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-fundraise-up-key-42"
ACCOUNT = "A1234567"


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


def supporter(**changes):
    return {"id": "SAAAAAAA", "account": {"id": ACCOUNT, "name": "Fixture org", "code": None}, "livemode": False,
        "created_at": "2026-10-06T00:00:00Z", "language": "en-US", "first_name": "Fixture", "last_name": "Person",
        "email": "private-fixture@example.com", "phone": "+10000000000", "address": {"city": "PRIVATE-ADDRESS"}, **changes}


def designation(**changes):
    return {"id": "E1234567", "account": {"id": ACCOUNT}, "name": "Owned fixture", "code": "fixture-42",
        "is_default": False, "created_at": "2026-10-06T00:00:00Z", "updated_at": "2026-10-06T00:00:00Z", **changes}


def campaign(**changes):
    return {"id": "FUN12345678", "account": {"id": ACCOUNT}, "name": "Fixture campaign", "code": None, "status": "active", **changes}


def page(items, more=False): return {"data": items, "has_more": more}


def credential(live=False, **changes):
    return {"credential_type": native.FAMILY, "api_key": TOKEN, "livemode": live, "account_id": ACCOUNT, **changes}


def node(config, live=False, creds=None):
    return NodeFactory.create_node(node_id="owned-fixture", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential(live) if creds is None else creds})


def transport(monkeypatch, reply):
    requests, policies = [], []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        policies.append("require_public" not in kwargs)
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, policies


@pytest.mark.asyncio
async def test_real_factory_explicit_test_scope_privacy_and_empty_reachability(monkeypatch):
    requests, policies = transport(monkeypatch, page([supporter()]))
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "success" and result["key_accepted"] and result["returned_account_match"]
    assert result["account_identity_verified"] is False and result["ownership_verified"] is False
    assert TOKEN not in str(result) and "private-fixture@example.com" not in str(result) and "PRIVATE-ADDRESS" not in str(result)
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert requests[0].url.host == "api.fundraiseup.com" and requests[0].url.path == "/v1/supporters"
    assert dict(requests[0].url.params) == {"livemode": "false", "limit": "1"} and policies == [True]
    transport(monkeypatch, page([]))
    empty = await node({"operation": "check_connection"}).run({})
    assert empty["status"] == "success" and empty["returned_account_match"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["list_campaigns", "list_fundraisers", "list_designations", "create_designation", "update_designation", "delete_designation"])
async def test_live_only_operations_never_fall_back_to_live(monkeypatch, op):
    requests, _ = transport(monkeypatch, page([]))
    config = {"operation": op}
    if op == "create_designation": config["name"] = "Owned fixture"
    if op in {"update_designation", "delete_designation"}: config["designation_id"] = "E1234567"
    if op == "update_designation": config["name"] = "Edited fixture"
    result = await node(config).run({})
    assert result["status"] == "error" and requests == [] and result["livemode"] is False


@pytest.mark.asyncio
async def test_account_filtering_keeps_raw_cursor_progress_without_returning_foreign_data(monkeypatch):
    body = page([supporter(id="SBBBBBBB", account={"id": "B1234567"}), supporter()], more=True)
    requests, _ = transport(monkeypatch, body)
    result = await node({"operation": "list_supporters", "limit": 2}).run({})
    assert result["status"] == "success" and result["items"] == [{"id": "SAAAAAAA", "account_id": ACCOUNT,
        "livemode": False, "created_at": "2026-10-06T00:00:00Z", "language": "en-US"}]
    assert result["excluded_other_account_count"] == 1 and result["next_starting_after"] == "SAAAAAAA"
    assert "SBBBBBBB" not in str(result) and "B1234567" not in str(result) and result["complete"] is False
    assert "account" not in requests[0].url.params  # No invented supporter account filter.


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty-more", "bool-more", "no-more", "not-list", "duplicate", "mode", "same-cursor"])
async def test_cursor_envelope_failures_are_not_complete_success(monkeypatch, failure):
    body = page([supporter()], more=True)
    config = {"operation": "list_supporters"}
    if failure == "empty-more": body["data"] = []
    elif failure == "bool-more": body["has_more"] = 1
    elif failure == "no-more": del body["has_more"]
    elif failure == "not-list": body["data"] = {}
    elif failure == "duplicate": body["data"] *= 2
    elif failure == "mode": body["data"][0]["livemode"] = True
    else: config["starting_after"] = "SAAAAAAA"
    requests, _ = transport(monkeypatch, body)
    assert (await node(config).run({}))["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
async def test_reverse_cursor_and_opt_in_contact_are_exact(monkeypatch):
    requests, _ = transport(monkeypatch, page([supporter()], more=True))
    result = await node({"operation": "list_supporters", "ending_before": "SCCCCCCC", "include_contact": True}).run({})
    assert result["next_ending_before"] == "SAAAAAAA" and result["next_starting_after"] is None
    assert result["items"][0]["email"] == "private-fixture@example.com" and "address" not in result["items"][0]
    assert dict(requests[0].url.params) == {"livemode": "false", "limit": "10", "ending_before": "SCCCCCCC"}


@pytest.mark.asyncio
async def test_fundraiser_account_membership_uses_exact_campaign_read(monkeypatch):
    item = {"id": "NAAAAAAA", "name": "Fixture fundraiser", "status": "paused", "campaign": {"id": "FUN12345678"}, "description": "PRIVATE-STORY", "goal": {"amount": 999}}
    def reply(request):
        return httpx.Response(200, json=campaign() if request.url.path.startswith("/v1/campaigns/") else page([item]))
    requests, _ = transport(monkeypatch, reply)
    result = await node({"operation": "list_fundraisers"}, live=True).run({})
    assert result["status"] == "success" and result["items"][0]["campaign"] == {"id": "FUN12345678"}
    assert [r.url.path for r in requests] == ["/v1/fundraisers", "/v1/campaigns/FUN12345678"]
    assert all(r.url.params["livemode"] == "true" for r in requests)
    assert "PRIVATE-STORY" not in str(result) and "amount" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_designation", "update_designation"])
async def test_designation_post_contract_200_mode_and_partial_code_clear(monkeypatch, operation):
    config = {"operation": operation, "name": "Owned fixture"}
    if operation == "update_designation": config.update(designation_id="E1234567", clear_code=True)
    requests, _ = transport(monkeypatch, designation())
    result = await node(config, live=True).run({})
    assert result["status"] == "success" and result["http_status"] == 200 and result["write_verified"] is False and result["readback_required"]
    assert result["attempted_designation_id"] == "E1234567" and requests[-1].method == "POST"
    payload = json.loads(requests[-1].content)
    assert payload == {"name": "Owned fixture", "livemode": True, **({"code": None} if operation == "update_designation" else {})}
    assert "campaign" not in payload and "is_default" not in payload
    if operation == "update_designation": assert requests[0].method == "GET" and requests[0].url.params["livemode"] == "true"


@pytest.mark.asyncio
async def test_default_designation_is_held_before_update_or_delete(monkeypatch):
    requests, _ = transport(monkeypatch, designation(is_default=True))
    result = await node({"operation": "update_designation", "designation_id": "E1234567", "name": "Edited"}, live=True).run({})
    assert result["status"] == "error" and len(requests) == 1 and requests[0].method == "GET"
    result = await node({"operation": "delete_designation", "designation_id": "E1234567"}, live=True).run({})
    assert result["status"] == "error" and len(requests) == 2 and all(request.method == "GET" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 409, 429, 500])
async def test_exact_status_no_retry_redirect_or_provider_body_echo(monkeypatch, status):
    requests, _ = transport(monkeypatch, lambda request: httpx.Response(status, headers={"Location": "https://other.example.com"}, json={"error": {"code": "parameter_invalid", "message": TOKEN, "stripe_error": {"secret": TOKEN}}}))
    result = await node({"operation": "list_supporters"}).run({})
    assert result["status"] == "error" and result["http_status"] == status and len(requests) == 1
    assert TOKEN not in str(result) and "stripe_error" not in str(result)


@pytest.mark.asyncio
async def test_uncertain_create_retains_returned_id_account_mismatch_without_retry(monkeypatch):
    requests, _ = transport(monkeypatch, designation(account={"id": "B1234567"}))
    result = await node({"operation": "create_designation", "name": "Owned fixture"}, live=True).run({})
    assert result["status"] == "error" and result["write_outcome_unknown"] and result["attempted_designation_id"] == "E1234567"
    assert len(requests) == 1


@pytest.mark.parametrize("mode", [None, "false", "true", 0, 1])
def test_credential_requires_explicit_boolean_mode_without_secret_validation_echo(mode):
    with pytest.raises(ValidationError) as error: native.FundraiseUpAPIKeyCredential(**credential(livemode=mode))
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("family", [None, "", 42, "other_api_key"])
def test_original_family_rejects_before_inherited_parse(family):
    data = {"config": {"operation": "check_connection"}, "credentials": credential(credential_type=family)}
    assert native.FundraiseUpNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError): native.FundraiseUpNode.parse_config(data)


def test_actual_schema_parity_and_mutually_exclusive_cursors():
    schema = native.FundraiseUpNode.get_config_schema()
    golden = json.loads((Path(__file__).parent / "fixtures/fundraise_up/native.json").read_text())
    operations = {value["properties"]["operation"]["const"] for value in schema["$defs"].values() if "operation" in value.get("properties", {})}
    assert operations == set(golden["operations"])
    creds = schema["$defs"]["FundraiseUpAPIKeyCredential"]
    assert set(creds["required"]) == {"api_key", "livemode", "account_id"} and "x-oauth-provider" not in creds
    with pytest.raises(ValidationError): native.FundraiseUpListSupportersConfig(starting_after="SAAAAAAA", ending_before="SBBBBBBB")


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_id", ["E1234567", "E7654321"])
async def test_delete_designation_uses_documented_route_and_checks_returned_id(monkeypatch, returned_id):
    def reply(request):
        return httpx.Response(200, json=designation() if request.method == "GET" else {"id": returned_id})
    requests, _ = transport(monkeypatch, reply)
    result = await node({"operation": "delete_designation", "designation_id": "E1234567"}, live=True).run({})
    assert [request.method for request in requests] == ["GET", "DELETE"]
    assert requests[0].url.params["livemode"] == "true"
    assert not requests[1].url.params and requests[1].content == b""
    assert result["status"] == ("success" if returned_id == "E1234567" else "error")

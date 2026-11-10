"""Offline Talkable node tests using staging's typed credential contract.

Transport, projection, validation and pagination coverage is retained from the
original integration without relying on its shared handler changes.
"""
import json
from types import SimpleNamespace
import httpx
import pytest
from nodes import talkable_node as native
from nodes.core import registry

NODE = "automation-talkable"
USER = "talkable-fixture-user"
OPERATIONS = {"list_campaigns", "get_person", "upsert_person_metadata", "list_advocate_referrals",
              "list_friend_referrals", "list_person_rewards", "list_person_shares", "calculate_sharing_rate",
              "list_traffic_sources", "list_assets", "get_asset"}

@pytest.fixture
def local(monkeypatch):
    state = SimpleNamespace(
        blob={"credential_type": "talkable_api_key", "api_key": "synthetic-talkable-key", "site_slug": "fixture-site"},
        requests=[], status=200, raw=None, content_type="application/json",
        result={"campaigns": [{"id": 7, "name": "Synthetic campaign", "status": "Disabled"}]})
    def transport(request):
        state.requests.append(request)
        if state.raw is not None:
            return httpx.Response(state.status, content=state.raw, headers={"Content-Type": state.content_type})
        return httpx.Response(state.status, json={"ok": True, "result": state.result})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(transport), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return state

async def run(local, operation="list_campaigns", **arguments):
    node = registry.NodeFactory.create_node("fixture", NODE,
        {"config": {"operation": operation, **arguments}, "credentials": local.blob}, user_id=USER)
    return await node.execute({})

def test_actual_registration_schema_credential_and_agent_catalog():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    from nodes.agent.node_op_tools import node_supports_op_tools
    assert registry.NODE_REGISTRY[NODE] is native.TalkableNode
    assert {operation.name for operation in get_operations_for_node_type(NODE)} == OPERATIONS
    assert node_accepted_credential_types(NODE) == {"talkable_api_key"}
    assert node_supports_op_tools(NODE)
    schema = native.TalkableNode.get_config_schema()
    credential = schema["$defs"]["TalkableApiKeyCredential"]
    assert set(credential["required"]) == {"api_key", "site_slug"}
    assert credential["properties"]["api_key"]["ui:widget"] == "password"
    assert native.TalkableNode.connection_evidence.proves == "reachability"
    assert native.TalkableNode.connection_evidence.identity_operation is None
    assert "synthetic-key" not in repr(native.TalkableApiKeyCredential(api_key="synthetic-key", site_slug="fixture-site"))


@pytest.mark.asyncio
async def test_upsert_exact_documented_body_drops_raw_private_fields(local):
    local.result = {"person": {"email": "fixture@example.test", "first_name": "Ada",
        "personal_claim_url": "https://private.invalid/claim", "identifier_hash": "private-hash"}}
    output = await run(local, "upsert_person_metadata", person_slug="person+tag@example.test", first_name="Ada",
                       custom_properties={"region": "north"})
    request = local.requests[0]
    assert request.method == "PUT" and request.url.raw_path.startswith(b"/api/v2/people/person%2Btag%40example.test")
    assert json.loads(request.content) == {"site_slug": "fixture-site", "data": {"first_name": "Ada", "custom_properties": {"region": "north"}}}
    assert request.url.params == httpx.QueryParams()
    assert "private.invalid" not in json.dumps(output) and "private-hash" not in json.dumps(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,suffix,resource", [
    ("list_advocate_referrals", "referrals_as_advocate", "referrals"),
    ("list_friend_referrals", "referrals_as_friend", "referrals"),
    ("list_person_rewards", "rewards", "rewards"), ("list_person_shares", "shares_by", "shares")])
async def test_native_person_report_routes_have_no_reward_or_sharing_effects(local, operation, suffix, resource):
    local.result = {resource: [{"id": 9, "coupon_code": "private-code", "short_url": "https://private.invalid", "fraud_details": "private"}]}
    output = await run(local, operation, person_slug="synthetic-person")
    assert local.requests[0].method == "GET" and local.requests[0].url.path.endswith("/" + suffix)
    assert output[resource] == [{"id": 9}]


@pytest.mark.asyncio
async def test_asset_pagination_metadata_projection_and_picker_continuation(local):
    local.result = {"assets": [{"id": 9, "name": "Synthetic asset", "url": "https://private.invalid/asset"}], "total": 101}
    output = await run(local, "list_assets", page=2, per_page=50)
    assert output["next_page"] == 3 and output["total"] == 101
    assert local.requests[0].url.params["page"] == "2"
    picker = await native.TalkableNode.load_field_options("asset_id", local.blob, page_token="2", search="missing")
    assert picker["options"] == [] and picker["next_page_token"] == "3"
    assert "private.invalid" not in json.dumps(output)


@pytest.mark.asyncio
async def test_unpaginated_reports_truncate_without_invented_continuation(local):
    local.result = {"campaigns": [{"id": n + 1, "name": str(n)} for n in range(105)]}
    output = await run(local, limit=2)
    assert len(output["campaigns"]) == 2 and output["truncated"] is True
    assert "next_page" not in output and "page" not in local.requests[0].url.params
    picker = await native.TalkableNode.load_field_options("campaign_id", local.blob, page_token="2")
    assert len(picker["options"]) == 50 and picker["next_page_token"] == "3"


@pytest.mark.asyncio
async def test_metric_documented_dates_array_filter_and_result(local):
    local.result = {"plain": 0.1, "formatted": "10%", "result_type": "number", "private": "discard"}
    output = await run(local, "calculate_sharing_rate", start_date="2026-01-01", end_date="2026-01-31", campaign_id=7)
    params = local.requests[0].url.params
    assert params["start_date"] == "01/01/2026" and params["campaign_ids[]"] == "7"
    assert output["data"] == {"plain": 0.1, "formatted": "10%", "result_type": "number"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "permission"), (422, "validation"), (429, "rate_limit"), (503, "unavailable"), (302, "protocol"), (204, "protocol")])
async def test_actual_transport_errors_are_static_and_not_retried(local, status, category):
    local.status = status
    local.raw = b'{"ok":false,"error_message":"synthetic-talkable-key private-person"}'
    output = await run(local)
    assert output["status"] == "error" and output["http_status"] == status and output["category"] == category
    assert len(local.requests) == 1 and "synthetic-talkable-key" not in json.dumps(output)
    assert "private-person" not in json.dumps(output)


@pytest.mark.asyncio
async def test_response_body_bound_is_enforced_before_parsing(local):
    local.raw = b"x" * (native.MAX_BODY_BYTES + 1)
    assert (await run(local))["category"] == "response_limit"


@pytest.mark.parametrize("config", [{"operation": "upsert_person_metadata", "person_slug": "synthetic", "unsubscribed": True},
    {"operation": "list_campaigns", "site_slug": "other-site"}, {"operation": "create_reward"},
    {"operation": "calculate_sharing_rate", "start_date": "2025-01-01", "end_date": "2026-10-06"}])
def test_actual_factory_refuses_undeclared_effects_scope_and_unbounded_range(local, config):
    with pytest.raises(ValueError):
        registry.NodeFactory.create_node("fixture", NODE, {"config": config, "credentials": local.blob}, user_id=USER)
    assert local.requests == []

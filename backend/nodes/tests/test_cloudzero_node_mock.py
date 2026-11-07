"""Prepared UNRUN: native factory/dispatch/current-row/picker/evidence seams."""
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from nodes import cloudzero_node as cn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
CredentialValidationRow = cn._CredentialAuthority

CREDS = {"credential_type": cn.FAMILIES[0], "api_key": "synthetic+/=private-key"}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
DIMENSIONS = {"dimensions": [{"id": "Region", "name": "Region"}, {"id": "User:Defined:AccountName", "name": "Account Name", "unknown": "omit"}]}
VIEW = {"id": "owned-view", "name": "Owned View", "principal_dimension": "Region", "last_updated": "1791320000.123", "filter": {"Region": ["us-east-1"]}, "connections": {"email": ["omit@example.test"], "slack": [{"url": "https://evil.test/?token=private"}]}, "unknown": "omit"}
COST = {"usage_date": "2026-09-01T00:00:00+00:00", "cost": -2.5, "Region": None, "User:Defined:AccountName": "Owned", "projected_row_count": 5, "unknown": "omit"}
OPS = ["test_connection", "list_dimensions", "get_dimension", "get_costs", "list_views", "get_view"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

def page(key, rows, *, total=None, next_cursor=None, previous=None):
    count = len(rows)
    return {key: rows, "pagination": {"page_count": 2 if next_cursor or previous else int(bool(count)), "item_count": count, "total_count": count if total is None else total, "cursor": {"next_cursor": next_cursor, "previous_cursor": previous, "has_next": next_cursor is not None, "has_previous": previous is not None}}}

class Response:
    def __init__(self, body=None, *, status=200, raw=None, content_type="application/json"):
        self.body, self.raw, self.status_code = body, raw, status
        self.headers = {"Content-Type": content_type}
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.body).encode()

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s", kwargs)
            item = responses.pop(0)
            return item if isinstance(item, Response) else Response(item)
    def client(**kwargs):
        assert kwargs == {"timeout": 30.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(cn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=cn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def test_actual_factory_six_closed_operations_numeric_forms_original_family():
    node = NodeFactory.create_node(node_id="native", node_type=cn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "list_views", "limit": "2"}, "credentials": CREDS})
    assert node.config.config.limit == 2
    defs = cn.CloudZeroNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    for family in (None, "http_bearer", "cloudzero_oauth"):
        data = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert cn.CloudZeroNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError, match="family"): cn.CloudZeroNode.parse_config(data)

@pytest.mark.parametrize("cfg", [{"operation": "get_costs", "start_date": "2026-02-30"}, {"operation": "get_costs", "start_date": "2026-09-02", "end_date": "2026-09-01"}, {"operation": "get_costs", "start_date": "2026-09-01", "group_by": ["Region", "Region"]}, {"operation": "get_costs", "start_date": "2026-09-01", "group_by": ["cost"]}, {"operation": "get_costs", "start_date": "2026-09-01", "filters_json": '{"Region":[true]}'}, {"operation": "get_costs", "start_date": "2026-09-01", "filters_json": '{"Region":["x"],"Region":["y"]}'}, {"operation": "get_costs", "start_date": "2026-09-01", "cost_type": "payment"}, {"operation": "list_views", "limit": True}, {"operation": "list_views", "limit": 101}, {"operation": "get_view", "view_id": "../admin"}, {"operation": "test_connection", "url": "https://evil.test"}, {"operation": "send_telemetry"}])
def test_documented_dates_filters_count_scope_and_unsupported_surface(cfg):
    with pytest.raises(ValueError): cn.CloudZeroNode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.asyncio
async def test_actual_dimensions_probe_raw_header_empty_reachability_and_privacy(wire, caplog):
    wire.responses.append({"dimensions": []})
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    assert wire.calls[0] == {"method": "GET", "url": cn.BASE+"/v2/billing/dimensions", "params": [("include_hidden", "false")], "headers": {"Authorization": CREDS["api_key"], "Accept": "application/json"}}
    assert result["data"]["dimension_count"] == 0 and result["data"]["protected_read_completed"] is True and result["data"]["account_identity_verified"] is False and result["data"]["cost_view_permissions_verified"] is False
    assert CREDS["api_key"] not in caplog.text and cn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context")
    assert "unrelated context" in caplog.text
    with pytest.raises(ValueError, match="Confirm"): await run("get_costs", {"start_date": "2026-09-01"})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_actual_cost_query_repeated_dimensions_filters_dynamic_columns_and_cursor(wire):
    cursor = "cache+/=opaque"
    wire.responses.extend([page("costs", [COST], total=2, next_cursor=cursor), page("costs", [{**COST, "cost": 0}], total=2, previous="previous-cache")])
    args = {"start_date": "2026-09-01", "end_date": "2026-10-01T00:00:00Z", "group_by": ["Region", "User:Defined:AccountName"], "filters_json": '{"!Account":["owned-account"]}', "cost_type": "usage_amount", "align_to_granularity": False, "include_projected_row_count": True, "confirm_query_quota": True}
    first = await run("get_costs", args); token = first["data"]["next_page_token"]
    second = await run("get_costs", {**args, "page_token": token})
    params = wire.calls[0]["params"]
    assert [value for key,value in params if key == "group_by"] == ["Region", "User:Defined:AccountName"] and json.loads(dict(params)["filters"]) == {"!Account": ["owned-account"]}
    assert dict(params)["align_to_granularity"] == "false" and "limit" not in dict(params)
    assert wire.calls[1]["params"] == [("cursor", cursor)]
    assert first["data"]["costs"] == [{k: COST[k] for k in ("usage_date", "cost", "Region", "User:Defined:AccountName", "projected_row_count")}]
    assert second["data"]["pagination"]["observed_chain_count"] == 2 and second["data"]["next_page_token"] is None and second["data"]["currency_verified"] is False
    assert all(call["method"] == "GET" for call in wire.calls) and len(wire.calls) == 2

@pytest.mark.asyncio
async def test_continuation_query_actor_key_current_revision_and_24h_before_http(wire, monkeypatch):
    wire.responses.append(page("costs", [COST], total=2, next_cursor="cache+/=opaque"))
    args = {"start_date": "2026-09-01", "confirm_query_quota": True}
    token = (await run("get_costs", args))["data"]["next_page_token"]
    for change in ({"start_date": "2026-09-02"}, {"granularity": "monthly"}, {"page_token": token+"x"}):
        with pytest.raises(ValueError, match="continuation"): await run("get_costs", {**args, "page_token": token, **change})
    query = {"params": cn._cost_query(cn.CloudZeroCostsConfig(**args))}
    for context in ({"_user_id": "other"}, {"_user_id": "actor", "_credential_id": "other-row"}):
        with pytest.raises(ValueError, match="continuation"): cn._decode_cursor(token, cn._shape(CREDS), context, "/v2/billing/costs", query)
    monkeypatch.setattr(cn, "_current_data", AsyncMock(return_value={**cn._shape(CREDS), "approval_revision": 3}))
    with pytest.raises(ValueError, match="continuation"): await run("get_costs", {**args, "page_token": token})
    monkeypatch.setattr(cn, "_current_data", AsyncMock(return_value=cn._shape(CREDS)))
    now = int(cn.time.time()); monkeypatch.setattr(cn.time, "time", lambda: now+86401)
    with pytest.raises(ValueError, match="expired"): await run("get_costs", {**args, "page_token": token})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_saved_views_exact_scope_projection_filters_optin_and_dimension_picker(wire):
    wire.responses.extend([page("views", [VIEW]), {"view": VIEW}, DIMENSIONS, DIMENSIONS])
    listed = await run("list_views", {"limit": "2"}); read = await run("get_view", {"view_id": VIEW["id"], "include_filters": True})
    dimension = await run("get_dimension", {"dimension_id": "User:Defined:AccountName"})
    picked = await cn.CloudZeroNode.load_field_options("dimension_id", CREDS, context={"_user_id": "actor", "include_hidden": True}, search="Account")
    assert "filter" not in listed["data"]["views"][0] and read["data"]["view"]["filter"] == VIEW["filter"] and read["data"]["returned_view_id_verified"] is True
    assert all(value not in json.dumps(listed)+json.dumps(read) for value in ("omit@example", "evil.test", "connections"))
    assert wire.calls[1]["url"] == cn.BASE+"/v2/views/owned-view" and dict(wire.calls[0]["params"])["sort_key"] == "last_updated"
    assert dimension["data"]["returned_dimension_id_verified"] is True and picked["options"][0]["value"] == "User:Defined:AccountName" and wire.calls[-1]["params"] == [("include_hidden", "true")]

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"view": {**VIEW, "id": "other-view"}}, {"view": {**VIEW, "last_updated": 42}}, {"view": None}, {"view": VIEW, "status": "rejected"}])
async def test_wrong_or_malformed_view_refused_once(wire, body):
    wire.responses.append(body)
    with pytest.raises(cn.CloudZeroAPIError): await run("get_view", {"view_id": VIEW["id"]})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["403", "410", "429", "503", "204", "html", "empty", "duplicate", "nan", "deep", "oversize"])
async def test_safe_unverified_errors_bounds_and_no_replay(wire, monkeypatch, case):
    response = Response(DIMENSIONS)
    if case.isdigit(): response = Response(status=int(case), raw=b"private nonJSON", content_type="text/plain")
    if case == "html": response.headers["Content-Type"] = "text/html"
    if case == "empty": response.raw = b""
    if case == "duplicate": response.raw = b'{"dimensions":[],"dimensions":null}'
    if case == "nan": response.raw = b'{"dimensions":[],"unknown":1e309}'
    if case == "deep": response.raw = b'['*40+b'0'+b']'*40
    if case == "oversize": monkeypatch.setattr(cn, "MAX_BYTES", 32)
    wire.responses.append(response)
    with pytest.raises(cn.CloudZeroAPIError) as error: await run("test_connection")
    assert error.value.authority_rejected is False and CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1 and cn._PRIVATE_REQUEST.get() is False
    if case == "403": assert error.value.http_status == 403

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"costs": [], "pagination": {}}, page("costs", [COST], total=0), page("costs", [COST], total=2), page("costs", [{**COST, "cost": True}]), page("costs", [{**COST, "Region": {"private": "omit"}}]), page("costs", [COST], total=2, next_cursor="synthetic%2b%2F%3dprivate-key")])
async def test_pagination_cost_and_secret_cursor_shapes(wire, body):
    wire.responses.append(body)
    with pytest.raises(cn.CloudZeroAPIError): await run("get_costs", {"start_date": "2026-09-01", "group_by": ["Region"], "confirm_query_quota": True})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_10000_native_cost_page_and_blank_filters_actual_dispatch(wire, monkeypatch):
    # A full page is the documented 10,000 rows; the boundary is checked at a lowered limit so it builds no 10,000-row page.
    assert cn.MAX_ROWS == 10000
    monkeypatch.setattr(cn, "MAX_ROWS", 10)
    wire.responses.append(page("costs", [COST]*10))
    result = await run("get_costs", {"start_date": "2026-09-01", "filters_json": "   ", "confirm_query_quota": True})
    assert len(result["data"]["costs"]) == 10 and "filters" not in dict(wire.calls[0]["params"]) and result["data"]["next_page_token"] is None

@pytest.mark.asyncio
async def test_current_row_type_over_blob_trusted_context_and_actual_stored_picker(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import encryption
    pool = SimpleNamespace(acquire=lambda: None)
    from wss.handlers import workflow_handler
    class Acquire:
        async def __aenter__(self): return object()
        async def __aexit__(self, *args): pass
    pool.acquire = Acquire
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="org"))
    row = CredentialValidationRow(cn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    authority = AsyncMock(return_value=row); monkeypatch.setattr(cn, "_fetch_authority", authority)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: {**CREDS, "credential_type": "http_bearer", "owner_id": "forged"}))
    fresh = await cn.CloudZeroNode.freshen_credential(credential_data=CREDS, pool=pool, user_id="actor", credential_id="saved")
    assert fresh["credential_type"] == cn.FAMILIES[0] and fresh["owner_id"] == "owner" and fresh["token_version"] == 2 and fresh["approval_revision"] == 1
    context = cn._context(fresh, {"_user_id": "actor", "_approval_pool": "forged", "_credential_id": "forged"})
    assert context["_approval_pool"] is pool and context["_credential_id"] == "saved" and context["_workflow_id"] is None
    with pytest.raises(ValueError, match="actor"): cn._context(fresh, {"_user_id": "other"})
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append(DIMENSIONS)
    result = await run_node_lookup(node_type=cn.NODE_TYPE, field_name="dimension_id", credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="wf", search="Region")
    assert result["options"] == [{"value": "Region", "label": "Region (Region)"}] and len(wire.calls) == 1 and all(call.args[1:] == ("saved", "actor", "org") for call in authority.call_args_list)

@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "foreign_family"])
async def test_invalid_current_row_stops_before_decrypt_or_transport(monkeypatch, wire, state):
    from utils import encryption
    row = CredentialValidationRow(cn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    if state == "missing": row = None
    if state == "revoked": row = replace(row, revoked_at=STAMP)
    if state == "foreign_family": row = replace(row, credential_type="http_bearer")
    monkeypatch.setattr(cn, "_fetch_authority", AsyncMock(return_value=row)); monkeypatch.setattr(encryption, "get_encryption", lambda: (_ for _ in ()).throw(AssertionError("No decrypt")))
    from wss.handlers import workflow_handler
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="org"))
    with pytest.raises(ValueError): await cn.CloudZeroNode.freshen_credential(CREDS, pool=MagicMock(), user_id="actor", credential_id="saved")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_real_execute_raw_binding_after_parser_and_secret_echo(monkeypatch, wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}
    loader = AsyncMock(return_value=cn._shape(raw)); monkeypatch.setattr(cn, "_current_data", loader)
    wire.responses.append({"dimensions": [{"id": "Region", "name": "synthetic%2b%2F%3dprivate-key"}]})
    result = await run("list_dimensions", credential_data=raw, credential_id="saved", pool=object())
    assert result["data"]["dimensions"][0]["name"] == "[redacted]" and loader.call_args_list[0].args[0]["owner_id"] == "owner" and loader.call_args_list[0].args[0]["approval_revision"] == 4
    loader.return_value = {**cn._shape(raw), "token_version": 5}
    with pytest.raises(cn.CloudZeroAPIError, match="binding changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    shaped = cn._shape(CREDS); monkeypatch.setattr(cn, "_current_data", AsyncMock(side_effect=[shaped, shaped, shaped, {**shaped, "approval_revision": 9}]))
    wire.responses.append(DIMENSIONS)
    with pytest.raises(cn.CloudZeroAPIError, match="changed"): await run("list_dimensions")
    assert len(wire.calls) == 2




@pytest.mark.asyncio
async def test_documented_cost_response_with_projected_counts_and_null_cursors(wire):
    # Copied from billing_cost in the provider docs; the pinned spec incorrectly
    # spells its nullable string type as JSON null instead of the string "null".
    # https://docs.cloudzero.com/reference/getbillingcosts
    body = {
        "costs": [
            {
                "usage_date": "2023-10-02T00:00:00+00:00",
                "cost": 1234.56,
                "projected_row_count": 482,
                "Region": "us-east-1"
            },
            {
                "usage_date": "2023-10-02T00:00:00+00:00",
                "cost": 567.89,
                "projected_row_count": 105,
                "Region": "us-west-1"
            }
        ],
        "pagination": {
            "page_count": 1,
            "item_count": 2,
            "total_count": 2,
            "cursor": {
                "next_cursor": None,
                "previous_cursor": None,
                "has_next": False,
                "has_previous": False
            }
        },
        "sorting": {
            "available": {
                "sort_keys": [
                    "usage_date"
                ],
                "sort_orders": [
                    "asc"
                ]
            },
            "current": [
                {
                    "sort_key": "usage_date",
                    "sort_order": "asc"
                }
            ]
        },
        "filtering": {
            "available": [],
            "current": {}
        },
        "total_count": 2
    }
    wire.responses.append(body)
    result = await run("get_costs", {"start_date": "2023-10-26T14:27:46+00:00", "group_by": ["Region"], "include_projected_row_count": True, "confirm_query_quota": True})
    assert result["data"]["costs"] == body["costs"]
    assert result["data"]["pagination"]["observed_chain_count"] == 2
    assert result["data"]["next_page_token"] is None

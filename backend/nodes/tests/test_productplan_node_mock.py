"""UNRUN ProductPlan native factory, dispatcher, authority and handler fixtures.

Synthetic tokens/responses only. No provider request or runtime qualification.
"""
import asyncio
import json
import socket
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from nodes import productplan_node as pn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from nodes.productplan_node import ProductPlanCredentialRow as CredentialValidationRow

PUBLIC_CLIENT = pn.guarded_async_client
CREDS = {"credential_type": pn.FAMILIES[0], "personal_access_token": "x" * 64}
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
ROADMAP = {"id": 1, "name": "Owned roadmap", "permission": "owner", "is_version": False, "lanes": ["Engineering"], "legends": ["Planned"], "owner": {"email": "omit@example.invalid"}, "description": "private"}
BAR = {"id": 2, "name": "Owned bar", "roadmap": {"id": 1, "url": "https://evil.test/omit"}, "parked": True, "is_container": False, "child_bar_count": 0, "percent_done": None, "tags": ["local"], "notes": "private"}
OBJECTIVE = {"id": 3, "name": "Objective", "subject": "CompanyWide", "risk_status": "low_risk", "location_status": "active", "description": "private"}
KEY_RESULT = {"id": 4, "start": 0.0, "target": 100.0, "current": 125.0, "progress": 125, "type": "NumberResult", "description": "private"}
IDEA = {"id": 5, "name": "Idea", "location_status": "visible", "customer": "omit", "source_email": "omit@example.invalid"}
LAUNCH = {"id": 6, "name": "Launch", "status": "low_risk", "user_id": 77}
TASK = {"id": 7, "name": "Task", "status": "to_do", "checklist_section_id": 10, "assigned_user_id": 77}
TEAM = {"id": 8, "name": "Team"}


def page(rows, *, current=1, total=None, pages=1):
    return {"results": rows, "paging": {"record_count": len(rows) if total is None else total, "page_count": pages, "current_page": current, "page_size": len(rows)}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class Response:
    def __init__(self, payload=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"content-type": content_type}
        self.raw = raw if raw is not None else json.dumps(payload).encode()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw


@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(pn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)


async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=pn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)


def test_actual_factory_union_original_family_and_numeric_fields():
    schema = pn.ProductPlanNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 18
    data = {"config": {"operation": "get_bar", "roadmap_id": "1", "bar_id": "2"}, "credentials": CREDS}
    node = NodeFactory.create_node(node_id="native", node_type=pn.NODE_TYPE, node_data=data, user_id="actor")
    assert node.config.config.roadmap_id == 1 and node.config.config.bar_id == 2
    for family in ("http_bearer", "productboard_token", None):
        bad = {**data, "credential_id": "saved", "credentials": {**CREDS, "credential_type": family}}
        assert pn.ProductPlanNode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"):
            pn.ProductPlanNode.parse_config(bad)
    assert pn.ProductPlanNode.parse_config({"config": {"operation": "test_connection"}, "credentials": {"personal_access_token": "x" * 64}}).credentials.credential_type == pn.FAMILIES[0]
    for field in ("endpoint", "personal_access_token", "parked", "share"):
        assert pn.ProductPlanNode.validate_config({
            **data, "config": {**data["config"], field: "unsupported"}})["valid"] is False


@pytest.mark.asyncio
async def test_protected_empty_access_exact_bearer_and_honest_evidence(monkeypatch, wire):
    wire.responses.append(Response(page([], pages=0)))
    result = await run("test_connection")
    assert result["data"]["protected_read_completed"] and result["data"]["account_identity_verified"] is False
    assert result["data"]["write_permission_verified"] is False
    assert wire.calls[0]["url"] == pn.BASE_URL + "/roadmaps"
    assert wire.calls[0]["headers"]["Authorization"] == "Bearer " + CREDS["personal_access_token"]
    assert wire.calls[0]["params"] == {"page": 1, "page_size": 1, "q[is_version_eq]": "false"}



@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,payload,route", [
    ("list_roadmaps", {}, page([ROADMAP]), "/roadmaps"),
    ("get_roadmap", {"roadmap_id": 1}, ROADMAP, "/roadmaps/1"),
    ("list_objectives", {"search": "Strategy"}, page([OBJECTIVE]), "/strategy/objectives"),
    ("get_objective", {"objective_id": 3}, OBJECTIVE, "/strategy/objectives/3"),
    ("list_key_results", {"objective_id": 3}, page([KEY_RESULT]), "/strategy/objectives/3/key_results"),
    ("get_key_result", {"objective_id": 3, "key_result_id": 4}, KEY_RESULT, "/strategy/objectives/3/key_results/4"),
    ("list_ideas", {}, page([IDEA]), "/discovery/ideas"),
    ("get_idea", {"idea_id": 5}, IDEA, "/discovery/ideas/5"),
    ("list_launches", {}, page([LAUNCH]), "/launches"),
    ("get_launch", {"launch_id": 6}, LAUNCH, "/launches/6"),
    ("list_launch_tasks", {"launch_id": 6}, page([TASK]), "/launches/6/tasks"),
    ("list_teams", {}, page([TEAM]), "/teams"),
])
async def test_actual_native_reads_and_closed_projection(wire, op, args, payload, route):
    wire.responses.append(Response(payload))
    result = await run(op, args)
    assert len(wire.calls) == 1 and wire.calls[0]["method"] == "GET" and wire.calls[0]["url"] == pn.BASE_URL + route
    for private in ("private", "omit", "assigned_user_id", "user_id", "source_email"):
        assert private not in json.dumps(result)
    assert '"owner":' not in json.dumps(result)
    if op == "list_objectives":
        assert wire.calls[0]["params"]["q[label_name_i_cont]"] == "Strategy"
        assert "q[name_i_cont]" not in wire.calls[0]["params"]
    if op == "get_key_result":
        assert result["data"]["parent_scope_source"] == "protected_request_route" and result["data"]["key_result"]["progress"] == 125


@pytest.mark.asyncio
@pytest.mark.parametrize("op,payload", [("get_bar", BAR), ("list_roadmap_bars", page([BAR]))])
async def test_bar_reads_use_actual_parent_reference(wire, op, payload):
    wire.responses.extend([Response(ROADMAP), Response(payload)])
    result = await run(op, {"roadmap_id": 1, **({"bar_id": 2} if op == "get_bar" else {})})
    assert len(wire.calls) == 2 and "evil.test" not in json.dumps(result)
    wrong = {**BAR, "roadmap": {"id": 99}}
    wire.responses.extend([Response(ROADMAP), Response(wrong if op == "get_bar" else page([wrong]))])
    with pytest.raises(pn.ProductPlanAPIError, match="selected roadmap"):
        await run(op, {"roadmap_id": 1, **({"bar_id": 2} if op == "get_bar" else {})})


@pytest.mark.asyncio
async def test_actual_create_201_has_no_invented_id_and_stays_parked(wire):
    wire.responses.extend([Response(ROADMAP), Response({"id": 222, "private": "omit"}, status=201)])
    result = (await run("create_bar", {"roadmap_id": "1", "name": "Disposable", "confirm_mutation": True, "percent_done": "0", "lane": "Engineering"}))["data"]
    assert wire.calls[-1]["json"] == {"roadmap_id": 1, "name": "Disposable", "parked": True, "is_container": False, "tags": [], "percent_done": 0, "lane": "Engineering"}
    assert wire.calls[-1]["method"] == "POST" and result["http_status"] == 201
    assert result["created_id"] is None and result["created_id_verified"] is False and result["independent_readback_verified"] is False
    wire.responses.extend([Response(ROADMAP), Response(status=201, raw=b"", content_type="")])
    assert (await run("create_bar", {"roadmap_id": 1, "name": "Disposable", "confirm_mutation": True}))["data"]["accepted"]


@pytest.mark.asyncio
async def test_sparse_keep_set_clear_actual_dispatch_and_leaf_delete(wire):
    for args, wanted in [({"new_name": "Renamed"}, {"name": "Renamed"}), ({"description_mode": "clear", "progress_mode": "clear", "tags_mode": "clear"}, {"description": None, "percent_done": None, "tags": []}), ({"tags_mode": "set", "tags": ["local"]}, {"tags": ["local"]})]:
        wire.responses.extend([Response(ROADMAP), Response(BAR), Response(status=204, raw=b"")])
        result = (await run("update_bar", {"roadmap_id": 1, "bar_id": 2, "confirm_mutation": True, **args}))["data"]
        assert wire.calls[-1]["method"] == "PATCH" and wire.calls[-1]["json"] == wanted
        assert result["independent_readback_verified"] is False
    wire.responses.extend([Response(ROADMAP), Response(BAR), Response(status=204, raw=b"")])
    result = (await run("delete_bar", {"roadmap_id": 1, "bar_id": 2, "confirm_mutation": True}))["data"]
    assert wire.calls[-1]["method"] == "DELETE" and "json" not in wire.calls[-1] and result["absence_verified"] is False


@pytest.mark.asyncio
async def test_intent_current_permission_child_and_grant_change_guards(monkeypatch, wire):
    for op, args in [("update_bar", {"roadmap_id": 1, "bar_id": 2, "confirm_mutation": True}), ("create_bar", {"roadmap_id": 1, "name": "New"}), ("get_bar", {"roadmap_id": True, "bar_id": 2}), ("create_bar", {"roadmap_id": 1, "name": "New", "confirm_mutation": True, "starts_on": "2026-10-07", "ends_on": "2026-10-06"}), ("arbitrary_request", {})]:
        with pytest.raises(ValueError):
            await run(op, args)
    assert wire.calls == []
    wire.responses.append(Response({**ROADMAP, "permission": "viewer"}))
    with pytest.raises(ValueError, match="permission"):
        await run("create_bar", {"roadmap_id": 1, "name": "New", "confirm_mutation": True})
    wire.responses.extend([Response(ROADMAP), Response({**BAR, "child_bar_count": 1})])
    with pytest.raises(ValueError, match="leaf"):
        await run("delete_bar", {"roadmap_id": 1, "bar_id": 2, "confirm_mutation": True})
    current = pn._shape(CREDS)
    monkeypatch.setattr(pn, "_current_data", AsyncMock(side_effect=[current, current, {**current, "approval_revision": 1}]))
    wire.responses.append(Response(ROADMAP))
    with pytest.raises(ValueError, match="changed"):
        await run("create_bar", {"roadmap_id": 1, "name": "New", "confirm_mutation": True})
    assert all(c["method"] == "GET" for c in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,raw,ctype,status", [
    ({"errors": ["private"]}, None, "application/json", 200),
    (page([]), None, "text/html", 200),
    (page([]), None, "application/json", 202),
    (dict(page([]), status="rejected"), None, "application/json", 200),
    (None, b'{"results":[],"paging":{},"meta":NaN}', "application/json", 200),
    (None, b'{"results":[],"paging":{},"meta":1e309}', "application/json", 200),
    (page([]), None, "application/json", 401),
])
async def test_invalid_unexecuted_response_errors_and_secret_privacy(wire, payload, raw, ctype, status):
    wire.responses.append(Response(payload, raw=raw, content_type=ctype, status=status))
    with pytest.raises(pn.ProductPlanAPIError) as caught:
        await run("list_roadmaps")
    assert "private" not in str(caught.value) and CREDS["personal_access_token"] not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_write_uncertainty_nonempty_204_no_replay_and_depth(wire):
    wire.responses.extend([Response(ROADMAP), Response(BAR), Response(status=204, raw=b'{"id":2}')])
    with pytest.raises(pn.ProductPlanAPIError, match="Write outcome is unverified"):
        await run("update_bar", {"roadmap_id": 1, "bar_id": 2, "confirm_mutation": True, "new_name": "Changed"})
    assert len(wire.calls) == 3
    nested = {}
    for _ in range(34):
        nested = {"nested": nested}
    wire.responses.append(Response(dict(page([]), meta=nested)))
    with pytest.raises(pn.ProductPlanAPIError, match="JSON"):
        await run("list_roadmaps")


@pytest.mark.asyncio
async def test_actual_picker_continuation_parent_search_and_bound(wire):
    rows = [{**ROADMAP, "id": i + 1} for i in range(25)]
    wire.responses.append(Response(page(rows, total=26, pages=2)))
    first = await pn.ProductPlanNode.load_field_options("roadmap_id", CREDS, context={"_user_id": "actor"})
    assert len(first["options"]) == 25 and first["next_page_token"]
    with pytest.raises(ValueError, match="continuation"):
        await pn.ProductPlanNode.load_field_options("roadmap_id", CREDS, context={"_user_id": "other"}, page_token=first["next_page_token"])
    wire.responses.append(Response(page([{**ROADMAP, "id": 26}], current=2, total=26, pages=2)))
    second = await pn.ProductPlanNode.load_field_options("roadmap_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    assert second["options"][0]["value"] == "26" and second["next_page_token"] is None
    before = len(wire.calls)
    with pytest.raises(ValueError, match="parent"):
        await pn.ProductPlanNode.load_field_options("bar_id", CREDS, context={"_user_id": "actor"})
    assert len(wire.calls) == before
    wire.responses.append(Response(page([KEY_RESULT])))
    result = await pn.ProductPlanNode.load_field_options("key_result_id", CREDS, context={"_user_id": "actor", "objective_id": 3}, search="4")
    assert result["options"] == [{"value": "4", "label": "Key result (4)"}]
    assert wire.calls[-1]["params"]["q[id_eq]"] == 4
    token = None
    for n in range(40):
        rows = [{**ROADMAP, "id": n * 25 + i + 1} for i in range(25)]
        wire.responses.append(Response(page(rows, current=n + 1, total=1001, pages=41)))
        if n == 39:
            with pytest.raises(pn.ProductPlanAPIError, match="1,000-item bound"):
                await pn.ProductPlanNode.load_field_options("roadmap_id", CREDS, context={"_user_id": "actor"}, page_token=token)
        else:
            token = (await pn.ProductPlanNode.load_field_options("roadmap_id", CREDS, context={"_user_id": "actor"}, page_token=token))["next_page_token"]


@pytest.mark.asyncio
async def test_current_row_family_revocation_before_decrypt_and_owned_lookup(monkeypatch, wire):
    from nodes.productplan_node import ProductPlanCredentialsRepo as CredentialsRepo
    from utils import credentials, encryption
    row = CredentialValidationRow(pn.FAMILIES[0], "owner", 2, STAMP, 0, None, "sealed")
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: (_ for _ in ()).throw(AssertionError("No decrypt"))))
    for actual in (None, replace(row, revoked_at=STAMP), replace(row, credential_type="http_bearer"), replace(row, token_version=0), replace(row, owner_id="")):
        monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", AsyncMock(return_value=actual))
        with pytest.raises(ValueError):
            await pn.ProductPlanNode.freshen_credential(CREDS, credential_id="saved", user_id="actor", pool=object(), organization_id="org")
    assert wire.calls == []
    from wss.handlers import workflow_handler
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="org"))
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=object())
    seen = []
    async def authority(self, cid, principal, org):
        seen.append((cid, principal, org))
        return row if principal == "owner" else None
    monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", authority)
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value="owner"))
    permitted = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", permitted)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: {**CREDS, "personal_access_token": "y" * 64, "credential_type": "stale"}))
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append(Response(page([ROADMAP])))
    result = await run_node_lookup(node_type=pn.NODE_TYPE, field_name="roadmap_id", credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="flow", context={"_credential_id": "forged", "_user_id": "forged"})
    assert result["options"][0]["value"] == "1" and wire.calls[0]["headers"]["Authorization"] == "Bearer " + "y" * 64
    assert seen == [("saved", p, "org") for p in ["actor", "owner"] * 2] and permitted.await_count == 2
    permitted.return_value = False
    with pytest.raises(ValueError):
        await pn.ProductPlanNode.freshen_credential(CREDS, credential_id="saved", user_id="actor", pool=object(), organization_id="org", workflow_id="flow")


@pytest.mark.asyncio
async def test_legacy_validation_defers_to_saved_connection_evidence():
    assert (await pn.ProductPlanNode.validate_credential_access(CREDS))["valid"] is None
    assert (await pn.ProductPlanNode.validate_credential_access({}))["valid"] is False


@pytest.mark.asyncio
async def test_native_strict_public_overrides_private_allowance(monkeypatch, wire):
    from utils import ssrf
    sent = []
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    real_client = PUBLIC_CLIENT
    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200)))
    monkeypatch.setattr(pn, "guarded_async_client", client)
    with pytest.raises(pn.ProductPlanAPIError, match="transport failed"):
        await run("test_connection")
    lookup.assert_awaited_once_with("app.productplan.com", 443, type=socket.SOCK_STREAM)
    assert sent == []


@pytest.mark.asyncio
async def test_public_transport_pins_dns_even_with_private_override(monkeypatch):
    from utils import ssrf
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    transport = AsyncMock()
    backend = pn._ProductPlanPublicBackend(backend=transport)
    await backend.connect_tcp("app.productplan.com", 443)
    assert transport.connect_tcp.await_args.args == ("93.184.215.14", 443)
    transport.reset_mock()
    lookup.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
    with pytest.raises(ssrf.SSRFError):
        await backend.connect_tcp("app.productplan.com", 443)
    transport.connect_tcp.assert_not_awaited()

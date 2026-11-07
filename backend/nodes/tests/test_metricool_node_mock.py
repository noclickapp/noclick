"""Unrun Metricool native factory/connect/admission/current-row/draft fixtures.

Only storage/encryption and HTTP boundaries are synthetic. These cases claim no
actual account entitlement, provider permission, publication or passing gate.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import metricool_node as native
from nodes.core import credential_connect, connection_evidence, registry, run_op
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, encryption
from wss.handlers import credentials_handler, workflow_handler
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE, USER, ORG = "automation-metricool", "fixture-user", "fixture-org"
CID = "00000000-0000-4000-8000-000000000042"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
RANGE = {"blog_id": "7", "start": "2026-10-01T00:00:00", "end": "2026-10-10T00:00:00", "timezone": "UTC"}
BRAND = {"id": 7, "userId": 91, "ownerUserId": 91, "label": "Shared fixture brand", "isShared": True,
    "hash": "private-fixture", "whiteLabelLink": "https://private.example/fixture", "tiktokBusinessTokenExpiration": "private-fixture"}
POST = {"id": 42, "draft": True, "text": "Fixture draft", "publicationDate": {"dateTime": "2026-10-08T12:00:00", "timezone": "UTC"},
    "providers": [{"network": "facebook", "status": "DRAFT", "detailedStatus": "private-fixture"}],
    "parentId": None, "descendants": [], "media": [], "postApprovalData": None, "libraryPostId": None,
    "creatorUserMail": "private-fixture", "notes": [{"text": "private-fixture"}]}
OPS = {"list_brands", "get_default_brand", "get_social_timeline", "list_instagram_posts", "list_facebook_posts", "list_linkedin_posts",
    "list_scheduler_posts", "get_scheduler_post", "get_scheduler_counters", "list_library_states", "create_draft", "update_draft", "delete_draft"}


@pytest.fixture
def ensure_native_db_pool(): yield


@pytest.fixture
def local(monkeypatch):
    state = SimpleNamespace(row={"id": CID, "name": "Synthetic Metricool", "credential_type": "metricool_api_key",
        "credential": b"synthetic-encrypted", "metadata": {}, "owner_id": USER, "token_version": 7,
        "approval_revision": 0, "created_at": UPDATED, "updated_at": UPDATED, "revoked_at": None},
        blob={"credential_type": "metricool_api_key", "api_token": "synthetic-metricool-token", "user_id": "23", "blog_id": "7"},
        allowed=True, allowed_users={USER}, requests=[], queries=[], responses=[], pending=None, status=200, raw=None,
        payload=None, mutation=None, brands=[deepcopy(BRAND)], posts=[deepcopy(POST)], write_status=None, ignore_write=False, paging=None)

    class Pool:
        @asynccontextmanager
        async def acquire(self): yield self

        async def fetchrow(self, sql, credential_id, user_id, org_id):
            assert "FROM credentials c" in sql and credential_id == CID and org_id == ORG
            assert user_id in {USER, "fixture-workflow-owner"}
            state.queries.append(sql)
            return deepcopy(state.row) if state.allowed and user_id in state.allowed_users else None

    state.pool = Pool()
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    for module in (credentials, encryption, credentials_handler, workflow_handler): monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: state.pool)
    monkeypatch.setattr("utils.credential_approval.get_native_pool", lambda: state.pool)
    monkeypatch.setattr(credentials, "get_native_pool", lambda: state.pool)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(side_effect=lambda **_: state.pending))

    def transport(request):
        assert request.url.host == "app.metricool.com" and request.url.path.startswith("/api/")
        assert "Authorization" not in request.headers and request.headers["X-Mc-Auth"] == "synthetic-metricool-token"
        assert request.url.params["userId"] == state.blob["user_id"]
        state.requests.append(request)
        if state.mutation: state.mutation(request)
        status = state.write_status if request.method != "GET" and state.write_status is not None else state.status
        if state.raw is not None: return httpx.Response(status, content=state.raw, headers={"Content-Type": "application/json"})
        if state.payload is not None: return httpx.Response(status, json=deepcopy(state.payload))
        route = request.url.path.removeprefix("/api")
        if request.method in {"POST", "PUT"}:
            body = json.loads(request.content)
            assert body["draft"] is True and body["providers"] == [{"network": "facebook"}]
            assert not {"autoPublish", "postApprovalData", "media", "saveExternalMediaFiles", "targetBrandId"}.intersection(body)
            record = deepcopy(POST)
            record.update(text=body["text"], publicationDate=body["publicationDate"], id=43 if request.method == "POST" else 42)
            if not state.ignore_write:
                if request.method == "POST": state.posts.append(record)
                else: state.posts[0] = record
            payload = {"data": record}
        elif request.method == "DELETE":
            if not state.ignore_write: state.posts = []
            payload = {"data": True}
        elif route == "/admin/simpleProfiles": payload = state.brands
        elif route == "/v2/scheduler/posts": payload = {"data": state.posts, **({"page": {"next": state.paging}} if state.paging is not None else {})}
        elif route.startswith("/v2/scheduler/posts/"): payload = {"data": next(row for row in state.posts if str(row["id"]) == route.rsplit("/", 1)[-1])}
        elif route == "/v2/scheduler/counters": payload = {"data": {"monthPublishedPostsByUser": 12, "monthPublishedPostsByBrand": 4, "aiSpentCreditsThisMonth": 100}}
        elif route == "/v2/scheduler/library/states": payload = {"data": [{"id": 8, "name": "Fixture", "color": "#123456", "position": 0, "private": "private-fixture"}]}
        elif route == "/v2/analytics/timelines": payload = {"data": [{"metric": request.url.params["metric"], "values": [{"dateTime": "2026-10-02T00:00:00Z", "value": 12, "private": "private-fixture"}]}]}
        else: payload = {"data": [{"postId": "fixture-social-post", "blogId": 7, "likes": 2, "comments": 1, "spend": 999, "picture": "https://private.example/fixture"}]}
        return httpx.Response(status, json=deepcopy(payload))

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    state.handler = credentials_handler.CredentialsHandler(sio)
    state.handler.get_pool = AsyncMock(return_value=state.pool)
    state.picker = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    state.picker.sio, state.picker.get_pool = sio, AsyncMock(return_value=state.pool)

    async def capture(_sio, sid, event, **_):
        assert sid == "fixture-sid"
        state.responses.append(event.model_dump())

    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    return state


async def run(local, operation="list_brands", **arguments):
    return await run_op.run_node_operation(node_type=NODE, operation=operation, arguments=arguments, user_id=USER,
        pool=local.pool, credential_id=CID, organization_id=ORG)


async def validate(local):
    request = CredentialValidateAccessRequest(request_id="fixture-validation", node_type=NODE, credential_id=CID)
    await local.handler.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


async def pick(local, **kwargs):
    request = WorkflowNodeLoadOptionsRequest(request_id="fixture-picker", node_type=NODE, field_name="blog_id", credential_id=CID, **kwargs)
    await local.picker.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


def test_actual_catalog_native_schema_secret_fields_and_brand_evidence():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    from nodes.agent.node_op_tools import node_supports_op_tools
    assert registry.NODE_REGISTRY[NODE] is native.MetricoolNode
    assert {op.name for op in get_operations_for_node_type(NODE)} == OPS
    assert node_accepted_credential_types(NODE) == {"metricool_api_key"} and node_supports_op_tools(NODE)
    assert native.MetricoolNode.get_config_schema()["$defs"]["MetricoolAPIKeyCredential"]["required"] == ["api_token", "user_id", "blog_id"]
    assert native.MetricoolNode.connection_evidence.identity_operation is None
    assert "synthetic" not in repr(native.MetricoolAPIKeyCredential(api_token="synthetic", user_id="23", blog_id="7"))


@pytest.mark.parametrize("fields", [{"api_token": "bad\nkey"}, {"user_id": True}, {"blog_id": "../admin"}, {"blog_id": "2147483648"}])
def test_actual_connect_shape_refuses_bad_key_and_scope(fields):
    _, errors, resolved = credential_connect.shape_credential("metricool_api_key", {"api_token": "synthetic", "user_id": "23", "blog_id": "7", **fields})
    assert errors and resolved[0] == NODE


@pytest.mark.asyncio
async def test_actual_factory_x_mc_auth_current_scope_shared_brand_not_false_owner_identity(local):
    local.blob["credential_type"] = "stale-blob-type"
    result = await run(local)
    assert result["status"] == "success" and result["items"][0]["isShared"] is True
    assert dict(local.requests[-1].url.params) == {"userId": "23", "blogId": "7"}
    assert "private-fixture" not in json.dumps(result) and "ownerUserId" not in result["items"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "revoked", "wrong_type"])
async def test_unavailable_current_authority_before_http(local, case):
    if case == "missing": local.allowed = False
    if case == "revoked": local.row["revoked_at"] = UPDATED
    if case == "wrong_type": local.row["credential_type"] = "buffer_api_key"
    try: assert (await run(local))["category"] == "authority"
    except ValueError: pass
    assert not local.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["pending", "rejected"])
async def test_actual_admission_collector_saved_hook_no_invented_execution(local, pending):
    local.pending = {"id": "fixture-approval", "status": pending, "new_request": False}
    assert (await run(local))["executed"] is False
    evidence = await connection_evidence.collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=local.pool, organization_id=ORG)
    assert evidence.reachable is None and evidence.samples == []
    assert not local.requests


@pytest.mark.asyncio
async def test_actual_connect_brand_evidence_serialization_no_identity_invention(local, monkeypatch):
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type="metricool_api_key", credential_data=local.blob, user_id=USER, pool=local.pool, organization_id=ORG)
    assert verdict.ok and verdict.evidence.account_label is None
    from wss.sender.responses import CredentialTestConnectionResponse
    serialized = CredentialTestConnectionResponse.from_evidence(verdict.evidence).model_dump()
    assert serialized["proves"] == "account" and serialized["samples"][0]["label"] == BRAND["label"]
    assert "private-fixture" not in json.dumps(serialized)


@pytest.mark.asyncio
async def test_saved_hook_and_actual_socket_picker_ignore_caller_user_token_url(local):
    assert (await validate(local))["valid"] is True
    result = await pick(local, context={"userId": "999", "blogId": "999", "api_token": "caller-token", "base_url": "https://private.example"})
    assert result["options"][0]["value"] == "7" and local.requests[-1].url.params["userId"] == "23"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "token", "user", "brand", "access"])
async def test_saved_current_authority_races_refuse_after_read(local, change):
    def mutation(_):
        if change == "revoked": local.row["revoked_at"] = UPDATED
        if change == "token": local.blob["api_token"] = "changed-synthetic"
        if change == "user": local.blob["user_id"] = "99"
        if change == "brand": local.blob["blog_id"] = "99"
        # A saved credential edit replaces the ciphertext as well as its decrypted fields.
        if change in {"token", "user", "brand"}: local.row["credential"] = b"changed-synthetic-encrypted"
        if change == "access": local.allowed = False
    local.mutation = mutation
    assert (await run(local))["category"] == "authority" and len(local.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["malformed", "outage", "accepted", "shape", "duplicate"])
async def test_ambiguous_read_unknown_and_private_errors_omitted(local, case):
    if case == "malformed": local.raw = b"{broken"
    if case == "outage": local.status = 503
    if case == "accepted": local.status = 202
    if case == "shape": local.payload = {"error_message": "synthetic-metricool-token private-fixture"}
    if case == "duplicate": local.raw = b'{"id":7,"id":8}'
    result = await validate(local)
    assert result["valid"] is None and "private-fixture" not in json.dumps(result) and "synthetic-metricool-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_selected_brand_and_post_window_witness_precede_child_lookup(local):
    result = await run(local, "list_instagram_posts", **{**RANGE, "blog_id": "8"})
    assert result["category"] == "permission" and len(local.requests) == 1
    local.requests.clear()
    result = await run(local, "get_scheduler_post", post_id="99", **RANGE)
    assert result["category"] == "permission" and [r.url.path for r in local.requests] == ["/api/admin/simpleProfiles", "/api/v2/scheduler/posts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_instagram_posts", "list_facebook_posts", "list_linkedin_posts"])
async def test_actual_social_typed_data_projection_and_date_scope(local, operation):
    result = await run(local, operation, **RANGE)
    expected = {"postId": "fixture-social-post", "comments": 1}
    if operation != "list_facebook_posts": expected["likes"] = 2
    assert result["status"] == "success" and result["items"] == [expected]
    assert "spend" not in json.dumps(result) and "private.example" not in json.dumps(result)
    assert dict(local.requests[-1].url.params) == {"userId": "23", "blogId": "7", "from": RANGE["start"], "to": RANGE["end"], "timezone": "UTC"}


@pytest.mark.asyncio
async def test_actual_timeline_counters_library_and_unfollowed_page_next(local):
    timeline = await run(local, "get_social_timeline", network="instagram", metric="likes", **RANGE)
    assert timeline["items"][0]["values"] == [{"dateTime": "2026-10-02T00:00:00Z", "value": 12}]
    assert local.requests[-1].url.params["subject"] == "posts"
    assert (await run(local, "get_scheduler_counters", blog_id="7"))["counters"] == {"monthPublishedPostsByUser": 12, "monthPublishedPostsByBrand": 4}
    assert (await run(local, "list_library_states", blog_id="7"))["items"][0]["id"] == "8"
    local.paging = "https://private.example/?userToken=private-fixture"
    result = await run(local, "list_scheduler_posts", **RANGE)
    assert result["has_more"] is True and result["pagination_following_supported"] is False
    assert "private-fixture" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_draft", "update_draft", "delete_draft"])
async def test_actual_closed_draft_crud_retains_nonpublishing_state_and_same_scope_readback(local, operation):
    args = {"blog_id": "7", "text": "Changed fixture", "planning_time": "2026-10-08T12:00:00", "timezone": "UTC"} if operation == "create_draft" else {**RANGE, "post_id": "42", **({"text": "Changed fixture"} if operation == "update_draft" else {})}
    result = await run(local, operation, **args)
    assert result["status"] == "success" and result["readback_performed"] is True
    writes = [r for r in local.requests if r.method != "GET"]
    assert len(writes) == 1 and writes[0].url.params["blogId"] == "7"
    if operation != "delete_draft":
        assert result["record"]["draft"] is True and result["record"]["providers"] == [{"network": "facebook", "status": "DRAFT"}]
        assert json.loads(writes[0].content)["draft"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["scheduled", "status", "parent", "descendants", "media", "approval", "unknown"])
async def test_nondraft_thread_media_and_unknown_state_refuse_before_write(local, case):
    row = local.posts[0]
    if case == "scheduled": row["draft"] = False
    if case == "status": row["providers"][0]["status"] = "PENDING"
    if case == "parent": row["parentId"] = 9
    if case == "descendants": row["descendants"] = [{"id": 8}]
    if case == "media": row["media"] = ["private-fixture"]
    if case == "approval": row["postApprovalData"] = {"sendMailToReviewers": True}
    if case == "unknown": row.pop("descendants")
    result = await run(local, "update_draft", post_id="42", text="Changed", **RANGE)
    assert result["mutation_outcome"] == "not_attempted" and all(r.method == "GET" for r in local.requests)


@pytest.mark.asyncio
async def test_failed_mutation_readback_preserves_cleanup_id_and_does_not_retry(local):
    local.write_status = 202
    result = await run(local, "update_draft", post_id="42", text="Changed", **RANGE)
    assert result["selected_id"] == "42" and result["mutation_outcome"] == "unverified"
    assert len([r for r in local.requests if r.method == "PUT"]) == 1
    local.write_status, local.ignore_write = None, True
    result = await run(local, "create_draft", blog_id="7", text="New fixture", planning_time="2026-10-08T12:00:00")
    assert result["selected_id"] == "43" and result["mutation_outcome"] == "unverified"


@pytest.mark.asyncio
async def test_actual_agent_field_scope_and_unclosed_operation_refusal(local):
    from nodes.agent.tool_execution import _execute_node_op_tool
    agent = SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=None, conversation_id="fixture-conversation")
    tool = {"node_type": NODE, "operation": "list_brands", "credential_id": CID}
    assert (await _execute_node_op_tool(agent, "metricool_brands", {}, tool, []))["status"] == "success"
    result = await _execute_node_op_tool(agent, "metricool_posts", RANGE, {**tool, "operation": "list_scheduler_posts", "field_scopes": {"blog_id": ["8"]}}, [])
    assert result["success"] is False and len(local.requests) == 1
    for op, args in [("publish", {}), ("generic_request", {}), ("create_draft", {"blog_id": "7", "text": "Fixture", "planning_time": "2026-10-08T12:00:00", "draft": False}),
        ("get_social_timeline", {**RANGE, "network": "instagram", "metric": "reactions"}), ("list_scheduler_posts", {**RANGE, "end": "2027-01-01T00:00:00"})]:
        with pytest.raises(ValueError): await run(local, op, **args)
    assert len(local.requests) == 1


@pytest.mark.asyncio
async def test_canonical_authorized_workflow_owner_fallback_withdrawal(local, monkeypatch):
    owner = "fixture-workflow-owner"
    local.allowed_users, local.row["owner_id"] = {owner}, owner
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=owner))
    authorized = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", authorized)
    async def workflow_run():
        return await run_op.run_node_operation(node_type=NODE, operation="list_brands", arguments={}, user_id=USER,
            pool=local.pool, credential_id=CID, organization_id=ORG, workflow_id="fixture-workflow")
    assert (await workflow_run())["status"] == "success"
    authorized.assert_awaited_with(local.pool, "fixture-workflow", CID)
    local.mutation = lambda _: setattr(authorized, "return_value", False)
    assert (await workflow_run())["category"] == "authority"


@pytest.mark.asyncio
async def test_resolved_credentials_support_standalone_draft_execution(local):
    data = {"credentials": local.blob, "config": {"operation": "create_draft",
        "blog_id": "7", "text": "Standalone fixture", "planning_time": "2026-10-08T12:00:00", "timezone": "UTC"}}
    node = native.MetricoolNode(node_id="fixture", node_type=NODE, node_data=data,
        config=native.MetricoolNodeConfig.model_validate(data))
    result = await node.execute({})
    assert result["status"] == "success" and result["readback_performed"] is True
    assert result["record"]["draft"] is True
    assert len([r for r in local.requests if r.method == "POST"]) == 1

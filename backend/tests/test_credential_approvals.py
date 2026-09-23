"""Credential restrictions use real database transactions and the shared runner.

These tests cover cross-account isolation, concurrent one-use admission, stale
policies, and the boundary between machine requests and human decisions.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from nodes.core.base import WorkflowNode, NodeConfig
from repositories.credential_approvals import CredentialApprovalRepo
from utils.credential_actions import CredentialActions

USER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000003"
OP = "automation-gmail.send_email_message"
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def approval_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    await pool.execute("INSERT INTO auth.users(id,email) VALUES($1::uuid,'approval-other@example.test') ON CONFLICT DO NOTHING", OTHER)
    ids = [str(uuid.uuid4()) for _ in range(2)]
    for cid in ids:
        await pool.execute("INSERT INTO credentials(id,owner_id,name,credential_type,credential) VALUES($1::uuid,$2::uuid,'Mail','google_gmail_oauth','encrypted-test')", cid, USER)
    try:
        yield pool, CredentialApprovalRepo(pool), ids
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE source='credential_approval' AND user_id=$1::uuid", USER)
        await pool.execute("DELETE FROM credentials WHERE id=ANY($1::uuid[])", [uuid.UUID(cid) for cid in ids])
        await pool.close()


def call(cid, **kwargs):
    return dict(credential_id=cid, user_id=USER, node_type="automation-gmail", operation="send_email_message",
                arguments={"to": ["recipient@example.test"], "subject": "Hello"}, **kwargs)


async def test_credential_isolation_and_monotonic_machine_rules(approval_db):
    _, repo, (a, b) = approval_db
    assert await repo.admit(**call(a)) is None
    await repo.tighten(a, USER, [OP])
    assert await repo.tighten(a, USER, []) == [OP]
    assert await repo.admit(**call(b)) is None
    assert (await repo.admit(**call(a)))["status"] == "pending"
    with pytest.raises(PermissionError):
        await repo.tighten(a, OTHER, ["*"])
    with pytest.raises(PermissionError):
        await repo.policy(a, OTHER)


async def test_pending_dedup_and_one_approved_call_under_concurrency(approval_db):
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    requests = await asyncio.gather(*(repo.admit(**call(cid)) for _ in range(5)))
    assert len({row["id"] for row in requests}) == 1
    request = requests[0]
    with pytest.raises(ValueError):
        await repo.decide_from_human(str(request["id"]), OTHER, "approved")
    await repo.decide_from_human(str(request["id"]), USER, "approved")
    results = await asyncio.gather(*(repo.admit(**call(cid)) for _ in range(5)))
    assert sum(result is None for result in results) == 1
    assert await pool.fetchval("SELECT consumed_at IS NOT NULL FROM approval_requests WHERE id=$1", request["id"])
    with pytest.raises(ValueError):
        await repo.decide_from_human(str(request["id"]), USER, "rejected")


async def test_approval_does_not_cover_changed_arguments_or_tightened_policy(approval_db):
    _, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    pending = await repo.admit(**call(cid))
    await repo.decide_from_human(str(pending["id"]), USER, "approved")
    changed = call(cid)
    changed["arguments"] = {"to": ["different@example.test"]}
    assert (await repo.admit(**changed))["status"] == "pending"
    await repo.tighten(cid, USER, ["*"])
    assert (await repo.admit(**call(cid)))["status"] == "pending"
    with pytest.raises(ValueError):
        await repo.replace_from_human(cid, USER, [], expected_revision=1)
    assert await repo.replace_from_human(cid, USER, [], expected_revision=2) == 3
    assert await repo.admit(**call(cid)) is None


async def test_expired_and_rejected_approvals_never_admit(approval_db):
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    request = await repo.admit(**call(cid))
    await repo.decide_from_human(str(request["id"]), USER, "rejected")
    assert (await repo.admit(**call(cid)))["status"] == "rejected"
    await pool.execute("UPDATE approval_requests SET expires_at=now()-interval '1 second' WHERE id=$1", request["id"])
    assert (await repo.admit(**call(cid)))["id"] != request["id"]


async def test_decision_and_coordinator_wakeup_commit_together(approval_db):
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    pending = await repo.admit(**call(cid, conversation_id=f"coordinator:{USER}",
        continuation={"epoch": "test", "depth": 0, "channel": "whatsapp_text", "request": "Send it"}))
    await repo.decide_from_human(str(pending["id"]), USER, "approved")
    event = await pool.fetchrow("SELECT payload,send_to_phone FROM coordinator_wakeups WHERE source_id=$1", pending["id"])
    assert event["payload"]["status"] == "approved" and event["send_to_phone"]


class MailConfig(BaseModel):
    operation: str = "send_email_message"
    to: str = "recipient@example.test"


class TestMailNode(WorkflowNode):
    __test__ = False
    async def execute(self, inputs):
        return await self.provider()


async def test_shared_node_boundary_never_calls_provider_before_approval(approval_db):
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    node = TestMailNode("mail", "automation-gmail", {"credential_id": cid, "_approval_pool": pool},
                        config=NodeConfig[MailConfig, None](config=MailConfig()), user_id=USER)
    node.provider = AsyncMock(return_value={"sent": True})
    pending = await node.run({})
    assert pending["executed"] is False and pending["status"] == "pending_approval"
    node.provider.assert_not_awaited()
    await repo.decide_from_human(pending["approval_id"], USER, "approved")
    assert (await node.run({}))["sent"] is True
    node.provider.assert_awaited_once()
    assert (await node.run({}))["status"] == "pending_approval"


async def test_connect_without_workflow_or_email_reuses_live_link(approval_db):
    pool, _, _ = approval_db
    actions = CredentialActions(pool=pool, user_id=USER)
    first = await actions.connect_credential("whatsapp_qr")
    second = await actions.connect_credential("whatsapp_qr")
    assert first["url"] == second["url"]
    assert first["request_id"] == second["request_id"]
    row = await pool.fetchrow("SELECT target_email,status FROM credential_requests WHERE id=$1::uuid", first["request_id"])
    assert row["target_email"] == "" and row["status"] == "pending"
    assert (await actions.credential_connection_status(first["request_id"]))["credential_id"] is None


async def test_browser_session_required_even_with_valid_machine_identity(monkeypatch):
    from fastapi import HTTPException
    from utils import credential_approval_routes as routes
    verifier = AsyncMock(return_value={"sub": USER, "role": "authenticated"})
    monkeypatch.setattr(routes, "verify_token", verifier)
    with pytest.raises(HTTPException) as error:
        await routes.human("Bearer machine-token")
    assert error.value.status_code == 401
    verifier.return_value = {"sub": USER, "role": "authenticated", "session_id": str(uuid.uuid4())}
    assert await routes.human("Bearer browser-token") == USER


async def test_legacy_socket_decision_cannot_approve_or_edit_credential_request(approval_db):
    from repositories.feed import FeedRepo
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    pending = await repo.admit(**call(cid))
    assert await FeedRepo(pool).resolve_approval(
        approval_id=pending["id"], decision="approved", decided_by_user_id=USER,
        values={"to": ["swapped@example.test"]},
    ) is None
    row = await repo.request(str(pending["id"]), USER)
    assert row["status"] == "pending"
    assert row["action_payload"]["arguments"]["to"] == ["recipient@example.test"]


async def test_dashboard_includes_personal_credential_approvals_in_org_context(approval_db):
    from repositories.feed import FeedRepo
    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    request = await repo.admit(**call(cid))
    pending, _ = await FeedRepo(pool).list_approvals(user_id=USER, org_uuid=uuid.uuid4())
    assert request["id"] in {row.id for row in pending}
    outsiders, _ = await FeedRepo(pool).list_approvals(user_id=OTHER, org_uuid=None)
    assert request["id"] not in {row.id for row in outsiders}
    await repo.tighten(cid, USER, ["*"])
    stale, _ = await FeedRepo(pool).list_approvals(user_id=USER, org_uuid=None)
    assert request["id"] not in {row.id for row in stale}


async def test_no_raw_token_export_or_lookup_bypass(approval_db, monkeypatch):
    from utils.credential_approval import forbid_secret_export
    from nodes.core.run_op import run_node_lookup
    from nodes.linear_node import LinearNode

    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    with pytest.raises(PermissionError, match="cannot be exported"):
        await forbid_secret_export(cid, pool=pool)
    loader = AsyncMock(return_value={"options": []})
    monkeypatch.setattr(LinearNode, "load_field_options", loader)
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value={"credential_type": "linear_pat", "api_key": "test"}))
    result = await run_node_lookup(node_type="automation-linear", field_name="team_id", credential_id=cid, user_id=USER, pool=pool)
    assert result["status"] == "pending_approval"
    loader.assert_not_awaited()


async def test_registered_mcp_call_creates_pending_approval_before_provider(approval_db, monkeypatch):
    from unittest.mock import MagicMock, patch
    from mcp_server import NoClickMCPServer, _user_id_var
    from nodes.gmail_node import GmailNode

    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
        server = NoClickMCPServer(MagicMock())
    monkeypatch.setattr(server, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value={
        "credential_type": "google_gmail_oauth", "access_token": "test", "refresh_token": "test",
        "expires_at": "2030-01-01T00:00:00Z", "email": "owner@example.test",
    }))
    provider = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(GmailNode, "execute", provider)
    token = _user_id_var.set(USER)
    try:
        tools = {tool.name: tool.fn for tool in await server.mcp.list_tools()}
        args = {"credential_id": cid, "node_type": "automation-gmail", "operation": "send_email_message",
                "arguments": {"to": ["recipient@example.test"], "subject": "Hello", "body": "Draft"}}
        result = await tools["call_credential_operation"](**args)
        assert result["status"] == "pending_approval"
        provider.assert_not_awaited()
        await repo.decide_from_human(result["approval_id"], USER, "approved")
        assert (await tools["call_credential_operation"](**args))["status"] == "success"
        provider.assert_awaited_once()
        assert "relax_credential_approval" not in tools
    finally:
        _user_id_var.reset(token)


async def test_phone_only_account_can_open_standalone_connection_link(approval_db, monkeypatch):
    from utils import credential_request_routes as routes
    pool, _, _ = approval_db
    await pool.execute("UPDATE auth.users SET email=NULL,raw_user_meta_data='{}' WHERE id=$1::uuid", OTHER)
    try:
        actions = CredentialActions(pool=pool, user_id=OTHER)
        connection = await actions.connect_credential("whatsapp_qr")
        token = connection["url"].rsplit("/", 1)[-1]
        monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
        details = await routes.get_credential_request(token)
        assert details.requester_name == "Your account"
        assert details.credential_type == "whatsapp_qr"
    finally:
        await pool.execute("UPDATE auth.users SET email='approval-other@example.test' WHERE id=$1::uuid", OTHER)


async def test_parallel_workflow_approvals_resume_once_after_checkpoint(approval_db, monkeypatch):
    """Real engine + admission + SQL; only checkpoint storage/relay/provider are stubs."""
    import copy
    from unittest.mock import MagicMock
    from utils.credential_approval_dispatch import resume_workflows
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    pool, repo, (cid, _) = approval_db
    await repo.tighten(cid, USER, [OP])
    workflow_id, execution_id = str(uuid.uuid4()), str(uuid.uuid4())
    nodes = [{"id": nid, "type": "automation-gmail", "config": {}} for nid in ("a", "b", "sink")]
    edges = [{"id": nid, "source": nid, "target": "sink"} for nid in ("a", "b")]
    await pool.execute("INSERT INTO workflows(id,owner_id,name,workflow) VALUES($1::uuid,$2::uuid,'Approval test',$3)",
                       workflow_id, USER, {"nodes": nodes, "edges": edges})
    await pool.execute("INSERT INTO workflow_executions(id,workflow_id,user_id,status) VALUES($1::uuid,$2::uuid,$3::uuid,'running')",
                       execution_id, workflow_id, USER)
    monkeypatch.setattr("utils.database_pool._native_pool", pool)
    sio = MagicMock()
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: sio)
    monkeypatch.setattr("wss.handlers.workflow_execution_handler.send_event", AsyncMock())
    monkeypatch.setattr("utils.credential_approval.notify_created", AsyncMock())
    relay = MagicMock(connect=AsyncMock(return_value=True), disconnect=AsyncMock())
    async def stopped(*args, **kwargs):
        await asyncio.Event().wait()
    relay.listen_for_stop = stopped
    monkeypatch.setattr("utils.execution_relay.create_execution_relay", lambda *a, **kw: relay)
    provider = AsyncMock(return_value={"sent": True})
    ran = []
    async def execute(self, node, outputs, sid, user_id, wf, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
        if node['id'] == 'sink':
            ran.append('sink')
            return {"done": True}
        instance = TestMailNode(node['id'], "automation-gmail", {"credential_id": cid, "_approval_pool": pool},
                                config=NodeConfig[MailConfig, None](config=MailConfig()), user_id=USER,
                                workflow_id=wf, execution_id=execution_id)
        instance.provider = provider
        return await instance.run({})
    monkeypatch.setattr(WorkflowExecutionHandler, "_execute_node", execute)
    checkpoint = {}
    async def load(*args):
        return copy.deepcopy(checkpoint)
    async def persist(self, wf, user_id, outputs, **kwargs):
        checkpoint.update(copy.deepcopy(outputs))
    monkeypatch.setattr("utils.node_outputs.execution_outputs", load)
    monkeypatch.setattr(WorkflowExecutionHandler, "_persist_node_outputs", persist)
    handler = WorkflowExecutionHandler(sio)
    try:
        result = await handler._execute_nodes_concurrent(nodes, edges, '', USER, workflow_id, execution_id=execution_id)
        outputs = result[2]
        assert outputs['a']['status'] == outputs['b']['status'] == 'pending_approval'
        assert not ran
        provider.assert_not_awaited()
        await repo.decide_from_human(outputs['a']['approval_id'], USER, 'approved')
        assert not await repo.resumable_workflows(execution_id), 'wait for this batch before running shared downstream'
        await repo.decide_from_human(outputs['b']['approval_id'], USER, 'approved')
        assert await resume_workflows(pool, execution_id) is False, 'instant approval waits for checkpoint'
        checkpoint.update(copy.deepcopy(outputs))
        await asyncio.gather(resume_workflows(pool, execution_id), resume_workflows(pool, execution_id))
        assert provider.await_count == 2
        assert ran == ['sink']
        assert await pool.fetchval("SELECT status FROM workflow_executions WHERE id=$1::uuid", execution_id) == 'completed'
        await resume_workflows(pool, execution_id)
        assert provider.await_count == 2 and ran == ['sink']
    finally:
        await pool.execute("DELETE FROM workflow_executions WHERE id=$1::uuid", execution_id)
        await pool.execute("DELETE FROM workflows WHERE id=$1::uuid", workflow_id)


async def test_scheduler_approval_callback_rejects_forgery_and_retries_missing_checkpoint(monkeypatch):
    import json
    from fastapi import HTTPException
    from starlette.requests import Request
    from utils import coordinator_wakeup_routes as routes
    from utils.scheduler_delivery import delivery_headers

    secret = 'test-scheduler-secret'
    monkeypatch.setattr(routes.scheduler, 'CRON_SCHEDULER_SECRET', secret)
    monkeypatch.setattr(routes, 'get_native_pool', lambda: object())
    body = {"user_id": USER, "target_kind": "credential_approval", "payload": {"approval_id": str(uuid.uuid4())}}
    raw = json.dumps(body).encode()
    def request(headers):
        async def receive():
            return {"type": "http.request", "body": raw}
        return Request({"type": "http", "method": "POST", "path": "/internal/scheduler/credential-approval",
                        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}, receive)
    row = {"status": "approved", "consumed_at": None, "execution_id": uuid.uuid4()}
    lookup = AsyncMock(return_value=row)
    resume = AsyncMock(return_value=False)
    monkeypatch.setattr(CredentialApprovalRepo, 'scheduled_request', lookup)
    monkeypatch.setattr('utils.credential_approval_dispatch.resume_workflows', resume)
    with pytest.raises(HTTPException) as forged:
        await routes.scheduled_credential_approval(request({}))
    assert forged.value.status_code == 401
    lookup.assert_not_awaited()
    with pytest.raises(HTTPException) as waiting:
        await routes.scheduled_credential_approval(request(delivery_headers(raw, secret)))
    assert waiting.value.status_code == 503
    lookup.assert_awaited_once_with(body['payload']['approval_id'], USER)
    resume.return_value = True
    assert await routes.scheduled_credential_approval(request(delivery_headers(raw, secret))) == {"delivered": True}


async def test_multi_credential_lookup_preserves_grants_until_every_owner_approves(approval_db):
    pool, repo, (a, b) = approval_db
    for cid in (a, b):
        await repo.tighten(cid, USER, ['*'])
    calls = [{**call(cid), 'operation': '__lookup__'} for cid in (a, b)]
    pending = await repo.admit_many(calls)
    assert len(pending) == 2
    await repo.decide_from_human(str(pending[0]['id']), USER, 'approved')
    remaining = await repo.admit_many(calls)
    assert [row['id'] for row in remaining] == [pending[1]['id']]
    assert await pool.fetchval('SELECT consumed_at FROM approval_requests WHERE id=$1', pending[0]['id']) is None
    await repo.decide_from_human(str(pending[1]['id']), USER, 'approved')
    # Opposite credential orders still serialize and admit only one invocation.
    results = await asyncio.gather(repo.admit_many(calls), repo.admit_many(list(reversed(calls))))
    assert sum(not result for result in results) == 1
    assert await pool.fetchval('SELECT count(*) FROM approval_requests WHERE id=ANY($1::uuid[]) AND consumed_at IS NOT NULL',
                              [row['id'] for row in pending]) == 2

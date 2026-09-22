"""Builder-owned lifecycle, attempt fencing, and independent result delivery."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.coordinator.tools import CoordinatorTools, coordinator_tool_params
from coder.workflow import requests
from repositories.builder_requests import BuilderRequestRepo
from repositories.conversation import ConversationRepo
from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
from utils import capabilities, task_notifications
from utils.builder_request import PublicationOptions
from utils.capabilities import INTERFACE_PUBLISH, OWNER_MESSAGE

pytestmark = pytest.mark.asyncio
USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def builder_request_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    workflow_id = str(uuid.uuid4())
    await pool.execute("INSERT INTO workflows(id,owner_id,name,workflow) VALUES ($1::uuid,$2::uuid,'Build test',$3)",
                       workflow_id, USER, {"nodes": [], "edges": []})
    repo = BuilderRequestRepo(pool)

    async def enqueue(**overrides):
        values = dict(user_id=USER, workflow_id=workflow_id,
                      publish=PublicationOptions(subdomain=f"app-{uuid.uuid4().hex[:12]}").model_dump(),
                      origin={"source": "coordinator", "coordinator_conversation_id": f"coordinator:{USER}"},
                      reply_conversation_id=f"coordinator:{USER}", reply_node_id="__coordinator__")
        values.update(overrides)
        return await repo.enqueue(**values)

    try:
        yield pool, repo, workflow_id, enqueue
    finally:
        await pool.execute("DELETE FROM workflows WHERE id=$1::uuid", workflow_id)
        await pool.execute("DELETE FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
        await pool.close()


async def test_concurrent_claims_and_duplicate_requests(builder_request_db):
    _, repo, _, enqueue = builder_request_db
    queued = await enqueue()
    with pytest.raises(ValueError, match="already pending"):
        await enqueue(instructions="Build an agent", publish=None)
    claims = await asyncio.gather(*(repo.claim() for _ in range(5)))
    assert [r["id"] for r in claims if r] == [queued["id"]]
    assert next(r for r in claims if r)["phase"] == "publishing"


@pytest.mark.parametrize("publish_after", [False, True])
async def test_one_lifecycle_through_questions_resume_and_completion(builder_request_db, publish_after):
    pool, repo, _, enqueue = builder_request_db
    queued = await enqueue(instructions="Build an interface", **({} if publish_after else {"publish": None}))
    first = await repo.claim()
    assert first["status"] == "running" and first["phase"] == "building"
    await repo.waiting(USER, first["id"], first["attempt_id"], {"ask_id": "q1", "inputs": []})
    assert await repo.claim() is None
    with pytest.raises(ValueError, match="not waiting"):
        await repo.claim_resume(str(uuid.uuid4()), first["conversation_id"], "q1")
    with pytest.raises(ValueError, match="not waiting"):
        await repo.claim_resume(USER, first["conversation_id"], "wrong")
    # A fresh process resumes the same request with a new execution attempt.
    restarted = BuilderRequestRepo(pool)
    resumed = await restarted.claim_resume(USER, first["conversation_id"], "q1")
    assert resumed["id"] == first["id"] and resumed["attempt_id"] != first["attempt_id"]
    with pytest.raises(ValueError, match="already resumed"):
        await restarted.claim_resume(USER, first["conversation_id"], "q1")
    await repo.build_finished(USER, first["id"], first["attempt_id"], success=True, summary="Stale completion")
    assert (await repo.list_for_user(USER))[0]["status"] == "running"
    await restarted.build_finished(USER, resumed["id"], resumed["attempt_id"], success=True, summary="Built it")
    result = (await repo.list_for_user(USER))[0]
    assert result["id"] == queued["id"] and result["pending_ask"] is None
    assert result["result"]["summary"] == "Built it"
    if publish_after:
        assert result["status"] == "queued" and result["phase"] == "publishing"
        publishing = await repo.claim()
        await repo.finish(publishing["id"], publishing["attempt_id"], result={"publication": {"url": "https://app.example"}})
    else:
        assert result["status"] == "completed"
    await restarted.build_finished(USER, resumed["id"], resumed["attempt_id"], success=False, summary="Late", error="late callback")
    assert (await repo.list_for_user(USER))[0]["status"] == "completed" and await repo.claim() is None


async def test_ownership_failure_and_private_storage(builder_request_db):
    pool, repo, workflow_id, enqueue = builder_request_db
    with pytest.raises(ValueError, match="permission"):
        await enqueue(user_id=str(uuid.uuid4()))
    await enqueue(instructions="Build")
    task = await repo.claim()
    assert await repo.list_for_user(str(uuid.uuid4()), request_id=str(task["id"])) == []
    await repo.build_finished(USER, task["id"], task["attempt_id"], success=False, summary="Failed", error="Build failed")
    assert await repo.claim() is None
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "failed" and row["error"] == "Build failed"
    await pool.execute("UPDATE workflows SET deleted_at=now() WHERE id=$1::uuid", workflow_id)
    with pytest.raises(ValueError, match="Workflow not found"):
        await enqueue()
    assert await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE relname='builder_requests'")
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1,'builder_requests','SELECT,INSERT,UPDATE,DELETE')", role)


@pytest.mark.parametrize("phone_success", [True, False])
async def test_result_and_phone_delivery_are_separate(builder_request_db, monkeypatch, phone_success):
    pool, repo, workflow_id, enqueue = builder_request_db
    queued = await enqueue(send_to_phone=True)
    publish = AsyncMock(return_value={"url": "https://app.example", "app_id": "app", "node_id": "ui"})
    phone = AsyncMock(return_value={"success": phone_success, "error": None if phone_success else "WhatsApp window closed"})
    monkeypatch.setattr(requests, "capability", lambda key: publish if key == INTERFACE_PUBLISH else None)
    monkeypatch.setattr(task_notifications, "capability", lambda key: phone if key == OWNER_MESSAGE else None)
    monkeypatch.setattr(requests, "get_sio", lambda: object())
    emit = AsyncMock()
    monkeypatch.setattr(task_notifications, "send_event", emit)
    await requests.run_request(pool, await repo.claim())
    publish.assert_awaited_once_with(pool, user_id=USER, workflow_id=workflow_id, **queued["publish"])
    claims = await asyncio.gather(*(repo.claim_notification() for _ in range(3)))
    assert sum(row is not None for row in claims) == 1
    await requests.notify_result(pool, next(row for row in claims if row))
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "completed" and row["result"]["publication"]["url"] == "https://app.example"
    assert row["phone_state"] == ("sent" if phone_success else "failed")
    assert row["delivery_error"] == (None if phone_success else "WhatsApp window closed")
    phone.assert_awaited_once_with(pool, USER, "Your interface is published.", link="https://app.example")
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(events) == 1 and "https://app.example" in events[0]["message"]
    assert ("WhatsApp window closed" in events[0]["message"]) is not phone_success
    assert await repo.claim_notification() is None and emit.call_args.kwargs["user_id"] == USER


async def test_interrupted_side_effect_is_not_replayed(builder_request_db):
    pool, repo, _, enqueue = builder_request_db
    await enqueue()
    task = await repo.claim()
    await pool.execute("UPDATE builder_requests SET lease_until=now()-interval '1 second' WHERE id=$1", task["id"])
    await repo.reap_stalled()
    await repo.finish(task["id"], task["attempt_id"], result={"publication": {"url": "late"}})
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "failed" and "may already be live" in row["error"]
    assert row["result"] is None and await repo.claim() is None


async def test_timeout_without_exception_text_is_still_a_failure(builder_request_db, monkeypatch):
    pool, repo, _, enqueue = builder_request_db
    await enqueue()
    monkeypatch.setattr(requests, "capability", lambda _: AsyncMock(side_effect=TimeoutError()))
    await requests.run_request(pool, await repo.claim())
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "failed" and row["error"] and row["result"] is None


async def test_cancel_blocks_follow_through_and_late_callbacks(builder_request_db):
    _, repo, _, enqueue = builder_request_db
    await enqueue(instructions="Build")
    task = await repo.claim()
    await repo.waiting(USER, task["id"], task["attempt_id"], {"ask_id": "q"})
    with pytest.raises(ValueError, match="No cancellable"):
        await repo.cancel(str(uuid.uuid4()), str(task["id"]))
    assert (await repo.cancel(USER, str(task["id"])))["status"] == "cancelled"
    await repo.build_finished(USER, task["id"], task["attempt_id"], success=True, summary="Late")
    with pytest.raises(ValueError, match="not waiting"):
        await repo.claim_resume(USER, task["conversation_id"], "q")
    assert await repo.claim() is None
    await enqueue()
    publishing = await repo.claim()
    with pytest.raises(ValueError, match="cannot be cancelled"):
        await repo.cancel(USER, str(publishing["id"]))


async def test_interrupted_phone_send_is_not_duplicated(builder_request_db, monkeypatch):
    pool, repo, _, enqueue = builder_request_db
    await enqueue(send_to_phone=True)
    task = await repo.claim()
    await repo.finish(task["id"], task["attempt_id"], result={"publication": {"url": "https://app.example"}})
    original = await repo.claim_notification()
    assert original["phone_state"] == "sending"
    await pool.execute("UPDATE builder_requests SET notification_lease_until=now()-interval '1 second' WHERE id=$1", original["id"])
    recovered = await repo.claim_notification()
    assert recovered["phone_state"] == "uncertain"
    phone = AsyncMock()
    monkeypatch.setattr(task_notifications, "capability", lambda _: phone)
    monkeypatch.setattr(requests, "get_sio", lambda: object())
    monkeypatch.setattr(task_notifications, "send_event", AsyncMock())
    await requests.notify_result(pool, recovered)
    phone.assert_not_awaited()
    assert not await repo.complete_notification(original, {}, phone_state="sent", delivery_error=None)
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(events) == 1 and "could not be confirmed" in events[0]["message"]


@pytest.mark.parametrize("instructions,publish", [
    ("Build an agent", None), ("Build a workflow", None), ("Build an interface", {"subdomain": "my-app"}),
    (None, {"subdomain": "existing-app"}),
])
async def test_coordinator_delegates_every_artifact_request_to_builder(builder_request_db, monkeypatch, instructions, publish):
    pool, repo, workflow_id, _ = builder_request_db
    tools = CoordinatorTools(pool=pool, sio=object(), user_id=USER, organization_id=None,
                             conversation_id=f"coordinator:{USER}", reply_channel="voice")
    monkeypatch.setattr(requests, "capability", lambda _: object())
    result = await tools.request_build(instructions, workflow_id=workflow_id, publish=publish)
    assert result["status"] == "queued" and result["phase"] == ("building" if instructions else "publishing")
    row = (await repo.list_for_user(USER))[0]
    assert row["send_to_phone"] and row["origin"]["source"] == "coordinator"
    assert row["conversation_id"] == result["builder_conversation_id"]
    status = await tools.build_status(request_id=result["request_id"])
    assert status["builds"][0]["request_id"] == result["request_id"]
    assert (await tools.cancel_build(result["request_id"]))["status"] == "cancelled"


async def test_one_tool_contract_and_optional_publisher():
    plain = {p["function"]["name"]: p["function"] for p in coordinator_tool_params()}
    publishing = {p["function"]["name"]: p["function"] for p in coordinator_tool_params(include_publishing=True)}
    assert set(plain) == set(publishing)
    assert {"request_build", "build_status", "cancel_build"} <= set(plain)
    assert not {"publish_interface", "publication_status", "cancel_publication"} & set(plain)
    assert "publish" not in plain["request_build"]["parameters"]["properties"]
    assert "publish" in publishing["request_build"]["parameters"]["properties"]
    for invalid in ("../other", "https://example.com", "ab", "a" * 64, "-bad"):
        with pytest.raises(ValueError):
            PublicationOptions(subdomain=invalid)


@pytest.mark.parametrize("publish_after", [False, True])
@pytest.mark.parametrize("source", ["coordinator", "api"])
async def test_builder_worker_and_real_answer_handler_share_the_request(builder_request_db, monkeypatch, publish_after, source):
    pool, repo, workflow_id, enqueue = builder_request_db
    queued = await enqueue(instructions="Build a dashboard", origin={"source": source, "client_reference": "test"},
                           **({} if publish_after else {"publish": None}))
    cid = queued["conversation_id"]
    monkeypatch.setattr(WorkflowBuilderHandler, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(requests, "get_sio", lambda: SimpleNamespace())
    builder = SimpleNamespace(edit=AsyncMock(), generation_id="resumed",
                              graph_state=SimpleNamespace(workflow_name="App", summary="Created dashboard"))
    pending = {"ask_id": "credentials", "inputs": []}
    ask = SimpleNamespace(to_dict=lambda: pending)
    monkeypatch.setattr(capabilities, "_providers", {})
    monkeypatch.setattr("wss.handlers.workflow_builder_handler.send_event", AsyncMock())

    async def start_build(handler, sid, request, caller_user_id=None):
        assert caller_user_id == USER and sid == ""
        assert request.edit_prompt == queued["instructions"]
        assert request.user_context["source"] == source
        await pool.execute(ConversationRepo._UPSERT_CHAT_EVENT_SQL, cid, USER, workflow_id, None, [
            {"role": "user", "message": request.edit_prompt},
            {"role": "assistant", "message": "Connect a credential", "pending_ask": pending},
        ], "Build", None)
        await handler._maybe_notify_agent_ask(request=request, user_id=USER, builder=builder, pending_ask=ask)

    # The worker uses the normal headless builder entry point; only the model is replaced.
    monkeypatch.setattr(WorkflowBuilderHandler, "_edit_workflow_impl", start_build)
    await requests.run_request(pool, await repo.claim())
    assert (await repo.list_for_user(USER))[0]["status"] == "waiting_for_input"

    # Exercise the actual answer handler: it restores caller context from the
    # builder request, independent of coordinator-specific conversation naming.
    handler = WorkflowBuilderHandler(SimpleNamespace())
    monkeypatch.setattr("billing.plan_limits.check_ai_builder_limit", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr("wss.handlers.workflow_builder_handler.AgenticBuilder", lambda **_: builder)
    monkeypatch.setattr(handler, "_create_platform_ops", lambda *a, **k: None)
    monkeypatch.setattr(handler, "_create_skill_provider", lambda *a: None, raising=False)
    monkeypatch.setattr(handler, "_emit_active_gen_started", AsyncMock())
    finished_request = None

    async def finish_build(sid, resumed_builder, *, request, **kwargs):
        nonlocal finished_request
        finished_request = request
        assert request.user_context["source"] == source
        assert request.user_context["client_reference"] == "test"
        assert request.user_context["builder_request_id"] == str(queued["id"])
        await handler._maybe_notify_agent_result(request=request, user_id=USER, builder=builder, segments=[])

    monkeypatch.setattr(handler, "_drive_builder_and_terminate", finish_build)
    await handler.handle_input_response("", {"conversation_id": cid, "ask_id": "credentials",
                                             "values": {}, "message": "Connected; continue"}, caller_user_id=USER)
    assert finished_request is not None
    builder.edit.assert_awaited_once()
    publish = AsyncMock(return_value={"url": "https://app.example"})
    monkeypatch.setattr(requests, "capability", lambda key: publish if key == INTERFACE_PUBLISH else None)
    if publish_after:
        ready = await repo.claim()
        assert ready["id"] == queued["id"] and ready["phase"] == "publishing"
        await requests.run_request(pool, ready)
        publish.assert_awaited_once_with(pool, user_id=USER, workflow_id=workflow_id, **queued["publish"])
    else:
        assert await repo.claim() is None
        publish.assert_not_awaited()
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "completed" and row["result"]["summary"] == "Created dashboard"
    assert ("publication" in row["result"]) is publish_after
    await handler._maybe_notify_agent_result(request=finished_request, user_id=USER, builder=builder, segments=[])
    assert await repo.claim() is None


async def test_new_workflow_uses_existing_creator_and_builder_request(builder_request_db, monkeypatch):
    pool, repo, _, _ = builder_request_db
    monkeypatch.setattr("billing.plan_limits.check_workflow_limit", AsyncMock(return_value=(True, None)))
    request = await requests.submit_request(pool, user_id=USER, instructions="Build an agent", name="Inbox agent")
    try:
        workflow = await pool.fetchrow("SELECT owner_id,name,workflow FROM workflows WHERE id=$1", request["workflow_id"])
        assert str(workflow["owner_id"]) == USER and workflow["name"] == "Inbox agent"
        assert workflow["workflow"] == {"nodes": [], "edges": []}
        assert request["instructions"] == "Build an agent" and request["phase"] == "building"
        assert (await repo.claim())["id"] == request["id"]
    finally:
        await pool.execute("DELETE FROM workflows WHERE id=$1", request["workflow_id"])


async def test_editor_can_build_but_cannot_publish_and_access_is_rechecked(builder_request_db, monkeypatch):
    pool, repo, workflow_id, enqueue = builder_request_db
    editor = str(uuid.uuid4())
    await pool.execute("INSERT INTO auth.users(id,email) VALUES ($1::uuid,$2)", editor, f"{editor}@example.com")
    try:
        await pool.execute("""INSERT INTO resource_shares
            (resource_type,resource_id,target_type,target_user_id,permission,shared_by)
            VALUES ('workflow',$1::uuid,'user',$2::uuid,'edit',$3::uuid)""", workflow_id, editor, USER)
        with pytest.raises(ValueError, match="permission"):
            await enqueue(user_id=editor)
        await enqueue(user_id=editor, instructions="Edit the workflow", publish=None)
        request = await repo.claim()
        await pool.execute("DELETE FROM resource_shares WHERE resource_id=$1::uuid", workflow_id)
        edit = AsyncMock()
        monkeypatch.setattr(WorkflowBuilderHandler, "edit_workflow", edit)
        await requests.run_request(pool, request)
        edit.assert_not_awaited()
        assert (await repo.list_for_user(editor))[0]["status"] == "failed"
    finally:
        await pool.execute("DELETE FROM auth.users WHERE id=$1::uuid", editor)

"""Real database claims, build continuation, and publication delivery."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import publications
from coder.coordinator.tools import CoordinatorTools, coordinator_tool_params
from repositories.coordinator_publications import CoordinatorPublicationRepo
from utils.capabilities import INTERFACE_PUBLISH, OWNER_MESSAGE
from utils.coordinator_publication import PublicationOptions

pytestmark = pytest.mark.asyncio
USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def publication_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    workflow_id = str(uuid.uuid4())
    await pool.execute("INSERT INTO workflows(id,owner_id,name,workflow) VALUES ($1::uuid,$2::uuid,'Publish test',$3)",
                       workflow_id, USER, {"nodes": [], "edges": []})
    repo = CoordinatorPublicationRepo(pool)

    async def enqueue(**overrides):
        values = dict(user_id=USER, workflow_id=workflow_id,
                      options=PublicationOptions(subdomain=f"app-{uuid.uuid4().hex[:12]}").model_dump(exclude={"send_to_phone"}))
        values.update(overrides)
        return await repo.enqueue(**values)

    try:
        yield pool, repo, workflow_id, enqueue
    finally:
        await pool.execute("DELETE FROM workflows WHERE id=$1::uuid", workflow_id)
        await pool.execute("DELETE FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
        await pool.close()


async def test_concurrent_claims_and_duplicate_requests(publication_db):
    _, repo, _, enqueue = publication_db
    queued = await enqueue()
    with pytest.raises(ValueError, match="already pending"):
        await enqueue()
    claims = await asyncio.gather(*(repo.claim() for _ in range(5)))
    assert [r["id"] for r in claims if r] == [queued["id"]]
    assert next(r for r in claims if r)["status"] == "publishing"


async def test_build_questions_and_duplicate_completions_survive_restart(publication_db):
    pool, repo, _, enqueue = publication_db
    cid = f"coordinator-builder:{USER}:test"
    queued = await enqueue(builder_conversation_id=cid, instructions="Build an interface")
    assert (await repo.claim())["status"] == "building"
    await repo.waiting(USER, cid)
    assert await repo.claim() is None
    restarted = CoordinatorPublicationRepo(pool)
    assert await restarted.build_finished(USER, cid, success=True)
    assert await restarted.build_finished(USER, cid, success=True)
    claimed = await restarted.claim()
    assert claimed["id"] == queued["id"] and claimed["status"] == "publishing"
    await restarted.finish(str(claimed["id"]), result={"url": "https://app.example"})
    assert await restarted.build_finished(USER, cid, success=False, error="late callback")
    assert (await restarted.list_for_user(USER))[0]["status"] == "completed"
    assert await restarted.claim() is None


async def test_ownership_and_failures_never_advance_to_publish(publication_db):
    pool, repo, _, enqueue = publication_db
    stranger = str(uuid.uuid4())
    with pytest.raises(ValueError, match="not owned"):
        await enqueue(user_id=stranger)
    cid = f"coordinator-builder:{USER}:failed"
    queued = await enqueue(builder_conversation_id=cid, instructions="Build")
    await repo.claim()
    assert await repo.build_finished(stranger, cid, success=True) is False
    assert await repo.list_for_user(stranger, str(queued["id"])) == []
    await repo.build_finished(USER, cid, success=False, error="Build failed")
    assert await repo.claim() is None
    row = (await repo.list_for_user(USER))[0]
    assert row["error"] == "Build failed" and row["result"] is None
    assert await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE relname='coordinator_publications'")
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1,'coordinator_publications','SELECT,INSERT,UPDATE,DELETE')", role)


@pytest.mark.parametrize("phone_success", [True, False])
async def test_publish_result_and_phone_delivery_are_separate(publication_db, monkeypatch, phone_success):
    pool, repo, workflow_id, enqueue = publication_db
    queued = await enqueue(send_to_phone=True)
    publish = AsyncMock(return_value={"url": "https://app.example", "app_id": "app", "node_id": "ui"})
    send_phone = AsyncMock(return_value={"success": phone_success, "error": None if phone_success else "WhatsApp window closed"})
    monkeypatch.setattr(publications, "capability", lambda key: {INTERFACE_PUBLISH: publish, OWNER_MESSAGE: send_phone}.get(key))
    monkeypatch.setattr(publications, "get_sio", lambda: object())
    emit = AsyncMock()
    monkeypatch.setattr(publications, "send_event", emit)
    await publications.run_publication(pool, await repo.claim())
    publish.assert_awaited_once_with(pool, user_id=USER, workflow_id=workflow_id, **queued["options"])
    notifications = await asyncio.gather(*(repo.claim_notification() for _ in range(3)))
    notification = next(row for row in notifications if row)
    assert sum(row is not None for row in notifications) == 1
    await publications.notify_result(pool, notification)
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "completed" and row["result"]["url"] == "https://app.example"
    assert row["phone_state"] == ("sent" if phone_success else "failed")
    assert row["delivery_error"] == (None if phone_success else "WhatsApp window closed")
    send_phone.assert_awaited_once_with(pool, USER, "Your interface is published.", link="https://app.example")
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(events) == 1 and "https://app.example" in events[0]["message"]
    assert ("WhatsApp window closed" in events[0]["message"]) is not phone_success
    assert await repo.claim_notification() is None
    assert emit.call_args.kwargs["user_id"] == USER


async def test_interrupted_publication_is_not_replayed(publication_db):
    pool, repo, _, enqueue = publication_db
    await enqueue()
    claimed = await repo.claim()
    await pool.execute("UPDATE coordinator_publications SET lease_until=now()-interval '1 second' WHERE id=$1", claimed["id"])
    await repo.reap_stalled()
    await repo.finish(str(claimed["id"]), result={"url": "late"})
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "failed" and "may already be live" in row["error"]
    assert row["result"] is None and await repo.claim() is None


async def test_timeout_without_exception_text_is_still_a_failure(publication_db, monkeypatch):
    pool, repo, _, enqueue = publication_db
    await enqueue()
    monkeypatch.setattr(publications, "capability", lambda _: AsyncMock(side_effect=TimeoutError()))
    await publications.run_publication(pool, await repo.claim())
    row = (await repo.list_for_user(USER))[0]
    assert row["status"] == "failed" and row["error"] and row["result"] is None


async def test_cancellation_blocks_late_build_completion_but_not_started_publish(publication_db):
    _, repo, _, enqueue = publication_db
    cid = f"coordinator-builder:{USER}:cancel"
    queued = await enqueue(builder_conversation_id=cid, instructions="Build")
    await repo.claim()
    await repo.waiting(USER, cid)
    with pytest.raises(ValueError, match="No cancellable"):
        await repo.cancel(str(uuid.uuid4()), str(queued["id"]))
    cancelled = await repo.cancel(USER, str(queued["id"]))
    assert cancelled["status"] == "cancelled"
    await repo.build_finished(USER, cid, success=True)
    assert await repo.claim() is None
    ready = await enqueue()
    await repo.claim()
    with pytest.raises(ValueError, match="cannot be cancelled"):
        await repo.cancel(USER, str(ready["id"]))


async def test_interrupted_phone_send_is_not_duplicated(publication_db, monkeypatch):
    pool, repo, _, enqueue = publication_db
    await enqueue(send_to_phone=True)
    claimed = await repo.claim()
    await repo.finish(str(claimed["id"]), result={"url": "https://app.example"})
    original = await repo.claim_notification()
    assert original["phone_state"] == "sending"
    await pool.execute("UPDATE coordinator_publications SET notification_lease_until=now()-interval '1 second' WHERE id=$1", original["id"])
    recovered = await repo.claim_notification()
    assert recovered["phone_state"] == "uncertain"
    phone = AsyncMock()
    monkeypatch.setattr(publications, "capability", lambda _: phone)
    monkeypatch.setattr(publications, "get_sio", lambda: object())
    monkeypatch.setattr(publications, "send_event", AsyncMock())
    await publications.notify_result(pool, recovered)
    phone.assert_not_awaited()
    assert not await repo.complete_notification(original, {}, phone_state="sent", delivery_error=None)
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id=$1", f"coordinator:{USER}")
    assert len(events) == 1 and "could not be confirmed" in events[0]["message"]


async def test_coordinator_queues_explicit_publication_and_remembers_phone_channel(publication_db, monkeypatch):
    pool, repo, workflow_id, _ = publication_db
    tools = CoordinatorTools(pool=pool, sio=object(), user_id=USER, organization_id=None,
                             conversation_id=f"coordinator:{USER}", reply_channel="voice")
    monkeypatch.setattr(tools, "_accessible_graph", AsyncMock(return_value=([], [], None, {}, {})))
    monkeypatch.setattr("coder.coordinator.tools.capability", lambda _: object())
    built = await tools.request_build("Build a customer dashboard", workflow_id=workflow_id, publish={"subdomain": "customer-dashboard"})
    assert built["status"] == "queued" and built["result"] is None
    row = (await repo.list_for_user(USER))[0]
    assert row["send_to_phone"] is True and row["options"]["subdomain"] == "customer-dashboard"
    assert row["builder_conversation_id"] == built["builder_conversation_id"]
    status = await tools.publication_status(built["publication_id"])
    assert status["publications"][0]["status"] == "queued"


async def test_publishing_tools_are_capability_gated_and_options_are_validated():
    def names(params):
        return {p["function"]["name"] for p in params}
    assert "publish_interface" not in names(coordinator_tool_params())
    assert {"publish_interface", "publication_status"} <= names(coordinator_tool_params(include_publishing=True))
    for invalid in ("../other", "https://example.com", "ab", "a" * 64, "-bad"):
        with pytest.raises(ValueError):
            PublicationOptions(subdomain=invalid)

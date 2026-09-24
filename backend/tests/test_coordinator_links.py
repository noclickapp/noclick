"""Human links resume the same coordinator without a chat nudge.

Real PostgreSQL transitions cover every credential provider entry point, atomic
rollback, duplicate submissions, policy reviews, and shared scheduler recovery.
"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from repositories.coordinator_links import CoordinatorLinkRepo
from repositories.coordinator_wakeups import CoordinatorWakeupRepo
from repositories.credentials import CredentialsRepo
from tests.test_credential_approvals import USER, OTHER, OP, approval_db  # noqa: F401
from utils.credential_actions import CredentialActions

pytestmark = pytest.mark.asyncio
CONTEXT = {"epoch": "", "depth": 0, "request": "Connect email and continue", "channel": "whatsapp_text", "turn_id": "links-test"}


@pytest.fixture
async def links_db(approval_db, monkeypatch):
    pool, approvals, ids = approval_db
    monkeypatch.setattr("utils.coordinator_links.dispatch_link", lambda *args: None)
    try:
        yield pool, approvals, ids
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE user_id=$1::uuid", USER)
        await pool.execute("DELETE FROM credential_requests WHERE requester_id=$1::uuid", USER)


async def connection(pool, credential_type="openai_api_key", context=CONTEXT):
    return await CredentialsRepo(pool).upsert_credential_request(
        requester_id=USER, target_email="", credential_type=credential_type,
        message="Connect and continue", reuse_pending=True, continuation=context,
    )


async def event_for(pool, resource_id):
    return dict(await pool.fetchrow("SELECT * FROM coordinator_wakeups WHERE await_key=$1 ORDER BY created_at DESC LIMIT 1",
                                   f"credential_request:{resource_id}"))


@pytest.mark.parametrize("kind", ["openai_api_key", "google_gmail_oauth", "agent_openai", "whatsapp_qr", "phone_number"])
async def test_all_credential_transitions_queue_once_without_route_dispatch(links_db, kind):
    pool, _, (cid, _) = links_db
    request = await connection(pool, kind)
    assert (await event_for(pool, request.id))["status"] == "waiting"
    assert await CoordinatorWakeupRepo(pool).claim() is None
    await asyncio.gather(*(pool.execute(
        "UPDATE credential_requests SET status='fulfilled',credential_id=$2::uuid WHERE id=$1::uuid", request.id, cid,
    ) for _ in range(3)))
    event = await event_for(pool, request.id)
    assert event["status"] == "queued"
    assert event["context"] == CONTEXT
    assert event["payload"]["credential_id"] == cid
    assert event["payload"]["status"] == "fulfilled"
    assert event["send_to_phone"] is True
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 1


async def test_real_provide_path_commits_credential_share_and_followup_together(links_db, monkeypatch):
    from utils import credential_request_routes as routes
    pool, _, _ = links_db
    request = await connection(pool)
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    monkeypatch.setattr(routes, "_provided_credential_owner", AsyncMock(return_value=OTHER))
    monkeypatch.setattr(routes, "get_encryption", lambda: type("Encryption", (), {
        "encrypt_credential": lambda self, value: "encrypted-only"})())
    result = await routes.provide_credential(request.token, routes.ProvideCredentialBody(credential_data={"api_key": "test-secret"}))
    event = await event_for(pool, request.id)
    assert event["payload"]["credential_id"] == result["credential_id"]
    assert "test-secret" not in json.dumps(event["payload"])
    assert await pool.fetchval("SELECT count(*) FROM resource_shares WHERE resource_id=$1::uuid AND target_user_id=$2::uuid",
                               result["credential_id"], USER) == 1


async def test_request_transition_and_wakeup_rollback_together(links_db):
    pool, _, (cid, _) = links_db
    request = await connection(pool)
    with pytest.raises(RuntimeError):
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("UPDATE credential_requests SET status='fulfilled',credential_id=$2::uuid WHERE id=$1::uuid", request.id, cid)
            assert await conn.fetchval("SELECT status FROM coordinator_wakeups WHERE await_key=$1", f"credential_request:{request.id}") == "queued"
            raise RuntimeError("Crash before commit")
    assert (await event_for(pool, request.id))["status"] == "waiting"
    assert await pool.fetchval("SELECT status FROM credential_requests WHERE id=$1::uuid", request.id) == "pending"


async def test_link_reuse_coalesces_but_reset_and_rotation_cannot_resume_old_request(links_db):
    pool, _, (cid, _) = links_db
    request = await connection(pool)
    assert (await connection(pool)).token == request.token
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 1
    await pool.execute("UPDATE credential_requests SET token='replacement' WHERE id=$1::uuid", request.id)
    assert (await event_for(pool, request.id))["status"] == "skipped"
    await pool.execute("UPDATE credential_requests SET status='fulfilled',credential_id=$2::uuid WHERE id=$1::uuid", request.id, cid)
    assert (await event_for(pool, request.id))["status"] == "skipped"
    await connection(pool)
    await CoordinatorWakeupRepo(pool).reset(USER)
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups WHERE status='waiting'") == 0


async def test_human_save_only_wakes_policy_review_and_preserves_actual_rules(links_db):
    pool, approvals, (cid, _) = links_db
    actions = CredentialActions(pool=pool, user_id=USER, continuation=CONTEXT)
    result = await actions.request_credential_permissions(cid)
    assert result["auto_resume"] and result["settings_url"].endswith(cid)
    await approvals.tighten(cid, USER, [OP])
    assert await CoordinatorLinkRepo(pool).pending("credential_policy", cid, USER)
    with pytest.raises(ValueError):
        await approvals.replace_from_human(cid, OTHER, [], 1)
    with pytest.raises(ValueError):
        await approvals.replace_from_human(cid, USER, [], 0)
    assert await CoordinatorLinkRepo(pool).pending("credential_policy", cid, USER)
    await approvals.replace_from_human(cid, USER, [OP], 1)  # Confirm unchanged rules is also a human response.
    event = await pool.fetchrow("SELECT * FROM coordinator_wakeups WHERE source='link'")
    assert event["status"] == "queued" and event["payload"]["status"] == "reviewed"
    assert event["payload"]["approval_operations"] == [OP]
    assert event["context"] == CONTEXT
    await approvals.replace_from_human(cid, USER, [], 2)
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 1
    assert (await pool.fetchval("SELECT payload FROM coordinator_wakeups"))["approval_operations"] == [OP]


async def test_non_coordinator_requests_and_regular_permission_saves_do_not_create_wakeups(links_db):
    pool, approvals, (cid, _) = links_db
    request = await connection(pool, context=None)
    await pool.execute("UPDATE credential_requests SET status='fulfilled',credential_id=$2::uuid WHERE id=$1::uuid", request.id, cid)
    await approvals.replace_from_human(cid, USER, [], 0)
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 0


@pytest.mark.parametrize("status,error,expected", [("cancelled", None, "cancelled"), ("expired", None, "expired"),
    ("pending", "Number unavailable", "failed"), ("provisioning", "Outcome cannot be confirmed", "uncertain")])
async def test_negative_results_resume_without_fabricating_success(links_db, status, error, expected):
    pool, _, _ = links_db
    request = await connection(pool, "phone_number")
    await pool.execute("UPDATE credential_requests SET status=$2,provision_error=$3 WHERE id=$1::uuid", request.id, status, error)
    event = await event_for(pool, request.id)
    assert event["status"] == "queued" and event["payload"]["status"] == expected


async def test_wait_expiry_and_private_schema(links_db):
    pool, _, _ = links_db
    request = await connection(pool)
    await pool.execute("UPDATE coordinator_wakeups SET await_expires_at=now()-interval '1 second'")
    await CoordinatorLinkRepo(pool).expire()
    event = await event_for(pool, request.id)
    assert event["status"] == "queued" and event["payload"]["status"] == "expired"
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1,'coordinator_wakeups','INSERT,UPDATE,SELECT')", role)
        for signature in ("complete_coordinator_link(text,jsonb)", "credential_request_complete_link()", "credential_approval_complete_link()"):
            assert not await pool.fetchval("SELECT has_function_privilege($1,$2,'EXECUTE')", role, signature)


async def test_old_submission_cannot_fulfill_a_refreshed_link(links_db):
    pool, _, _ = links_db
    old = await connection(pool)
    current = await CredentialsRepo(pool).upsert_credential_request(
        requester_id=USER, target_email='', credential_type='openai_api_key', message='New request', continuation=CONTEXT,
    )
    assert current.id == old.id and current.token != old.token
    count = await pool.fetchval('SELECT count(*) FROM credentials')
    with pytest.raises(ValueError):
        await CredentialsRepo(pool).store_provided_credential(
            request_id=old.id, request_token=old.token, owner_id=USER, requester_id=USER,
            organization_id=None, name='Stale', credential_type='openai_api_key', encrypted='encrypted', metadata={},
        )
    assert await pool.fetchval('SELECT count(*) FROM credentials') == count
    assert (await event_for(pool, current.id))['status'] == 'waiting'


async def test_waiting_link_cap_does_not_reject_reusing_an_existing_link(links_db):
    pool, _, _ = links_db
    request = await connection(pool)
    await pool.execute("INSERT INTO coordinator_wakeups(user_id,source,source_id,context,payload,status,await_key,await_expires_at) "
                       "SELECT $1::uuid,'link',gen_random_uuid(),'{}','{}','waiting','test:'||n,now()+interval '1 day' "
                       "FROM generate_series(1,99) n", USER)
    assert (await connection(pool)).id == request.id
    with pytest.raises(ValueError, match='Too many outstanding'):
        await connection(pool, 'google_gmail_oauth')
    assert await pool.fetchval("SELECT count(*) FROM credential_requests WHERE credential_type='google_gmail_oauth'") == 0


@pytest.mark.parametrize('channel', ['web', 'whatsapp_text'])
async def test_connection_tool_registers_its_returned_link_with_original_channel(links_db, channel):
    pool, _, _ = links_db
    actions = CredentialActions(pool=pool, user_id=USER, continuation={**CONTEXT, 'channel': channel})
    result = await actions.connect_credential('whatsapp_qr')
    assert result['auto_resume'] and result['url']
    event = await event_for(pool, result['request_id'])
    assert event['status'] == 'waiting'
    assert event['context']['channel'] == channel
    assert event['send_to_phone'] == (channel != 'web')


async def test_machine_tightening_finishes_without_requesting_an_unnecessary_human_review(links_db):
    pool, _, (cid, _) = links_db
    actions = CredentialActions(pool=pool, user_id=USER, continuation=CONTEXT)
    result = await actions.require_credential_approval(cid, [OP])
    assert result == {'approval_operations': [OP]}
    assert await pool.fetchval('SELECT count(*) FROM coordinator_wakeups') == 0

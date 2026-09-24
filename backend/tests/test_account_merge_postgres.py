"""A phone-only account folding into the email account its owner proves they
hold, against real Postgres: the merge plan covers every user-keyed column
(the ratchet), the merge moves work and keeps history, and the two ways in —
a code typed into the chat (utils/account_link.py) and a number verified on
the web by a signed-in account — both end in the same merge."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from repositories import account_merge
from repositories.account_merge import (
    KEEP_COLUMNS, MOVE_COLUMNS, ORG_KEEP_TABLES, ORG_MOVE_TABLES, SPECIAL_COLUMNS, merge_accounts, personal_workspace,
)
from repositories.phones import PhoneRepo
from tests.test_phone_accounts_postgres import FakeAuthAdmin, phones_db  # noqa: F401 — the shared fixture
from tests.test_phone_identity import FakeVerify
from utils.account_link import AccountLink, AccountLinkError, MAX_CHECKS, MAX_SENDS_PER_ACCOUNT
from utils.phone_identity import PhoneIdentity

pytestmark = pytest.mark.asyncio

OPEN_EDITION_ONLY = {
    ("instance_provider_keys", "updated_by"), ("local_cron_schedules", "user_id"),
    ("mcp_server_links", "user_id"), ("workflow_embeddings", "owner_id"),
}
HOSTED_ONLY = {("voice_calls", "user_id")}
# The local scheduler creates its table on first use, in either edition.
CREATED_AT_RUNTIME = {("local_cron_schedules", "user_id")}

USER_KEYED = """
SELECT cl.relname AS table_name, a.attname AS column_name
FROM pg_class cl
JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE cl.relkind IN ('r', 'p') AND (
    a.attname ~ '(^|_)(user_id|owner_id|created_by|updated_by|shared_by|forked_by|requester_id|inviter_id|redeemer_id|invited_by|decided_by|authorized_by|triggered_by)$'
    OR EXISTS (SELECT 1 FROM pg_constraint k WHERE k.contype = 'f' AND k.confrelid = 'auth.users'::regclass
               AND k.conrelid = cl.oid AND a.attnum = ANY(k.conkey)))
"""


async def test_every_user_keyed_column_has_a_merge_decision(phones_db):
    pool, *_ = phones_db
    in_schema = {(r["table_name"], r["column_name"]) for r in await pool.fetch(USER_KEYED)}
    planned = set(MOVE_COLUMNS) | set(SPECIAL_COLUMNS) | set(KEEP_COLUMNS)
    # Decide MOVE or KEEP in repositories/account_merge.py for any column listed here.
    assert sorted(in_schema - planned) == []
    # The plan spans both editions; what this schema lacks must be the other edition's.
    absent = (planned - in_schema) - CREATED_AT_RUNTIME
    assert absent in (OPEN_EDITION_ONLY - CREATED_AT_RUNTIME, HOSTED_ONLY)

    with_org = {r["relname"] for r in await pool.fetch(
        "SELECT cl.relname FROM pg_class cl JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public' "
        "JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = 'organization_id' AND NOT a.attisdropped "
        "WHERE cl.relkind IN ('r', 'p')")}
    org_planned = set(ORG_MOVE_TABLES) | set(ORG_KEEP_TABLES)
    assert org_planned - with_org in ({"workflow_embeddings"}, set())
    assert with_org <= org_planned
    assert set(ORG_MOVE_TABLES) <= {t for t, _ in MOVE_COLUMNS}


async def make_email_account(pool, email):
    return str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id", email))


async def seed_phone_account(pool, svc, phone):
    source = (await svc.claim_for_channel(phone, name="Ada", source="whatsapp")).user_id
    org = await pool.fetchval("SELECT organization_id FROM organization_members WHERE user_id = $1::uuid", source)
    workflow = await pool.fetchval(
        "INSERT INTO workflows (owner_id, organization_id, name) VALUES ($1::uuid, $2, 'Plant alerts') RETURNING id",
        source, org)
    await pool.execute(
        "INSERT INTO credentials (owner_id, organization_id, credential_type, credential, name) "
        "VALUES ($1::uuid, $2, 'slack', 'x', 'Slack')", source, org)
    await pool.execute("INSERT INTO webhooks (user_id, workflow_id, node_id) VALUES ($1::uuid, $2, 'trigger')", source, workflow)
    await pool.execute("INSERT INTO workflow_folders (owner_id, organization_id, name) VALUES ($1::uuid, $2, 'Home')", source, org)
    await pool.execute(
        "INSERT INTO coordinator_memories (user_id, name, description, memory_type, content) "
        "VALUES ($1::uuid, 'plants', 'Which plants', 'user', 'Ferns and a cactus')", source)
    await pool.execute(
        "INSERT INTO conversations (conversation_id, user_id, events, metadata) VALUES ($1, $2::uuid, $3, $4)",
        f"coordinator:{source}", source, [{"role": "user", "message": "water the ferns"}],
        {"sdk_history": [{"role": "user", "content": "water the ferns"}]})
    await pool.execute(
        "INSERT INTO user_usage_events (user_id, total_cost, usage_type, usage_subtype) VALUES ($1::uuid, 1.5, 'ai_usage', 'x')",
        source)
    return source, str(workflow)


async def test_a_merge_moves_the_work_keeps_the_history_and_retires_the_phone_account(phones_db):
    pool, repo, _, svc = phones_db
    source, workflow = await seed_phone_account(pool, svc, "+15550200001")
    target = await make_email_account(pool, f"{uuid.uuid4().hex[:8]}@example.com")
    t_org = await personal_workspace(pool, target)
    await pool.execute("INSERT INTO workflow_folders (owner_id, organization_id, name) VALUES ($1::uuid, $2::uuid, 'Home')", target, t_org)
    await pool.execute(
        "INSERT INTO coordinator_memories (user_id, name, description, memory_type, content) "
        "VALUES ($1::uuid, 'plants', 'Garden notes', 'user', 'Roses')", target)
    await pool.execute(
        "INSERT INTO conversations (conversation_id, user_id, events, metadata) VALUES ($1, $2::uuid, $3, $4)",
        f"coordinator:{target}", target, [{"role": "user", "message": "hi from the web"}],
        {"sdk_history": [{"role": "user", "content": "hi from the web"}]})

    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await merge_accounts(conn, source=source, target=target)
    assert result.moved["workflows.owner_id"] == 1 and result.moved["user_phones.user_id"] == 1

    row = await pool.fetchrow("SELECT owner_id, organization_id FROM workflows WHERE id = $1::uuid", workflow)
    assert (str(row["owner_id"]), str(row["organization_id"])) == (target, t_org)
    assert str(await pool.fetchval("SELECT user_id FROM webhooks WHERE workflow_id = $1::uuid", workflow)) == target
    assert await pool.fetchval("SELECT count(*) FROM credentials WHERE owner_id = $1::uuid AND organization_id = $2::uuid", target, t_org) == 1
    assert sorted(r["name"] for r in await pool.fetch("SELECT name FROM workflow_folders WHERE owner_id = $1::uuid", target)) == ["Home", "Home (WhatsApp)"]
    names = sorted(r["name"] for r in await pool.fetch("SELECT name FROM coordinator_memories WHERE user_id = $1::uuid", target))
    assert names == ["plants", f"plants-{source[:8]}"]

    # One coordinator thread, the phone chat after the web one.
    conv = await pool.fetchrow("SELECT events, metadata FROM conversations WHERE conversation_id = $1", f"coordinator:{target}")
    assert [e["message"] for e in conv["events"]] == ["hi from the web", "water the ferns"]
    assert len(conv["metadata"]["sdk_history"]) == 2
    assert await pool.fetchval("SELECT 1 FROM conversations WHERE conversation_id = $1", f"coordinator:{source}") is None

    # The number now reaches the target; usage history stays with the retired account.
    assert str((await repo.get_user_by_phone("+15550200001"))["user_id"]) == target
    assert await pool.fetchval("SELECT count(*) FROM user_usage_events WHERE user_id = $1::uuid", source) == 1
    retired = await pool.fetchrow("SELECT phone, raw_user_meta_data FROM auth.users WHERE id = $1::uuid", source)
    assert retired["phone"] is None and retired["raw_user_meta_data"]["merged_into"] == target


async def test_a_code_typed_into_the_chat_connects_it_to_the_email_account(phones_db):
    pool, repo, admin, svc = phones_db
    source, workflow = await seed_phone_account(pool, svc, "+15550200002")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    target = await make_email_account(pool, email)
    sent = []

    async def send_code(to, code, phone_masked):
        sent.append((to, code, phone_masked))
        return True
    link = AccountLink(pool, send_code=send_code, admin=lambda: admin)

    assert (await link.start(source, f"  {email.upper()} "))["sent_to"] == email
    to, code, phone_masked = sent[-1]
    assert to == email and len(code) == 6 and phone_masked.endswith("0002")
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(AccountLinkError) as exc:
        await link.verify(source, wrong)
    assert exc.value.kind == "invalid_code"
    # Nothing moved on a wrong code, nor on a right one until the turn completes.
    verified = await link.verify(source, f"{code[:3]} {code[3:]}")
    assert verified.merges is True and verified.email == email
    assert str(await pool.fetchval("SELECT owner_id FROM workflows WHERE id = $1::uuid", workflow)) == source

    assert await link.complete(source) == target
    assert str(await pool.fetchval("SELECT owner_id FROM workflows WHERE id = $1::uuid", workflow)) == target
    assert str((await repo.get_user_by_phone("+15550200002"))["user_id"]) == target
    assert await link.complete(source) is None  # once


async def test_an_email_no_account_has_becomes_this_accounts_sign_in(phones_db):
    pool, _, admin, svc = phones_db
    source, workflow = await seed_phone_account(pool, svc, "+15550200003")
    updates = []

    async def update_user(user_id, **attributes):
        updates.append((user_id, attributes))
        return {"id": user_id}
    admin.update_user = update_user
    sent = []

    async def send_code(to, code, phone_masked):
        sent.append(code)
        return True
    link = AccountLink(pool, send_code=send_code, admin=lambda: admin)
    await link.start(source, "new.person@example.com")
    verified = await link.verify(source, sent[-1])
    assert verified.merges is False
    assert await link.complete(source) == source
    assert updates == [(source, {"email": "new.person@example.com", "email_confirm": True})]
    assert str(await pool.fetchval("SELECT owner_id FROM workflows WHERE id = $1::uuid", workflow)) == source


async def test_codes_are_capped_and_expire(phones_db):
    pool, _, admin, svc = phones_db
    source, _ = await seed_phone_account(pool, svc, "+15550200004")
    sent = []

    async def send_code(to, code, phone_masked):
        sent.append(code)
        return True
    link = AccountLink(pool, send_code=send_code, admin=lambda: admin)
    with pytest.raises(AccountLinkError) as exc:
        await link.verify(source, "123456")
    assert exc.value.kind == "no_code"
    with pytest.raises(AccountLinkError) as exc:
        await link.start(source, "not-an-email")
    assert exc.value.kind == "invalid_email"

    await link.start(source, "cap@example.com")
    wrong = "000000" if sent[-1] != "000000" else "111111"
    for _ in range(MAX_CHECKS):
        with pytest.raises(AccountLinkError):
            await link.verify(source, wrong)
    with pytest.raises(AccountLinkError) as exc:
        await link.verify(source, sent[-1])
    assert exc.value.kind == "too_many_checks"

    for _ in range(MAX_SENDS_PER_ACCOUNT - 1):
        await link.start(source, "cap@example.com")
    with pytest.raises(AccountLinkError) as exc:
        await link.start(source, "cap@example.com")
    assert exc.value.kind == "too_many_sends"

    await pool.execute("UPDATE account_link_challenges SET expires_at = now() - interval '1 second' WHERE user_id = $1::uuid "
                       "AND status = 'pending'", source)
    with pytest.raises(AccountLinkError) as exc:
        await link.verify(source, sent[-1])
    assert exc.value.kind == "expired"

    # An account that already has an email has nothing to connect.
    with pytest.raises(AccountLinkError) as exc:
        await link.start(await make_email_account(pool, f"{uuid.uuid4().hex[:8]}@example.com"), "x@example.com")
    assert exc.value.kind == "has_email"


async def test_verifying_a_phone_only_accounts_number_on_the_web_absorbs_it(phones_db):
    pool, repo, admin, svc = phones_db
    source, workflow = await seed_phone_account(pool, svc, "+15550200005")
    target = await make_email_account(pool, f"{uuid.uuid4().hex[:8]}@example.com")
    web = PhoneIdentity(repo, FakeVerify(), admin=lambda: admin)
    started = await web.start_link(target, "+15550200005")
    linked = await web.check_link(target, started["challenge_id"], "123456")
    assert linked["phone"] == "+15550200005"
    assert str(await pool.fetchval("SELECT owner_id FROM workflows WHERE id = $1::uuid", workflow)) == target
    assert str((await repo.get_user_by_phone("+15550200005"))["user_id"]) == target

    # A number held by an account WITH an email is never absorbed.
    other = await make_email_account(pool, f"{uuid.uuid4().hex[:8]}@example.com")
    started = await web.start_link(other, "+15550200005")
    with pytest.raises(Exception) as exc:
        await web.check_link(other, started["challenge_id"], "123456")
    assert getattr(exc.value, "kind", None) == "linked_elsewhere"
    assert str((await repo.get_user_by_phone("+15550200005"))["user_id"]) == target

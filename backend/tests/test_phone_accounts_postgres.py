"""Phone bindings against real Postgres: several numbers per account, one
account per live number, and the phone-only account a channel-authenticated
first contact makes (utils/phone_identity.py:claim_for_channel). The auth
admin is faked the way GoTrue behaves — an auth.users row, the number stored
without its +, a taken number refused with 422 — so the signup triggers run."""

import asyncio
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from repositories.phones import PhoneRepo
from utils.phone_identity import PhoneIdentity
from utils.supabase_admin import SupabaseAdminError

pytestmark = pytest.mark.asyncio

EMAIL_USER = "00000000-0000-0000-0000-000000000001"  # seeded with test@example.com


class FakeAuthAdmin:
    def __init__(self, pool):
        self.pool = pool
        self.created = []

    async def create_user(self, *, phone, phone_confirm, user_metadata):
        assert phone_confirm is True
        digits = phone.lstrip("+")
        if await self.pool.fetchval("SELECT 1 FROM auth.users WHERE phone = $1", digits):
            raise SupabaseAdminError("phone_exists", status_code=422)
        await asyncio.sleep(0.05)  # a real round trip; concurrent claims overlap here
        user_id = await self.pool.fetchval(
            "INSERT INTO auth.users (phone, phone_confirmed_at, raw_user_meta_data) "
            "VALUES ($1, now(), $2) RETURNING id",
            digits, user_metadata,
        )
        self.created.append(str(user_id))
        return {"id": str(user_id)}


@pytest.fixture
async def phones_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg as fixture_asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await fixture_asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=8, init=setup_asyncpg_codecs,
    )
    admin = FakeAuthAdmin(pool)
    repo = PhoneRepo(pool)
    try:
        yield pool, repo, admin, PhoneIdentity(repo, None, admin=lambda: admin)
    finally:
        await pool.close()


async def verify_link(repo, user_id, phone):
    challenge = await repo.create_challenge(
        user_id=user_id, phone_e164=phone, provider_sid="VE1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    return await repo.consume_and_link(user_id=user_id, phone_e164=phone, challenge_id=str(challenge["id"]))


async def test_first_contact_makes_a_phone_only_account_with_a_workspace(phones_db):
    pool, repo, admin, svc = phones_db
    first = await svc.claim_for_channel("+15550100001", name="Ada", source="whatsapp")
    assert first.created is True and admin.created == [first.user_id]

    user = await pool.fetchrow("SELECT email, phone, raw_user_meta_data FROM auth.users WHERE id = $1::uuid", first.user_id)
    assert user["email"] is None and user["phone"] == "15550100001"
    assert user["raw_user_meta_data"]["name"] == "Ada"
    # The signup triggers ran: a free-tier billing row and a personal workspace.
    assert await pool.fetchval("SELECT subscription_tier FROM user_billing WHERE id = $1::uuid", first.user_id) == "free"
    assert await pool.fetchval(
        "SELECT o.name FROM organization_members m JOIN organizations o ON o.id = m.organization_id "
        "WHERE m.user_id = $1::uuid AND m.role = 'owner'", first.user_id,
    ) == "Ada's Workspace"
    assert (await repo.get_user_by_phone("+15550100001"))["source"] == "whatsapp"

    again = await svc.claim_for_channel("+15550100001", name="Ada", source="whatsapp")
    assert again.user_id == first.user_id and again.created is False
    assert admin.created == [first.user_id]


async def test_concurrent_first_contacts_make_one_account(phones_db):
    _, repo, admin, svc = phones_db
    claims = await asyncio.gather(*(
        svc.claim_for_channel("+15550100002", name="", source="whatsapp") for _ in range(5)
    ))
    assert len({c.user_id for c in claims}) == 1
    assert [c.created for c in claims].count(True) == 1 and len(admin.created) == 1
    assert str((await repo.get_user_by_phone("+15550100002"))["user_id"]) == claims[0].user_id


async def test_an_auth_user_whose_binding_never_landed_is_adopted(phones_db):
    pool, repo, admin, svc = phones_db
    orphan = await pool.fetchval(
        "INSERT INTO auth.users (phone, raw_user_meta_data) VALUES ('15550100003', $1) RETURNING id",
        {"username": "+1•••••••0003"},
    )
    claim = await svc.claim_for_channel("+15550100003", name="", source="whatsapp")
    assert claim.user_id == str(orphan) and claim.created is False and admin.created == []


async def test_several_numbers_reach_one_account_and_a_number_reaches_one_account(phones_db):
    pool, repo, _, svc = phones_db
    await verify_link(repo, EMAIL_USER, "+15550100004")
    await verify_link(repo, EMAIL_USER, "+15550100005")
    assert [p["phone_e164"] for p in await repo.list_active_phones(EMAIL_USER)] == ["+15550100004", "+15550100005"]
    for number in ("+15550100004", "+15550100005"):
        assert str((await repo.get_user_by_phone(number))["user_id"]) == EMAIL_USER
        # A first contact from a bound number reaches the existing account.
        claim = await svc.claim_for_channel(number, name="", source="whatsapp")
        assert claim.user_id == EMAIL_USER and claim.created is False

    # Outbound goes to the number the account last messaged from.
    await repo.touch_seen("+15550100004")
    assert (await repo.get_reach_phone(EMAIL_USER))["phone_e164"] == "+15550100004"

    other = await pool.fetchval("INSERT INTO auth.users (email) VALUES ('other@example.com') RETURNING id")
    with pytest.raises(asyncpg.UniqueViolationError):
        await verify_link(repo, str(other), "+15550100004")
    assert str((await repo.get_user_by_phone("+15550100004"))["user_id"]) == EMAIL_USER

    # Relinking a number the account already holds revives the same row.
    relinked = await verify_link(repo, EMAIL_USER, "+15550100005")
    assert relinked["link_version"] == 2 and relinked["source"] == "verify"


async def test_unlinking_a_number_hands_it_to_a_fresh_account_not_the_old_one(phones_db):
    pool, repo, admin, svc = phones_db
    first = await svc.claim_for_channel("+15550100006", name="", source="whatsapp")
    await verify_link(repo, first.user_id, "+15550100007")
    assert await svc.unlink(first.user_id, "+15550100006") is True
    # The auth phone goes with it: whoever holds the number next can't reach this account by it.
    assert await pool.fetchval("SELECT phone FROM auth.users WHERE id = $1::uuid", first.user_id) is None

    successor = await svc.claim_for_channel("+15550100006", name="", source="whatsapp")
    assert successor.created is True and successor.user_id != first.user_id
    assert str((await repo.get_user_by_phone("+15550100007"))["user_id"]) == first.user_id

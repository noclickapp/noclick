"""A closed account's sign-in stops working at once (``utils.account_status``): a Supabase access token issued before
its sign-in was banned or deleted still verifies until it expires, so ``utils.auth.verify_token`` asks after the
account too, and every way the app takes such a token (its REST routes, the socket's connect) refuses it. Over the
real ``auth.users`` columns GoTrue sets."""

import asyncio
import logging
import time
import uuid

import jwt
import pytest
from fastapi import HTTPException

# Assembled at collection, as the other tests of server.py's handlers do: assembling it inside a test made that test's
# seconds turn on what its worker had run before it.
import server
from utils import account_status
from utils.auth import AccountClosed, authenticate_http_request, verify_socket_token, verify_token

pytestmark = pytest.mark.asyncio

SECRET = "account-status-test-secret-of-forty-bytes"
# A refusal is one bounded status read (account_status.READ_S for a connection, again for the query).
CONNECT_S = 10


@pytest.fixture
def pool(postgres_pool, monkeypatch):
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: postgres_pool)
    monkeypatch.setattr("utils.auth.get_supabase_public_key", lambda: None)
    monkeypatch.setattr("utils.auth.get_supabase_jwt_secret", lambda: SECRET)
    return postgres_pool


async def _user(pool) -> str:
    return str(await pool.fetchval("INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                                   f"status-{uuid.uuid4().hex[:10]}@example.com"))


def _token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "aud": "authenticated", "role": "authenticated",
                       "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")


class Reset:
    """A connection the read can't get through: reset under it."""

    async def fetchval(self, *args, timeout):
        raise ConnectionResetError("Connection reset by peer")


class ExhaustedPool:
    """A pool with no connection to give within the wait."""

    def acquire(self, *, timeout):
        assert timeout == account_status.READ_S
        return self

    async def __aenter__(self):
        raise asyncio.TimeoutError()

    async def __aexit__(self, *exc):
        return False


def _lapsed(user_id: str) -> None:
    """This process's verdict for the account, long past its keep."""
    verdict, _ = account_status._verdicts[user_id]
    account_status._verdicts[user_id] = (verdict, time.monotonic() - 3600)


class _Req:
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


@pytest.mark.parametrize("closing", [
    "UPDATE auth.users SET banned_until = now() + interval '876000 hours' WHERE id = $1::uuid",
    "UPDATE auth.users SET deleted_at = now() WHERE id = $1::uuid",
    "DELETE FROM auth.users WHERE id = $1::uuid",
])
async def test_a_token_from_before_the_close_stops_verifying(pool, closing):
    user = await _user(pool)
    token = _token(user)
    assert (await verify_token(token))["sub"] == user
    assert (await verify_socket_token(token))[0] == user
    assert (await authenticate_http_request(_Req(token)))[0] == user

    await pool.execute(closing, user)
    account_status.forget(user)
    with pytest.raises(AccountClosed, match=account_status.CLOSED):
        await verify_token(token)
    # The socket's connect and update_auth refuse it as an invalid token: the browser goes to sign in.
    with pytest.raises(jwt.InvalidTokenError):
        await verify_socket_token(token)
    with pytest.raises(HTTPException) as refused:
        await authenticate_http_request(_Req(token))
    assert (refused.value.status_code, refused.value.detail) == (401, account_status.CLOSED)


async def test_a_ban_that_has_lapsed_is_open_again(pool):
    user = await _user(pool)
    await pool.execute("UPDATE auth.users SET banned_until = now() - interval '1 minute' WHERE id = $1::uuid", user)
    assert await account_status.is_open(user)


async def test_a_verdict_is_kept_briefly_then_read_again(pool):
    user = await _user(pool)

    class Counted:
        reads = 0

        async def fetchval(self, *args, timeout):
            assert timeout == account_status.READ_S
            Counted.reads += 1
            return await pool.fetchval(*args, timeout=timeout)

    db = Counted()
    assert await account_status.is_open(user, db) and await account_status.is_open(user, db)
    assert Counted.reads == 1

    await pool.execute("UPDATE auth.users SET banned_until = now() + interval '1 day' WHERE id = $1::uuid", user)
    assert await account_status.is_open(user, db)  # this process's verdict, kept KEEP_S
    verdict, until = account_status._verdicts[user]
    assert verdict and 0 < until - time.monotonic() <= account_status.KEEP_S
    account_status._verdicts[user] = (verdict, time.monotonic() - 1)  # once that has passed
    assert not await account_status.is_open(user, db)
    assert Counted.reads == 2


async def test_forget_drops_the_verdict_at_once(pool):
    user = await _user(pool)
    assert await account_status.is_open(user)
    await pool.execute("UPDATE auth.users SET deleted_at = now() WHERE id = $1::uuid", user)
    account_status.forget(user)
    assert not await account_status.is_open(user)


async def test_the_socket_refuses_a_closed_accounts_token_at_connect(pool):
    from socketio.exceptions import ConnectionRefusedError

    user = await _user(pool)
    await pool.execute("UPDATE auth.users SET banned_until = now() + interval '1 day' WHERE id = $1::uuid", user)
    account_status.forget(user)
    with pytest.raises(ConnectionRefusedError) as refused:
        try:
            await asyncio.wait_for(server.connect("sid-closed", {}, {"token": _token(user)}), CONNECT_S)
        except asyncio.TimeoutError:
            pytest.fail(f"connect neither refused nor accepted a closed account's token within {CONNECT_S}s")
    assert refused.value.args[0] == {"message": "Token verification failed", "code": "token_invalid",
                                     "reason": account_status.CLOSED}


async def test_an_unreadable_status_takes_this_processs_last_verdict_however_old(pool):
    opened, closed = await _user(pool), await _user(pool)
    await pool.execute("UPDATE auth.users SET banned_until = now() + interval '1 day' WHERE id = $1::uuid", closed)
    for user in (opened, closed):
        await account_status.is_open(user)
        _lapsed(user)
    assert await account_status.is_open(opened, Reset()) is True
    assert await account_status.is_open(closed, Reset()) is False
    # Still lapsed: the next request reads again.
    assert account_status._verdicts[opened][1] < time.monotonic()
    assert await account_status.is_open(opened) is True and account_status._verdicts[opened][1] > time.monotonic()


async def test_an_unreadable_status_never_locks_a_valid_token_out(pool, monkeypatch, caplog):
    user = await _user(pool)
    token = _token(user)
    await pool.execute("UPDATE auth.users SET deleted_at = now() WHERE id = $1::uuid", user)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: ExhaustedPool())
    with caplog.at_level(logging.WARNING, logger="utils.account_status"):
        # Nothing this process read says it's closed: open, while the database can't say.
        assert (await verify_token(token))["sub"] == user
        assert (await authenticate_http_request(_Req(token)))[0] == user
    [warned] = [r for r in caplog.records if r.name == "utils.account_status"]  # once per account per KEEP_S
    assert warned.levelno == logging.WARNING and user in warned.getMessage()
    assert "TimeoutError" in warned.getMessage() and token not in warned.getMessage()
    assert user not in account_status._verdicts

    # Once it can read again, the row refuses it at once.
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    with pytest.raises(AccountClosed):
        await verify_token(token)


async def test_a_slow_read_is_cut_off_and_taken_as_unknown(pool, monkeypatch):
    user = await _user(pool)
    monkeypatch.setattr(account_status, "READ_S", 0.2)
    async with pool.acquire() as holder, holder.transaction():
        await holder.execute("LOCK TABLE auth.users IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        assert await account_status.is_open(user) is True
        assert time.monotonic() - started < 1.5
    assert await account_status.is_open(user) is True and user in account_status._verdicts

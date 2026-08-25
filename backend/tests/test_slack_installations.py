"""Tests for the Slack workspace installation store (utils/slack_installations.py).

Copying a workspace bot token into sibling credential rows permits an older
bundle to overwrite a newly rotated single-use refresh token. These tests pin
the replacement design — ONE installation row per
workspace, refreshed through the shared choke point, nothing to sync.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from tests.slack_installation_fakes import (
    BOT_FIELDS,
    _FakeEncryption,
    _FakePool,
    _db,
    _enc,
)


class TestResolveAndSeed:
    async def test_no_team_id_returns_none(self):
        from utils.slack_installations import resolve_slack_installation

        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            assert await resolve_slack_installation(
                _FakePool(_db()), {"access_token": "xoxb-1"}
            ) is None

    async def test_seed_picks_newest_sibling_bundle(self):
        """Regression shape: one sibling holds a stale (consumed) bundle, one
        holds the live one. Seeding must pick the NEWEST expires_at — seeding
        from the stale copy would brick the chain on first refresh."""
        from utils.slack_installations import resolve_slack_installation

        stale = {**BOT_FIELDS, "access_token": "old", "refresh_token": "rt-old",
                 "expires_at": "2026-06-09T00:00:00+00:00"}
        live = {**BOT_FIELDS, "access_token": "new", "refresh_token": "rt-new",
                "expires_at": "2026-06-10T00:00:00+00:00"}
        anchor = dict(stale)  # the triggering credential itself holds the stale copy
        db = _db(sibling_blobs=[_enc(stale), _enc(live)])
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            installation_id, bundle = await resolve_slack_installation(_FakePool(db), anchor)
        assert bundle["access_token"] == "new"
        assert bundle["refresh_token"] == "rt-new"
        assert db["installations"][0]["team_id"] == "T1"

    async def test_seed_is_idempotent(self):
        from utils.slack_installations import resolve_slack_installation

        cred = {**BOT_FIELDS, "access_token": "a", "refresh_token": "r",
                "expires_at": "2026-06-10T00:00:00+00:00"}
        db = _db(sibling_blobs=[_enc(cred)])
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            id1, _ = await resolve_slack_installation(_FakePool(db), dict(cred))
            id2, _ = await resolve_slack_installation(_FakePool(db), dict(cred))
        assert id1 == id2
        assert len(db["installations"]) == 1

    async def test_revoked_installation_raises_reconnect(self):
        from utils.slack_installations import resolve_slack_installation

        db = _db(installations=[{
            "id": "inst-1", "team_id": "T1", "app_id": "A1", "client_id": "",
            "installation": _enc({**BOT_FIELDS, "access_token": "a"}),
            "revoked_at": "2026-06-10T00:00:00+00:00",
            "revoked_reason": "F29_user_revoked", "token_version": 4,
        }])
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            with pytest.raises(ValueError, match="reconnect"):
                await resolve_slack_installation(
                    _FakePool(db), {**BOT_FIELDS, "access_token": "a"}
                )

    async def test_fuzzy_match_unknown_app_id(self):
        """Credentials predating app_id capture must resolve to the workspace's
        existing installation, not create a competing second chain."""
        from utils.slack_installations import resolve_slack_installation

        db = _db(installations=[{
            "id": "inst-1", "team_id": "T1", "app_id": "A1", "client_id": "",
            "installation": _enc({**BOT_FIELDS, "access_token": "a", "refresh_token": "r",
                                  "expires_at": "2026-06-10T00:00:00+00:00"}),
            "revoked_at": None, "revoked_reason": None, "token_version": 2,
        }])
        old_cred = {"team_id": "T1", "access_token": "stale"}  # no app_id
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            installation_id, _ = await resolve_slack_installation(_FakePool(db), old_cred)
        assert installation_id == "inst-1"
        assert len(db["installations"]) == 1


class TestEnsureFreshSlackBotToken:
    def _seeded_db(self, expires_at: str):
        return _db(installations=[{
            "id": "inst-1", "team_id": "T1", "app_id": "A1", "client_id": "",
            "installation": _enc({**BOT_FIELDS, "access_token": "tok-1",
                                  "refresh_token": "rt-1", "expires_at": expires_at}),
            "revoked_at": None, "revoked_reason": None, "token_version": 1,
        }])

    async def test_fresh_token_merges_without_refresh(self):
        from utils.slack_installations import ensure_fresh_slack_bot_token

        db = self._seeded_db("2099-01-01T00:00:00+00:00")
        cred = {"team_id": "T1", "app_id": "A1", "access_token": "stale-copy",
                "refresh_token": "rt-stale-copy",
                "expires_at": "2020-01-01T00:00:00+00:00",  # stale copy is expired
                "user_access_token": "user-tok"}
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            token = await ensure_fresh_slack_bot_token(
                _FakePool(db), cred, user_id="u1", credential_id="c1",
                caller_path="execute",
            )
        assert token == "tok-1"
        assert cred["access_token"] == "tok-1"          # stale blob copy replaced
        assert cred["user_access_token"] == "user-tok"  # user fields untouched
        assert "token_version" not in cred              # installation bookkeeping doesn't leak

    async def test_expired_token_refreshes_installation_row(self):
        from utils.slack_installations import ensure_fresh_slack_bot_token

        db = self._seeded_db("2020-01-01T00:00:00+00:00")

        class _Tokens:
            access_token = "tok-2"
            refresh_token = "rt-2"
            expires_at = "2099-01-01T00:00:00+00:00"
            scope = "chat:write"
            token_type = "bot"

        async def fake_refresh(rt, client_id=None, client_secret=None):
            assert rt == "rt-1"
            return _Tokens()

        cred = {"team_id": "T1", "app_id": "A1", "access_token": "stale-copy",
                "refresh_token": "rt-stale-copy",
                "expires_at": "2020-01-01T00:00:00+00:00"}
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()), patch(
            "nodes.oauth.slack_oauth.refresh_access_token", new=fake_refresh
        ):
            token = await ensure_fresh_slack_bot_token(
                _FakePool(db), cred, user_id="u1", credential_id="c1",
                caller_path="execute",
            )
        assert token == "tok-2"
        assert cred["refresh_token"] == "rt-2"
        persisted = json.loads(db["installations"][0]["installation"])
        assert persisted["refresh_token"] == "rt-2"
        assert db["installations"][0]["token_version"] == 2  # trigger bumped

    async def test_rejected_token_adopts_rotated_bundle_without_burning(self):
        """A rejected embedded bot token may lag the installation chain: the bot
        token is revoked-but-unexpired after the installation chain rotated.
        The execute path passes the rejected token as ``invalid_access_token``;
        the already-rotated bundle must be ADOPTED — no provider refresh call,
        no extra single-use rotation burned."""
        from utils.slack_installations import ensure_fresh_slack_bot_token

        db = self._seeded_db("2099-01-01T00:00:00+00:00")

        async def fake_refresh(rt, client_id=None, client_secret=None):
            raise AssertionError(
                "provider refresh called — a rotation was burned for a bundle "
                "that had already rotated past the rejected token"
            )

        cred = {"team_id": "T1", "app_id": "A1",
                "access_token": "revoked-but-unexpired",
                "refresh_token": "rt-stale-copy",
                "expires_at": "2099-01-01T00:00:00+00:00"}  # locally "fresh"
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()), patch(
            "nodes.oauth.slack_oauth.refresh_access_token", new=fake_refresh
        ):
            token = await ensure_fresh_slack_bot_token(
                _FakePool(db), cred, user_id="u1", credential_id="c1",
                invalid_access_token="revoked-but-unexpired",
                caller_path="execute",
            )
        assert token == "tok-1"                 # the chain's newer token, adopted
        assert cred["access_token"] == "tok-1"  # merged into the blob copy
        assert db["installations"][0]["token_version"] == 1  # no rotation burned

    async def test_concurrent_siblings_burn_one_rotation(self):
        """Concurrent-refresh regression: two credentials of the same workspace
        refresh concurrently. The per-installation lock + in-lock re-read must
        produce exactly ONE provider rotation, and both credential dicts end on
        the same fresh bundle — no copy can clobber the rotated token."""
        from utils.slack_installations import ensure_fresh_slack_bot_token

        db = self._seeded_db("2020-01-01T00:00:00+00:00")
        refresh_calls = []

        class _Tokens:
            access_token = "tok-2"
            refresh_token = "rt-2"
            expires_at = "2099-01-01T00:00:00+00:00"
            scope = "chat:write"
            token_type = "bot"

        async def fake_refresh(rt, client_id=None, client_secret=None):
            refresh_calls.append(rt)
            await asyncio.sleep(0.01)  # widen the race window
            return _Tokens()

        cred_a = {"team_id": "T1", "app_id": "A1", "access_token": "copy-a",
                  "refresh_token": "rt-copy-a", "expires_at": "2020-01-01T00:00:00+00:00"}
        cred_b = {"team_id": "T1", "app_id": "A1", "access_token": "copy-b",
                  "refresh_token": "rt-copy-b", "expires_at": "2020-01-01T00:00:00+00:00"}
        pool = _FakePool(db)
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()), patch(
            "nodes.oauth.slack_oauth.refresh_access_token", new=fake_refresh
        ):
            tok_a, tok_b = await asyncio.gather(
                ensure_fresh_slack_bot_token(pool, cred_a, user_id="u-a",
                                             credential_id="c-a", caller_path="execute"),
                ensure_fresh_slack_bot_token(pool, cred_b, user_id="u-b",
                                             credential_id="c-b", caller_path="freshen"),
            )
        assert refresh_calls == ["rt-1"], "exactly one rotation must hit the provider"
        assert tok_a == tok_b == "tok-2"
        assert cred_a["refresh_token"] == cred_b["refresh_token"] == "rt-2"
        persisted = json.loads(db["installations"][0]["installation"])
        assert persisted["refresh_token"] == "rt-2"


class TestUpsertFromExchange:
    async def test_exchange_overwrites_existing_installation(self):
        from utils.slack_installations import upsert_slack_installation_from_exchange

        db = _db(installations=[{
            "id": "inst-1", "team_id": "T1", "app_id": "A1", "client_id": "",
            "installation": _enc({**BOT_FIELDS, "access_token": "old", "refresh_token": "rt-old"}),
            "revoked_at": "2026-06-10T00:00:00+00:00",  # previously revoked
            "revoked_reason": "F29_user_revoked", "token_version": 9,
        }])
        fresh = {**BOT_FIELDS, "access_token": "tok-new", "refresh_token": "rt-new",
                 "expires_at": "2099-01-01T00:00:00+00:00"}
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            await upsert_slack_installation_from_exchange(_FakePool(db), fresh)
        row = db["installations"][0]
        persisted = json.loads(row["installation"])
        assert persisted["access_token"] == "tok-new"
        assert row["revoked_at"] is None, "reconnect must clear the auto-revoke flag"
        assert row["token_version"] == 10  # trigger bumped

    async def test_exchange_creates_installation_for_new_workspace(self):
        from utils.slack_installations import upsert_slack_installation_from_exchange

        db = _db()
        fresh = {**BOT_FIELDS, "access_token": "tok", "refresh_token": "rt",
                 "expires_at": "2099-01-01T00:00:00+00:00"}
        with patch("utils.encryption.get_encryption", return_value=_FakeEncryption()):
            await upsert_slack_installation_from_exchange(_FakePool(db), fresh)
        assert len(db["installations"]) == 1
        assert db["installations"][0]["team_id"] == "T1"

    async def test_locally_fresh_token_skips_resolution(self):
        """Execute-path no-op parity: a locally fresh, unforced token must not
        touch the database at all (the pool would raise if used)."""
        from utils.slack_installations import ensure_fresh_slack_bot_token

        cred = {"team_id": "T1", "access_token": "tok-local",
                "refresh_token": "rt", "expires_at": "2099-01-01T00:00:00+00:00"}
        token = await ensure_fresh_slack_bot_token(
            object(), cred, user_id="u1", credential_id="c1", caller_path="execute",
        )
        assert token == "tok-local"

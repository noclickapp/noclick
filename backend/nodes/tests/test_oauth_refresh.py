"""Tests for the shared OAuth refresh helper (nodes/core/oauth_refresh.py).

This is the one implementation every OAuth node now routes through, so it is
covered exhaustively: expiry detection, refresh + persist, the concurrent-
refresh no-op (re-read the DB inside the lock), and recovery when a rotating
refresh token was consumed by another container.

Run: pytest nodes/tests/test_oauth_refresh.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, patch

from nodes.core.oauth_refresh import ensure_fresh_oauth_token, is_token_expired


def _iso(delta_seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    ).isoformat()


def _tokens(
    access_token: str,
    refresh_token: str = "r2",
    ttl: int = 3600,
    *,
    scope: str | None = None,
    token_type: str = "Bearer",
):
    return type(
        "Tokens",
        (),
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": _iso(ttl),
            "scope": scope,
            "token_type": token_type,
        },
    )()


# ---------------------------------------------------------------------------
# is_token_expired
# ---------------------------------------------------------------------------


class TestIsTokenExpired:
    def test_future_token_not_expired(self):
        assert is_token_expired(_iso(3600)) is False

    def test_past_token_expired(self):
        assert is_token_expired(_iso(-3600)) is True

    def test_within_buffer_counts_as_expired(self):
        # Expires in 2 minutes — inside the default 5-minute buffer.
        assert is_token_expired(_iso(120)) is True

    def test_missing_expiry_not_expired(self):
        assert is_token_expired(None) is False

    def test_unparseable_expiry_treated_as_expired(self):
        assert is_token_expired("not-a-date") is True


# ---------------------------------------------------------------------------
# ensure_fresh_oauth_token
# ---------------------------------------------------------------------------


class TestEnsureFreshOAuthToken:
    async def test_fresh_token_returned_without_refresh(self):
        cred = {"access_token": "good", "refresh_token": "r1", "expires_at": _iso(3600)}
        refresh = AsyncMock()
        token = await ensure_fresh_oauth_token(
            pool=object(), credential_id="cid", user_id="uid",
            credential=cred, refresh=refresh,
        )
        assert token == "good"
        refresh.assert_not_awaited()

    async def test_force_refresh_refreshes_even_when_token_is_fresh(self):
        cred = {"access_token": "good", "refresh_token": "r1", "expires_at": _iso(3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "good", "refresh_token": "r1", "expires_at": _iso(3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            refresh = AsyncMock(return_value=_tokens("forced-token", "r2"))
            token = await ensure_fresh_oauth_token(
                pool=object(),
                credential_id="cid",
                user_id="uid",
                credential=cred,
                refresh=refresh,
                force_refresh=True,
            )

        assert token == "forced-token"
        assert cred["access_token"] == "forced-token"
        assert cred["refresh_token"] == "r2"
        refresh.assert_awaited_once_with("r1")
        persist.assert_awaited_once()

    async def test_no_expiry_returned_as_is(self):
        cred = {"access_token": "good", "refresh_token": "r1", "expires_at": None}
        refresh = AsyncMock()
        token = await ensure_fresh_oauth_token(
            pool=object(), credential_id="cid", user_id="uid",
            credential=cred, refresh=refresh,
        )
        assert token == "good"
        refresh.assert_not_awaited()

    async def test_expired_without_refresh_token_raises(self):
        cred = {"access_token": "stale", "expires_at": _iso(-3600)}
        with pytest.raises(ValueError, match="no refresh token"):
            await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, refresh=AsyncMock(),
            )

    async def test_no_ids_refreshes_in_memory_only(self):
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            token = await ensure_fresh_oauth_token(
                pool=object(), credential_id=None, user_id=None,
                credential=cred, refresh=AsyncMock(return_value=_tokens("new-token")),
            )
        assert token == "new-token"
        assert cred["access_token"] == "new-token"
        persist.assert_not_awaited()  # nothing to persist to

    async def test_expired_refreshed_and_persisted(self):
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            token = await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, refresh=AsyncMock(return_value=_tokens("new-token", "r2")),
            )
        assert token == "new-token"
        assert cred["access_token"] == "new-token"
        assert cred["refresh_token"] == "r2"  # rotated token adopted
        persist.assert_awaited_once()

    async def test_explicit_provider_metadata_is_adopted_and_persisted(self):
        cred = {
            "access_token": "stale",
            "refresh_token": "r1",
            "expires_at": _iso(-3600),
            "instance_url": "https://old.my.salesforce.com",
        }
        refreshed = _tokens("new-token", "r2")
        refreshed.instance_url = "https://rotated.my.salesforce.com"
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=dict(cred)),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            token = await ensure_fresh_oauth_token(
                pool=object(),
                credential_id="cid",
                user_id="uid",
                credential=cred,
                refresh=AsyncMock(return_value=refreshed),
                additional_token_fields=("instance_url",),
            )

        assert token == "new-token"
        assert cred["instance_url"] == "https://rotated.my.salesforce.com"
        assert (
            persist.await_args.kwargs["new_data"]["instance_url"]
            == "https://rotated.my.salesforce.com"
        )

    async def test_expired_custom_token_keys_refresh_without_touching_default_keys(self):
        cred = {
            "access_token": "bot-token",
            "refresh_token": "bot-refresh",
            "expires_at": _iso(3600),
            "user_access_token": "stale-user",
            "user_refresh_token": "user-r1",
            "user_expires_at": _iso(-3600),
        }
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "bot-token",
                "refresh_token": "bot-refresh",
                "expires_at": _iso(3600),
                "user_access_token": "stale-user",
                "user_refresh_token": "user-r1",
                "user_expires_at": _iso(-3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            token = await ensure_fresh_oauth_token(
                pool=object(),
                credential_id="cid",
                user_id="uid",
                credential=cred,
                refresh=AsyncMock(return_value=_tokens("new-user", "user-r2")),
                access_token_key="user_access_token",
                refresh_token_key="user_refresh_token",
                expires_at_key="user_expires_at",
            )
        assert token == "new-user"
        assert cred["access_token"] == "bot-token"
        assert cred["refresh_token"] == "bot-refresh"
        assert cred["user_access_token"] == "new-user"
        assert cred["user_refresh_token"] == "user-r2"
        persisted = persist.await_args.kwargs["new_data"]
        assert persisted["access_token"] == "bot-token"
        assert persisted["user_access_token"] == "new-user"

    async def test_expired_refresh_preserves_scope_and_token_type(self):
        cred = {
            "access_token": "stale",
            "refresh_token": "r1",
            "expires_at": _iso(-3600),
        }
        refreshed = _tokens(
            "new-token",
            "r2",
            scope="read:jira-work read:board-scope:jira-software",
            token_type="Bearer",
        )
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "stale",
                "refresh_token": "r1",
                "expires_at": _iso(-3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ) as persist:
            token = await ensure_fresh_oauth_token(
                pool=object(),
                credential_id="cid",
                user_id="uid",
                credential=cred,
                refresh=AsyncMock(return_value=refreshed),
            )
        assert token == "new-token"
        assert cred["scope"] == "read:jira-work read:board-scope:jira-software"
        assert cred["token_type"] == "Bearer"
        persist.assert_awaited_once()

    async def test_concurrent_refresh_is_noop_when_db_fresh(self):
        # The lock holder re-reads the DB; if another execution already
        # refreshed, adopt that token without a second refresh.
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        refresh = AsyncMock()
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "db-token", "refresh_token": "r9", "expires_at": _iso(3600),
            }),
        ):
            token = await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, refresh=refresh,
            )
        assert token == "db-token"
        refresh.assert_not_awaited()

    async def test_force_refresh_does_not_adopt_fresh_db_row(self):
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "db-token", "refresh_token": "r9", "expires_at": _iso(3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ):
            refresh = AsyncMock(return_value=_tokens("forced-token", "r10"))
            token = await ensure_fresh_oauth_token(
                pool=object(),
                credential_id="cid",
                user_id="uid",
                credential=cred,
                refresh=refresh,
                force_refresh=True,
            )

        assert token == "forced-token"
        assert cred["access_token"] == "forced-token"
        assert cred["refresh_token"] == "r10"
        refresh.assert_awaited_once_with("r9")

    async def test_refresh_failure_recovers_from_db(self):
        # A rotating refresh token consumed by another container — refresh
        # fails, but re-reading the DB yields the token it persisted.
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        loads = [
            {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)},
            {"access_token": "other-token", "refresh_token": "r5", "expires_at": _iso(3600)},
        ]
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(side_effect=loads),
        ):
            token = await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid", credential=cred,
                refresh=AsyncMock(side_effect=ValueError("invalid_grant")),
            )
        assert token == "other-token"

    async def test_force_refresh_failure_does_not_adopt_unchanged_fresh_db_row(self):
        cred = {"access_token": "revoked", "refresh_token": "r1", "expires_at": _iso(3600)}
        unchanged = {"access_token": "revoked", "refresh_token": "r1", "expires_at": _iso(3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=unchanged),
        ):
            with pytest.raises(ValueError, match="refresh failed"):
                await ensure_fresh_oauth_token(
                    pool=object(),
                    credential_id="cid",
                    user_id="uid",
                    credential=cred,
                    refresh=AsyncMock(side_effect=ValueError("invalid_refresh_token")),
                    force_refresh=True,
                )

    async def test_refresh_failure_with_no_recovery_raises(self):
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        stale = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=stale),
        ):
            with pytest.raises(ValueError, match="refresh failed"):
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid", credential=cred,
                    refresh=AsyncMock(side_effect=ValueError("invalid_grant")),
                )

    async def test_persist_db_error_after_refresh_raises(self):
        # A successful refresh consumes the single-use rotating token. If the
        # write dies on a DB exception, the rotated successor is gone and the
        # next refresh would submit a revoked token, bricking the credential.
        # Fail loudly instead of returning it (no CAS retry on exceptions).
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(0, "UndefinedColumnError")),
        ):
            with pytest.raises(ValueError, match="could not be persisted"):
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=cred,
                    refresh=AsyncMock(return_value=_tokens("new-token", "r2")),
                )

    async def test_persist_zero_rows_row_deleted_raises(self):
        # Zero rows with no error and the row gone on re-read = credential was
        # deleted mid-refresh (F39). Same loud failure as before CAS existed.
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        stale = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(side_effect=[stale, None]),  # in-lock read, post-conflict read
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(0, None)),
        ):
            with pytest.raises(ValueError, match="could not be persisted"):
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=cred,
                    refresh=AsyncMock(return_value=_tokens("new-token", "r2")),
                )

    async def test_persist_version_conflict_retries_with_merge(self):
        # CAS guard lost once: a concurrent writer bumped token_version between
        # our in-lock re-read and persist. The retry must overlay OUR refreshed
        # token onto the WINNER's row (their non-token fields survive) and
        # persist against the winner's version.
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        stale = {
            "access_token": "stale", "refresh_token": "r1",
            "expires_at": _iso(-3600), "token_version": 7,
        }
        winner = {
            "access_token": "stale", "refresh_token": "r1",
            "expires_at": _iso(-3600), "token_version": 8,
            "user_access_token": "winner-user-token",  # concurrent user-chain refresh
        }
        update_mock = AsyncMock(side_effect=[(0, None), (1, None)])
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(side_effect=[stale, winner]),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=update_mock,
        ):
            token = await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred,
                refresh=AsyncMock(return_value=_tokens("new-token", "r2")),
            )
        assert token == "new-token"
        assert update_mock.await_count == 2
        retry_kwargs = update_mock.await_args_list[1].kwargs
        merged = retry_kwargs["new_data"]
        assert merged["access_token"] == "new-token"
        assert merged["refresh_token"] == "r2"
        assert merged["user_access_token"] == "winner-user-token"
        assert retry_kwargs["expected_token_version"] == 8
        # The caller's dict reflects the merged persisted state.
        assert cred["user_access_token"] == "winner-user-token"

    async def test_persist_version_conflict_twice_raises(self):
        # If a concurrent writer wins the CAS twice in a row, give up loudly —
        # returning a token whose rotated successor was never saved would brick
        # the credential silently.
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        stale = {
            "access_token": "stale", "refresh_token": "r1",
            "expires_at": _iso(-3600), "token_version": 7,
        }
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=stale),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(0, None)),
        ):
            with pytest.raises(ValueError, match="concurrent writer kept winning"):
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=cred,
                    refresh=AsyncMock(return_value=_tokens("new-token", "r2")),
                )


class TestForceRefreshOnceScope:
    """force_refresh_once_scope: trigger-test batches force at most one
    rotation per token chain; repeats downgrade to expiry-gated refreshes."""

    @staticmethod
    def _fresh_cred():
        return {"access_token": "tok", "refresh_token": "r1", "expires_at": _iso(+3600)}

    async def test_second_force_in_scope_downgrades_to_noop(self):
        from nodes.core.oauth_refresh import force_refresh_once_scope

        cred = self._fresh_cred()
        refresh = AsyncMock(return_value=_tokens("tok-2", "r2"))
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=self._fresh_cred()),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ):
            with force_refresh_once_scope():
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=cred, refresh=refresh, force_refresh=True,
                )
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=cred, refresh=refresh, force_refresh=True,
                )
        assert refresh.await_count == 1, "second force must downgrade to in-lock noop"

    async def test_distinct_token_chains_not_deduped(self):
        # The bot and user chains on one credential rotate independently —
        # deduping across refresh_token_key would skip a needed user rotation.
        from nodes.core.oauth_refresh import force_refresh_once_scope

        bot_cred = self._fresh_cred()
        user_cred = {
            "user_access_token": "utok", "user_refresh_token": "ur1",
            "user_expires_at": _iso(+3600),
        }
        refresh = AsyncMock(return_value=_tokens("tok-2", "r2"))
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(side_effect=lambda *a: dict(bot_cred, **user_cred)),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ):
            with force_refresh_once_scope():
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=bot_cred, refresh=refresh, force_refresh=True,
                )
                await ensure_fresh_oauth_token(
                    pool=object(), credential_id="cid", user_id="uid",
                    credential=user_cred, refresh=refresh, force_refresh=True,
                    access_token_key="user_access_token",
                    refresh_token_key="user_refresh_token",
                    expires_at_key="user_expires_at",
                )
        assert refresh.await_count == 2

    async def test_no_scope_forces_every_time(self):
        cred = self._fresh_cred()
        refresh = AsyncMock(return_value=_tokens("tok-2", "r2"))
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=self._fresh_cred()),
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new=AsyncMock(return_value=(1, None)),
        ):
            await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, refresh=refresh, force_refresh=True,
            )
            await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, refresh=refresh, force_refresh=True,
            )
        assert refresh.await_count == 2

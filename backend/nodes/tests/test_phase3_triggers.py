"""Phase 3 webhook-trigger tests — Google Drive, Google Calendar, Jira.

These triggers use expiring push subscriptions (Google watch channels, Jira
dynamic webhooks) tracked in the webhook_channels table and renewed by a
scheduled worker. Tests cover: the Google OAuth refresh-and-persist helper, channel
registration/renewal, the X-Goog-Channel-Token verification, the sync-message
handshake, and the renewal dispatcher.

Run: pytest nodes/tests/test_phase3_triggers.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, patch

from nodes.google_drive_node import (
    GoogleDriveNode,
    GoogleDriveOnChangeConfig,
    _ms_to_datetime,
)
from nodes.google_calendar_node import (
    GoogleCalendarNode,
    GoogleCalendarOnEventConfig,
)
from nodes.jira_node import (
    JiraNode,
    _MATCH_ALL_JQL,
    _jira_api_base_from_dict,
    _jira_auth_headers_from_dict,
)
from nodes.core.watch_channels import WatchChannelTriggerMixin, renew_channel


def _iso(delta_seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    ).isoformat()


# ---------------------------------------------------------------------------
# Google OAuth refresh-and-persist
# ---------------------------------------------------------------------------


class TestEnsureFreshGoogleToken:
    async def test_fresh_token_returned_as_is(self):
        from nodes.oauth.google_token import ensure_fresh_google_token

        cred = {"access_token": "still_good", "expires_at": _iso(3600)}
        with patch(
            "nodes.oauth.google_token.refresh_access_token", new=AsyncMock()
        ) as mock_refresh:
            token = await ensure_fresh_google_token(None, "cid", "uid", cred)
        assert token == "still_good"
        mock_refresh.assert_not_awaited()

    async def test_expired_token_refreshed_and_persisted(self):
        from nodes.oauth.google_token import ensure_fresh_google_token

        cred = {
            "access_token": "stale",
            "refresh_token": "r",
            "expires_at": _iso(-3600),
        }
        new_tokens = type(
            "T",
            (),
            {"access_token": "fresh", "refresh_token": "r2", "expires_at": _iso(3600)},
        )()
        with patch(
            "nodes.oauth.google_token.refresh_access_token",
            new=AsyncMock(return_value=new_tokens),
        ), patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(
                return_value={
                    "access_token": "stale",
                    "refresh_token": "r",
                    "expires_at": _iso(-3600),
                }
            ),
        ), patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ) as mock_update:
            token = await ensure_fresh_google_token(object(), "cid", "uid", cred)
        assert token == "fresh"
        assert cred["access_token"] == "fresh"
        mock_update.assert_awaited_once()

    async def test_expired_without_refresh_token_raises(self):
        from nodes.oauth.google_token import ensure_fresh_google_token

        cred = {"access_token": "stale", "expires_at": _iso(-3600)}
        with pytest.raises(ValueError, match="refresh token"):
            await ensure_fresh_google_token(None, "cid", "uid", cred)


# ---------------------------------------------------------------------------
# Google Drive trigger
# ---------------------------------------------------------------------------


class TestGoogleDriveTrigger:
    def test_uses_watch_channel_mixin(self):
        assert issubclass(GoogleDriveNode, WatchChannelTriggerMixin)

    def test_trigger_op_in_schema(self):
        schema = GoogleDriveNode.get_config_schema()
        op = schema["$defs"]["GoogleDriveOnChangeConfig"]["properties"]["operation"]
        assert op["const"] == "on_drive_change"
        assert op["x-is-trigger"] is True

    def test_ms_to_datetime(self):
        dt = _ms_to_datetime("1700000000000")
        assert dt.year == 2023
        # A missing/invalid value falls back to a future expiry.
        assert _ms_to_datetime(None) > datetime.now(timezone.utc)

    def test_sync_message_is_handshake(self):
        assert GoogleDriveNode.handle_webhook_handshake(
            b"", {"x-goog-resource-state": "sync"}
        ) == {}

    def test_change_message_is_not_handshake(self):
        assert GoogleDriveNode.handle_webhook_handshake(
            b"", {"x-goog-resource-state": "change"}
        ) is None

    def test_channel_token_verification(self):
        config = {"signing_secret": "tok-abc"}
        assert GoogleDriveNode.verify_webhook_signature(
            b"", {"x-goog-channel-token": "tok-abc"}, config
        ) is True
        assert GoogleDriveNode.verify_webhook_signature(
            b"", {"x-goog-channel-token": "wrong"}, config
        ) is False
        assert GoogleDriveNode.verify_webhook_signature(b"", {}, {}) is False

    def test_resolve_trigger_payload_returns_none(self):
        # Drive notifications are wake-up signals — execute() must run.
        assert GoogleDriveNode.resolve_trigger_payload({"x": 1}, {}) is None

    async def test_register_watch_channel(self):
        with patch(
            "nodes.google_drive_node.ensure_fresh_google_token",
            new=AsyncMock(return_value="access-tok"),
        ), patch(
            "nodes.google_drive_node.get_watch_channel",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.google_drive_node.drive_get_start_page_token",
            new=AsyncMock(return_value="PT-START"),
        ), patch(
            "nodes.google_drive_node.drive_watch_changes",
            new=AsyncMock(return_value={"resourceId": "RID", "expiration": "1700000000000"}),
        ), patch(
            "nodes.google_drive_node.save_watch_channel", new=AsyncMock()
        ) as mock_save:
            result = await GoogleDriveNode._register_watch_channel(
                pool=object(),
                user_id="uid",
                workflow_id="wid",
                node_id="n1",
                webhook_id="whid",
                webhook_url="https://wh.hooks.example.test/whid",
                credential={"access_token": "t", "expires_at": _iso(3600)},
                credential_id="cid",
                config={},
            )
        assert result["signing_secret"]
        assert result["drive_page_token"] == "PT-START"
        mock_save.assert_awaited_once()
        assert mock_save.await_args.kwargs["provider"] == "google_drive"
        assert mock_save.await_args.kwargs["resource_id"] == "RID"


# ---------------------------------------------------------------------------
# Google Calendar trigger
# ---------------------------------------------------------------------------


class TestGoogleCalendarTrigger:
    def test_uses_watch_channel_mixin(self):
        assert issubclass(GoogleCalendarNode, WatchChannelTriggerMixin)

    def test_trigger_op_in_schema(self):
        schema = GoogleCalendarNode.get_config_schema()
        op = schema["$defs"]["GoogleCalendarOnEventConfig"]["properties"]["operation"]
        assert op["const"] == "on_calendar_event"
        assert op["x-is-trigger"] is True

    def test_sync_message_is_handshake(self):
        assert GoogleCalendarNode.handle_webhook_handshake(
            b"", {"x-goog-resource-state": "sync"}
        ) == {}

    def test_channel_token_verification(self):
        config = {"signing_secret": "cal-tok"}
        assert GoogleCalendarNode.verify_webhook_signature(
            b"", {"x-goog-channel-token": "cal-tok"}, config
        ) is True
        assert GoogleCalendarNode.verify_webhook_signature(
            b"", {"x-goog-channel-token": "no"}, config
        ) is False

    async def test_register_watch_channel_stores_calendar_id(self):
        with patch(
            "nodes.google_calendar_node.ensure_fresh_google_token",
            new=AsyncMock(return_value="access-tok"),
        ), patch(
            "nodes.google_calendar_node.get_watch_channel",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.google_calendar_node.calendar_get_sync_token",
            new=AsyncMock(return_value="SYNC-1"),
        ), patch(
            "nodes.google_calendar_node.calendar_watch_events",
            new=AsyncMock(return_value={"resourceId": "RID", "expiration": "1700000000000"}),
        ), patch(
            "nodes.google_calendar_node.save_watch_channel", new=AsyncMock()
        ) as mock_save:
            result = await GoogleCalendarNode._register_watch_channel(
                pool=object(),
                user_id="uid",
                workflow_id="wid",
                node_id="n1",
                webhook_id="whid",
                webhook_url="https://wh.hooks.example.test/whid",
                credential={"access_token": "t", "expires_at": _iso(3600)},
                credential_id="cid",
                config={"calendar_id": "team@group.calendar.google.com"},
            )
        assert result["calendar_sync_token"] == "SYNC-1"
        # The calendar id must be persisted so the renewal job can re-watch it.
        assert (
            mock_save.await_args.kwargs["watched_resource"]
            == "team@group.calendar.google.com"
        )


# ---------------------------------------------------------------------------
# Jira trigger
# ---------------------------------------------------------------------------


class TestJiraTrigger:
    def test_uses_watch_channel_mixin(self):
        assert issubclass(JiraNode, WatchChannelTriggerMixin)

    def test_trigger_op_in_schema(self):
        schema = JiraNode.get_config_schema()
        op = schema["$defs"]["JiraOnIssueCreatedConfig"]["properties"]["operation"]
        assert op["const"] == "on_issue_created"
        assert op["x-is-trigger"] is True

    def test_trigger_event_map_covers_all_trigger_ops(self):
        defs = JiraNode.get_config_schema()["$defs"]
        trigger_ops = {
            v["properties"]["operation"]["const"]
            for v in defs.values()
            if v.get("properties", {}).get("operation", {}).get("x-is-trigger")
        }
        assert trigger_ops == set(JiraNode._trigger_event_map)

    def test_api_base_oauth_vs_token(self):
        oauth = {"credential_type": "jira_oauth", "cloud_id": "CID", "access_token": "t"}
        assert "ex/jira/CID" in _jira_api_base_from_dict(oauth)
        token = {"credential_type": "jira_api_token", "domain": "acme.atlassian.net"}
        assert _jira_api_base_from_dict(token) == "https://acme.atlassian.net/rest/api/3"

    def test_auth_headers_oauth_vs_token(self):
        oauth = {"credential_type": "jira_oauth", "access_token": "tok"}
        assert _jira_auth_headers_from_dict(oauth)["Authorization"] == "Bearer tok"
        token = {
            "credential_type": "jira_api_token",
            "email": "a@b.com",
            "api_token": "xyz",
        }
        assert _jira_auth_headers_from_dict(token)["Authorization"].startswith("Basic ")

    async def test_freshen_credential_backfills_oauth_metadata_from_db(self):
        class _FakeAcquire:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _FakePool:
            def __init__(self, conn):
                self._conn = conn

            def acquire(self):
                return _FakeAcquire(self._conn)

        class _FakeConn:
            def __init__(self):
                self.fetchrow = AsyncMock(
                    return_value={
                        "metadata": {
                            "cloud_id": "CID-123",
                            "site_name": "Acme Jira",
                            "site_url": "https://acme.atlassian.net",
                            "scopes": [
                                "read:jira-work",
                                "manage:jira-webhook",
                            ],
                        }
                    }
                )

        conn = _FakeConn()
        pool = _FakePool(conn)

        async def _passthrough(credential_data, **_kwargs):
            return credential_data

        with patch(
            "wss.handlers.workflow_handler.get_user_org_context",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.core.oauth_refresh.freshen_oauth_credential",
            new=AsyncMock(side_effect=_passthrough),
        ):
            refreshed = await JiraNode.freshen_credential(
                {
                    "credential_type": "jira_oauth",
                    "access_token": "token-1",
                    "refresh_token": "refresh-1",
                    "expires_at": _iso(3600),
                },
                pool=pool,
                user_id="uid",
                credential_id="cid",
            )

        assert refreshed["cloud_id"] == "CID-123"
        assert refreshed["site_name"] == "Acme Jira"
        assert refreshed["site_url"] == "https://acme.atlassian.net"
        assert refreshed["scope"] == "read:jira-work manage:jira-webhook"

    def test_no_signature_override(self):
        # Jira dynamic webhooks carry no HMAC — the node deliberately inherits
        # the permissive base default (URL secrecy is the security boundary).
        assert JiraNode.verify_webhook_signature(b"x", {}, {}) is True

    async def test_register_watch_channel(self):
        mock_register = AsyncMock(return_value="9001")
        with patch(
            "nodes.jira_node.get_watch_channel",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.jira_node.jira_register_webhook",
            new=mock_register,
        ), patch(
            "nodes.jira_node.save_watch_channel", new=AsyncMock()
        ) as mock_save:
            result = await JiraNode._register_watch_channel(
                pool=object(),
                user_id="uid",
                workflow_id="wid",
                node_id="n1",
                webhook_id="whid",
                webhook_url="https://wh.hooks.example.test/whid",
                credential={"credential_type": "jira_api_token", "domain": "acme.atlassian.net",
                            "email": "a@b.com", "api_token": "xyz"},
                credential_id="cid",
                config={"events": ["jira:issue_created"], "jql_filter": "project = PROJ"},
            )
        assert result == {}
        mock_save.assert_awaited_once()
        kwargs = mock_save.await_args.kwargs
        assert kwargs["provider"] == "jira"
        assert kwargs["channel_id"] == "9001"
        assert mock_register.await_args.args[4] == "project = PROJ"

    async def test_register_watch_channel_builds_jql_from_project_key(self):
        mock_register = AsyncMock(return_value="9001")
        with patch(
            "nodes.jira_node.get_watch_channel",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.jira_node.jira_register_webhook",
            new=mock_register,
        ), patch(
            "nodes.jira_node.save_watch_channel", new=AsyncMock()
        ):
            await JiraNode._register_watch_channel(
                pool=object(),
                user_id="uid",
                workflow_id="wid",
                node_id="n1",
                webhook_id="whid",
                webhook_url="https://wh.hooks.example.test/whid",
                credential={"credential_type": "jira_api_token", "domain": "acme.atlassian.net",
                            "email": "a@b.com", "api_token": "xyz"},
                credential_id="cid",
                config={"operation": "on_issue_created", "project_key": "CHECKO"},
            )

        assert mock_register.await_args.args[4] == "project = CHECKO"

    async def test_register_watch_channel_defaults_to_match_all_jql(self):
        # With no jql_filter/project_key, the trigger must register a match-all
        # JQL — Jira rejects an empty jqlFilter ("Empty JQL search not supported").
        mock_register = AsyncMock(return_value="9001")
        with patch(
            "nodes.jira_node.get_watch_channel",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.jira_node.jira_register_webhook",
            new=mock_register,
        ), patch(
            "nodes.jira_node.save_watch_channel", new=AsyncMock()
        ):
            await JiraNode._register_watch_channel(
                pool=object(),
                user_id="uid",
                workflow_id="wid",
                node_id="n1",
                webhook_id="whid",
                webhook_url="https://wh.hooks.example.test/whid",
                credential={"credential_type": "jira_api_token", "domain": "acme.atlassian.net",
                            "email": "a@b.com", "api_token": "xyz"},
                credential_id="cid",
                config={"operation": "on_issue_created"},
            )

        assert mock_register.await_args.args[4] == _MATCH_ALL_JQL
        assert mock_register.await_args.args[4] != ""

    async def test_renew_extends_expiry(self):
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={"credential_type": "jira_api_token",
                                        "domain": "acme.atlassian.net",
                                        "email": "a@b.com", "api_token": "xyz"}),
        ), patch(
            "nodes.jira_node.jira_refresh_webhook", new=AsyncMock()
        ) as mock_refresh, patch(
            "nodes.jira_node.update_channel_subscription", new=AsyncMock()
        ) as mock_update:
            await JiraNode.renew_watch_channel(
                object(),
                {
                    "id": "row-1",
                    "user_id": "uid",
                    "credential_id": "cid",
                    "channel_id": "9001",
                },
            )
        mock_refresh.assert_awaited_once()
        mock_update.assert_awaited_once()


# ---------------------------------------------------------------------------
# Renewal dispatcher
# ---------------------------------------------------------------------------


class TestRenewalDispatch:
    async def test_dispatches_to_node_class(self):
        with patch.object(
            GoogleDriveNode, "renew_watch_channel", new=AsyncMock()
        ) as mock_renew:
            await renew_channel(
                object(), {"provider": "google_drive", "id": "row-1"}
            )
        mock_renew.assert_awaited_once()

    async def test_unknown_provider_is_noop(self):
        # Should not raise — just logs and returns.
        await renew_channel(object(), {"provider": "mystery", "id": "row-1"})


# ---------------------------------------------------------------------------
# Renewal hardening — adaptive timing + failure recording
# ---------------------------------------------------------------------------


class TestRenewalHardening:
    def test_renew_after_is_midpoint_of_remaining_life(self):
        from datetime import timedelta
        from nodes.core.watch_channels import renew_after_for

        # A channel that lives ~10 more hours should renew in ~5 hours, so the
        # hourly cron safely covers it regardless of the granted TTL.
        renew_at = renew_after_for(
            datetime.now(timezone.utc) + timedelta(hours=10)
        )
        hours_until = (
            renew_at - datetime.now(timezone.utc)
        ).total_seconds() / 3600
        assert 4.5 < hours_until < 5.5

    def test_renew_after_already_expired_is_immediate(self):
        from datetime import timedelta
        from nodes.core.watch_channels import renew_after_for

        renew_at = renew_after_for(
            datetime.now(timezone.utc) - timedelta(hours=1)
        )
        assert renew_at <= datetime.now(timezone.utc) + timedelta(seconds=1)

    async def test_renew_channel_records_failure_without_raising(self):
        from nodes.core.watch_channels import renew_channel

        with patch.object(
            GoogleDriveNode,
            "renew_watch_channel",
            new=AsyncMock(side_effect=RuntimeError("watch API down")),
        ), patch(
            "nodes.core.watch_channels.record_renewal_failure",
            new=AsyncMock(return_value={"renewal_attempts": 3, "expires_at": None}),
        ) as mock_record:
            # Must not raise — the renewal job continues with the rest of the batch.
            await renew_channel(
                object(), {"provider": "google_drive", "id": "row-1"}
            )
        mock_record.assert_awaited_once()
        assert mock_record.await_args.args[1] == "row-1"

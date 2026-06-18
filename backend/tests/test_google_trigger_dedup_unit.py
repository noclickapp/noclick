"""Unit tests (pure mock, no DB/network) for the per-node Google watch
dedup. These live under tests/ (run by backend-tests.yml) rather than
nodes/tests/ because they need no credentials or live APIs.

Contract: x-goog-message-number is monotonic *per channel* and restarts for
each channel, while one resource_id is shared by every channel watching the
same feed. The node's wake-up dedup therefore keys on x-goog-channel-id:
  - a redelivery WITHIN the same channel (number <= last seen) short-circuits
    before any token refresh / list API call;
  - a delivery from a DIFFERENT channel must NOT be judged stale — it falls
    through (here, to the credentials check), so a re-registered channel's low
    numbers are never dropped (the flaky-trigger bug this fixes).
"""

from unittest.mock import AsyncMock, patch

import pytest

from nodes.google_drive_node import (
    GoogleDriveNode, GoogleDriveNodeConfig,
    GoogleDriveOnFileChangedConfig, GoogleDriveOAuthCredential,
)
from nodes.google_calendar_node import (
    GoogleCalendarNode, GoogleCalendarNodeConfig,
    GoogleCalendarOnEventConfig, GoogleCalendarOAuthCredential,
)

DRIVE_CRED = GoogleDriveOAuthCredential(
    access_token="mock", refresh_token="mock",
    expires_at="2099-12-31T23:59:59Z", email="test@example.com",
)
CAL_CRED = GoogleCalendarOAuthCredential(
    access_token="mock", refresh_token="mock",
    expires_at="2099-12-31T23:59:59Z", email="test@example.com",
)


def _headers(channel_id, message_number):
    return {
        "_triggerPayload": {
            "_webhook": {
                "headers": {
                    "x-goog-message-number": str(message_number),
                    "x-goog-resource-id": "shared-resource",
                    "x-goog-channel-id": channel_id,
                }
            }
        }
    }


def _drive_node(node_data, credentials):
    config = GoogleDriveOnFileChangedConfig(drive_page_token="cursor-1", watch_target_id="file-1")
    return GoogleDriveNode(
        node_id="n", node_type="automation-google-drive", node_data=node_data,
        config=GoogleDriveNodeConfig(config=config, credentials=credentials),
        sio=None, sid=None, workflow_id="wf", user_id="u",
    ), config


def _cal_node(node_data, credentials):
    config = GoogleCalendarOnEventConfig(calendar_sync_token="sync-1", calendar_id="primary")
    return GoogleCalendarNode(
        node_id="n", node_type="automation-google-calendar", node_data=node_data,
        config=GoogleCalendarNodeConfig(config=config, credentials=credentials),
        sio=None, sid=None, workflow_id="wf", user_id="u",
    ), config


_DRIVE_STATE = {
    "page_token": "cursor-1",
    "last_google_message_number": 1000,
    "last_google_resource_id": "shared-resource",
    "last_google_channel_id": "channel-1",
}
_CAL_STATE = {
    "sync_token": "sync-1",
    "last_google_message_number": 1000,
    "last_google_resource_id": "shared-resource",
    "last_google_channel_id": "channel-1",
}


# ── Drive ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drive_same_channel_redelivery_short_circuits():
    node, config = _drive_node(_headers("channel-1", 999), DRIVE_CRED)
    with (
        patch.object(node, "_load_node_state", AsyncMock(return_value=dict(_DRIVE_STATE))),
        patch("nodes.google_drive_node.ensure_fresh_google_token", new=AsyncMock()) as refresh,
        patch("nodes.google_drive_node.drive_list_changes", new=AsyncMock()) as list_changes,
    ):
        result = await node._trigger_on_drive_change(config, DRIVE_CRED)
    assert result["deduped"] is True
    assert result["change_count"] == 0
    refresh.assert_not_awaited()
    list_changes.assert_not_awaited()


@pytest.mark.asyncio
async def test_drive_different_channel_not_deduped():
    """Different channel must NOT short-circuit — it falls through to the
    credentials check (None -> ValueError), proving the delivery was accepted."""
    node, config = _drive_node(_headers("channel-2", 5), None)
    with patch.object(node, "_load_node_state", AsyncMock(return_value=dict(_DRIVE_STATE))):
        with pytest.raises(ValueError, match="credentials"):
            await node._trigger_on_drive_change(config, None)


# ── Calendar ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_same_channel_redelivery_short_circuits():
    node, config = _cal_node(_headers("channel-1", 999), CAL_CRED)
    with (
        patch.object(node, "_load_node_state", AsyncMock(return_value=dict(_CAL_STATE))),
        patch("nodes.google_calendar_node.ensure_fresh_google_token", new=AsyncMock()) as refresh,
        patch("nodes.google_calendar_node.calendar_list_changed_events", new=AsyncMock()) as list_events,
    ):
        result = await node._trigger_on_calendar_event(config, CAL_CRED)
    assert result["deduped"] is True
    assert result["event_count"] == 0
    refresh.assert_not_awaited()
    list_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_different_channel_not_deduped():
    node, config = _cal_node(_headers("channel-2", 5), None)
    with patch.object(node, "_load_node_state", AsyncMock(return_value=dict(_CAL_STATE))):
        with pytest.raises(ValueError, match="credentials"):
            await node._trigger_on_calendar_event(config, None)

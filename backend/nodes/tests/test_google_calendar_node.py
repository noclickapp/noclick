"""
Mock tests for Google Calendar workflow node.

Tests all 13 Google Calendar operations with mocked HTTP responses:
- Event operations: list_events, get_event, create_event, update_event, delete_event, quick_add, get_instances, move_event
- Calendar operations: list_calendars, get_calendar, create_calendar, clear_calendar
- Utility operations: query_freebusy

Uses httpx mocking to simulate Google Calendar API responses without real credentials.
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

# Import the node and config classes
from nodes.google_calendar_node import (
    GoogleCalendarNode,
    GoogleCalendarNodeConfig,
    GoogleCalendarOAuthCredential,
    GoogleCalendarOnEventActiveConfig,
    GoogleCalendarOnEventConfig,
    # Event operations
    GoogleCalendarListEventsConfig,
    GoogleCalendarGetEventConfig,
    GoogleCalendarCreateEventConfig,
    GoogleCalendarUpdateEventConfig,
    GoogleCalendarDeleteEventConfig,
    GoogleCalendarQuickAddConfig,
    GoogleCalendarGetInstancesConfig,
    GoogleCalendarMoveEventConfig,
    # Calendar operations
    GoogleCalendarListCalendarsConfig,
    GoogleCalendarGetCalendarConfig,
    GoogleCalendarCreateCalendarConfig,
    GoogleCalendarClearCalendarConfig,
    # Utility operations
    GoogleCalendarQueryFreebusyConfig,
)


# Test credentials (mock - never used for real API calls)
TEST_CREDENTIALS = GoogleCalendarOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",  # Far future to avoid refresh
    email="test@example.com",
)


def create_node(config) -> GoogleCalendarNode:
    """Create a GoogleCalendarNode instance with the given config."""
    node_config = GoogleCalendarNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    node = GoogleCalendarNode(
        node_id="test-node",
        node_type="automation-google-calendar",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


def mock_response(status_code: int, json_data: dict = None, text: str = ""):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text or ""
    response.json.return_value = json_data or {}
    return response


class TestCalendarTriggerRuntime:
    def test_schema_hides_legacy_active_trigger(self):
        schema = GoogleCalendarNode.get_config_schema()
        config_schema = schema["properties"]["config"]
        mapping = config_schema["discriminator"]["mapping"]

        assert "on_event_active" not in mapping
        assert "GoogleCalendarOnEventActiveConfig" not in schema["$defs"]
        assert all(
            option.get("$ref") != "#/$defs/GoogleCalendarOnEventActiveConfig"
            for option in config_schema["oneOf"]
        )

    def test_parse_config_still_supports_legacy_active_trigger(self):
        parsed = GoogleCalendarNode.parse_config(
            {
                "config": {
                    "operation": "on_event_active",
                    "calendar_id": "primary",
                },
                "credentials": {
                    "access_token": "tok",
                    "refresh_token": "refresh",
                    "expires_at": "2099-12-31T23:59:59Z",
                    "email": "test@example.com",
                },
            }
        )

        assert isinstance(parsed.config, GoogleCalendarOnEventActiveConfig)
        assert parsed.config.operation == "on_event_active"

    def test_zero_event_trigger_output_does_not_propagate(self):
        assert (
            GoogleCalendarNode.should_propagate_output(
                {"events": [], "event_count": 0},
                {"operation": "on_calendar_event"},
            )
            is False
        )
        assert (
            GoogleCalendarNode.should_propagate_output(
                {"events": [{"id": "evt-1"}], "event_count": 1},
                {"operation": "on_calendar_event"},
            )
            is True
        )

    # Channel-keyed wake-up dedup is covered by the pure-mock unit suite at
    # tests/test_google_trigger_dedup_unit.py (runs in backend-tests.yml; no
    # credentials/DB), so it isn't duplicated in this integration file.


# ============================================================================
# Event Operations Tests (8 operations)
# ============================================================================


class TestListEvents:
    """Test list_events operation."""

    @pytest.mark.asyncio
    async def test_list_events_success(self):
        """Test listing events returns events successfully."""
        config = GoogleCalendarListEventsConfig(calendar_id="primary", max_results=10)
        node = create_node(config)

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Meeting",
                    "description": "Team standup",
                    "location": "Conference Room A",
                    "start": {"dateTime": "2024-01-15T10:00:00Z"},
                    "end": {"dateTime": "2024-01-15T11:00:00Z"},
                    "status": "confirmed",
                    "htmlLink": "https://calendar.google.com/event?id=event1",
                    "creator": {"email": "creator@example.com"},
                    "organizer": {"email": "organizer@example.com"},
                    "attendees": [],
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_events)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_calendar_events"
            assert result["event_count"] == 1
            assert len(result["events"]) == 1
            assert result["events"][0]["id"] == "event1"
            assert result["events"][0]["summary"] == "Meeting"

    @pytest.mark.asyncio
    async def test_list_events_with_time_range(self):
        """Test listing events with time range filters."""
        config = GoogleCalendarListEventsConfig(
            calendar_id="primary",
            time_min="2024-01-01T00:00:00Z",
            time_max="2024-01-31T23:59:59Z",
            max_results=50,
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["event_count"] == 0

    @pytest.mark.asyncio
    async def test_list_events_with_search_query(self):
        """Test listing events with search query."""
        config = GoogleCalendarListEventsConfig(
            calendar_id="primary", search_query="meeting"
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert result["status"] == "success"


class TestGetEvent:
    """Test get_event operation."""

    @pytest.mark.asyncio
    async def test_get_event_success(self):
        """Test getting a single event."""
        config = GoogleCalendarGetEventConfig(
            calendar_id="primary", event_id="event123"
        )
        node = create_node(config)

        mock_event = {
            "id": "event123",
            "summary": "Team Meeting",
            "description": "Weekly sync",
            "location": "Room B",
            "start": {"dateTime": "2024-01-15T14:00:00Z"},
            "end": {"dateTime": "2024-01-15T15:00:00Z"},
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/event?id=event123",
            "creator": {"email": "creator@example.com"},
            "organizer": {"email": "organizer@example.com"},
            "attendees": [],
            "recurrence": None,
            "reminders": {"useDefault": True},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_calendar_event"
            assert result["event"]["id"] == "event123"
            assert result["event"]["summary"] == "Team Meeting"

    @pytest.mark.asyncio
    async def test_get_event_not_found(self):
        """Test getting a non-existent event."""
        config = GoogleCalendarGetEventConfig(
            calendar_id="primary", event_id="nonexistent"
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, {"error": {"message": "Event not found"}}
            )

            with pytest.raises(ValueError, match="Event not found"):
                await node.execute({})


class TestCreateEvent:
    """Test create_event operation."""

    @pytest.mark.asyncio
    async def test_create_event_success(self):
        """Test creating a new event."""
        config = GoogleCalendarCreateEventConfig(
            calendar_id="primary",
            summary="New Meeting",
            description="Important meeting",
            location="Conference Room",
            start_time="2024-01-20T10:00:00Z",
            end_time="2024-01-20T11:00:00Z",
            timezone="America/New_York",
            attendees="john@example.com, jane@example.com",
            send_notifications=True,
        )
        node = create_node(config)

        mock_created_event = {
            "id": "new_event_123",
            "summary": "New Meeting",
            "description": "Important meeting",
            "location": "Conference Room",
            "start": {"dateTime": "2024-01-20T10:00:00Z"},
            "end": {"dateTime": "2024-01-20T11:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?id=new_event_123",
            "status": "confirmed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(201, mock_created_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_calendar_event"
            assert result["event_id"] == "new_event_123"
            assert result["event"]["summary"] == "New Meeting"

    @pytest.mark.asyncio
    async def test_create_event_minimal(self):
        """Test creating an event with minimal required fields."""
        config = GoogleCalendarCreateEventConfig(
            calendar_id="primary",
            summary="Quick Meeting",
            start_time="2024-01-20T10:00:00Z",
            end_time="2024-01-20T10:30:00Z",
        )
        node = create_node(config)

        mock_created_event = {
            "id": "minimal_event",
            "summary": "Quick Meeting",
            "start": {"dateTime": "2024-01-20T10:00:00Z"},
            "end": {"dateTime": "2024-01-20T10:30:00Z"},
            "htmlLink": "https://calendar.google.com/event?id=minimal_event",
            "status": "confirmed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["event_id"] == "minimal_event"


class TestUpdateEvent:
    """Test update_event operation."""

    @pytest.mark.asyncio
    async def test_update_event_success(self):
        """Test updating an existing event."""
        config = GoogleCalendarUpdateEventConfig(
            calendar_id="primary",
            event_id="event_to_update",
            summary="Updated Meeting Title",
            description="Updated description",
            send_notifications=True,
        )
        node = create_node(config)

        existing_event = {
            "id": "event_to_update",
            "summary": "Old Title",
            "description": "Old description",
            "start": {"dateTime": "2024-01-15T10:00:00Z"},
            "end": {"dateTime": "2024-01-15T11:00:00Z"},
        }

        updated_event = {
            "id": "event_to_update",
            "summary": "Updated Meeting Title",
            "description": "Updated description",
            "start": {"dateTime": "2024-01-15T10:00:00Z"},
            "end": {"dateTime": "2024-01-15T11:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?id=event_to_update",
            "status": "confirmed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, existing_event)
            mock_instance.put.return_value = mock_response(200, updated_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_calendar_event"
            assert result["event"]["summary"] == "Updated Meeting Title"


class TestDeleteEvent:
    """Test delete_event operation."""

    @pytest.mark.asyncio
    async def test_delete_event_success(self):
        """Test deleting an event."""
        config = GoogleCalendarDeleteEventConfig(
            calendar_id="primary", event_id="event_to_delete", send_notifications=True
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            # Delete returns 204 No Content on success
            mock_response_obj = mock_response(204)
            mock_response_obj.text = ""
            mock_instance.delete.return_value = mock_response_obj

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_calendar_event"
            assert result["event_id"] == "event_to_delete"


class TestQuickAdd:
    """Test quick_add operation."""

    @pytest.mark.asyncio
    async def test_quick_add_success(self):
        """Test quick adding an event from natural language."""
        config = GoogleCalendarQuickAddConfig(
            calendar_id="primary",
            text="Meeting with John tomorrow at 3pm",
            send_notifications=True,
        )
        node = create_node(config)

        mock_event = {
            "id": "quick_added_event",
            "summary": "Meeting with John",
            "start": {"dateTime": "2024-01-16T15:00:00Z"},
            "end": {"dateTime": "2024-01-16T16:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?id=quick_added_event",
            "status": "confirmed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_event_from_text"
            assert result["input_text"] == "Meeting with John tomorrow at 3pm"
            assert result["event_id"] == "quick_added_event"


class TestGetInstances:
    """Test get_instances operation for recurring events."""

    @pytest.mark.asyncio
    async def test_get_instances_success(self):
        """Test getting instances of a recurring event."""
        config = GoogleCalendarGetInstancesConfig(
            calendar_id="primary",
            event_id="recurring_event_id",
            time_min="2024-01-01T00:00:00Z",
            time_max="2024-03-31T23:59:59Z",
            max_results=10,
        )
        node = create_node(config)

        mock_instances = {
            "items": [
                {
                    "id": "instance_1",
                    "recurringEventId": "recurring_event_id",
                    "summary": "Weekly Standup",
                    "start": {"dateTime": "2024-01-08T09:00:00Z"},
                    "end": {"dateTime": "2024-01-08T09:30:00Z"},
                    "status": "confirmed",
                    "htmlLink": "https://calendar.google.com/event?id=instance_1",
                },
                {
                    "id": "instance_2",
                    "recurringEventId": "recurring_event_id",
                    "summary": "Weekly Standup",
                    "start": {"dateTime": "2024-01-15T09:00:00Z"},
                    "end": {"dateTime": "2024-01-15T09:30:00Z"},
                    "status": "confirmed",
                    "htmlLink": "https://calendar.google.com/event?id=instance_2",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_instances)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_recurring_event_instances"
            assert result["instance_count"] == 2
            assert len(result["instances"]) == 2


class TestMoveEvent:
    """Test move_event operation."""

    @pytest.mark.asyncio
    async def test_move_event_success(self):
        """Test moving an event to another calendar."""
        config = GoogleCalendarMoveEventConfig(
            calendar_id="primary",
            event_id="event_to_move",
            destination_calendar_id="work_calendar_id",
            send_notifications=True,
        )
        node = create_node(config)

        mock_moved_event = {
            "id": "event_to_move",
            "summary": "Moved Meeting",
            "start": {"dateTime": "2024-01-15T10:00:00Z"},
            "end": {"dateTime": "2024-01-15T11:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?id=event_to_move",
            "status": "confirmed",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_moved_event)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "move_event_to_calendar"
            assert result["source_calendar_id"] == "primary"
            assert result["destination_calendar_id"] == "work_calendar_id"


# ============================================================================
# Calendar Operations Tests (4 operations)
# ============================================================================


class TestListCalendars:
    """Test list_calendars operation."""

    @pytest.mark.asyncio
    async def test_list_calendars_success(self):
        """Test listing all calendars."""
        config = GoogleCalendarListCalendarsConfig(
            show_hidden=False, show_deleted=False
        )
        node = create_node(config)

        mock_calendars = {
            "items": [
                {
                    "id": "primary",
                    "summary": "My Calendar",
                    "description": "Main calendar",
                    "timeZone": "America/New_York",
                    "primary": True,
                    "accessRole": "owner",
                    "backgroundColor": "#4285f4",
                    "foregroundColor": "#ffffff",
                },
                {
                    "id": "work_calendar",
                    "summary": "Work",
                    "description": "Work events",
                    "timeZone": "America/New_York",
                    "primary": False,
                    "accessRole": "owner",
                    "backgroundColor": "#16a765",
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_calendars)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_user_calendars"
            assert result["calendar_count"] == 2
            assert len(result["calendars"]) == 2

    @pytest.mark.asyncio
    async def test_list_calendars_with_hidden(self):
        """Test listing calendars including hidden ones."""
        config = GoogleCalendarListCalendarsConfig(show_hidden=True, show_deleted=False)
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert result["status"] == "success"


class TestGetCalendar:
    """Test get_calendar operation."""

    @pytest.mark.asyncio
    async def test_get_calendar_success(self):
        """Test getting calendar metadata."""
        config = GoogleCalendarGetCalendarConfig(calendar_id="primary")
        node = create_node(config)

        mock_calendar = {
            "id": "primary",
            "summary": "My Calendar",
            "description": "Main calendar",
            "location": "New York",
            "timeZone": "America/New_York",
            "conferenceProperties": {
                "allowedConferenceSolutionTypes": ["hangoutsMeet"]
            },
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_calendar)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_calendar_metadata"
            assert result["calendar"]["id"] == "primary"
            assert result["calendar"]["summary"] == "My Calendar"


class TestCreateCalendar:
    """Test create_calendar operation."""

    @pytest.mark.asyncio
    async def test_create_calendar_success(self):
        """Test creating a new calendar."""
        config = GoogleCalendarCreateCalendarConfig(
            summary="Project Calendar",
            description="Calendar for project events",
            timezone="America/Los_Angeles",
            location="San Francisco",
        )
        node = create_node(config)

        mock_created_calendar = {
            "id": "new_calendar_123",
            "summary": "Project Calendar",
            "description": "Calendar for project events",
            "location": "San Francisco",
            "timeZone": "America/Los_Angeles",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created_calendar)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_calendar"
            assert result["calendar_id"] == "new_calendar_123"
            assert result["calendar"]["summary"] == "Project Calendar"

    @pytest.mark.asyncio
    async def test_create_calendar_minimal(self):
        """Test creating a calendar with minimal fields."""
        config = GoogleCalendarCreateCalendarConfig(summary="Simple Calendar")
        node = create_node(config)

        mock_created_calendar = {
            "id": "simple_cal",
            "summary": "Simple Calendar",
            "timeZone": "UTC",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(201, mock_created_calendar)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["calendar"]["summary"] == "Simple Calendar"


class TestClearCalendar:
    """Test clear_calendar operation."""

    @pytest.mark.asyncio
    async def test_clear_calendar_success(self):
        """Test clearing all events from a calendar."""
        config = GoogleCalendarClearCalendarConfig(calendar_id="test_calendar")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_response_obj = mock_response(204)
            mock_response_obj.text = ""
            mock_instance.post.return_value = mock_response_obj

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "clear_calendar_events"
            assert result["calendar_id"] == "test_calendar"


# ============================================================================
# Utility Operations Tests (1 operation)
# ============================================================================


class TestQueryFreebusy:
    """Test query_freebusy operation."""

    @pytest.mark.asyncio
    async def test_query_freebusy_success(self):
        """Test querying free/busy information."""
        config = GoogleCalendarQueryFreebusyConfig(
            calendar_ids="primary, colleague@example.com",
            time_min="2024-01-15T09:00:00Z",
            time_max="2024-01-15T18:00:00Z",
        )
        node = create_node(config)

        mock_freebusy = {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2024-01-15T10:00:00Z",
                            "end": "2024-01-15T11:00:00Z",
                        },
                        {
                            "start": "2024-01-15T14:00:00Z",
                            "end": "2024-01-15T15:00:00Z",
                        },
                    ],
                    "errors": [],
                },
                "colleague@example.com": {
                    "busy": [
                        {"start": "2024-01-15T11:00:00Z", "end": "2024-01-15T12:00:00Z"}
                    ],
                    "errors": [],
                },
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_freebusy)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "query_calendar_availability"
            assert "primary" in result["calendars"]
            assert "colleague@example.com" in result["calendars"]
            assert len(result["calendars"]["primary"]["busy"]) == 2


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_response(self):
        """Test handling of API error responses."""
        config = GoogleCalendarGetEventConfig(
            calendar_id="primary", event_id="nonexistent"
        )
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                404, {"error": {"message": "Not Found"}}
            )

            with pytest.raises(ValueError, match="Not Found"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = GoogleCalendarListEventsConfig(calendar_id="primary")
        node_config = GoogleCalendarNodeConfig(config=config, credentials=None)
        node = GoogleCalendarNode(
            node_id="test-node",
            node_type="automation-google-calendar",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test handling of rate limit errors."""
        config = GoogleCalendarListEventsConfig(calendar_id="primary")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(
                429, {"error": {"message": "Rate Limit Exceeded"}}
            )

            with pytest.raises(ValueError, match="Rate Limit Exceeded"):
                await node.execute({})


# ============================================================================
# Dynamic Field Options Tests
# ============================================================================


class TestDynamicFieldOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_calendar_options(self):
        """Test loading calendar options for dropdowns."""
        mock_calendars = {
            "items": [
                {
                    "id": "primary",
                    "summary": "My Calendar",
                    "primary": True,
                    "accessRole": "owner",
                    "backgroundColor": "#4285f4",
                },
                {
                    "id": "work@example.com",
                    "summary": "Work Calendar",
                    "primary": False,
                    "accessRole": "writer",
                },
            ]
        }

        credential_data = {
            "access_token": "mock_token",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_calendars)

            options = await GoogleCalendarNode.load_field_options(
                "calendar_id", credential_data
            )

            assert len(options) == 2
            # Primary calendar should be first
            assert options[0]["metadata"]["primary"] == True
            assert "Primary" in options[0]["label"]

    @pytest.mark.asyncio
    async def test_load_destination_calendar_options(self):
        """Test loading destination calendar options (same as calendar_id)."""
        credential_data = {
            "access_token": "mock_token",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            options = await GoogleCalendarNode.load_field_options(
                "destination_calendar_id", credential_data
            )

            assert options == []


# ============================================================================
# Token Refresh Tests
# ============================================================================


class TestTokenRefresh:
    """Test OAuth token refresh functionality."""

    @pytest.mark.asyncio
    async def test_uses_valid_token(self):
        """Test that a valid token is used without refresh."""
        config = GoogleCalendarListEventsConfig(calendar_id="primary")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert result["status"] == "success"
            # Token should be used as-is since it's not expired


# ============================================================================
# Response Structure Tests
# ============================================================================


class TestResponseStructure:
    """Test that response structure is consistent."""

    @pytest.mark.asyncio
    async def test_response_has_required_fields(self):
        """Test that all responses have required fields."""
        config = GoogleCalendarListEventsConfig(calendar_id="primary")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"items": []})

            result = await node.execute({})

            assert "type" in result
            assert result["type"] == "google_calendar"
            assert "operation" in result
            assert "timestamp" in result
            assert "status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

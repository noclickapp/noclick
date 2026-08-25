"""
Mock tests for the Cal.com REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Bookings: list, get, create, cancel, reschedule
- Event Types: list, get
- Availability: get slots
- Schedules: list
- Profile: get me
- Trigger: on_booking_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: event-type dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.cal_com_node import (
    CalComNode,
    CalComNodeConfig,
    CalComApiKeyCredential,
    CalComOAuthCredential,
    _credential_bearer_token,
    CalComListBookingsConfig,
    CalComGetBookingConfig,
    CalComCreateBookingConfig,
    CalComCancelBookingConfig,
    CalComRescheduleBookingConfig,
    CalComListEventTypesConfig,
    CalComGetEventTypeConfig,
    CalComGetSlotsConfig,
    CalComListSchedulesConfig,
    CalComGetMeConfig,
    CalComBookingTriggerConfig,
    CalComConfirmBookingConfig,
    CalComDeclineBookingConfig,
    CalComMarkNoShowConfig,
    CalComGetRecordingsConfig,
    CalComCreateEventTypeConfig,
    CalComUpdateEventTypeConfig,
    CalComDeleteEventTypeConfig,
    CalComGetScheduleConfig,
    CalComCreateScheduleConfig,
    CalComUpdateScheduleConfig,
    CalComDeleteScheduleConfig,
    CalComListOOOConfig,
    CalComCreateOOOConfig,
    CalComDeleteOOOConfig,
    CalComUpdateMeConfig,
    CalComListWebhooksConfig,
    CalComReserveSlotConfig,
    _parse_json_field,
    CALCOM_TRIGGER_EVENTS,
)


@pytest.fixture
def api_key_credentials():
    return CalComApiKeyCredential(api_key="cal_test_key_12345")


def create_cal_com_node(config):
    return CalComNode(
        node_id="test-cal-com-node",
        node_type="automation-cal-com",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def _envelope(data):
    """Cal.com v2 wraps results in {status, data}."""
    return {"status": "success", "data": data}


class TestCalComBookingsMock:
    @pytest.mark.asyncio
    async def test_list_bookings(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComListBookingsConfig(status="upcoming", take="10"),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope([{"uid": "bk_1"}, {"uid": "bk_2"}]))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_bookings"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_booking(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComGetBookingConfig(booking_uid="bk_123"),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"uid": "bk_123", "title": "Intro call"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_booking"
        assert result["data"]["uid"] == "bk_123"

    @pytest.mark.asyncio
    async def test_create_booking(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComCreateBookingConfig(
                event_type_id="42",
                start="2026-07-01T10:00:00Z",
                attendee_name="Ada",
                attendee_email="ada@example.com",
                attendee_timezone="UTC",
            ),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(201, _envelope({"uid": "bk_new", "status": "accepted"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_booking"
        assert result["data"]["uid"] == "bk_new"

    @pytest.mark.asyncio
    async def test_cancel_booking(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComCancelBookingConfig(booking_uid="bk_123", cancellation_reason="No longer needed"),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"uid": "bk_123", "status": "cancelled"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "cancel_booking"

    @pytest.mark.asyncio
    async def test_reschedule_booking(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComRescheduleBookingConfig(booking_uid="bk_123", start="2026-07-02T10:00:00Z"),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"uid": "bk_new2"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reschedule_booking"


class TestCalComEventTypesMock:
    @pytest.mark.asyncio
    async def test_list_event_types(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComListEventTypesConfig(), credentials=api_key_credentials
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": 1, "title": "30 min"}]))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_event_types"

    @pytest.mark.asyncio
    async def test_get_event_type(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComGetEventTypeConfig(event_type_id="42"), credentials=api_key_credentials
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"id": 42, "title": "Demo"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_event_type"
        assert result["data"]["id"] == 42


class TestCalComAvailabilityMock:
    @pytest.mark.asyncio
    async def test_get_slots(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComGetSlotsConfig(
                event_type_id="42", start="2026-07-01T00:00:00Z", end="2026-07-02T00:00:00Z"
            ),
            credentials=api_key_credentials,
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"2026-07-01": [{"start": "10:00"}]}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_slots"


class TestCalComSchedulesMock:
    @pytest.mark.asyncio
    async def test_list_schedules(self, api_key_credentials):
        config = CalComNodeConfig(config=CalComListSchedulesConfig(), credentials=api_key_credentials)
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": 7, "name": "Working hours"}]))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_schedules"


class TestCalComProfileMock:
    @pytest.mark.asyncio
    async def test_get_me(self, api_key_credentials):
        config = CalComNodeConfig(config=CalComGetMeConfig(), credentials=api_key_credentials)
        node = create_cal_com_node(config)
        mock_client = create_mock_client(200, _envelope({"username": "ada", "email": "ada@example.com"}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["username"] == "ada"


class TestCalComTriggerMock:
    @pytest.mark.asyncio
    async def test_on_booking_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = CalComNodeConfig(
            config=CalComBookingTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_cal_com_node(config)
        payload = {"triggerEvent": "BOOKING_CREATED", "payload": {"uid": "bk_x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_booking_event"
        assert result["data"]["triggerEvent"] == "BOOKING_CREATED"
        # default trigger (no event_types) reports all events as subscribed
        assert set(result["data"]["subscribed_events"]) == set(CALCOM_TRIGGER_EVENTS)

    @pytest.mark.asyncio
    async def test_on_booking_event_reports_selected_events(self):
        """The trigger output reflects the user's event_types selection."""
        config = CalComNodeConfig(
            config=CalComBookingTriggerConfig(
                webhook_url="https://abc.hooks.example.test",
                event_types="BOOKING_CREATED,BOOKING_CANCELLED",
            ),
            credentials=None,
        )
        node = create_cal_com_node(config)
        result = await node.execute({"triggerEvent": "BOOKING_CANCELLED"})
        assert result["data"]["subscribed_events"] == ["BOOKING_CREATED", "BOOKING_CANCELLED"]

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.cal_com_node._calcom_request",
            return_value={"status": "success", "data": {"id": 99}},
        ) as mock_req:
            extra = await CalComNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "cal_test"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "99"
        assert extra["signing_secret"]
        # Default (no event_types selected) subscribes to all known events.
        triggers = mock_req.call_args.kwargs["json_body"]["triggers"]
        assert set(triggers) == set(CALCOM_TRIGGER_EVENTS)

    @pytest.mark.asyncio
    async def test_register_subscribes_to_selected_events(self):
        """Selecting specific event_types subscribes the webhook to exactly those."""
        with patch(
            "nodes.cal_com_node._calcom_request",
            return_value={"status": "success", "data": {"id": 99}},
        ) as mock_req:
            await CalComNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "cal_test"},
                config={"event_types": "BOOKING_CANCELLED,MEETING_ENDED"},
                node_id="node-1",
            )
        triggers = mock_req.call_args.kwargs["json_body"]["triggers"]
        assert triggers == ["BOOKING_CANCELLED", "MEETING_ENDED"]

    @pytest.mark.asyncio
    async def test_register_single_event_selection(self):
        """A single selected event subscribes to just that event."""
        with patch(
            "nodes.cal_com_node._calcom_request",
            return_value={"status": "success", "data": {"id": 7}},
        ) as mock_req:
            await CalComNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "cal_test"},
                config={"event_types": "BOOKING_CREATED"},
                node_id="node-1",
            )
        triggers = mock_req.call_args.kwargs["json_body"]["triggers"]
        assert triggers == ["BOOKING_CREATED"]

    @pytest.mark.asyncio
    async def test_register_all_events_sentinel(self):
        """The '*' sentinel subscribes to every supported event."""
        with patch(
            "nodes.cal_com_node._calcom_request",
            return_value={"status": "success", "data": {"id": 8}},
        ) as mock_req:
            await CalComNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "cal_test"},
                config={"event_types": "*"},
                node_id="node-1",
            )
        triggers = mock_req.call_args.kwargs["json_body"]["triggers"]
        assert set(triggers) == set(CALCOM_TRIGGER_EVENTS)

    def test_filter_trigger_payload_passes_selected_event(self):
        """A selected event runs the workflow."""
        config = {"operation": "on_booking_event", "event_types": "BOOKING_CANCELLED,MEETING_ENDED"}
        assert CalComNode.filter_trigger_payload({"triggerEvent": "BOOKING_CANCELLED"}, config) is True
        assert CalComNode.filter_trigger_payload({"triggerEvent": "MEETING_ENDED"}, config) is True

    def test_filter_trigger_payload_skips_unselected_event(self):
        """A non-selected event is skipped (returns False)."""
        config = {"operation": "on_booking_event", "event_types": "BOOKING_CANCELLED"}
        assert CalComNode.filter_trigger_payload({"triggerEvent": "BOOKING_CREATED"}, config) is False

    def test_filter_trigger_payload_all_events_passes_everything(self):
        """'*' (all events) and unset event_types both pass every delivery."""
        for cfg in (
            {"operation": "on_booking_event", "event_types": "*"},
            {"operation": "on_booking_event"},
        ):
            assert CalComNode.filter_trigger_payload({"triggerEvent": "RECORDING_READY"}, cfg) is True
            assert CalComNode.filter_trigger_payload({"triggerEvent": "OOO_CREATED"}, cfg) is True

    def test_filter_trigger_payload_untagged_payload_passes(self):
        """A delivery with no triggerEvent (manual/test POST) is not dropped."""
        config = {"operation": "on_booking_event", "event_types": "BOOKING_CREATED"}
        assert CalComNode.filter_trigger_payload({"payload": {"uid": "x"}}, config) is True

    def test_filter_trigger_payload_non_trigger_op_passes(self):
        """Non-trigger operations are never filtered."""
        assert CalComNode.filter_trigger_payload({"triggerEvent": "BOOKING_CREATED"}, {"operation": "list_bookings"}) is True

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.cal_com_node._calcom_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await CalComNode._unregister_external_webhook(
                credential={"api_key": "cal_test"},
                config={"external_webhook_id": "99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"triggerEvent":"BOOKING_CREATED"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert CalComNode.verify_webhook_signature(
            body, {"x-cal-signature-256": good_sig}, {"signing_secret": secret}
        )
        assert not CalComNode.verify_webhook_signature(
            body, {"x-cal-signature-256": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert CalComNode.verify_webhook_signature(body, {}, {})


class TestCalComErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = CalComNodeConfig(
            config=CalComGetBookingConfig(booking_uid="missing"), credentials=api_key_credentials
        )
        node = create_cal_com_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Booking not found"}})
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = CalComNodeConfig(config=CalComGetMeConfig(), credentials=None)
        node = create_cal_com_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestCalComDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_event_type_options(self):
        """Dropdown loader uses the canonical signature: it receives an
        already-freshened credential dict as ``credential_data``."""
        async def fake_request(*args, **kwargs):
            return {"status": "success", "data": [{"id": 1, "title": "30 min", "lengthInMinutes": 30}]}

        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            result = await CalComNode.load_field_options(
                "event_type_id", {"api_key": "cal_test"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "1"
        assert "30 min" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_event_type_options_oauth_and_groups(self):
        """OAuth credential + grouped event-type response are both handled."""
        async def fake_request(api_key, *args, **kwargs):
            assert api_key == "oauth_tok"  # bearer resolved from access_token
            return {
                "status": "success",
                "data": {"eventTypeGroups": [{"eventTypes": [{"id": 7, "title": "Demo", "length": 15}]}]},
            }

        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            result = await CalComNode.load_field_options(
                "event_type_id", {"access_token": "oauth_tok", "credential_type": "cal_com_oauth"}, context={}
            )
        assert result["options"][0]["value"] == "7"
        assert "Demo" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_options_no_credential(self):
        result = await CalComNode.load_field_options("event_type_id", {}, context={})
        assert result == {"options": []}


class TestCalComJsonHelper:
    def test_parse_json_field(self):
        assert _parse_json_field(None, "X") is None
        assert _parse_json_field("", "X") is None
        assert _parse_json_field("  ", "X") is None
        assert _parse_json_field('[{"a":1}]', "X") == [{"a": 1}]
        assert _parse_json_field('{"k":"v"}', "X") == {"k": "v"}
        with pytest.raises(ValueError, match="must be valid JSON"):
            _parse_json_field("{not json", "Availability")


class TestCalComNewOperationsMock:
    """Smoke + body-shape coverage for the expanded single-user operations."""

    async def _run(self, config, json_data=None, status_code=200):
        node = create_cal_com_node(CalComNodeConfig(config=config, credentials=CalComApiKeyCredential(api_key="k")))
        mock_client = create_mock_client(status_code, _envelope(json_data if json_data is not None else {}))
        with patch("nodes.cal_com_node.httpx.AsyncClient", return_value=mock_client):
            return await node.execute({})

    @pytest.mark.asyncio
    async def test_booking_actions(self):
        assert (await self._run(CalComConfirmBookingConfig(booking_uid="b1")))["action"] == "confirm_booking"
        assert (await self._run(CalComDeclineBookingConfig(booking_uid="b1", reason="busy")))["action"] == "decline_booking"
        assert (await self._run(CalComMarkNoShowConfig(booking_uid="b1", host_absent="true")))["action"] == "mark_no_show"
        assert (await self._run(CalComGetRecordingsConfig(booking_uid="b1")))["action"] == "get_recordings"

    @pytest.mark.asyncio
    async def test_event_type_writes(self):
        assert (await self._run(CalComCreateEventTypeConfig(title="T", slug="s", length_minutes="30"), status_code=201))["status"] == "success"
        assert (await self._run(CalComUpdateEventTypeConfig(event_type_id="7", title="New")))["status"] == "success"
        assert (await self._run(CalComDeleteEventTypeConfig(event_type_id="7")))["status"] == "success"

    @pytest.mark.asyncio
    async def test_schedule_ops(self):
        avail = '[{"days":["Monday"],"startTime":"09:00","endTime":"17:00"}]'
        assert (await self._run(CalComGetScheduleConfig(schedule_id="1")))["action"] == "get_schedule"
        assert (await self._run(CalComCreateScheduleConfig(name="S", timezone="UTC", is_default="false", availability_json=avail), status_code=201))["status"] == "success"
        assert (await self._run(CalComUpdateScheduleConfig(schedule_id="1", name="S2")))["status"] == "success"
        assert (await self._run(CalComDeleteScheduleConfig(schedule_id="1")))["status"] == "success"

    @pytest.mark.asyncio
    async def test_ooo_ops(self):
        assert (await self._run(CalComListOOOConfig()))["action"] == "list_ooo"
        assert (await self._run(CalComCreateOOOConfig(start="2026-09-01T00:00:00Z", end="2026-09-03T00:00:00Z", reason="vacation"), status_code=201))["status"] == "success"
        assert (await self._run(CalComDeleteOOOConfig(ooo_id="5")))["status"] == "success"

    @pytest.mark.asyncio
    async def test_profile_webhooks_slots(self):
        assert (await self._run(CalComUpdateMeConfig(bio="hi")))["action"] == "update_me"
        assert (await self._run(CalComListWebhooksConfig()))["action"] == "list_webhooks"
        assert (await self._run(CalComReserveSlotConfig(event_type_id="42", slot_start="2026-08-03T10:00:00Z"), status_code=201))["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_schedule_body_shape(self):
        """Availability JSON must be parsed into a list and isDefault coerced to bool."""
        captured = {}

        async def fake_request(api_key, method, endpoint, version, json_body=None, **kwargs):
            captured.update(method=method, endpoint=endpoint, body=json_body)
            return {"status": "success", "action": "create_schedule", "data": {}}

        node = create_cal_com_node(CalComNodeConfig(
            config=CalComCreateScheduleConfig(name="S", timezone="UTC", is_default="true",
                                              availability_json='[{"days":["Monday"],"startTime":"09:00","endTime":"17:00"}]'),
            credentials=CalComApiKeyCredential(api_key="k")))
        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            await node.execute({})
        assert captured["method"] == "POST" and captured["endpoint"] == "/schedules"
        assert captured["body"]["isDefault"] is True
        assert captured["body"]["availability"] == [{"days": ["Monday"], "startTime": "09:00", "endTime": "17:00"}]

    @pytest.mark.asyncio
    async def test_mark_no_show_body(self):
        captured = {}

        async def fake_request(api_key, method, endpoint, version, json_body=None, **kwargs):
            captured["body"] = json_body
            return {"status": "success", "action": "mark_no_show", "data": {}}

        node = create_cal_com_node(CalComNodeConfig(
            config=CalComMarkNoShowConfig(booking_uid="b1", host_absent="true",
                                          attendees_json='[{"email":"a@x.com","absent":true}]'),
            credentials=CalComApiKeyCredential(api_key="k")))
        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            await node.execute({})
        assert captured["body"]["host"] is True
        assert captured["body"]["attendees"] == [{"email": "a@x.com", "absent": True}]

    @pytest.mark.asyncio
    async def test_create_event_type_advanced_json_merge(self):
        captured = {}

        async def fake_request(api_key, method, endpoint, version, json_body=None, **kwargs):
            captured["body"] = json_body
            return {"status": "success", "action": "create_event_type", "data": {}}

        node = create_cal_com_node(CalComNodeConfig(
            config=CalComCreateEventTypeConfig(title="T", slug="s", length_minutes="30",
                                               advanced_json='{"hidden":true}'),
            credentials=CalComApiKeyCredential(api_key="k")))
        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            await node.execute({})
        assert captured["body"]["lengthInMinutes"] == 30
        assert captured["body"]["hidden"] is True


class TestCalComOAuth:
    @pytest.fixture
    def oauth_credentials(self):
        return CalComOAuthCredential(
            access_token="cal_oauth_access_123",
            refresh_token="cal_oauth_refresh_456",
            expires_at="2099-01-01T00:00:00+00:00",  # far future → not expired
            email="user@example.com",
        )

    def test_bearer_token_resolution(self, oauth_credentials, api_key_credentials):
        assert _credential_bearer_token(oauth_credentials) == "cal_oauth_access_123"
        assert _credential_bearer_token(api_key_credentials) == "cal_test_key_12345"
        assert _credential_bearer_token({"access_token": "a"}) == "a"
        assert _credential_bearer_token({"api_key": "k"}) == "k"
        assert _credential_bearer_token(None) is None

    @pytest.mark.asyncio
    async def test_execute_uses_oauth_access_token(self, oauth_credentials):
        """A read op with an OAuth credential must send the access token as Bearer."""
        config = CalComNodeConfig(
            config=CalComListBookingsConfig(take="5"), credentials=oauth_credentials
        )
        node = create_cal_com_node(config)
        captured = {}

        async def fake_request(api_key, *args, **kwargs):
            captured["api_key"] = api_key
            return {"status": "success", "action": "list_bookings", "data": []}

        with patch("nodes.cal_com_node._calcom_request", side_effect=fake_request):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured["api_key"] == "cal_oauth_access_123"

    @pytest.mark.asyncio
    async def test_freshen_credential_apikey_is_noop(self):
        """API-key credentials have no refresh token → freshen is a pure no-op."""
        cred = {"api_key": "cal_test", "credential_type": "cal_com_api_key"}
        result = await CalComNode.freshen_credential(cred)
        assert result == cred

    @pytest.mark.asyncio
    async def test_oauth_exchange_and_userinfo(self):
        from nodes.oauth import calcom_oauth

        post_resp = Mock()
        post_resp.status_code = 200
        post_resp.json = lambda: {
            "access_token": "at_new", "refresh_token": "rt_new",
            "expires_in": 1800, "scope": "BOOKING_READ", "token_type": "bearer",
        }
        get_resp = Mock()
        get_resp.status_code = 200
        get_resp.json = lambda: {"data": {"id": 42, "username": "neo", "email": "neo@x.com", "name": "Neo"}}

        client = Mock()
        async def post(*a, **k): return post_resp
        async def get(*a, **k): return get_resp
        client.post = post
        client.get = get
        async def aenter(self): return client
        async def aexit(self, *a): return None
        client.__aenter__ = aenter
        client.__aexit__ = aexit

        with patch.dict("os.environ", {"CALCOM_CLIENT_ID": "cid", "CALCOM_CLIENT_SECRET": "sec"}), \
             patch("nodes.oauth.calcom_oauth.httpx.AsyncClient", return_value=client):
            tokens, user = await calcom_oauth.exchange_code_for_tokens("code", "https://cb")
        assert tokens.access_token == "at_new"
        assert tokens.refresh_token == "rt_new"
        assert tokens.expires_at is not None
        assert user.username == "neo"
        assert user.email == "neo@x.com"

    @pytest.mark.asyncio
    async def test_oauth_refresh(self):
        from nodes.oauth import calcom_oauth

        resp = Mock()
        resp.status_code = 200
        resp.json = lambda: {"access_token": "at2", "refresh_token": "rt2", "expires_in": 1800}
        client = Mock()
        async def post(*a, **k): return resp
        client.post = post
        async def aenter(self): return client
        async def aexit(self, *a): return None
        client.__aenter__ = aenter
        client.__aexit__ = aexit

        with patch.dict("os.environ", {"CALCOM_CLIENT_ID": "cid", "CALCOM_CLIENT_SECRET": "sec"}), \
             patch("nodes.oauth.calcom_oauth.httpx.AsyncClient", return_value=client):
            tokens = await calcom_oauth.refresh_access_token("rt1")
        assert tokens.access_token == "at2"
        assert tokens.refresh_token == "rt2"

    def test_auth_url(self):
        from nodes.oauth import calcom_oauth
        with patch.dict("os.environ", {"CALCOM_CLIENT_ID": "my_cid", "CALCOM_CLIENT_SECRET": "sec"}):
            url = calcom_oauth.get_calcom_auth_url(
                ["BOOKING_READ", "BOOKING_WRITE"], state="st8", redirect_uri="https://cb"
            )
        assert url.startswith("https://app.cal.com/auth/oauth2/authorize?")
        assert "client_id=my_cid" in url
        assert "response_type=code" in url
        assert "state=st8" in url
        # space-separated scopes are URL-encoded as +
        assert "BOOKING_READ" in url and "BOOKING_WRITE" in url

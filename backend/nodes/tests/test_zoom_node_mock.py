"""
Mock tests for the Zoom REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Meetings: list, create, get, update, delete, past details, participants,
  registrants (add/list), invitation
- Webinars: list, create, get, update, delete, registrants (add/list)
- Users: list, create, get, update, delete
- Recordings: user list, meeting get/delete, account list
- Phone: list call logs
- Team Chat: send message
- Auth: Server-to-Server token mint + full S2S execution path
- Triggers: one per Zoom event; passthrough + per-event filter routing,
  signature verification, URL-validation handshake
- Error handling: API errors, missing credentials
"""

import hashlib
import hmac
import json

import pytest
from unittest.mock import Mock, patch

from nodes.zoom_node import (
    ZoomNode,
    ZoomNodeConfig,
    ZoomServerToServerCredential,
    ZoomOAuthCredential,
    ZoomListMeetingsConfig,
    ZoomCreateMeetingConfig,
    ZoomGetMeetingConfig,
    ZoomUpdateMeetingConfig,
    ZoomDeleteMeetingConfig,
    ZoomGetPastMeetingConfig,
    ZoomListPastParticipantsConfig,
    ZoomAddMeetingRegistrantConfig,
    ZoomListMeetingRegistrantsConfig,
    ZoomGetMeetingInvitationConfig,
    ZoomListWebinarsConfig,
    ZoomCreateWebinarConfig,
    ZoomGetWebinarConfig,
    ZoomUpdateWebinarConfig,
    ZoomDeleteWebinarConfig,
    ZoomAddWebinarRegistrantConfig,
    ZoomListWebinarRegistrantsConfig,
    ZoomListUsersConfig,
    ZoomCreateUserConfig,
    ZoomGetUserConfig,
    ZoomUpdateUserConfig,
    ZoomDeleteUserConfig,
    ZoomListUserRecordingsConfig,
    ZoomGetMeetingRecordingsConfig,
    ZoomDeleteMeetingRecordingsConfig,
    ZoomListAccountRecordingsConfig,
    ZoomListCallLogsConfig,
    ZoomSendChatMessageConfig,
    ZOOM_TRIGGER_CONFIGS,
    ZOOM_TRIGGER_EVENT,
)


@pytest.fixture
def oauth_credentials():
    """User-delegated OAuth credential — carries an access token directly."""
    return ZoomOAuthCredential(access_token="zoom_test_access_token")


@pytest.fixture
def s2s_credentials():
    return ZoomServerToServerCredential(
        account_id="acc_123", client_id="cid_123", client_secret="secret_123"
    )


def create_zoom_node(config):
    return ZoomNode(
        node_id="test-zoom-node",
        node_type="automation-zoom",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, content=b"{}"):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = content
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, content=b"{}"):
    """Mock httpx.AsyncClient whose .request() / .post() return the mock response
    and which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, content)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request
    mock_client.post = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def patch_zoom_client(mock_client):
    return patch("nodes.zoom_node.httpx.AsyncClient", return_value=mock_client)


# ============================================================================
# Meetings
# ============================================================================


class TestZoomMeetingsMock:
    @pytest.mark.asyncio
    async def test_list_meetings(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListMeetingsConfig(user_id="me", type="scheduled"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"meetings": [{"id": 1}, {"id": 2}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings"
        assert len(result["data"]["meetings"]) == 2

    @pytest.mark.asyncio
    async def test_create_meeting(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomCreateMeetingConfig(
                user_id="me", topic="Standup", type="2", start_time="2026-07-01T10:00:00Z", duration="30"
            ),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(201, {"id": 999, "topic": "Standup"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_meeting"
        assert result["data"]["id"] == 999

    @pytest.mark.asyncio
    async def test_get_meeting(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetMeetingConfig(meeting_id="123"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"id": 123, "topic": "Demo"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_meeting"
        assert result["data"]["id"] == 123

    @pytest.mark.asyncio
    async def test_update_meeting(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomUpdateMeetingConfig(meeting_id="123", topic="Renamed"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_meeting"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_delete_meeting(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomDeleteMeetingConfig(meeting_id="123"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_meeting"

    @pytest.mark.asyncio
    async def test_get_past_meeting(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetPastMeetingConfig(meeting_id="abc=="), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"uuid": "abc==", "participants_count": 5})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_past_meeting"
        assert result["data"]["participants_count"] == 5

    @pytest.mark.asyncio
    async def test_list_past_participants(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListPastParticipantsConfig(meeting_id="abc=="),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"participants": [{"name": "Ada"}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_past_participants"

    @pytest.mark.asyncio
    async def test_add_meeting_registrant(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomAddMeetingRegistrantConfig(
                meeting_id="123", email="a@b.com", first_name="Ada"
            ),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(201, {"registrant_id": "reg_1", "join_url": "https://z"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_meeting_registrant"
        assert result["data"]["registrant_id"] == "reg_1"

    @pytest.mark.asyncio
    async def test_list_meeting_registrants(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListMeetingRegistrantsConfig(meeting_id="123", status="approved"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"registrants": [{"id": "r1"}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meeting_registrants"

    @pytest.mark.asyncio
    async def test_get_meeting_invitation(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetMeetingInvitationConfig(meeting_id="123"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"invitation": "Join Zoom Meeting..."})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_meeting_invitation"
        assert "invitation" in result["data"]


# ============================================================================
# Webinars
# ============================================================================


class TestZoomWebinarsMock:
    @pytest.mark.asyncio
    async def test_list_webinars(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListWebinarsConfig(user_id="me"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"webinars": [{"id": 11}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webinars"

    @pytest.mark.asyncio
    async def test_create_webinar(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomCreateWebinarConfig(user_id="me", topic="Launch", duration="60"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(201, {"id": 555, "topic": "Launch"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webinar"
        assert result["data"]["id"] == 555

    @pytest.mark.asyncio
    async def test_get_webinar(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetWebinarConfig(webinar_id="555"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"id": 555})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_webinar"

    @pytest.mark.asyncio
    async def test_update_webinar(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomUpdateWebinarConfig(webinar_id="555", topic="Updated"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_webinar"

    @pytest.mark.asyncio
    async def test_delete_webinar(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomDeleteWebinarConfig(webinar_id="555"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webinar"

    @pytest.mark.asyncio
    async def test_add_webinar_registrant(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomAddWebinarRegistrantConfig(
                webinar_id="555", email="a@b.com", first_name="Ada"
            ),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(201, {"registrant_id": "wreg_1"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_webinar_registrant"

    @pytest.mark.asyncio
    async def test_list_webinar_registrants(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListWebinarRegistrantsConfig(webinar_id="555"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"registrants": []})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webinar_registrants"


# ============================================================================
# Users
# ============================================================================


class TestZoomUsersMock:
    # list_users / create_user removed 2026-08-11 (need user:*:admin scopes not
    # registered in the Marketplace app) — their tests were removed with them.
    @pytest.mark.asyncio
    async def test_get_user(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetUserConfig(user_id="me"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"id": "u1", "email": "me@b.com"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_user"

    @pytest.mark.asyncio
    async def test_update_user(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomUpdateUserConfig(user_id="u1", first_name="Ada"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_user"

    @pytest.mark.asyncio
    async def test_delete_user(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomDeleteUserConfig(user_id="u1", action="disassociate"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_user"


# ============================================================================
# Recordings
# ============================================================================


class TestZoomRecordingsMock:
    @pytest.mark.asyncio
    async def test_list_user_recordings(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListUserRecordingsConfig(user_id="me", from_date="2026-06-01"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"meetings": [{"uuid": "abc"}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_user_recordings"

    @pytest.mark.asyncio
    async def test_get_meeting_recordings(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetMeetingRecordingsConfig(meeting_id="123"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"recording_files": [{"id": "f1"}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_meeting_recordings"

    @pytest.mark.asyncio
    async def test_delete_meeting_recordings(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomDeleteMeetingRecordingsConfig(meeting_id="123", action="trash"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(204, None, content=b"")
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_meeting_recordings"

    # list_account_recordings removed 2026-08-11 (needs
    # cloud_recording:read:list_account_recordings:admin, not registered) — test
    # removed with the operation.


# ============================================================================
# Phone & Chat
# ============================================================================


class TestZoomPhoneChatMock:
    @pytest.mark.asyncio
    async def test_list_call_logs(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomListCallLogsConfig(from_date="2026-06-01", to_date="2026-06-30"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(200, {"call_logs": [{"id": "c1"}]})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_call_logs"

    @pytest.mark.asyncio
    async def test_send_chat_message(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomSendChatMessageConfig(user_id="me", message="hi", to_contact="a@b.com"),
            credentials=oauth_credentials,
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(201, {"id": "msg_1", "message": "hi"})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_chat_message"
        assert result["data"]["id"] == "msg_1"


# ============================================================================
# Auth — Server-to-Server token mint + full S2S execution
# ============================================================================


class TestZoomServerToServerAuthMock:
    @pytest.mark.asyncio
    async def test_s2s_full_execution(self, s2s_credentials):
        """S2S credential: token POST then the API request, both mocked."""
        config = ZoomNodeConfig(
            config=ZoomGetMeetingConfig(meeting_id="123"), credentials=s2s_credentials
        )
        node = create_zoom_node(config)
        # First call (token mint) returns access_token; second (API) returns the meeting.
        token_client = create_mock_client(200, {"access_token": "minted_token", "expires_in": 3600})
        api_client = create_mock_client(200, {"id": 123, "topic": "Demo"})
        clients = iter([token_client, api_client])
        with patch("nodes.zoom_node.httpx.AsyncClient", side_effect=lambda *a, **k: next(clients)):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_meeting"
        assert result["data"]["id"] == 123

    @pytest.mark.asyncio
    async def test_s2s_token_mint_failure(self, s2s_credentials):
        """A failed token mint raises before any API call."""
        config = ZoomNodeConfig(
            config=ZoomGetMeetingConfig(meeting_id="123"), credentials=s2s_credentials
        )
        node = create_zoom_node(config)
        token_client = create_mock_client(400, {"reason": "Invalid client_id"})
        with patch("nodes.zoom_node.httpx.AsyncClient", return_value=token_client):
            with pytest.raises(ValueError, match="Zoom token request failed"):
                await node.execute({})


# ============================================================================
# Trigger
# ============================================================================


class TestZoomTriggerMock:
    def test_one_trigger_per_event(self):
        """The single receive-webhook trigger is decomposed into one op per event."""
        assert len(ZOOM_TRIGGER_CONFIGS) == 96  # 95 events + on_any_zoom_event
        assert "on_any_zoom_event" in ZOOM_TRIGGER_CONFIGS
        for op, cls in ZOOM_TRIGGER_CONFIGS.items():
            extra = cls.model_fields["operation"].json_schema_extra
            assert extra["const"] == op and extra["x-is-trigger"] is True

    @pytest.mark.parametrize("op", ["on_meeting_started", "on_recording_completed",
                                    "on_user_created", "on_any_zoom_event"])
    @pytest.mark.asyncio
    async def test_trigger_passthrough(self, op):
        """Each per-event trigger passes the inbound webhook payload through."""
        config = ZoomNodeConfig(
            config=ZOOM_TRIGGER_CONFIGS[op](webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_zoom_node(config)
        payload = {"event": "recording.completed", "payload": {"object": {"id": 123}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == op
        assert result["data"]["event"] == "recording.completed"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.parametrize("op,event", [
        ("on_meeting_started", "meeting.started"),
        ("on_recording_completed", "recording.completed"),
        ("on_user_created", "user.created"),
        ("on_phone_sms_received", "phone.sms_received"),
    ])
    def test_trigger_fires_only_on_its_event(self, op, event):
        assert ZoomNode.filter_trigger_payload({"event": event}, {"operation": op}) is True
        for other in ("meeting.ended", "webinar.started", "chat_message.sent"):
            if other != event:
                assert ZoomNode.filter_trigger_payload({"event": other}, {"operation": op}) is False

    def test_on_any_event_passes_everything(self):
        for ev in ("meeting.started", "webinar.ended", "recording.completed",
                   "user.created", "phone.callee_answered", "chat_message.sent"):
            assert ZoomNode.filter_trigger_payload({"event": ev}, {"operation": "on_any_zoom_event"}) is True

    def test_unknown_operation_passes(self):
        assert ZoomNode.filter_trigger_payload({"event": "meeting.started"}, {"operation": "receive_webhook"}) is True

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event":"meeting.started"}'
        timestamp = "1718800000"
        message = f"v0:{timestamp}:{body.decode()}"
        digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        good_sig = f"v0={digest}"
        headers = {"x-zm-signature": good_sig, "x-zm-request-timestamp": timestamp}
        assert ZoomNode.verify_webhook_signature(body, headers, {"signing_secret": secret})
        bad_headers = {"x-zm-signature": "v0=deadbeef", "x-zm-request-timestamp": timestamp}
        assert not ZoomNode.verify_webhook_signature(body, bad_headers, {"signing_secret": secret})
        # no secret stored yet -> accept (trigger not armed)
        assert ZoomNode.verify_webhook_signature(body, {}, {})
        # secret present but signature header missing -> reject
        assert not ZoomNode.verify_webhook_signature(body, {}, {"signing_secret": secret})

    def test_handle_webhook_handshake(self):
        plain = "abc123plain"
        secret = "topsecret"
        body = json.dumps(
            {"event": "endpoint.url_validation", "payload": {"plainToken": plain}}
        ).encode()
        # With the Secret Token: must return plainToken + the HMAC encryptedToken
        # (Zoom rejects the CRC without a correct encryptedToken).
        resp = ZoomNode.handle_webhook_handshake(body, {}, {"signing_secret": secret})
        expected = hmac.new(secret.encode(), plain.encode(), hashlib.sha256).hexdigest()
        assert resp == {"plainToken": plain, "encryptedToken": expected}
        # Without a stored secret: falls back to the plain-token echo.
        assert ZoomNode.handle_webhook_handshake(body, {}, {}) == {"plainToken": plain}
        # a normal event is not a handshake
        normal = json.dumps({"event": "meeting.started", "payload": {}}).encode()
        assert ZoomNode.handle_webhook_handshake(normal, {}, {}) is None


# ============================================================================
# Dynamic options (user_id dropdown -> GET /users)
# ============================================================================


class TestZoomDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_user_options_oauth(self):
        """OAuth credential: the loader reads the token directly and maps users."""
        users_payload = {
            "users": [
                {
                    "id": "u1",
                    "email": "ada@example.com",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                },
                {"id": "u2", "email": "tu@example.com", "display_name": "Alan Turing"},
                {"id": None, "email": "skipme@example.com"},  # no id -> skipped
            ]
        }
        mock_client = create_mock_client(200, users_payload)
        with patch_zoom_client(mock_client):
            result = await ZoomNode.load_field_options(
                field_name="user_id",
                credential_data={
                    "credential_type": "zoom_oauth",
                    "access_token": "tok_oauth",
                },
            )
        opts = result["options"]
        assert len(opts) == 2  # the id-less row is dropped
        assert opts[0] == {"label": "Ada Lovelace (ada@example.com)", "value": "u1"}
        assert opts[1] == {"label": "Alan Turing (tu@example.com)", "value": "u2"}

    @pytest.mark.asyncio
    async def test_load_user_options_s2s_mints_token(self):
        """S2S credential: the loader mints a token, then lists users."""
        # One mock response serves both the token POST and the /users GET.
        combined = {
            "access_token": "minted_s2s_token",
            "users": [{"id": "u9", "email": "ops@example.com", "display_name": "Ops Bot"}],
        }
        mock_client = create_mock_client(200, combined)
        with patch_zoom_client(mock_client):
            result = await ZoomNode.load_field_options(
                field_name="user_id",
                credential_data={
                    "credential_type": "zoom_server_to_server",
                    "account_id": "acc_1",
                    "client_id": "cid_1",
                    "client_secret": "sec_1",
                },
            )
        opts = result["options"]
        assert opts == [{"label": "Ops Bot (ops@example.com)", "value": "u9"}]

    @pytest.mark.asyncio
    async def test_load_options_unknown_field_returns_empty(self):
        result = await ZoomNode.load_field_options(
            field_name="meeting_id",
            credential_data={"access_token": "tok"},
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_user_options_no_credential_returns_empty(self):
        result = await ZoomNode.load_field_options(field_name="user_id", credential_data=None)
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_user_options_api_error_returns_empty(self):
        mock_client = create_mock_client(403, {"message": "No permission"})
        with patch_zoom_client(mock_client):
            result = await ZoomNode.load_field_options(
                field_name="user_id",
                credential_data={"access_token": "tok"},
            )
        assert result == {"options": []}


# ============================================================================
# Error handling
# ============================================================================


class TestZoomErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = ZoomNodeConfig(
            config=ZoomGetMeetingConfig(meeting_id="missing"), credentials=oauth_credentials
        )
        node = create_zoom_node(config)
        mock_client = create_mock_client(404, {"message": "Meeting does not exist", "code": 3001})
        with patch_zoom_client(mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "does not exist" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ZoomNodeConfig(config=ZoomGetUserConfig(user_id="me"), credentials=None)
        node = create_zoom_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Full-coverage dispatch tests — every registry op (generated across all Zoom
# product areas) builds a minimal config, mocks the HTTP layer, runs execute(),
# and must dispatch cleanly to _zoom_request with a resolved /path. Guards
# against handler/field drift across the ~1,500-op surface.
# ============================================================================

from typing import get_args
import nodes.zoom_node as _zmod
from nodes.zoom_node import ZoomConfig

_MEMBERS = {m.model_fields["operation"].default: m for m in get_args(get_args(ZoomConfig)[0])}
_ACTION_OPS = [op for op in _MEMBERS if op not in _zmod.ZOOM_TRIGGER_CONFIGS]
# OAuth cred with far-future expiry so _ensure_fresh_token no-ops (no network/DB).
_COV_CRED = ZoomOAuthCredential(access_token="tok", refresh_token="r", expires_at="2099-01-01T00:00:00+00:00")


def _build_min(model):
    kwargs = {}
    for name, field in model.model_fields.items():
        if name == "operation" or not field.is_required():
            continue
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        enum = extra.get("enum")
        kwargs[name] = enum[0] if enum else ("{}" if name.endswith("_json") else "1")
    return model(**kwargs)


@pytest.mark.parametrize("op", _ACTION_OPS)
@pytest.mark.asyncio
async def test_zoom_operation_dispatches(op):
    captured = {}

    async def fake_request(token, method, endpoint, params=None, json_body=None, action_name="request"):
        captured["endpoint"] = endpoint
        return {"status": "success", "action": action_name, "data": {}}

    node = create_zoom_node(ZoomNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_COV_CRED))
    with patch.object(_zmod, "_zoom_request", side_effect=fake_request):
        result = await node.execute({})
    assert result["status"] == "success", f"{op}: {result.get('error')}"
    assert result["action"] == op
    assert captured.get("endpoint", "").startswith("/"), f"{op}: bad endpoint {captured.get('endpoint')}"
    assert "{" not in captured["endpoint"], f"{op}: unresolved path {captured['endpoint']}"


def test_zoom_full_coverage_op_count():
    """Lock in the operable surface after the 2026-08-11 cleanup: 404 non-working
    ops were removed (286 needed :admin/:master scopes not registered in the
    Marketplace app; 118 pointed at invented/deprecated/mis-pathed Zoom endpoints),
    verified by a full-scope live sweep. Assert they're excluded and the surviving
    surface is still large and unique."""
    # every removed op is undispatchable
    for op in _zmod._REMOVED_OPERATIONS:
        assert op not in _zmod.OPERATION_HANDLERS, f"{op} was removed but still dispatchable"
    # 404 generated ops via denylist + 9 more marketplace/whiteboard scope-blocked
    assert len(_zmod._REMOVED_OPERATIONS) == 413
    # the 3 hand-written scope-blocked ops were pulled from the union + dispatch
    assert not any(op in _MEMBERS for op in ("list_users", "create_user", "list_account_recordings"))
    assert len(_zmod.OPERATION_HANDLERS) > 1000
    consts = [op for op in _MEMBERS]
    assert len(consts) == len(set(consts))  # no duplicate discriminators
    assert len(_ACTION_OPS) > 1000

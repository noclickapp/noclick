"""
Mock tests for the Fellow (fellow.ai) REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Profile: get me
- Recordings: list, get, delete
- Notes: list, get, delete
- Action Items: list, get, complete, archive
- Webhooks: list, create, get, update, delete
- Triggers: all 4 decomposed triggers + catch-all, registration per event type,
  signature verification
- Error handling: API errors, missing credentials
"""

import base64
import hashlib
import hmac
import json

import pytest
from unittest.mock import Mock, patch

from nodes.fellow_node import (
    FELLOW_TRIGGER_EVENTS,
    FellowNode,
    FellowNodeConfig,
    FellowAPIKeyCredential,
    FellowGetMeConfig,
    FellowListRecordingsConfig,
    FellowGetRecordingConfig,
    FellowDeleteRecordingConfig,
    FellowListNotesConfig,
    FellowGetNoteConfig,
    FellowDeleteNoteConfig,
    FellowListActionItemsConfig,
    FellowGetActionItemConfig,
    FellowCompleteActionItemConfig,
    FellowArchiveActionItemConfig,
    FellowListWebhooksConfig,
    FellowCreateWebhookConfig,
    FellowGetWebhookConfig,
    FellowUpdateWebhookConfig,
    FellowDeleteWebhookConfig,
    FellowOnAINoteGeneratedConfig,
    FellowOnAINoteSharedConfig,
    FellowOnActionItemAssignedConfig,
    FellowOnActionItemCompletedConfig,
    FellowEventTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return FellowAPIKeyCredential(subdomain="acme", api_key="fellow_test_key_12345")


def create_fellow_node(config):
    return FellowNode(
        node_id="test-fellow-node",
        node_type="automation-fellow",
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


class TestFellowProfileMock:
    @pytest.mark.asyncio
    async def test_get_me(self, api_key_credentials):
        config = FellowNodeConfig(config=FellowGetMeConfig(), credentials=api_key_credentials)
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "u_1", "email": "ada@example.com"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["email"] == "ada@example.com"


class TestFellowRecordingsMock:
    @pytest.mark.asyncio
    async def test_list_recordings(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowListRecordingsConfig(
                title="standup", include_transcript="true", page_size="10"
            ),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "rec_1"}, {"id": "rec_2"}]})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_recordings"
        assert len(result["data"]["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_recording(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetRecordingConfig(recording_id="rec_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "rec_123", "title": "Weekly sync"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_recording"
        assert result["data"]["id"] == "rec_123"

    @pytest.mark.asyncio
    async def test_delete_recording(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowDeleteRecordingConfig(recording_id="rec_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_recording"
        assert result["data"]["success"] is True


class TestFellowNotesMock:
    @pytest.mark.asyncio
    async def test_list_notes(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowListNotesConfig(include_content_markdown="true"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "note_1"}]})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_notes"

    @pytest.mark.asyncio
    async def test_get_note(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetNoteConfig(note_id="note_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "note_123", "title": "Notes"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_note"
        assert result["data"]["id"] == "note_123"

    @pytest.mark.asyncio
    async def test_delete_note(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowDeleteNoteConfig(note_id="note_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_note"


class TestFellowActionItemsMock:
    @pytest.mark.asyncio
    async def test_list_action_items(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowListActionItemsConfig(scope="assigned_to_me"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "ai_1"}, {"id": "ai_2"}]})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_action_items"
        assert len(result["data"]["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_action_item(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetActionItemConfig(action_item_id="ai_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "ai_123", "text": "Ship the node"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_action_item"
        assert result["data"]["id"] == "ai_123"

    @pytest.mark.asyncio
    async def test_complete_action_item(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowCompleteActionItemConfig(action_item_id="ai_123", completed="true"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "ai_123", "completed": True})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "complete_action_item"
        assert result["data"]["completed"] is True

    @pytest.mark.asyncio
    async def test_archive_action_item(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowArchiveActionItemConfig(action_item_id="ai_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "ai_123", "archived": True})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "archive_action_item"


class TestFellowWebhooksMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowListWebhooksConfig(), credentials=api_key_credentials
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "wh_1"}]})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowCreateWebhookConfig(
                url="https://abc.hooks.example.test", events="ai_note.generated,action_item.assigned"
            ),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(201, {"id": "wh_new"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["id"] == "wh_new"

    @pytest.mark.asyncio
    async def test_get_webhook(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetWebhookConfig(webhook_id="wh_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "wh_123", "url": "https://x"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_webhook"
        assert result["data"]["id"] == "wh_123"

    @pytest.mark.asyncio
    async def test_update_webhook(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowUpdateWebhookConfig(
                webhook_id="wh_123", events="ai_note.generated"
            ),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(200, {"id": "wh_123", "events": ["ai_note.generated"]})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_webhook"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowDeleteWebhookConfig(webhook_id="wh_123"),
            credentials=api_key_credentials,
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


class TestFellowTriggerMock:
    # ------------------------------------------------------------------
    # Decomposed trigger passthrough
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_on_ai_note_generated_passthrough(self):
        config = FellowNodeConfig(
            config=FellowOnAINoteGeneratedConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fellow_node(config)
        payload = {"type": "ai_note.generated", "data": {"id": "note_x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_ai_note_generated"
        assert result["event_types"] == ["ai_note.generated"]
        assert result["data"]["type"] == "ai_note.generated"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_on_ai_note_shared_passthrough(self):
        config = FellowNodeConfig(
            config=FellowOnAINoteSharedConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fellow_node(config)
        payload = {"type": "ai_note.shared_to_channel", "data": {"id": "note_y"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_ai_note_shared"
        assert result["event_types"] == ["ai_note.shared_to_channel"]

    @pytest.mark.asyncio
    async def test_on_action_item_assigned_passthrough(self):
        config = FellowNodeConfig(
            config=FellowOnActionItemAssignedConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fellow_node(config)
        payload = {"type": "action_item.assigned", "data": {"id": "ai_1"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_action_item_assigned"
        assert result["event_types"] == ["action_item.assigned"]

    @pytest.mark.asyncio
    async def test_on_action_item_completed_passthrough(self):
        config = FellowNodeConfig(
            config=FellowOnActionItemCompletedConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fellow_node(config)
        payload = {"type": "action_item.completed", "data": {"id": "ai_2"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_action_item_completed"
        assert result["event_types"] == ["action_item.completed"]

    @pytest.mark.asyncio
    async def test_on_fellow_event_catchall_passthrough(self):
        """Catch-all trigger passes all event types and remains backward-compat."""
        config = FellowNodeConfig(
            config=FellowEventTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fellow_node(config)
        payload = {"type": "ai_note.generated", "data": {"id": "note_x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_fellow_event"
        assert result["event_types"] == FELLOW_TRIGGER_EVENTS
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    # ------------------------------------------------------------------
    # Registration: each trigger subscribes to its own event type(s)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_register_external_webhook_ai_note_generated(self):
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": "wh_1", "secret": "whsec_dGVzdA=="}},
        ) as mock_req:
            extra = await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme", "api_key": "k"},
                config={"operation": "on_ai_note_generated"},
                node_id="n1",
            )
        sent = mock_req.call_args.kwargs.get("json_body", {})
        assert sent.get("enabled_events") == ["ai_note.generated"]
        assert extra["external_webhook_id"] == "wh_1"
        assert extra["signing_secret"] == "whsec_dGVzdA=="

    @pytest.mark.asyncio
    async def test_register_external_webhook_ai_note_shared(self):
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": "wh_2", "secret": "whsec_dGVzdA=="}},
        ) as mock_req:
            await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme", "api_key": "k"},
                config={"operation": "on_ai_note_shared"},
                node_id="n2",
            )
        sent = mock_req.call_args.kwargs.get("json_body", {})
        assert sent.get("enabled_events") == ["ai_note.shared_to_channel"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_action_item_assigned(self):
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": "wh_3", "secret": "whsec_dGVzdA=="}},
        ) as mock_req:
            await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme", "api_key": "k"},
                config={"operation": "on_action_item_assigned"},
                node_id="n3",
            )
        sent = mock_req.call_args.kwargs.get("json_body", {})
        assert sent.get("enabled_events") == ["action_item.assigned"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_action_item_completed(self):
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": "wh_4", "secret": "whsec_dGVzdA=="}},
        ) as mock_req:
            await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme", "api_key": "k"},
                config={"operation": "on_action_item_completed"},
                node_id="n4",
            )
        sent = mock_req.call_args.kwargs.get("json_body", {})
        assert sent.get("enabled_events") == ["action_item.completed"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_catchall(self):
        """Catch-all trigger registers all 4 events."""
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": "wh_all", "secret": "whsec_dGVzdA=="}},
        ) as mock_req:
            await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme", "api_key": "k"},
                config={"operation": "on_fellow_event"},
                node_id="n5",
            )
        sent = mock_req.call_args.kwargs.get("json_body", {})
        assert sent.get("enabled_events") == FELLOW_TRIGGER_EVENTS
        assert len(sent["enabled_events"]) == 4

    @pytest.mark.asyncio
    async def test_register_external_webhook_partial_response(self):
        """Registration must raise if Fellow returns no id or no secret."""
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {"id": None, "secret": None}},
        ):
            with pytest.raises(ValueError, match="incomplete data"):
                await FellowNode._register_external_webhook(
                    webhook_url="https://abc.hooks.example.test",
                    credential={"subdomain": "acme", "api_key": "fellow_test"},
                    config={},
                    node_id="node-1",
                )

    @pytest.mark.asyncio
    async def test_register_external_webhook_missing_creds(self):
        with pytest.raises(ValueError, match="subdomain and API key"):
            await FellowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"subdomain": "acme"},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.fellow_node._fellow_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await FellowNode._unregister_external_webhook(
                credential={"subdomain": "acme", "api_key": "fellow_test"},
                config={"external_webhook_id": "wh_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature_svix(self):
        """Fellow uses Svix: HMAC-SHA256 over '{svix-id}.{svix-timestamp}.{body}',
        secret is whsec_<base64>, signature is 'v1,<base64>'."""
        import time as _time

        raw_secret = b"test-secret-bytes"
        whsec = "whsec_" + base64.b64encode(raw_secret).decode()
        body = b'{"event":"ai_note.generated"}'
        svix_id = "msg_01H0J2VKXZ"
        svix_ts = str(int(_time.time()))  # must be within replay window
        signed_content = f"{svix_id}.{svix_ts}.".encode() + body
        sig_b64 = base64.b64encode(
            hmac.new(raw_secret, signed_content, hashlib.sha256).digest()
        ).decode()
        good_headers = {
            "svix-id": svix_id,
            "svix-timestamp": svix_ts,
            "svix-signature": f"v1,{sig_b64}",
        }
        assert FellowNode.verify_webhook_signature(body, good_headers, {"signing_secret": whsec})
        # Wrong signature
        bad_headers = {**good_headers, "svix-signature": "v1,deadbeefdeadbeef"}
        assert not FellowNode.verify_webhook_signature(body, bad_headers, {"signing_secret": whsec})
        # Missing svix headers → reject
        assert not FellowNode.verify_webhook_signature(body, {}, {"signing_secret": whsec})
        # No secret stored → accept (trigger not yet armed)
        assert FellowNode.verify_webhook_signature(body, {}, {})
        # Multiple signatures in header (Svix rotation)
        multi_headers = {**good_headers, "svix-signature": f"v1,oldsig v1,{sig_b64}"}
        assert FellowNode.verify_webhook_signature(body, multi_headers, {"signing_secret": whsec})
        # Replayed (old) timestamp → reject
        old_ts = str(int(_time.time()) - 400)
        old_content = f"{svix_id}.{old_ts}.".encode() + body
        old_sig = base64.b64encode(hmac.new(raw_secret, old_content, hashlib.sha256).digest()).decode()
        old_headers = {**good_headers, "svix-timestamp": old_ts, "svix-signature": f"v1,{old_sig}"}
        assert not FellowNode.verify_webhook_signature(body, old_headers, {"signing_secret": whsec})

    def test_handle_webhook_handshake_url_verification(self):
        """Fellow sends a url_verification challenge; node must echo it back."""
        challenge = "test-challenge-token-abc123"
        body = json.dumps({"type": "url_verification", "challenge": challenge}).encode()
        result = FellowNode.handle_webhook_handshake(body, {})
        assert result == {"challenge": challenge}

    def test_handle_webhook_handshake_normal_event(self):
        """Normal webhook events must not be intercepted by the handshake hook."""
        body = json.dumps({"type": "ai_note.generated", "data": {}}).encode()
        assert FellowNode.handle_webhook_handshake(body, {}) is None

    def test_handle_webhook_handshake_invalid_json(self):
        """Garbage body must not raise, just return None."""
        assert FellowNode.handle_webhook_handshake(b"not-json", {}) is None


class TestFellowErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetNoteConfig(note_id="missing"), credentials=api_key_credentials
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(404, {"message": "Note not found"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_rate_limited_error(self, api_key_credentials):
        config = FellowNodeConfig(
            config=FellowGetMeConfig(), credentials=api_key_credentials
        )
        node = create_fellow_node(config)
        mock_client = create_mock_client(429, {"error": "rate_limited"})
        with patch("nodes.fellow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 429
        assert "rate_limited" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = FellowNodeConfig(config=FellowGetMeConfig(), credentials=None)
        node = create_fellow_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

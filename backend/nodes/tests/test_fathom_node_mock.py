"""
Mock tests for the Fathom meeting-notetaker REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Meetings: list, list with summaries / action items / CRM matches, by type, external-only
- Meeting Types: list
- Recordings: get summary, get transcript
- Teams: list teams, list team members
- Webhooks: create, delete
- Trigger: on_new_meeting passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: meeting-type + team dropdowns
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.fathom_node import (
    FathomNode,
    FathomNodeConfig,
    FathomApiKeyCredential,
    FathomBearerTokenCredential,
    FathomOAuthCredential,
    FathomListMeetingsConfig,
    FathomListMeetingsWithSummariesConfig,
    FathomListMeetingsWithActionItemsConfig,
    FathomListMeetingsWithCrmMatchesConfig,
    FathomListMeetingsByTypeConfig,
    FathomListExternalMeetingsConfig,
    FathomListMeetingTypesConfig,
    FathomGetSummaryConfig,
    FathomGetTranscriptConfig,
    FathomListTeamsConfig,
    FathomListTeamMembersConfig,
    FathomCreateWebhookConfig,
    FathomDeleteWebhookConfig,
    FathomNewMeetingTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return FathomApiKeyCredential(api_key="fathom_test_key_12345")


@pytest.fixture
def bearer_credentials():
    return FathomBearerTokenCredential(bearer_token="bearer_test_token_12345")


@pytest.fixture
def oauth_credentials():
    return FathomOAuthCredential(
        access_token="oauth_access_token_12345",
        refresh_token="oauth_refresh_token_12345",
        expires_at="2099-01-01T00:00:00+00:00",
        scope="public_api",
    )


def create_fathom_node(config):
    return FathomNode(
        node_id="test-fathom-node",
        node_type="automation-fathom",
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


def create_mock_client(status_code=200, json_data=None, recorder=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        if recorder is not None:
            recorder.append({"args": args, "kwargs": kwargs})
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


class TestFathomMeetingsMock:
    @pytest.mark.asyncio
    async def test_list_meetings(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingsConfig(
                created_after="2026-06-01T00:00:00Z", include_summary="true"
            ),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 1}, {"id": 2}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings"
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_meetings_sends_expected_api_key_headers_and_query_params(
        self, api_key_credentials
    ):
        config = FathomNodeConfig(
            config=FathomListMeetingsConfig(
                created_after="2026-06-01T00:00:00Z",
                created_before="2026-06-30T00:00:00Z",
                meeting_type="Sales Call",
                recorded_by="ada@example.com, grace@example.com",
                teams="Sales, CS",
                calendar_invitees_domains="example.com, partner.io",
                calendar_invitees_domains_type="all",
                include_action_items="true",
                include_crm_matches="true",
                include_highlights="true",
                cursor="cursor_123",
            ),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        calls = []
        mock_client = create_mock_client(200, {"items": []}, recorder=calls)
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        request = calls[0]["kwargs"]
        assert request["headers"]["X-Api-Key"] == "fathom_test_key_12345"
        assert "Authorization" not in request["headers"]
        assert request["params"] == {
            "created_after": "2026-06-01T00:00:00Z",
            "created_before": "2026-06-30T00:00:00Z",
            "meeting_type": "Sales Call",
            "recorded_by[]": ["ada@example.com", "grace@example.com"],
            "teams[]": ["Sales", "CS"],
            "calendar_invitees_domains[]": ["example.com", "partner.io"],
            "calendar_invitees_domains_type": "all",
            "include_action_items": True,
            "include_crm_matches": True,
            "include_highlights": True,
            "cursor": "cursor_123",
        }

    @pytest.mark.asyncio
    async def test_list_meetings_with_summaries(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingsWithSummariesConfig(),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 1, "default_summary": "..."}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings_with_summaries"

    @pytest.mark.asyncio
    async def test_list_meetings_with_summaries_rejected_for_oauth_credentials(
        self, oauth_credentials
    ):
        config = FathomNodeConfig(
            config=FathomListMeetingsWithSummariesConfig(),
            credentials=oauth_credentials,
        )
        node = create_fathom_node(config)
        with patch.object(FathomNode, "_get_runtime_credential", return_value=oauth_credentials.model_dump()):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "Get Recording Summary" in result["error"]

    @pytest.mark.asyncio
    async def test_list_meetings_with_action_items(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingsWithActionItemsConfig(),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 1, "action_items": []}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings_with_action_items"

    @pytest.mark.asyncio
    async def test_list_meetings_with_crm_matches(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingsWithCrmMatchesConfig(),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 1, "crm_matches": []}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings_with_crm_matches"

    @pytest.mark.asyncio
    async def test_list_meetings_by_type(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingsByTypeConfig(meeting_type="Sales Call"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 9}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meetings_by_type"

    @pytest.mark.asyncio
    async def test_list_external_meetings(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListExternalMeetingsConfig(),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"id": 11}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_external_meetings"

    @pytest.mark.asyncio
    async def test_list_meeting_types(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListMeetingTypesConfig(),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"name": "Sales Call"}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_meeting_types"


class TestFathomRecordingsMock:
    @pytest.mark.asyncio
    async def test_get_summary(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomGetSummaryConfig(recording_id="12345"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"summary": "A productive call"})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_summary"
        assert result["data"]["summary"] == "A productive call"

    @pytest.mark.asyncio
    async def test_get_transcript(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomGetTranscriptConfig(recording_id="12345"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"transcript": [{"speaker": "Ada"}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_transcript"
        assert result["data"]["transcript"][0]["speaker"] == "Ada"


class TestFathomTeamsMock:
    @pytest.mark.asyncio
    async def test_list_teams(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListTeamsConfig(), credentials=api_key_credentials
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"name": "Sales"}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    async def test_list_team_members(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomListTeamMembersConfig(team="Sales"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(200, {"items": [{"email": "ada@example.com"}]})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_team_members"

    @pytest.mark.asyncio
    async def test_list_teams_uses_bearer_auth_when_configured(self, bearer_credentials):
        config = FathomNodeConfig(
            config=FathomListTeamsConfig(), credentials=bearer_credentials
        )
        node = create_fathom_node(config)
        calls = []
        mock_client = create_mock_client(200, {"items": [{"name": "Sales"}]}, recorder=calls)
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        request = calls[0]["kwargs"]
        assert request["headers"]["Authorization"] == "Bearer bearer_test_token_12345"
        assert "X-Api-Key" not in request["headers"]


class TestFathomWebhooksMock:
    @pytest.mark.asyncio
    async def test_create_webhook(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomCreateWebhookConfig(
                destination_url="https://example.com/hook",
                triggered_for="my_recordings",
                include_summary="true",
            ),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(201, {"id": "wh_1", "destination_url": "https://example.com/hook"})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["id"] == "wh_1"

    @pytest.mark.asyncio
    async def test_create_webhook_sends_required_body_flags(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomCreateWebhookConfig(
                destination_url="https://example.com/hook",
                triggered_for="shared_team_recordings",
                include_summary="true",
                include_action_items="true",
                include_transcript="true",
            ),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        calls = []
        mock_client = create_mock_client(201, {"id": "wh_1"}, recorder=calls)
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        request = calls[0]["kwargs"]
        assert request["json"] == {
            "destination_url": "https://example.com/hook",
            "triggered_for": ["shared_team_recordings"],
            "include_transcript": True,
            "include_summary": True,
            "include_action_items": True,
        }

    @pytest.mark.asyncio
    async def test_delete_webhook(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomDeleteWebhookConfig(webhook_id="wh_1"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"
        assert result["data"]["success"] is True


class TestFathomTriggerMock:
    @pytest.mark.asyncio
    async def test_on_new_meeting_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = FathomNodeConfig(
            config=FathomNewMeetingTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_fathom_node(config)
        payload = {"id": 42, "title": "Discovery call", "default_summary": "Notes"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_new_meeting"
        assert result["data"]["id"] == 42
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.fathom_node._fathom_request",
            return_value={"status": "success", "data": {"id": "wh_99", "secret": "whsec_abc"}},
        ) as mock_req:
            extra = await FathomNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "fathom_test"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh_99"
        assert extra["signing_secret"] == "whsec_abc"

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.fathom_node._fathom_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await FathomNode._unregister_external_webhook(
                credential={"api_key": "fathom_test"},
                config={"external_webhook_id": "wh_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        # Build a Svix-style signature the way Fathom signs deliveries.
        raw_secret = b"super-secret-bytes-32-chars-long!!"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()
        msg_id = "msg_123"
        timestamp = "1700000000"
        body = b'{"id":42}'
        signed_content = f"{msg_id}.{timestamp}.".encode() + body
        good_sig = base64.b64encode(
            hmac.new(raw_secret, signed_content, hashlib.sha256).digest()
        ).decode()
        headers = {
            "webhook-id": msg_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": f"v1,{good_sig}",
        }
        assert FathomNode.verify_webhook_signature(body, headers, {"signing_secret": secret})

        bad_headers = dict(headers)
        bad_headers["webhook-signature"] = "v1,deadbeef"
        assert not FathomNode.verify_webhook_signature(
            body, bad_headers, {"signing_secret": secret}
        )

        # no secret stored yet -> accept (trigger not armed)
        assert FathomNode.verify_webhook_signature(body, {}, {})


class TestFathomErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomGetSummaryConfig(recording_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(404, {"message": "Recording not found"})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_api_error_falls_back_when_provider_body_is_empty(self, api_key_credentials):
        config = FathomNodeConfig(
            config=FathomGetSummaryConfig(recording_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_fathom_node(config)
        mock_client = create_mock_client(404, {})
        with patch("nodes.fathom_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert result["error"] == "Fathom API returned HTTP 404"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = FathomNodeConfig(config=FathomListTeamsConfig(), credentials=None)
        node = create_fathom_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestFathomDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_meeting_type_options(self):
        with patch(
            "nodes.fathom_node._fathom_request",
            return_value={
                "status": "success",
                "data": {"items": [{"name": "Sales Call"}, {"name": "Internal"}]},
            },
        ):
            result = await FathomNode.load_field_options(
                "meeting_type", {"api_key": "fathom_test"}, context={}
            )
        assert "options" in result
        values = [o["value"] for o in result["options"]]
        assert "Sales Call" in values
        assert "Internal" in values

    @pytest.mark.asyncio
    async def test_load_team_options(self):
        with patch(
            "nodes.fathom_node._fathom_request",
            return_value={
                "status": "success",
                "data": {"items": [{"name": "Engineering"}]},
            },
        ):
            result = await FathomNode.load_field_options(
                "team", {"api_key": "fathom_test"}, context={}
            )
        assert result["options"][0]["value"] == "Engineering"

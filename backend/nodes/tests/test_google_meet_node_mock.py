"""
Mock tests for the Google Meet REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Spaces: create, get, update, end active conference
- Conference Records: get, list
- Participants: get, list
- Participant Sessions: get, list
- Recordings: get, list
- Transcripts: get, list, get entry, list entries
- Smart Notes: get, list
- Error handling: API errors, missing credentials

The Google Meet node authenticates via OAuth. `_ensure_fresh_token` touches the
DB to refresh + persist the token, so it is patched to return a static token in
every execute-path test.
"""

import pytest
from unittest.mock import Mock, patch

from nodes.google_meet_node import (
    GoogleMeetNode,
    GoogleMeetNodeConfig,
    GoogleMeetOAuthCredential,
    GoogleMeetCreateSpaceConfig,
    GoogleMeetGetSpaceConfig,
    GoogleMeetUpdateSpaceConfig,
    GoogleMeetEndActiveConferenceConfig,
    GoogleMeetGetConferenceRecordConfig,
    GoogleMeetListConferenceRecordsConfig,
    GoogleMeetGetParticipantConfig,
    GoogleMeetListParticipantsConfig,
    GoogleMeetGetParticipantSessionConfig,
    GoogleMeetListParticipantSessionsConfig,
    GoogleMeetGetRecordingConfig,
    GoogleMeetListRecordingsConfig,
    GoogleMeetGetTranscriptConfig,
    GoogleMeetListTranscriptsConfig,
    GoogleMeetGetTranscriptEntryConfig,
    GoogleMeetListTranscriptEntriesConfig,
    GoogleMeetGetSmartNotesConfig,
    GoogleMeetListSmartNotesConfig,
    GoogleMeetOnNewConferenceRecordConfig,
    _build_space_config,
)


@pytest.fixture
def oauth_credentials():
    return GoogleMeetOAuthCredential(
        access_token="ya29.test_access_token",
        refresh_token="1//test_refresh_token",
        expires_at="2099-01-01T00:00:00Z",
        email="user@example.com",
    )


def create_google_meet_node(config):
    return GoogleMeetNode(
        node_id="test-google-meet-node",
        node_type="automation-google-meet",
        node_data={"credential_id": "cred-1"},
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
    mock_response.content = b"{}" if json_data is not None else b""
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


async def _run(node, status_code, json_data):
    """Execute a node with the HTTP client + token refresh mocked."""
    mock_client = create_mock_client(status_code, json_data)
    with patch(
        "nodes.google_meet_node.httpx.AsyncClient", return_value=mock_client
    ), patch.object(
        GoogleMeetNode, "_ensure_fresh_token", return_value="fresh_token"
    ):
        return await node.execute({})


class TestGoogleMeetSpacesMock:
    @pytest.mark.asyncio
    async def test_create_space(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetCreateSpaceConfig(access_type="OPEN"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(
            node, 200, {"name": "spaces/abc", "meetingUri": "https://meet.google.com/xyz"}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_space"
        assert result["data"]["meetingUri"] == "https://meet.google.com/xyz"

    @pytest.mark.asyncio
    async def test_get_space(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetSpaceConfig(space_name="abc"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "spaces/abc", "meetingCode": "abc-defg-hij"})
        assert result["status"] == "success"
        assert result["action"] == "get_space"
        assert result["data"]["meetingCode"] == "abc-defg-hij"

    @pytest.mark.asyncio
    async def test_update_space(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetUpdateSpaceConfig(
                space_name="spaces/abc", access_type="TRUSTED", moderation="ON"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "spaces/abc", "config": {"accessType": "TRUSTED"}})
        assert result["status"] == "success"
        assert result["action"] == "update_space"

    @pytest.mark.asyncio
    async def test_end_active_conference(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetEndActiveConferenceConfig(space_name="abc"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {})
        assert result["status"] == "success"
        assert result["action"] == "end_active_conference"


class TestGoogleMeetConferenceRecordsMock:
    @pytest.mark.asyncio
    async def test_get_conference_record(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetConferenceRecordConfig(conference_record_name="rec1"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "conferenceRecords/rec1"})
        assert result["status"] == "success"
        assert result["action"] == "get_conference_record"
        assert result["data"]["name"] == "conferenceRecords/rec1"

    @pytest.mark.asyncio
    async def test_list_conference_records(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListConferenceRecordsConfig(
                filter='space.name="spaces/abc"', page_size="10"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(
            node, 200, {"conferenceRecords": [{"name": "conferenceRecords/rec1"}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_conference_records"
        assert len(result["data"]["conferenceRecords"]) == 1


class TestGoogleMeetParticipantsMock:
    @pytest.mark.asyncio
    async def test_get_participant(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetParticipantConfig(
                participant_name="conferenceRecords/rec1/participants/p1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "conferenceRecords/rec1/participants/p1"})
        assert result["status"] == "success"
        assert result["action"] == "get_participant"

    @pytest.mark.asyncio
    async def test_list_participants(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListParticipantsConfig(conference_record_name="rec1"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"participants": [{"name": "p1"}, {"name": "p2"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_participants"
        assert len(result["data"]["participants"]) == 2

    @pytest.mark.asyncio
    async def test_get_participant_session(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetParticipantSessionConfig(
                participant_session_name="conferenceRecords/rec1/participants/p1/participantSessions/s1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "...participantSessions/s1"})
        assert result["status"] == "success"
        assert result["action"] == "get_participant_session"

    @pytest.mark.asyncio
    async def test_list_participant_sessions(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListParticipantSessionsConfig(
                participant_name="conferenceRecords/rec1/participants/p1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"participantSessions": [{"name": "s1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_participant_sessions"


class TestGoogleMeetRecordingsMock:
    @pytest.mark.asyncio
    async def test_get_recording(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetRecordingConfig(
                recording_name="conferenceRecords/rec1/recordings/r1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "conferenceRecords/rec1/recordings/r1"})
        assert result["status"] == "success"
        assert result["action"] == "get_recording"

    @pytest.mark.asyncio
    async def test_list_recordings(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListRecordingsConfig(conference_record_name="rec1"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"recordings": [{"name": "r1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_recordings"


class TestGoogleMeetTranscriptsMock:
    @pytest.mark.asyncio
    async def test_get_transcript(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetTranscriptConfig(
                transcript_name="conferenceRecords/rec1/transcripts/t1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "conferenceRecords/rec1/transcripts/t1"})
        assert result["status"] == "success"
        assert result["action"] == "get_transcript"

    @pytest.mark.asyncio
    async def test_list_transcripts(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListTranscriptsConfig(conference_record_name="rec1"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"transcripts": [{"name": "t1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_transcripts"

    @pytest.mark.asyncio
    async def test_get_transcript_entry(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetTranscriptEntryConfig(
                entry_name="conferenceRecords/rec1/transcripts/t1/entries/e1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "...entries/e1", "text": "Hello"})
        assert result["status"] == "success"
        assert result["action"] == "get_transcript_entry"
        assert result["data"]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_list_transcript_entries(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListTranscriptEntriesConfig(
                transcript_name="conferenceRecords/rec1/transcripts/t1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(
            node, 200, {"transcriptEntries": [{"text": "Hi"}, {"text": "Bye"}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_transcript_entries"
        assert len(result["data"]["transcriptEntries"]) == 2


class TestGoogleMeetSmartNotesMock:
    @pytest.mark.asyncio
    async def test_get_smart_notes(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetSmartNotesConfig(
                smart_notes_name="conferenceRecords/rec1/smartNotes/sn1"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"name": "conferenceRecords/rec1/smartNotes/sn1"})
        assert result["status"] == "success"
        assert result["action"] == "get_smart_notes"

    @pytest.mark.asyncio
    async def test_list_smart_notes(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetListSmartNotesConfig(conference_record_name="rec1"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(node, 200, {"smartNotes": [{"name": "sn1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_smart_notes"


class TestGoogleMeetSpaceConfigBuilder:
    """`_build_space_config` maps the flat config fields onto the nested
    Meet SpaceConfig body + update-mask paths. Field names/values are
    live-verified against the Meet REST v2 API."""

    def test_full_settings_body_and_mask(self):
        cfg = GoogleMeetCreateSpaceConfig(
            access_type="OPEN",
            entry_point_access="ALL",
            moderation="ON",
            auto_recording="ON",
            auto_transcription="ON",
            auto_smart_notes="OFF",
            chat_restriction="HOSTS_ONLY",
            reaction_restriction="NO_RESTRICTION",
            present_restriction="HOSTS_ONLY",
            default_join_as_viewer="ON",
        )
        body, paths = _build_space_config(cfg)
        assert body["accessType"] == "OPEN"
        assert body["entryPointAccess"] == "ALL"
        assert body["moderation"] == "ON"
        assert body["moderationRestrictions"] == {
            "chatRestriction": "HOSTS_ONLY",
            "reactionRestriction": "NO_RESTRICTION",
            "presentRestriction": "HOSTS_ONLY",
            "defaultJoinAsViewerType": "ON",
        }
        assert body["artifactConfig"] == {
            "recordingConfig": {"autoRecordingGeneration": "ON"},
            "transcriptionConfig": {"autoTranscriptionGeneration": "ON"},
            "smartNotesConfig": {"autoSmartNotesGeneration": "OFF"},
        }
        assert set(paths) == {
            "config.accessType",
            "config.entryPointAccess",
            "config.moderation",
            "config.moderationRestrictions",
            "config.artifactConfig",
        }

    def test_empty_config_emits_nothing(self):
        body, paths = _build_space_config(GoogleMeetUpdateSpaceConfig(space_name="abc"))
        assert body == {}
        assert paths == []

    def test_partial_artifact_only_recording(self):
        body, paths = _build_space_config(
            GoogleMeetUpdateSpaceConfig(space_name="abc", auto_recording="ON")
        )
        assert body == {"artifactConfig": {"recordingConfig": {"autoRecordingGeneration": "ON"}}}
        assert paths == ["config.artifactConfig"]


class TestGoogleMeetSpaceSettingsExecute:
    """create/update space send the full nested SpaceConfig to the API."""

    @pytest.mark.asyncio
    async def test_create_space_sends_artifact_config(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetCreateSpaceConfig(access_type="OPEN", auto_recording="ON"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        captured = {}
        mock_client = create_mock_client(200, {"name": "spaces/abc"})

        orig_request = mock_client.request

        async def capture(*args, **kwargs):
            captured.update(kwargs)
            return await orig_request(*args, **kwargs)

        mock_client.request = capture
        with patch(
            "nodes.google_meet_node.httpx.AsyncClient", return_value=mock_client
        ), patch.object(GoogleMeetNode, "_ensure_fresh_token", return_value="t"):
            result = await node.execute({})
        assert result["status"] == "success"
        body = captured["json"]
        assert body["config"]["accessType"] == "OPEN"
        assert body["config"]["artifactConfig"]["recordingConfig"]["autoRecordingGeneration"] == "ON"

    @pytest.mark.asyncio
    async def test_update_space_sets_update_mask(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetUpdateSpaceConfig(
                space_name="spaces/abc", moderation="ON", auto_transcription="ON"
            ),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        captured = {}
        mock_client = create_mock_client(200, {"name": "spaces/abc"})
        orig_request = mock_client.request

        async def capture(*args, **kwargs):
            captured.update(kwargs)
            return await orig_request(*args, **kwargs)

        mock_client.request = capture
        with patch(
            "nodes.google_meet_node.httpx.AsyncClient", return_value=mock_client
        ), patch.object(GoogleMeetNode, "_ensure_fresh_token", return_value="t"):
            result = await node.execute({})
        assert result["status"] == "success"
        mask = captured["params"]["updateMask"]
        assert "config.moderation" in mask
        assert "config.artifactConfig" in mask


class TestGoogleMeetErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetSpaceConfig(space_name="missing"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run(
            node, 404, {"error": {"code": 404, "message": "Requested entity was not found."}}
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = GoogleMeetNodeConfig(
            config=GoogleMeetGetSpaceConfig(space_name="abc"), credentials=None
        )
        node = create_google_meet_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Poll-based trigger: on_new_conference_record
# ============================================================================


class TestGoogleMeetTriggerPayloadResolution:
    """resolve_trigger_payload: the cron POST is a wake-up signal for the poll
    trigger (return None so execute() runs), while non-trigger ops pass through."""

    def test_returns_none_for_trigger_op(self):
        payload = {"source": "poll_trigger"}
        resolved = GoogleMeetNode.resolve_trigger_payload(
            payload, {"operation": "on_new_conference_record"}
        )
        assert resolved is None

    def test_passthrough_for_normal_op(self):
        # resolve_trigger_payload is only ever consulted when a webhook fires the
        # node, which for this node only happens for the poll trigger. A normal
        # (push-style) op gets the WorkflowNode default: the payload unchanged.
        from nodes.core.base import WorkflowNode

        payload = {"hello": "world"}
        assert (
            WorkflowNode.resolve_trigger_payload(payload, {"operation": "get_space"})
            == payload
        )


async def _run_trigger(node, status_code, json_data, state_store):
    """Execute the poll trigger with httpx, token refresh, and the node's
    persistent state (used by _filter_unseen for dedup) all mocked. The same
    `state_store` dict is shared across polls to exercise baseline + dedup."""
    mock_client = create_mock_client(status_code, json_data)

    async def fake_load_state(self):
        return dict(state_store)

    async def fake_save_state(self, state, **_):
        state_store.clear()
        state_store.update(state)

    async def fake_emit(self, output):
        return None

    with patch(
        "nodes.google_meet_node.httpx.AsyncClient", return_value=mock_client
    ), patch.object(
        GoogleMeetNode, "_ensure_fresh_token", return_value="fresh_token"
    ), patch.object(
        GoogleMeetNode, "_load_node_state", fake_load_state
    ), patch.object(
        GoogleMeetNode, "_save_node_state", fake_save_state
    ), patch.object(
        GoogleMeetNode, "emit", fake_emit
    ):
        return await node.execute({})


class TestGoogleMeetTriggerPoll:
    @pytest.mark.asyncio
    async def test_poll_baselines_then_emits_new_and_dedupes(self, oauth_credentials):
        """First poll baselines (emits nothing), second poll emits the newly
        ended meeting, a repeat poll of the same records emits nothing."""
        config = GoogleMeetNodeConfig(
            config=GoogleMeetOnNewConferenceRecordConfig(),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        state_store: dict = {}

        # Poll 1: one ended meeting already present -> baseline, emit nothing.
        baseline_payload = {
            "conferenceRecords": [
                {"name": "conferenceRecords/rec1", "endTime": "2026-06-19T10:00:00Z"},
            ]
        }
        result = await _run_trigger(node, 200, baseline_payload, state_store)
        assert result["status"] == "success"
        assert result["operation"] == "on_new_conference_record"
        assert result["new_count"] == 0
        assert result["conference_records"] == []
        assert "conferenceRecords/rec1" in state_store.get("seen_ids", [])

        # Poll 2: a second meeting ended -> only rec2 is emitted.
        new_payload = {
            "conferenceRecords": [
                {"name": "conferenceRecords/rec2", "endTime": "2026-06-19T11:00:00Z"},
                {"name": "conferenceRecords/rec1", "endTime": "2026-06-19T10:00:00Z"},
            ]
        }
        result = await _run_trigger(node, 200, new_payload, state_store)
        assert result["new_count"] == 1
        assert result["conference_records"][0]["name"] == "conferenceRecords/rec2"

        # Poll 3: same records again -> nothing new (deduped via cursor/seen set).
        result = await _run_trigger(node, 200, new_payload, state_store)
        assert result["new_count"] == 0
        assert result["conference_records"] == []

    @pytest.mark.asyncio
    async def test_poll_ignores_active_meetings_without_endtime(self, oauth_credentials):
        """A conference still in progress (no endTime) must not be emitted, even
        after the baseline poll."""
        config = GoogleMeetNodeConfig(
            config=GoogleMeetOnNewConferenceRecordConfig(),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        # Pre-seed the seen set so this is not the baseline poll.
        state_store: dict = {"seen_ids": ["conferenceRecords/old"]}

        payload = {
            "conferenceRecords": [
                {"name": "conferenceRecords/active"},  # no endTime -> in progress
                {"name": "conferenceRecords/ended", "endTime": "2026-06-19T12:00:00Z"},
            ]
        }
        result = await _run_trigger(node, 200, payload, state_store)
        assert result["new_count"] == 1
        assert result["conference_records"][0]["name"] == "conferenceRecords/ended"
        names = {r["name"] for r in result["conference_records"]}
        assert "conferenceRecords/active" not in names

    @pytest.mark.asyncio
    async def test_poll_propagates_api_error(self, oauth_credentials):
        """An API error from conferenceRecords.list surfaces as an error result,
        not a (mis)emitted trigger."""
        config = GoogleMeetNodeConfig(
            config=GoogleMeetOnNewConferenceRecordConfig(space_name="abc"),
            credentials=oauth_credentials,
        )
        node = create_google_meet_node(config)
        result = await _run_trigger(
            node,
            403,
            {"error": {"code": 403, "message": "Permission denied."}},
            {},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 403

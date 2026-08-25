"""
Mock tests for the Attio CRM REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Records: list, get, create, update, upsert, delete, search
- Schema: list objects, list attributes, list lists
- List entries: list, create, update, delete
- Notes: list, create, delete
- Tasks: list, create, update, delete
- Comments: create
- Workspace: list members, identify self
- Trigger: on_attio_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: object + list dropdowns
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.attio_node import (
    AttioNode,
    AttioNodeConfig,
    AttioAPIKeyCredential,
    AttioListRecordsConfig,
    AttioGetRecordConfig,
    AttioCreateRecordConfig,
    AttioUpdateRecordConfig,
    AttioUpsertRecordConfig,
    AttioDeleteRecordConfig,
    AttioSearchRecordsConfig,
    AttioListObjectsConfig,
    AttioListAttributesConfig,
    AttioListListsConfig,
    AttioListEntriesConfig,
    AttioCreateListEntryConfig,
    AttioUpdateListEntryConfig,
    AttioDeleteListEntryConfig,
    AttioListNotesConfig,
    AttioCreateNoteConfig,
    AttioDeleteNoteConfig,
    AttioListTasksConfig,
    AttioCreateTaskConfig,
    AttioUpdateTaskConfig,
    AttioDeleteTaskConfig,
    AttioCreateCommentConfig,
    AttioListWorkspaceMembersConfig,
    AttioGetWorkspaceMemberConfig,
    AttioIdentifySelfConfig,
    AttioWebhookTriggerConfig,
    AttioGetObjectConfig,
    AttioCreateObjectConfig,
    AttioUpdateObjectConfig,
    AttioGetAttributeConfig,
    AttioCreateAttributeConfig,
    AttioUpdateAttributeConfig,
    AttioListSelectOptionsConfig,
    AttioCreateSelectOptionConfig,
    AttioUpdateSelectOptionConfig,
    AttioListStatusesConfig,
    AttioCreateStatusConfig,
    AttioUpdateStatusConfig,
    AttioOverwriteRecordConfig,
    AttioListRecordEntriesConfig,
    AttioListRecordAttributeValuesConfig,
    AttioGetListConfig,
    AttioCreateListConfig,
    AttioUpdateListConfig,
    AttioGetListEntryConfig,
    AttioAssertListEntryConfig,
    AttioOverwriteListEntryConfig,
    AttioListEntryAttributeValuesConfig,
    AttioGetNoteConfig,
    AttioGetTaskConfig,
    AttioCreateEntryCommentConfig,
    AttioReplyToThreadConfig,
    AttioGetCommentConfig,
    AttioDeleteCommentConfig,
    AttioListThreadsConfig,
    AttioListEntryThreadsConfig,
    AttioGetThreadConfig,
    AttioListFilesConfig,
    AttioGetFileConfig,
    AttioListMeetingsConfig,
    AttioGetMeetingConfig,
)


@pytest.fixture
def api_key_credentials():
    return AttioAPIKeyCredential(access_token="attio_test_token_12345")


def create_attio_node(config):
    return AttioNode(
        node_id="test-attio-node",
        node_type="automation-attio",
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
    """Attio wraps results in {data: ...}."""
    return {"data": data}


class TestAttioRecordsMock:
    @pytest.mark.asyncio
    async def test_list_records(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioListRecordsConfig(object="companies", limit="10"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "r1"}, {"id": "r2"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_records"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_record(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioGetRecordConfig(object="people", record_id="rec_123"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"record_id": "rec_123"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_record"
        assert result["data"]["id"]["record_id"] == "rec_123"

    @pytest.mark.asyncio
    async def test_create_record(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateRecordConfig(
                object="companies", values_json='{"name": "Acme"}'
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"record_id": "rec_new"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_record"
        assert result["data"]["id"]["record_id"] == "rec_new"

    @pytest.mark.asyncio
    async def test_update_record(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioUpdateRecordConfig(
                object="companies", record_id="rec_123", values_json='{"name": "Acme Inc"}'
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"record_id": "rec_123"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_record"

    @pytest.mark.asyncio
    async def test_upsert_record(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioUpsertRecordConfig(
                object="companies",
                matching_attribute="domains",
                values_json='{"domains": ["acme.com"]}',
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"record_id": "rec_up"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upsert_record"

    @pytest.mark.asyncio
    async def test_delete_record(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioDeleteRecordConfig(object="companies", record_id="rec_123"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_record"

    @pytest.mark.asyncio
    async def test_search_records(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioSearchRecordsConfig(object="companies", query="acme"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "r1"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_records"


class TestAttioSchemaMock:
    @pytest.mark.asyncio
    async def test_list_objects(self, api_key_credentials):
        config = AttioNodeConfig(config=AttioListObjectsConfig(), credentials=api_key_credentials)
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"api_slug": "companies"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_objects"

    @pytest.mark.asyncio
    async def test_list_attributes(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioListAttributesConfig(target="objects", identifier="companies"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"api_slug": "name"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_attributes"

    @pytest.mark.asyncio
    async def test_list_lists(self, api_key_credentials):
        config = AttioNodeConfig(config=AttioListListsConfig(), credentials=api_key_credentials)
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"api_slug": "leads"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_lists"


class TestAttioListEntriesMock:
    @pytest.mark.asyncio
    async def test_list_entries(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioListEntriesConfig(list="leads", limit="5"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "e1"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_entries"

    @pytest.mark.asyncio
    async def test_create_list_entry(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateListEntryConfig(
                list="leads", parent_record_id="rec_1", parent_object="companies"
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"entry_id": "e_new"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_list_entry"

    @pytest.mark.asyncio
    async def test_update_list_entry(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioUpdateListEntryConfig(
                list="leads", entry_id="e_1", entry_values_json='{"stage": "won"}'
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"entry_id": "e_1"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_list_entry"

    @pytest.mark.asyncio
    async def test_delete_list_entry(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioDeleteListEntryConfig(list="leads", entry_id="e_1"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_list_entry"


class TestAttioNotesMock:
    @pytest.mark.asyncio
    async def test_list_notes(self, api_key_credentials):
        config = AttioNodeConfig(config=AttioListNotesConfig(), credentials=api_key_credentials)
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "n1"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_notes"

    @pytest.mark.asyncio
    async def test_create_note(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateNoteConfig(
                parent_object="companies",
                parent_record_id="rec_1",
                title="Call summary",
                content="Spoke with the CEO.",
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"note_id": "n_new"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_note"

    @pytest.mark.asyncio
    async def test_delete_note(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioDeleteNoteConfig(note_id="n_1"), credentials=api_key_credentials
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_note"


class TestAttioTasksMock:
    @pytest.mark.asyncio
    async def test_list_tasks(self, api_key_credentials):
        config = AttioNodeConfig(config=AttioListTasksConfig(), credentials=api_key_credentials)
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "t1"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_tasks"

    @pytest.mark.asyncio
    async def test_create_task(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateTaskConfig(content="Follow up with Acme"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"task_id": "t_new"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_task"

    @pytest.mark.asyncio
    async def test_update_task(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioUpdateTaskConfig(task_id="t_1", is_completed="true"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"task_id": "t_1"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_task"

    @pytest.mark.asyncio
    async def test_delete_task(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioDeleteTaskConfig(task_id="t_1"), credentials=api_key_credentials
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_task"


class TestAttioCommentWorkspaceMock:
    @pytest.mark.asyncio
    async def test_create_comment(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateCommentConfig(
                content="Looks good", record_object="companies", record_id="rec_1",
                author_workspace_member_id="wm_1",
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"id": {"comment_id": "c_new"}}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_comment"

    @pytest.mark.asyncio
    async def test_create_comment_resolves_author_from_self(self, api_key_credentials):
        """With no author set, the node introspects /v2/self for the token owner."""
        config = AttioNodeConfig(
            config=AttioCreateCommentConfig(
                content="Auto author", record_object="companies", record_id="rec_1"
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            if endpoint == "/v2/self":
                return {"status": "success", "data": {"authorized_by_workspace_member_id": "wm_self"}}
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"comment_id": "c_new"}}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured["json_body"]["data"]["author"] == {"type": "workspace-member", "id": "wm_self"}

    @pytest.mark.asyncio
    async def test_list_workspace_members(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioListWorkspaceMembersConfig(), credentials=api_key_credentials
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope([{"id": "wm1"}]))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_workspace_members"

    @pytest.mark.asyncio
    async def test_identify_self(self, api_key_credentials):
        config = AttioNodeConfig(config=AttioIdentifySelfConfig(), credentials=api_key_credentials)
        node = create_attio_node(config)
        mock_client = create_mock_client(200, _envelope({"workspace_id": "ws_1", "active": True}))
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "identify_self"
        assert result["data"]["workspace_id"] == "ws_1"


class TestAttioTriggerMock:
    @pytest.mark.asyncio
    async def test_on_attio_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = AttioNodeConfig(
            config=AttioWebhookTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_attio_node(config)
        payload = {"events": [{"event_type": "record.created", "id": {"record_id": "rec_x"}}]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_attio_event"
        assert result["data"]["events"][0]["event_type"] == "record.created"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.attio_node._attio_request",
            return_value={
                "status": "success",
                "data": {"id": {"webhook_id": "wh_99"}, "secret": "shh"},
            },
        ) as mock_req:
            extra = await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh_99"
        assert extra["signing_secret"] == "shh"

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.attio_node._attio_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await AttioNode._unregister_external_webhook(
                credential={"access_token": "attio_test"},
                config={"external_webhook_id": "wh_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"events":[]}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert AttioNode.verify_webhook_signature(
            body, {"attio-signature": good_sig}, {"signing_secret": secret}
        )
        assert not AttioNode.verify_webhook_signature(
            body, {"attio-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert AttioNode.verify_webhook_signature(body, {}, {})


class TestAttioTriggerEventSelectionMock:
    @pytest.mark.asyncio
    async def test_register_subscribes_to_all_events_by_default(self):
        """With event_types unset (default '*'), every supported event is subscribed."""
        from nodes.attio_node import ATTIO_TRIGGER_EVENTS

        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"webhook_id": "wh_1"}, "secret": "s"}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={},
                node_id="node-1",
            )
        subs = captured["json_body"]["data"]["subscriptions"]
        subscribed = {s["event_type"] for s in subs}
        assert subscribed == set(ATTIO_TRIGGER_EVENTS)

    @pytest.mark.asyncio
    async def test_register_subscribes_to_selected_events(self):
        """The webhook is created subscribing only to the user-selected event types."""
        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"webhook_id": "wh_2"}, "secret": "s"}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={"event_types": "record.created, task.created"},
                node_id="node-1",
            )
        subs = captured["json_body"]["data"]["subscriptions"]
        subscribed = {s["event_type"] for s in subs}
        assert subscribed == {"record.created", "task.created"}

    @pytest.mark.asyncio
    async def test_register_unknown_event_falls_back_to_all(self):
        """An unrecognized event_types value falls back to subscribing to all events."""
        from nodes.attio_node import ATTIO_TRIGGER_EVENTS

        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"webhook_id": "wh_3"}, "secret": "s"}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={"event_types": "bogus.event"},
                node_id="node-1",
            )
        subs = captured["json_body"]["data"]["subscriptions"]
        subscribed = {s["event_type"] for s in subs}
        assert subscribed == set(ATTIO_TRIGGER_EVENTS)

    def test_filter_passes_selected_event(self):
        """A delivery whose event matches the selection fires the workflow."""
        payload = {"events": [{"event_type": "record.created", "id": {"record_id": "r1"}}]}
        config = {"operation": "on_attio_event", "event_types": "record.created"}
        assert AttioNode.filter_trigger_payload(payload, config) is True

    def test_filter_skips_unselected_event(self):
        """A delivery whose event isn't selected is skipped."""
        payload = {"events": [{"event_type": "task.deleted", "id": {"task_id": "t1"}}]}
        config = {"operation": "on_attio_event", "event_types": "record.created"}
        assert AttioNode.filter_trigger_payload(payload, config) is False

    def test_filter_passes_when_any_event_in_batch_matches(self):
        """Attio batches events; the trigger fires if any event in the batch matches."""
        payload = {
            "events": [
                {"event_type": "note.created"},
                {"event_type": "record.updated"},
            ]
        }
        config = {"operation": "on_attio_event", "event_types": "record.updated, task.created"}
        assert AttioNode.filter_trigger_payload(payload, config) is True

    def test_filter_all_events_always_fires(self):
        """The default '*' selection fires for any event without filtering."""
        payload = {"events": [{"event_type": "workspace-member.created"}]}
        config = {"operation": "on_attio_event", "event_types": "*"}
        assert AttioNode.filter_trigger_payload(payload, config) is True
        # Unset event_types behaves like '*'.
        assert AttioNode.filter_trigger_payload(payload, {"operation": "on_attio_event"}) is True

    def test_filter_bare_single_event_payload(self):
        """A non-batched payload (bare event_type) is also classified correctly."""
        config = {"operation": "on_attio_event", "event_types": "list-entry.created"}
        assert (
            AttioNode.filter_trigger_payload(
                {"event_type": "list-entry.created"}, config
            )
            is True
        )
        assert (
            AttioNode.filter_trigger_payload(
                {"event_type": "list-entry.deleted"}, config
            )
            is False
        )


def create_capturing_client(captured, status_code=200, json_data=None):
    """Mock client that records the (method, url, params, json) of each request."""
    mock_response = create_mock_response(status_code, json_data if json_data is not None else _envelope({}))
    mock_client = Mock()

    async def async_request(method=None, url=None, headers=None, params=None, json=None):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return mock_response

    mock_client.request = async_request
    mock_client.__aenter__ = lambda self: _acoro(mock_client)
    mock_client.__aexit__ = lambda self, *a: _acoro(None)
    return mock_client


async def _acoro(v):
    return v


class TestAttioNewOperationsMock:
    """Verify every added operation dispatches to the correct method + endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cfg,method,path_frag", [
        (AttioGetObjectConfig(object="companies"), "GET", "/v2/objects/companies"),
        (AttioCreateObjectConfig(api_slug="p", singular_noun="P", plural_noun="Ps"), "POST", "/v2/objects"),
        (AttioUpdateObjectConfig(object="companies", plural_noun="X"), "PATCH", "/v2/objects/companies"),
        (AttioGetAttributeConfig(target="objects", identifier="companies", attribute="name"), "GET", "/attributes/name"),
        (AttioCreateAttributeConfig(target="objects", identifier="companies", title="T", api_slug="t", type="text"), "POST", "/objects/companies/attributes"),
        (AttioUpdateAttributeConfig(target="objects", identifier="companies", attribute="t", values_json='{"title":"z"}'), "PATCH", "/attributes/t"),
        (AttioListSelectOptionsConfig(target="objects", identifier="companies", attribute="s"), "GET", "/attributes/s/options"),
        (AttioCreateSelectOptionConfig(target="objects", identifier="companies", attribute="s", title="A"), "POST", "/attributes/s/options"),
        (AttioUpdateSelectOptionConfig(target="objects", identifier="companies", attribute="s", option="o1", title="B"), "PATCH", "/attributes/s/options/o1"),
        (AttioListStatusesConfig(target="objects", identifier="companies", attribute="st"), "GET", "/attributes/st/statuses"),
        (AttioCreateStatusConfig(target="objects", identifier="companies", attribute="st", title="Won"), "POST", "/attributes/st/statuses"),
        (AttioUpdateStatusConfig(target="objects", identifier="companies", attribute="st", status="s1", values_json='{"title":"z"}'), "PATCH", "/attributes/st/statuses/s1"),
        (AttioOverwriteRecordConfig(object="companies", record_id="r1", values_json='{"name":"x"}'), "PUT", "/objects/companies/records/r1"),
        (AttioListRecordEntriesConfig(object="companies", record_id="r1"), "GET", "/records/r1/entries"),
        (AttioListRecordAttributeValuesConfig(object="companies", record_id="r1", attribute="name"), "GET", "/records/r1/attributes/name/values"),
        (AttioGetListConfig(list="leads"), "GET", "/v2/lists/leads"),
        (AttioCreateListConfig(name="L", api_slug="l", parent_object="companies", workspace_access="full-access"), "POST", "/v2/lists"),
        (AttioUpdateListConfig(list="leads", name="L2"), "PATCH", "/v2/lists/leads"),
        (AttioGetListEntryConfig(list="leads", entry_id="e1"), "GET", "/lists/leads/entries/e1"),
        (AttioAssertListEntryConfig(list="leads", parent_record_id="r1", parent_object="companies"), "PUT", "/lists/leads/entries"),
        (AttioOverwriteListEntryConfig(list="leads", entry_id="e1", entry_values_json="{}"), "PUT", "/lists/leads/entries/e1"),
        (AttioListEntryAttributeValuesConfig(list="leads", entry_id="e1", attribute="stage"), "GET", "/entries/e1/attributes/stage/values"),
        (AttioGetNoteConfig(note_id="n1"), "GET", "/v2/notes/n1"),
        (AttioGetTaskConfig(task_id="t1"), "GET", "/v2/tasks/t1"),
        (AttioGetCommentConfig(comment_id="c1"), "GET", "/v2/comments/c1"),
        (AttioDeleteCommentConfig(comment_id="c1"), "DELETE", "/v2/comments/c1"),
        (AttioListThreadsConfig(record_object="companies", record_id="r1"), "GET", "/v2/threads"),
        (AttioGetThreadConfig(thread_id="th1"), "GET", "/v2/threads/th1"),
        (AttioReplyToThreadConfig(content="hi", thread_id="th1", author_workspace_member_id="wm1"), "POST", "/v2/comments"),
        (AttioCreateEntryCommentConfig(content="hi", entry_list="leads", entry_id="e1", author_workspace_member_id="wm1"), "POST", "/v2/comments"),
        (AttioGetWorkspaceMemberConfig(workspace_member_id="wm1"), "GET", "/v2/workspace_members/wm1"),
        (AttioListFilesConfig(object="companies", record_id="r1"), "GET", "/v2/files"),
        (AttioGetFileConfig(file_id="f1"), "GET", "/v2/files/f1"),
        (AttioListMeetingsConfig(), "GET", "/v2/meetings"),
        (AttioGetMeetingConfig(meeting_id="m1"), "GET", "/v2/meetings/m1"),
    ])
    async def test_operation_routing(self, api_key_credentials, cfg, method, path_frag):
        config = AttioNodeConfig(config=cfg, credentials=api_key_credentials)
        node = create_attio_node(config)
        captured = {}
        client = create_capturing_client(captured)
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success", result
        assert captured["method"] == method, f"{cfg.operation}: {captured['method']} != {method}"
        assert path_frag in captured["url"], f"{cfg.operation}: {path_frag} not in {captured['url']}"

    @pytest.mark.asyncio
    async def test_list_entry_threads(self, api_key_credentials):
        from nodes.attio_node import AttioListEntryThreadsConfig
        config = AttioNodeConfig(
            config=AttioListEntryThreadsConfig(entry_list="leads", entry_id="e1"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        captured = {}
        client = create_capturing_client(captured)
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=client):
            await node.execute({})
        assert captured["params"]["list"] == "leads"
        assert captured["params"]["entry_id"] == "e1"

    @pytest.mark.asyncio
    async def test_create_attribute_body(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioCreateAttributeConfig(
                target="objects", identifier="companies", title="Score",
                api_slug="score", type="number", is_required="true", is_unique="false",
            ),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        captured = {}
        client = create_capturing_client(captured)
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=client):
            await node.execute({})
        data = captured["json"]["data"]
        assert data["is_required"] is True
        assert data["is_unique"] is False
        assert data["type"] == "number"


class TestAttioNewEventsMock:
    def test_new_webhook_events_present(self):
        from nodes.attio_node import ATTIO_TRIGGER_EVENTS
        for evt in ("record.merged", "comment.resolved", "comment.unresolved"):
            assert evt in ATTIO_TRIGGER_EVENTS


class TestAttioDecomposedTriggersMock:
    """The single trigger is decomposed into per-category triggers; each
    registers only its category's events and fires only on those."""

    from nodes.attio_node import (
        AttioOnRecordEventConfig, AttioOnListEntryEventConfig, AttioOnNoteEventConfig,
        AttioOnTaskEventConfig, AttioOnCommentEventConfig,
    )

    CATEGORY_CASES = [
        ("on_record_event", "AttioOnRecordEventConfig", {"record.created", "record.updated", "record.deleted", "record.merged"}),
        ("on_list_entry_event", "AttioOnListEntryEventConfig", {"list-entry.created", "list-entry.updated", "list-entry.deleted"}),
        ("on_note_event", "AttioOnNoteEventConfig", {"note.created", "note.updated", "note.deleted", "note-content.updated"}),
        ("on_task_event", "AttioOnTaskEventConfig", {"task.created", "task.updated", "task.deleted"}),
        ("on_comment_event", "AttioOnCommentEventConfig", {"comment.created", "comment.deleted", "comment.resolved", "comment.unresolved"}),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation,cls_name,expected_events", CATEGORY_CASES)
    async def test_register_subscribes_to_category_events(self, operation, cls_name, expected_events):
        """Each category trigger registers exactly its category's events by default."""
        import nodes.attio_node as A
        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"webhook_id": "wh_x"}, "secret": "s"}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={"operation": operation},  # default event_types '*'
                node_id="node-1",
            )
        subs = {s["event_type"] for s in captured["json_body"]["data"]["subscriptions"]}
        assert subs == expected_events

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation,cls_name,expected_events", CATEGORY_CASES)
    async def test_execute_passthrough_per_category(self, operation, cls_name, expected_events):
        """Each trigger passes the inbound batch payload through and reports its action.

        Real Attio delivery (verified live) is a batch: {"webhook_id", "events":[...]}.
        """
        import nodes.attio_node as A
        cfg_cls = getattr(A, cls_name)
        config = AttioNodeConfig(config=cfg_cls(webhook_url="https://abc.hooks.example.test"), credentials=None)
        node = create_attio_node(config)
        one_event = sorted(expected_events)[0]
        payload = {"webhook_id": "wh_1", "events": [
            {"event_type": one_event, "id": {"record_id": "x"}, "actor": {"type": "api-token", "id": "t"}}
        ]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == operation
        assert set(result["event_types"]) == expected_events
        assert result["data"]["events"][0]["event_type"] == one_event

    @pytest.mark.asyncio
    async def test_register_narrows_within_category(self):
        """A category trigger can narrow to a subset of its own events."""
        captured = {}

        async def fake_request(token, method, endpoint, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return {"status": "success", "data": {"id": {"webhook_id": "wh"}, "secret": "s"}}

        with patch("nodes.attio_node._attio_request", side_effect=fake_request):
            await AttioNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "attio_test"},
                config={"operation": "on_record_event", "event_types": "record.created"},
                node_id="n",
            )
        subs = {s["event_type"] for s in captured["json_body"]["data"]["subscriptions"]}
        assert subs == {"record.created"}

    def test_filter_real_batch_format(self):
        """Real Attio delivery is a batch {events:[...]}; the filter classifies it."""
        cfg = {"operation": "on_record_event", "event_types": "record.created"}
        assert AttioNode.filter_trigger_payload(
            {"webhook_id": "w", "events": [{"event_type": "record.created", "id": {}}]}, cfg) is True
        assert AttioNode.filter_trigger_payload(
            {"webhook_id": "w", "events": [{"event_type": "record.deleted", "id": {}}]}, cfg) is False
        # A batch fires if ANY event matches.
        assert AttioNode.filter_trigger_payload(
            {"events": [{"event_type": "record.deleted"}, {"event_type": "record.created"}]}, cfg) is True

    def test_filter_bare_single_event_tolerated(self):
        """A bare single-event shape is also tolerated defensively."""
        cfg = {"operation": "on_record_event", "event_types": "record.created"}
        assert AttioNode.filter_trigger_payload({"event_type": "record.created", "id": {}}, cfg) is True
        assert AttioNode.filter_trigger_payload({"event_type": "record.deleted", "id": {}}, cfg) is False

    def test_filter_category_default_fires_on_its_events(self):
        """A category trigger at default '*' fires for any event in its category."""
        cfg = {"operation": "on_note_event", "event_types": "*"}
        assert AttioNode.filter_trigger_payload({"events": [{"event_type": "note-content.updated"}]}, cfg) is True
        # ...but not for an out-of-category event.
        assert AttioNode.filter_trigger_payload({"events": [{"event_type": "task.created"}]}, cfg) is False

    def test_catch_all_still_fires_on_everything(self):
        cfg = {"operation": "on_attio_event", "event_types": "*"}
        for evt in ("record.created", "list.deleted", "workspace-member.created", "call-recording.created"):
            assert AttioNode.filter_trigger_payload({"events": [{"event_type": evt}]}, cfg) is True


class TestAttioErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = AttioNodeConfig(
            config=AttioGetRecordConfig(object="companies", record_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_attio_node(config)
        mock_client = create_mock_client(404, {"message": "Record not found"})
        with patch("nodes.attio_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = AttioNodeConfig(config=AttioIdentifySelfConfig(), credentials=None)
        node = create_attio_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestAttioDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_object_options(self):
        with patch(
            "nodes.attio_node._attio_request",
            return_value={
                "status": "success",
                "data": [{"api_slug": "companies", "plural_noun": "Companies"}],
            },
        ):
            result = await AttioNode.load_field_options(
                "object", {"access_token": "attio_test"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "companies"
        assert result["options"][0]["label"] == "Companies"

    @pytest.mark.asyncio
    async def test_load_list_options(self):
        with patch(
            "nodes.attio_node._attio_request",
            return_value={
                "status": "success",
                "data": [{"api_slug": "leads", "name": "Leads"}],
            },
        ):
            result = await AttioNode.load_field_options(
                "list", {"access_token": "attio_test"}
            )
        assert result["options"][0]["value"] == "leads"
        assert result["options"][0]["label"] == "Leads"

    @pytest.mark.asyncio
    async def test_load_options_missing_token_returns_empty(self):
        result = await AttioNode.load_field_options("object", {})
        assert result == {"options": []}

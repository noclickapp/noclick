"""
Mock tests for the ClickUp REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Hierarchy: get teams, spaces, folders, lists, workspace members
- Tasks: create, get, list, update, delete, filtered team tasks
- Lists & Folders: create list, create folder
- Comments: create, get task comments
- Custom Fields: get accessible fields, set field value
- Time Tracking: create / get time entries, start / stop timer
- Goals: create, get goals
- Trigger: on_task_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Auth header branching: personal token (no prefix) vs OAuth (Bearer)
- Dynamic options: Workspace dropdown

Run: pytest nodes/tests/test_clickup_node_mock.py -q
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.clickup_node import (
    ClickUpNode,
    ClickUpNodeConfig,
    ClickUpOAuthCredential,
    ClickUpPersonalTokenCredential,
    _auth_header,
    ClickUpGetTeamsConfig,
    ClickUpGetSpacesConfig,
    ClickUpGetFoldersConfig,
    ClickUpGetListsConfig,
    ClickUpGetWorkspaceMembersConfig,
    ClickUpCreateTaskConfig,
    ClickUpGetTasksConfig,
    ClickUpGetTaskConfig,
    ClickUpUpdateTaskConfig,
    ClickUpDeleteTaskConfig,
    ClickUpGetFilteredTeamTasksConfig,
    ClickUpCreateListConfig,
    ClickUpCreateFolderConfig,
    ClickUpCreateTaskCommentConfig,
    ClickUpGetTaskCommentsConfig,
    ClickUpGetAccessibleFieldsConfig,
    ClickUpSetCustomFieldConfig,
    ClickUpCreateTimeEntryConfig,
    ClickUpGetTimeEntriesConfig,
    ClickUpStartTimerConfig,
    ClickUpStopTimerConfig,
    ClickUpCreateGoalConfig,
    ClickUpGetGoalsConfig,
    ClickUpTaskTriggerConfig,
)


@pytest.fixture
def pat_credentials():
    return ClickUpPersonalTokenCredential(personal_token="pk_12345_ABCDEF")


def create_clickup_node(config):
    return ClickUpNode(
        node_id="test-clickup-node",
        node_type="automation-clickup",
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


# ============================================================================
# Hierarchy
# ============================================================================


class TestClickUpHierarchyMock:
    @pytest.mark.asyncio
    async def test_get_teams(self, pat_credentials):
        config = ClickUpNodeConfig(config=ClickUpGetTeamsConfig(), credentials=pat_credentials)
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"teams": [{"id": "111", "name": "Acme"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_teams"
        assert result["data"]["teams"][0]["id"] == "111"

    @pytest.mark.asyncio
    async def test_get_spaces(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetSpacesConfig(team_id="111"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"spaces": [{"id": "s1", "name": "Eng"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_spaces"

    @pytest.mark.asyncio
    async def test_get_folders(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetFoldersConfig(space_id="s1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"folders": [{"id": "f1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_folders"

    @pytest.mark.asyncio
    async def test_get_lists(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetListsConfig(folder_id="f1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"lists": [{"id": "l1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_lists"

    @pytest.mark.asyncio
    async def test_get_workspace_members(self, pat_credentials):
        # ClickUp has no /team/{id}/members endpoint — members are read from the
        # GET /team payload and filtered to the selected Workspace.
        config = ClickUpNodeConfig(
            config=ClickUpGetWorkspaceMembersConfig(team_id="111"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(
            200,
            {"teams": [{"id": "111", "name": "Acme", "members": [{"user": {"id": 1}}]}]},
        )
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_workspace_members"
        assert result["data"]["members"] == [{"user": {"id": 1}}]


# ============================================================================
# Tasks
# ============================================================================


class TestClickUpTasksMock:
    @pytest.mark.asyncio
    async def test_create_task(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateTaskConfig(
                list_id="l1",
                name="Ship it",
                priority="2",
                assignees="123,456",
                due_date="1700000000000",
                tags="bug,urgent",
            ),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "task_1", "name": "Ship it"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_task"
        assert result["data"]["id"] == "task_1"

    @pytest.mark.asyncio
    async def test_get_tasks(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetTasksConfig(list_id="l1", page="0"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"tasks": [{"id": "t1"}, {"id": "t2"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_tasks"
        assert len(result["data"]["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_get_task(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetTaskConfig(task_id="task_1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "task_1", "name": "Ship it"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_task"
        assert result["data"]["id"] == "task_1"

    @pytest.mark.asyncio
    async def test_update_task(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpUpdateTaskConfig(task_id="task_1", status="done", priority="1"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "task_1", "status": {"status": "done"}})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_task"

    @pytest.mark.asyncio
    async def test_delete_task(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpDeleteTaskConfig(task_id="task_1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_task"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_filtered_team_tasks(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetFilteredTeamTasksConfig(
                team_id="111", statuses="open,in progress", assignees="123", tags="bug"
            ),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"tasks": [{"id": "t1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_filtered_team_tasks"


# ============================================================================
# Lists & Folders
# ============================================================================


class TestClickUpListsFoldersMock:
    @pytest.mark.asyncio
    async def test_create_list(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateListConfig(folder_id="f1", name="Sprint 1"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "l_new", "name": "Sprint 1"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_list"

    @pytest.mark.asyncio
    async def test_create_folder(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateFolderConfig(space_id="s1", name="Q3"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "f_new", "name": "Q3"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_folder"


# ============================================================================
# Comments
# ============================================================================


class TestClickUpCommentsMock:
    @pytest.mark.asyncio
    async def test_create_task_comment(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateTaskCommentConfig(
                task_id="task_1", comment_text="LGTM", notify_all="true"
            ),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"id": "c1"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_task_comment"

    @pytest.mark.asyncio
    async def test_get_task_comments(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetTaskCommentsConfig(task_id="task_1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"comments": [{"id": "c1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_task_comments"


# ============================================================================
# Custom Fields
# ============================================================================


class TestClickUpCustomFieldsMock:
    @pytest.mark.asyncio
    async def test_get_accessible_fields(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetAccessibleFieldsConfig(list_id="l1"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"fields": [{"id": "fld1", "name": "Severity"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_accessible_fields"

    @pytest.mark.asyncio
    async def test_set_custom_field(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpSetCustomFieldConfig(task_id="task_1", field_id="fld1", value="High"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "set_custom_field"


# ============================================================================
# Time Tracking
# ============================================================================


class TestClickUpTimeTrackingMock:
    @pytest.mark.asyncio
    async def test_create_time_entry(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateTimeEntryConfig(
                team_id="111", start="1700000000000", duration="3600000", task_id="task_1"
            ),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"data": {"id": "te1"}})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_time_entry"

    @pytest.mark.asyncio
    async def test_get_time_entries(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetTimeEntriesConfig(team_id="111"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "te1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_time_entries"

    @pytest.mark.asyncio
    async def test_start_timer(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpStartTimerConfig(team_id="111", task_id="task_1"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"data": {"id": "running"}})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "start_timer"

    @pytest.mark.asyncio
    async def test_stop_timer(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpStopTimerConfig(team_id="111"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"data": {"id": "stopped"}})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "stop_timer"


# ============================================================================
# Goals
# ============================================================================


class TestClickUpGoalsMock:
    @pytest.mark.asyncio
    async def test_create_goal(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpCreateGoalConfig(team_id="111", name="Ship v2"),
            credentials=pat_credentials,
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"goal": {"id": "g1"}})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_goal"

    @pytest.mark.asyncio
    async def test_get_goals(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetGoalsConfig(team_id="111"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(200, {"goals": [{"id": "g1"}]})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_goals"


# ============================================================================
# Auth header branching
# ============================================================================


class TestClickUpAuthHeader:
    def test_personal_token_no_prefix(self):
        assert _auth_header({"personal_token": "pk_abc"}) == "pk_abc"

    def test_oauth_bearer_prefix(self):
        assert _auth_header({"access_token": "oauth_xyz"}) == "Bearer oauth_xyz"

    def test_oauth_credential_dump_branches_to_bearer(self):
        cred = ClickUpOAuthCredential(access_token="oauth_xyz").model_dump()
        assert _auth_header(cred) == "Bearer oauth_xyz"

    def test_missing_token_raises(self):
        with pytest.raises(ValueError, match="No ClickUp token"):
            _auth_header({})


# ============================================================================
# Trigger
# ============================================================================


class TestClickUpTriggerMock:
    @pytest.mark.asyncio
    async def test_on_task_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = ClickUpNodeConfig(
            config=ClickUpTaskTriggerConfig(
                team_id="111", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_clickup_node(config)
        payload = {"event": "taskCreated", "task_id": "task_1"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_task_event"
        assert result["data"]["event"] == "taskCreated"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.clickup_node._clickup_request",
            return_value={
                "status": "success",
                "data": {"id": "wh_99", "webhook": {"id": "wh_99", "secret": "shh"}},
            },
        ) as mock_req:
            extra = await ClickUpNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"personal_token": "pk_test"},
                config={"team_id": "111"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh_99"
        assert extra["signing_secret"] == "shh"

    @pytest.mark.asyncio
    async def test_register_subscribes_to_selected_events(self):
        """The events array sent to ClickUp matches the user's event_types selection."""
        with patch(
            "nodes.clickup_node._clickup_request",
            return_value={"status": "success", "data": {"id": "wh_1", "webhook": {"id": "wh_1"}}},
        ) as mock_req:
            await ClickUpNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"personal_token": "pk_test"},
                config={"team_id": "111", "event_types": "taskCreated,taskStatusUpdated"},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        assert body["endpoint"] == "https://abc.hooks.example.test"
        assert set(body["events"]) == {"taskCreated", "taskStatusUpdated"}

    @pytest.mark.asyncio
    async def test_register_wildcard_subscribes_to_all_events(self):
        """The `*` wildcard (and the empty default) expand to every supported event."""
        from nodes.clickup_node import ALL_CLICKUP_EVENTS

        for selection in ("*", None, ""):
            cfg = {"team_id": "111"}
            if selection is not None:
                cfg["event_types"] = selection
            with patch(
                "nodes.clickup_node._clickup_request",
                return_value={"status": "success", "data": {"webhook": {"id": "wh_x"}}},
            ) as mock_req:
                await ClickUpNode._register_external_webhook(
                    webhook_url="https://abc.hooks.example.test",
                    credential={"personal_token": "pk_test"},
                    config=cfg,
                    node_id="node-1",
                )
            events = mock_req.call_args.kwargs["json_body"]["events"]
            assert set(events) == set(ALL_CLICKUP_EVENTS)
            assert "*" not in events

    def test_filter_passes_selected_event(self):
        """A delivery whose event is in the selection is processed."""
        assert ClickUpNode.filter_trigger_payload(
            {"event": "taskCreated", "task_id": "t1"},
            {"event_types": "taskCreated,taskDeleted"},
        )

    def test_filter_skips_unselected_event(self):
        """A delivery whose event is NOT in the selection is dropped."""
        assert not ClickUpNode.filter_trigger_payload(
            {"event": "taskUpdated", "task_id": "t1"},
            {"event_types": "taskCreated,taskDeleted"},
        )

    def test_filter_wildcard_passes_everything(self):
        """`*` / empty selection processes every event."""
        for selection in ("*", "", None):
            cfg = {} if selection is None else {"event_types": selection}
            assert ClickUpNode.filter_trigger_payload({"event": "spaceDeleted"}, cfg)

    def test_filter_passes_non_event_payload(self):
        """A payload without an `event` field (e.g. a ping) is not dropped."""
        assert ClickUpNode.filter_trigger_payload(
            {"webhook": {"id": "wh_1"}}, {"event_types": "taskCreated"}
        )

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_team(self):
        with pytest.raises(ValueError, match="Workspace"):
            await ClickUpNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"personal_token": "pk_test"},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.clickup_node._clickup_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await ClickUpNode._unregister_external_webhook(
                credential={"personal_token": "pk_test"},
                config={"external_webhook_id": "wh_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event":"taskCreated"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert ClickUpNode.verify_webhook_signature(
            body, {"x-signature": good_sig}, {"signing_secret": secret}
        )
        assert not ClickUpNode.verify_webhook_signature(
            body, {"x-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert ClickUpNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestClickUpErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, pat_credentials):
        config = ClickUpNodeConfig(
            config=ClickUpGetTaskConfig(task_id="missing"), credentials=pat_credentials
        )
        node = create_clickup_node(config)
        mock_client = create_mock_client(404, {"err": "Task not found", "ECODE": "ITEM_007"})
        with patch("nodes.clickup_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ClickUpNodeConfig(config=ClickUpGetTeamsConfig(), credentials=None)
        node = create_clickup_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestClickUpDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_team_options(self):
        with patch(
            "utils.credential_loader.load_credential",
            return_value={"personal_token": "pk_test"},
        ), patch(
            "nodes.clickup_node._clickup_request",
            return_value={
                "status": "success",
                "data": {"teams": [{"id": "111", "name": "Acme"}]},
            },
        ):
            result = await ClickUpNode.load_field_options(
                "team_id", "user-1", {}, credential_ids={"clickup": "cred-1"}, pool=Mock()
            )
        assert "options" in result
        assert result["options"][0]["value"] == "111"
        assert result["options"][0]["label"] == "Acme"

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await ClickUpNode.load_field_options(
            "not_a_field", "user-1", {}, credential_ids={"clickup": "cred-1"}, pool=Mock()
        )
        assert result == {"options": []}

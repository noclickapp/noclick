"""
Mock tests for the Asana REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Users: get current user, list users
- Workspaces: list workspaces, list teams, list custom fields
- Projects: list, get, create, update, delete; list project tasks/sections
- Tasks: search, get, create, update, delete, project moves, subtasks,
  followers, comments, section placement, tags
- Tags: list tags, add tag to task
- Trigger: on_resource_change passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: workspace dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.asana_node import (
    AsanaNode,
    AsanaNodeConfig,
    AsanaPATCredential,
    AsanaGetMeConfig,
    AsanaListWorkspacesConfig,
    AsanaListUsersConfig,
    AsanaListTeamsConfig,
    AsanaListCustomFieldsConfig,
    AsanaListProjectsConfig,
    AsanaGetProjectConfig,
    AsanaCreateProjectConfig,
    AsanaUpdateProjectConfig,
    AsanaDeleteProjectConfig,
    AsanaListProjectTasksConfig,
    AsanaListProjectSectionsConfig,
    AsanaSearchTasksConfig,
    AsanaGetTaskConfig,
    AsanaCreateTaskConfig,
    AsanaUpdateTaskConfig,
    AsanaDeleteTaskConfig,
    AsanaAddTaskToProjectConfig,
    AsanaRemoveTaskFromProjectConfig,
    AsanaListSubtasksConfig,
    AsanaCreateSubtaskConfig,
    AsanaAddFollowersConfig,
    AsanaRemoveFollowersConfig,
    AsanaAddCommentConfig,
    AsanaListCommentsConfig,
    AsanaAddTaskToSectionConfig,
    AsanaListTagsConfig,
    AsanaAddTagToTaskConfig,
    AsanaTriggerConfig,
)


@pytest.fixture
def credentials():
    return AsanaPATCredential(access_token="1/asana_pat_test_token")


def create_asana_node(config):
    return AsanaNode(
        node_id="test-asana-node",
        node_type="automation-asana",
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
    """Asana wraps results in {"data": ...}."""
    return {"data": data}


async def _run(node, status_code, json_data):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.asana_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Users / Workspaces
# ============================================================================


class TestAsanaUsersWorkspacesMock:
    @pytest.mark.asyncio
    async def test_get_me(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(config=AsanaGetMeConfig(), credentials=credentials)
        )
        result = await _run(node, 200, _envelope({"gid": "1", "name": "Ada"}))
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["name"] == "Ada"

    @pytest.mark.asyncio
    async def test_list_workspaces(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(config=AsanaListWorkspacesConfig(), credentials=credentials)
        )
        result = await _run(node, 200, _envelope([{"gid": "9", "name": "Acme"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_workspaces"
        assert result["data"][0]["gid"] == "9"

    @pytest.mark.asyncio
    async def test_list_users(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListUsersConfig(workspace_gid="9"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "u1", "name": "Bob"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    @pytest.mark.asyncio
    async def test_list_teams(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListTeamsConfig(workspace_gid="9"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "t1", "name": "Eng"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    async def test_list_custom_fields(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListCustomFieldsConfig(workspace_gid="9"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "cf1", "name": "Priority"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_custom_fields"


# ============================================================================
# Projects
# ============================================================================


class TestAsanaProjectsMock:
    @pytest.mark.asyncio
    async def test_list_projects(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListProjectsConfig(workspace_gid="9"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "p1", "name": "Launch"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_projects"

    @pytest.mark.asyncio
    async def test_get_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaGetProjectConfig(project_gid="p1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope({"gid": "p1", "name": "Launch"}))
        assert result["status"] == "success"
        assert result["action"] == "get_project"
        assert result["data"]["gid"] == "p1"

    @pytest.mark.asyncio
    async def test_create_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaCreateProjectConfig(workspace_gid="9", name="New Project"),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, _envelope({"gid": "p2", "name": "New Project"}))
        assert result["status"] == "success"
        assert result["action"] == "create_project"
        assert result["data"]["gid"] == "p2"

    @pytest.mark.asyncio
    async def test_update_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaUpdateProjectConfig(project_gid="p1", name="Renamed", archived="true"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({"gid": "p1", "name": "Renamed"}))
        assert result["status"] == "success"
        assert result["action"] == "update_project"

    @pytest.mark.asyncio
    async def test_delete_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaDeleteProjectConfig(project_gid="p1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "delete_project"

    @pytest.mark.asyncio
    async def test_list_project_tasks(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListProjectTasksConfig(project_gid="p1", completed_since="now"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "task1", "name": "Do thing"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_project_tasks"

    @pytest.mark.asyncio
    async def test_list_sections(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListProjectSectionsConfig(project_gid="p1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "s1", "name": "To Do"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_sections"


# ============================================================================
# Tasks
# ============================================================================


class TestAsanaTasksMock:
    @pytest.mark.asyncio
    async def test_search_tasks(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaSearchTasksConfig(workspace_gid="9", text="bug", completed="false"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "task1", "name": "Bug"}]))
        assert result["status"] == "success"
        assert result["action"] == "search_tasks"

    @pytest.mark.asyncio
    async def test_get_task(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaGetTaskConfig(task_gid="task1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope({"gid": "task1", "name": "Task"}))
        assert result["status"] == "success"
        assert result["action"] == "get_task"
        assert result["data"]["gid"] == "task1"

    @pytest.mark.asyncio
    async def test_create_task(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaCreateTaskConfig(
                    workspace_gid="9",
                    name="New Task",
                    assignee="me",
                    due_on="2026-07-01",
                    projects="p1,p2",
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, _envelope({"gid": "task9", "name": "New Task"}))
        assert result["status"] == "success"
        assert result["action"] == "create_task"
        assert result["data"]["gid"] == "task9"

    @pytest.mark.asyncio
    async def test_update_task(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaUpdateTaskConfig(task_gid="task1", name="Renamed", completed="true"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({"gid": "task1", "completed": True}))
        assert result["status"] == "success"
        assert result["action"] == "update_task"

    @pytest.mark.asyncio
    async def test_delete_task(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaDeleteTaskConfig(task_gid="task1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "delete_task"

    @pytest.mark.asyncio
    async def test_add_task_to_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaAddTaskToProjectConfig(
                    task_gid="task1", project_gid="p1", section_gid="s1"
                ),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "add_task_to_project"

    @pytest.mark.asyncio
    async def test_remove_task_from_project(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaRemoveTaskFromProjectConfig(task_gid="task1", project_gid="p1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "remove_task_from_project"

    @pytest.mark.asyncio
    async def test_list_subtasks(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListSubtasksConfig(task_gid="task1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "sub1", "name": "Subtask"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_subtasks"

    @pytest.mark.asyncio
    async def test_create_subtask(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaCreateSubtaskConfig(task_gid="task1", name="Subtask"),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, _envelope({"gid": "sub9", "name": "Subtask"}))
        assert result["status"] == "success"
        assert result["action"] == "create_subtask"
        assert result["data"]["gid"] == "sub9"

    @pytest.mark.asyncio
    async def test_add_followers(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaAddFollowersConfig(task_gid="task1", followers="u1,u2"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({"gid": "task1"}))
        assert result["status"] == "success"
        assert result["action"] == "add_followers"

    @pytest.mark.asyncio
    async def test_remove_followers(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaRemoveFollowersConfig(task_gid="task1", followers="u1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({"gid": "task1"}))
        assert result["status"] == "success"
        assert result["action"] == "remove_followers"

    @pytest.mark.asyncio
    async def test_add_task_to_section(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaAddTaskToSectionConfig(section_gid="s1", task_gid="task1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "add_task_to_section"


# ============================================================================
# Comments
# ============================================================================


class TestAsanaCommentsMock:
    @pytest.mark.asyncio
    async def test_add_comment(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaAddCommentConfig(task_gid="task1", text="Nice work"),
                credentials=credentials,
            )
        )
        result = await _run(node, 201, _envelope({"gid": "story1", "text": "Nice work"}))
        assert result["status"] == "success"
        assert result["action"] == "add_comment"
        assert result["data"]["text"] == "Nice work"

    @pytest.mark.asyncio
    async def test_list_comments(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListCommentsConfig(task_gid="task1"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "story1", "text": "Hi"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_comments"


# ============================================================================
# Tags
# ============================================================================


class TestAsanaTagsMock:
    @pytest.mark.asyncio
    async def test_list_tags(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaListTagsConfig(workspace_gid="9"), credentials=credentials
            )
        )
        result = await _run(node, 200, _envelope([{"gid": "tag1", "name": "urgent"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_tags"

    @pytest.mark.asyncio
    async def test_add_tag_to_task(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaAddTagToTaskConfig(task_gid="task1", tag_gid="tag1"),
                credentials=credentials,
            )
        )
        result = await _run(node, 200, _envelope({}))
        assert result["status"] == "success"
        assert result["action"] == "add_tag_to_task"


# ============================================================================
# Trigger
# ============================================================================


class TestAsanaTriggerMock:
    @pytest.mark.asyncio
    async def test_on_resource_change_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = AsanaNodeConfig(
            config=AsanaTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_asana_node(config)
        payload = {"events": [{"action": "changed", "resource": {"gid": "task1"}}]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_resource_change"
        assert result["data"]["events"][0]["action"] == "changed"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        extra = await AsanaNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test",
            credential={"access_token": "1/tok"},
            config={},
            node_id="node-1",
        )
        assert extra["trigger_registered"] is False

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_token(self):
        with pytest.raises(ValueError, match="access token is required"):
            await AsanaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.asana_node._asana_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await AsanaNode._unregister_external_webhook(
                credential={"access_token": "1/tok"},
                config={"external_webhook_id": "wh1"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "asana_hook_secret"
        body = b'{"events":[{"action":"changed"}]}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert AsanaNode.verify_webhook_signature(
            body, {"x-hook-signature": good_sig}, {"signing_secret": secret}
        )
        assert not AsanaNode.verify_webhook_signature(
            body, {"x-hook-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret yet (handshake not completed) -> reject unsigned requests
        assert not AsanaNode.verify_webhook_signature(body, {}, {})

    def test_handle_webhook_handshake_echoes_secret(self):
        secret = "xhs-abc123"
        result = AsanaNode.handle_webhook_handshake(b"", {"x-hook-secret": secret})
        assert result is not None
        assert result["__response_headers__"]["X-Hook-Secret"] == secret
        assert result["__signing_secret__"] == secret

    def test_handle_webhook_handshake_ignores_normal_requests(self):
        # No X-Hook-Secret → not a handshake
        result = AsanaNode.handle_webhook_handshake(b'{"events":[]}', {"x-hook-signature": "abc"})
        assert result is None


# ============================================================================
# Trigger — event-type selection
# ============================================================================


class TestAsanaTriggerEventTypesMock:
    def test_trigger_config_defaults_to_all_events(self):
        cfg = AsanaTriggerConfig(webhook_url="https://abc.hooks.example.test")
        assert cfg.event_types == "*"

    def test_build_webhook_filters_always_none(self):
        # _build_webhook_filters always returns None — Asana requires resource_type
        # in each filter entry (400 without it), so we register with no server-side
        # filters and rely on filter_trigger_payload for in-band action filtering.
        assert AsanaNode._build_webhook_filters("*") is None
        assert AsanaNode._build_webhook_filters("") is None
        assert AsanaNode._build_webhook_filters(None) is None
        assert AsanaNode._build_webhook_filters("changed,*") is None
        assert AsanaNode._build_webhook_filters("added,changed") is None
        assert AsanaNode._build_webhook_filters("deleted") is None

    @pytest.mark.asyncio
    async def test_register_external_webhook_never_sends_filters(self):
        """Registration POSTs /webhooks without a filters array regardless of
        event_types — Asana requires resource_type in each filter (400 without it);
        in-band filtering via filter_trigger_payload handles action selection."""
        captured = {}

        async def fake_request(token, method, endpoint, json_data=None, **kwargs):
            captured["method"] = method
            captured["endpoint"] = endpoint
            captured["json_data"] = json_data
            return {"status": "success", "data": {"gid": "wh_99"}}

        for event_types in ("added,changed", "*", "deleted", ""):
            captured.clear()
            with patch("nodes.asana_node._asana_request", side_effect=fake_request):
                extra = await AsanaNode._register_external_webhook(
                    webhook_url="https://abc.hooks.example.test",
                    credential={"access_token": "1/tok"},
                    config={"resource_gid": "task1", "event_types": event_types},
                    node_id="node-1",
                )
            assert captured["method"] == "POST"
            assert captured["endpoint"] == "/webhooks"
            assert captured["json_data"]["resource"] == "task1"
            assert captured["json_data"]["target"] == "https://abc.hooks.example.test"
            assert "filters" not in captured["json_data"], f"Unexpected filters for event_types={event_types!r}"
            assert extra["trigger_registered"] is True
            assert extra["external_webhook_id"] == "wh_99"

    @pytest.mark.asyncio
    async def test_register_external_webhook_without_resource_is_unarmed(self):
        """No resource_gid -> provisioned but not armed; no API call is made."""
        with patch("nodes.asana_node._asana_request") as mock_req:
            extra = await AsanaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "1/tok"},
                config={"event_types": "added"},
                node_id="node-1",
            )
        assert extra["trigger_registered"] is False
        mock_req.assert_not_called()

    def test_filter_passes_selected_event(self):
        payload = {"events": [{"action": "changed", "resource": {"gid": "t1"}}]}
        assert AsanaNode.filter_trigger_payload(
            payload, {"event_types": "changed,added"}
        )

    def test_filter_skips_non_selected_event(self):
        payload = {"events": [{"action": "deleted", "resource": {"gid": "t1"}}]}
        assert not AsanaNode.filter_trigger_payload(
            payload, {"event_types": "changed,added"}
        )

    def test_filter_passes_when_any_event_matches(self):
        payload = {
            "events": [
                {"action": "deleted", "resource": {"gid": "t1"}},
                {"action": "added", "resource": {"gid": "t2"}},
            ]
        }
        assert AsanaNode.filter_trigger_payload(payload, {"event_types": "added"})

    def test_filter_all_events_passes_everything(self):
        payload = {"events": [{"action": "undeleted", "resource": {"gid": "t1"}}]}
        # Default "*" and missing config both accept all deliveries.
        assert AsanaNode.filter_trigger_payload(payload, {"event_types": "*"})
        assert AsanaNode.filter_trigger_payload(payload, {})

    def test_filter_non_event_post_passes(self):
        # A handshake / non-event body has no "events" list — let it through so
        # the signature/handshake hooks (not this filter) decide.
        assert AsanaNode.filter_trigger_payload(
            {"foo": "bar"}, {"event_types": "added"}
        )


# ============================================================================
# Error handling
# ============================================================================


class TestAsanaErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        node = create_asana_node(
            AsanaNodeConfig(
                config=AsanaGetTaskConfig(task_gid="missing"), credentials=credentials
            )
        )
        result = await _run(
            node, 404, {"errors": [{"message": "task: Not a recognized ID"}]}
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not a recognized id" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_asana_node(
            AsanaNodeConfig(config=AsanaGetMeConfig(), credentials=None)
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestAsanaDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_workspace_options(self):
        with patch(
            "nodes.asana_node._asana_request",
            return_value={
                "status": "success",
                "data": [{"gid": "9", "name": "Acme"}, {"gid": "10", "name": "Beta"}],
            },
        ):
            result = await AsanaNode.load_field_options(
                "workspace_gid", {"access_token": "1/tok"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "9"
        assert result["options"][0]["label"] == "Acme"

    @pytest.mark.asyncio
    async def test_load_workspace_options_search(self):
        with patch(
            "nodes.asana_node._asana_request",
            return_value={
                "status": "success",
                "data": [{"gid": "9", "name": "Acme"}, {"gid": "10", "name": "Beta"}],
            },
        ):
            result = await AsanaNode.load_field_options(
                "workspace_gid", {"access_token": "1/tok"}, context={}, search="beta"
            )
        assert len(result["options"]) == 1
        assert result["options"][0]["label"] == "Beta"

    @pytest.mark.asyncio
    async def test_load_options_no_token(self):
        result = await AsanaNode.load_field_options("workspace_gid", {}, context={})
        assert result["options"] == []

"""
Mock tests for the LaunchDarkly REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Feature flags: list, get, create, toggle, delete, copy, status
- Projects: list, get, create, delete
- Environments: list, create, delete
- Segments: list, create, update, delete
- Webhooks: list, create, delete
- Members: list, invite
- Account: audit log, metrics, roles, teams, approval request, tokens
- Trigger: on_account_activity passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: project dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.launchdarkly_node import (
    LaunchDarklyNode,
    LaunchDarklyNodeConfig,
    LaunchDarklyTokenCredential,
    LaunchDarklyListFlagsConfig,
    LaunchDarklyGetFlagConfig,
    LaunchDarklyCreateFlagConfig,
    LaunchDarklyUpdateFlagConfig,
    LaunchDarklyDeleteFlagConfig,
    LaunchDarklyCopyFlagConfig,
    LaunchDarklyGetFlagStatusConfig,
    LaunchDarklyListProjectsConfig,
    LaunchDarklyGetProjectConfig,
    LaunchDarklyCreateProjectConfig,
    LaunchDarklyDeleteProjectConfig,
    LaunchDarklyListEnvironmentsConfig,
    LaunchDarklyCreateEnvironmentConfig,
    LaunchDarklyDeleteEnvironmentConfig,
    LaunchDarklyListSegmentsConfig,
    LaunchDarklyCreateSegmentConfig,
    LaunchDarklyUpdateSegmentConfig,
    LaunchDarklyDeleteSegmentConfig,
    LaunchDarklyListWebhooksConfig,
    LaunchDarklyCreateWebhookConfig,
    LaunchDarklyDeleteWebhookConfig,
    LaunchDarklyListMembersConfig,
    LaunchDarklyInviteMembersConfig,
    LaunchDarklyGetAuditLogConfig,
    LaunchDarklyListMetricsConfig,
    LaunchDarklyListRolesConfig,
    LaunchDarklyListTeamsConfig,
    LaunchDarklyCreateApprovalRequestConfig,
    LaunchDarklyListTokensConfig,
    LaunchDarklyWebhookTriggerConfig,
)


@pytest.fixture
def token_credentials():
    return LaunchDarklyTokenCredential(access_token="api-test-token-123", region="commercial")


def create_ld_node(config):
    return LaunchDarklyNode(
        node_id="test-launchdarkly-node",
        node_type="automation-launchdarkly",
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
    mock_response.content = b'{"ok": true}'
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
# Feature flags
# ============================================================================


class TestLaunchDarklyFlagsMock:
    @pytest.mark.asyncio
    async def test_list_flags(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListFlagsConfig(project_key="web", limit="10"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "flag-a"}, {"key": "flag-b"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_flags"
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_flag(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyGetFlagConfig(project_key="web", feature_flag_key="new-checkout"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"key": "new-checkout", "name": "New Checkout"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_flag"
        assert result["data"]["key"] == "new-checkout"

    @pytest.mark.asyncio
    async def test_create_flag(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateFlagConfig(
                project_key="web", name="Beta", key="beta", tags="a,b", temporary="true"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"key": "beta", "name": "Beta"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_flag"
        assert result["data"]["key"] == "beta"

    @pytest.mark.asyncio
    async def test_update_flag_toggle(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyUpdateFlagConfig(
                project_key="web",
                feature_flag_key="new-checkout",
                environment_key="production",
                turn_on="true",
                comment="Launch it",
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"key": "new-checkout"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_flag"

    @pytest.mark.asyncio
    async def test_delete_flag(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyDeleteFlagConfig(project_key="web", feature_flag_key="beta"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_flag"

    @pytest.mark.asyncio
    async def test_copy_flag(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCopyFlagConfig(
                project_key="web",
                feature_flag_key="new-checkout",
                source_environment_key="staging",
                target_environment_key="production",
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"key": "new-checkout"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "copy_flag"

    @pytest.mark.asyncio
    async def test_get_flag_status(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyGetFlagStatusConfig(
                project_key="web", environment_key="production", feature_flag_key="new-checkout"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"name": "active"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_flag_status"
        assert result["data"]["name"] == "active"


# ============================================================================
# Projects
# ============================================================================


class TestLaunchDarklyProjectsMock:
    @pytest.mark.asyncio
    async def test_list_projects(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListProjectsConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "web", "name": "Web"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_projects"

    @pytest.mark.asyncio
    async def test_get_project(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyGetProjectConfig(project_key="web"), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"key": "web", "name": "Web"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_project"
        assert result["data"]["key"] == "web"

    @pytest.mark.asyncio
    async def test_create_project(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateProjectConfig(name="Mobile", key="mobile"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"key": "mobile"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_project"

    @pytest.mark.asyncio
    async def test_delete_project(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyDeleteProjectConfig(project_key="mobile"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_project"


# ============================================================================
# Environments
# ============================================================================


class TestLaunchDarklyEnvironmentsMock:
    @pytest.mark.asyncio
    async def test_list_environments(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListEnvironmentsConfig(project_key="web"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "production"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_environments"

    @pytest.mark.asyncio
    async def test_create_environment(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateEnvironmentConfig(
                project_key="web", name="QA", key="qa", color="ff0000"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"key": "qa"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_environment"

    @pytest.mark.asyncio
    async def test_delete_environment(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyDeleteEnvironmentConfig(project_key="web", environment_key="qa"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_environment"


# ============================================================================
# Segments
# ============================================================================


class TestLaunchDarklySegmentsMock:
    @pytest.mark.asyncio
    async def test_list_segments(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListSegmentsConfig(project_key="web", environment_key="production"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "beta-users"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_segments"

    @pytest.mark.asyncio
    async def test_create_segment(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateSegmentConfig(
                project_key="web", environment_key="production", name="Beta", key="beta-users"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"key": "beta-users"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_segment"

    @pytest.mark.asyncio
    async def test_update_segment(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyUpdateSegmentConfig(
                project_key="web",
                environment_key="production",
                segment_key="beta-users",
                add_included="user-1,user-2",
                add_excluded="user-3",
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"key": "beta-users"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_segment"

    @pytest.mark.asyncio
    async def test_delete_segment(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyDeleteSegmentConfig(
                project_key="web", environment_key="production", segment_key="beta-users"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_segment"


# ============================================================================
# Webhooks (management)
# ============================================================================


class TestLaunchDarklyWebhooksMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListWebhooksConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"_id": "wh1"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateWebhookConfig(
                url="https://example.com/hook", name="My Hook", sign="true", secret="s3cr3t"
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"_id": "wh1"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyDeleteWebhookConfig(webhook_id_value="wh1"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


# ============================================================================
# Members
# ============================================================================


class TestLaunchDarklyMembersMock:
    @pytest.mark.asyncio
    async def test_list_members(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListMembersConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"email": "a@example.com"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_members"

    @pytest.mark.asyncio
    async def test_invite_members(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyInviteMembersConfig(email="new@example.com", role="writer"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"email": "new@example.com"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "invite_members"


# ============================================================================
# Account / misc
# ============================================================================


class TestLaunchDarklyAccountMock:
    @pytest.mark.asyncio
    async def test_get_audit_log(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyGetAuditLogConfig(limit="5"), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"_id": "ent1"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_audit_log"

    @pytest.mark.asyncio
    async def test_list_metrics(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListMetricsConfig(project_key="web"), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "conversion"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_metrics"

    @pytest.mark.asyncio
    async def test_list_roles(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListRolesConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "deployer"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_roles"

    @pytest.mark.asyncio
    async def test_list_teams(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListTeamsConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"key": "platform"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    async def test_create_approval_request(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyCreateApprovalRequestConfig(
                project_key="web",
                feature_flag_key="new-checkout",
                environment_key="production",
                description="Ship it",
                notify_member_ids="m1,m2",
            ),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(201, {"_id": "ar1"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_approval_request"

    @pytest.mark.asyncio
    async def test_list_tokens(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyListTokensConfig(), credentials=token_credentials
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(200, {"items": [{"_id": "tok1"}]})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_tokens"


# ============================================================================
# Trigger
# ============================================================================


class TestLaunchDarklyTriggerMock:
    @pytest.mark.asyncio
    async def test_on_account_activity_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyWebhookTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_ld_node(config)
        payload = {"kind": "flag", "accesses": [{"action": "updateOn"}]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_account_activity"
        assert result["data"]["kind"] == "flag"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"
        # default selection is all activity
        assert result["data"]["event_types"] == ["*"]

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={"status": "success", "data": {"_id": "wh99"}},
        ) as mock_req:
            extra = await LaunchDarklyNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok", "region": "commercial"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh99"
        assert extra["signing_secret"]
        # No event_types selected -> "all activity" -> no policy statements sent.
        body = mock_req.call_args.kwargs["json_body"]
        assert "statements" not in body

    @pytest.mark.asyncio
    async def test_register_external_webhook_subscribes_to_selected_events(self):
        """Selecting specific events registers a matching policy statement filter."""
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={"status": "success", "data": {"_id": "wh99"}},
        ) as mock_req:
            await LaunchDarklyNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok", "region": "commercial"},
                config={"event_types": "flag.toggled,flag.created"},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        statements = body["statements"]
        assert len(statements) == 2
        all_actions = [a for s in statements for a in s["actions"]]
        assert "updateOn" in all_actions  # flag.toggled
        assert "createFlag" in all_actions  # flag.created
        # every statement targets the flag resource
        assert all("flag" in s["resources"][0] for s in statements)

    @pytest.mark.asyncio
    async def test_register_external_webhook_all_events_no_statements(self):
        """Explicitly selecting '*' (all activity) sends no policy filter."""
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={"status": "success", "data": {"_id": "wh99"}},
        ) as mock_req:
            await LaunchDarklyNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok", "region": "commercial"},
                config={"event_types": "*"},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        assert "statements" not in body

    def test_filter_trigger_payload_all_events_pass(self):
        """The default (all activity) accepts any delivery."""
        payload = {
            "accesses": [{"action": "deleteFlag", "resource": "proj/d:env/p:flag/x"}]
        }
        assert LaunchDarklyNode.filter_trigger_payload(payload, {}) is True
        assert LaunchDarklyNode.filter_trigger_payload(payload, {"event_types": "*"}) is True

    def test_filter_trigger_payload_skips_non_selected(self):
        """A delivery whose action isn't in the selected events is skipped."""
        # Selected: flag toggled only. Incoming: a flag deletion -> skip.
        payload = {
            "kind": "flag",
            "accesses": [{"action": "deleteFlag", "resource": "proj/d:env/p:flag/x"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(payload, {"event_types": "flag.toggled"})
            is False
        )
        # A project change while only flag.toggled is selected -> skip (wrong resource kind).
        proj_payload = {
            "kind": "project",
            "accesses": [{"action": "updateProjectName", "resource": "proj/d"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(proj_payload, {"event_types": "flag.toggled"})
            is False
        )

    def test_filter_trigger_payload_flag_updated_ignores_project_event(self):
        """flag.updated must not match a project's update action (resource anchoring)."""
        proj_payload = {
            "kind": "project",
            "accesses": [{"action": "updateProjectName", "resource": "proj/d"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(proj_payload, {"event_types": "flag.updated"})
            is False
        )

    def test_filter_trigger_payload_passes_selected(self):
        """A delivery whose action matches a selected event is processed."""
        toggle_payload = {
            "kind": "flag",
            "accesses": [{"action": "updateOn", "resource": "proj/d:env/p:flag/x"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(toggle_payload, {"event_types": "flag.toggled"})
            is True
        )
        # flag.updated accepts any action on a flag resource (e.g. rule change).
        rule_payload = {
            "kind": "flag",
            "accesses": [{"action": "updateRules", "resource": "proj/d:env/p:flag/x"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(rule_payload, {"event_types": "flag.updated"})
            is True
        )
        # Multi-select: flag.toggled OR project.changed.
        proj_payload = {
            "kind": "project",
            "accesses": [{"action": "updateProjectName", "resource": "proj/d"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(
                proj_payload, {"event_types": "flag.toggled,project.changed"}
            )
            is True
        )

    def test_filter_trigger_payload_resource_hierarchy_isolation(self):
        """Parent segments in a resource path must not match a child event.

        A flag resource is ``proj/d:env/p:flag/x`` — it contains ``proj/`` and
        ``env/`` as parent segments, but the acted-on resource is the flag, so a
        project- or environment-scoped trigger must NOT fire on it.
        """
        flag_event = {
            "kind": "flag",
            "accesses": [{"action": "updateOn", "resource": "proj/d:env/p:flag/x"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(flag_event, {"event_types": "project.changed"})
            is False
        )
        assert (
            LaunchDarklyNode.filter_trigger_payload(
                flag_event, {"event_types": "environment.changed"}
            )
            is False
        )
        # An actual environment change (last segment is env) DOES fire env.changed.
        env_event = {
            "kind": "environment",
            "accesses": [{"action": "updateName", "resource": "proj/d:env/p"}],
        }
        assert (
            LaunchDarklyNode.filter_trigger_payload(
                env_event, {"event_types": "environment.changed"}
            )
            is True
        )

    def test_filter_trigger_payload_skips_when_no_accesses(self):
        """A selective trigger skips a payload that carries no access entries."""
        assert (
            LaunchDarklyNode.filter_trigger_payload(
                {"kind": "flag", "accesses": []}, {"event_types": "flag.toggled"}
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_register_external_webhook_failure_raises(self):
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={"status": "error", "error": "forbidden"},
        ):
            with pytest.raises(ValueError, match="registration failed"):
                await LaunchDarklyNode._register_external_webhook(
                    webhook_url="https://abc.hooks.example.test",
                    credential={"access_token": "tok"},
                    config={},
                    node_id="node-1",
                )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await LaunchDarklyNode._unregister_external_webhook(
                credential={"access_token": "tok", "region": "commercial"},
                config={"external_webhook_id": "wh99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"kind":"flag"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert LaunchDarklyNode.verify_webhook_signature(
            body, {"x-ld-signature": good_sig}, {"signing_secret": secret}
        )
        assert not LaunchDarklyNode.verify_webhook_signature(
            body, {"x-ld-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert LaunchDarklyNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestLaunchDarklyErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, token_credentials):
        config = LaunchDarklyNodeConfig(
            config=LaunchDarklyGetFlagConfig(project_key="web", feature_flag_key="missing"),
            credentials=token_credentials,
        )
        node = create_ld_node(config)
        mock_client = create_mock_client(404, {"message": "Flag not found", "code": "not_found"})
        with patch("nodes.launchdarkly_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = LaunchDarklyNodeConfig(config=LaunchDarklyListProjectsConfig(), credentials=None)
        node = create_ld_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestLaunchDarklyDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_project_options(self):
        # New load_field_options contract: credential arrives already decrypted.
        with patch(
            "nodes.launchdarkly_node._ld_request",
            return_value={
                "status": "success",
                "data": {"items": [{"key": "web", "name": "Web App"}]},
            },
        ):
            result = await LaunchDarklyNode.load_field_options(
                "project_key",
                {"access_token": "tok", "region": "commercial"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "web"
        assert "Web App" in result["options"][0]["label"]


class TestLaunchDarklyOperationRegistry:
    """Structural integrity of the full stable-API operation registry."""

    def test_every_config_has_a_handler_and_names_are_unique(self):
        import typing
        from nodes.launchdarkly_node import OPERATION_CONFIGS, OPERATION_HANDLERS
        cfg_ops = [typing.get_args(c.model_fields["operation"].annotation)[0] for c in OPERATION_CONFIGS]
        assert len(cfg_ops) == len(set(cfg_ops)), "duplicate operation names in registry"
        assert set(cfg_ops) == set(OPERATION_HANDLERS), "config/handler op mismatch"
        # handlers are plain async fns taking (c, token, region)
        import inspect
        for op, fn in OPERATION_HANDLERS.items():
            assert inspect.iscoroutinefunction(fn), f"{op} handler is not async"

    def test_full_union_covers_all_ops_uniquely(self):
        import typing
        from nodes.launchdarkly_node import LaunchDarklyConfig
        members = typing.get_args(typing.get_args(LaunchDarklyConfig)[0])
        ops = [typing.get_args(m.model_fields["operation"].annotation)[0] for m in members]
        assert len(ops) == len(set(ops)), "duplicate op in discriminated union"
        assert len(ops) >= 200, f"expected the full stable surface, got {len(ops)}"

    def test_config_schema_builds_for_all_ops(self):
        # get_config_schema() must succeed over the whole 200+ op union.
        schema = LaunchDarklyNode.get_config_schema()
        assert isinstance(schema, dict) and schema

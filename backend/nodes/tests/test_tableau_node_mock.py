"""
Mock tests for the Tableau REST API node.

Exercises every operation with mocked HTTP responses (no live API calls). The
node signs in first to exchange a PAT for an X-Tableau-Auth token + site LUID,
so operation tests patch `_tableau_signin` to a successful result and mock the
operation's own httpx request.

- Projects: query, create, delete
- Workbooks: query, get, refresh, delete
- Views: query, image, pdf, data
- Data Sources: query, get, refresh, delete
- Users & Groups: get users, add user, query groups, add user to group
- Webhooks: list, create, test, delete
- Trigger: on_tableau_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: sign-in error, API error, missing credentials
- Dynamic options: project + group dropdowns
"""


import pytest
from unittest.mock import Mock, patch

from nodes.tableau_node import (
    TableauNode,
    TableauNodeConfig,
    TableauPATCredential,
    TableauQueryProjectsConfig,
    TableauCreateProjectConfig,
    TableauDeleteProjectConfig,
    TableauQueryWorkbooksConfig,
    TableauGetWorkbookConfig,
    TableauRefreshWorkbookConfig,
    TableauDeleteWorkbookConfig,
    TableauQueryViewsConfig,
    TableauQueryViewImageConfig,
    TableauQueryViewPdfConfig,
    TableauQueryViewDataConfig,
    TableauQueryDataSourcesConfig,
    TableauGetDataSourceConfig,
    TableauRefreshDataSourceConfig,
    TableauDeleteDataSourceConfig,
    TableauGetUsersConfig,
    TableauAddUserConfig,
    TableauQueryGroupsConfig,
    TableauAddUserToGroupConfig,
    TableauListWebhooksConfig,
    TableauCreateWebhookConfig,
    TableauTestWebhookConfig,
    TableauDeleteWebhookConfig,
    TABLEAU_TRIGGER_CONFIGS,
    _TABLEAU_TRIGGER_EVENT_BY_OP,
)

# per-event trigger config classes, keyed by operation name
_TRIGGER_CLS = {c.model_fields["operation"].default: c for c in TABLEAU_TRIGGER_CONFIGS}


@pytest.fixture
def pat_credentials():
    return TableauPATCredential(
        server_url="https://10ax.online.tableau.com",
        site_content_url="MarketingTeam",
        pat_name="my-token",
        pat_secret="secret-value",
    )


SIGNIN_OK = {
    "status": "success",
    "token": "tableau-token-abc",
    "site_id": "site-luid-123",
    "timing_ms": {"signin": 5.0},
}


def create_tableau_node(config):
    return TableauNode(
        node_id="test-tableau-node",
        node_type="automation-tableau",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, content=b"", content_type="application/json"):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = content
    mock_response.headers = {"content-type": content_type}
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, content=b"", content_type="application/json"):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, content, content_type)
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


async def run_op(node, *, status_code=200, json_data=None, content=b"", content_type="application/json"):
    """Run an operation with a successful sign-in patched and a mocked op response."""
    mock_client = create_mock_client(status_code, json_data, content, content_type)
    with patch("nodes.tableau_node._tableau_signin", return_value=dict(SIGNIN_OK)), patch(
        "nodes.tableau_node.httpx.AsyncClient", return_value=mock_client
    ):
        return await node.execute({})


# ============================================================================
# Projects
# ============================================================================


class TestTableauProjectsMock:
    @pytest.mark.asyncio
    async def test_query_projects(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryProjectsConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"projects": {"project": [{"id": "p1", "name": "Sales"}]}})
        assert result["status"] == "success"
        assert result["action"] == "query_projects"
        assert result["data"]["projects"]["project"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_create_project(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauCreateProjectConfig(name="New Project", description="desc"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, status_code=201, json_data={"project": {"id": "p2", "name": "New Project"}})
        assert result["status"] == "success"
        assert result["action"] == "create_project"
        assert result["data"]["project"]["id"] == "p2"

    @pytest.mark.asyncio
    async def test_delete_project(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauDeleteProjectConfig(project_id="p1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_project"


# ============================================================================
# Workbooks
# ============================================================================


class TestTableauWorkbooksMock:
    @pytest.mark.asyncio
    async def test_query_workbooks(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryWorkbooksConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"workbooks": {"workbook": [{"id": "wb1"}]}})
        assert result["status"] == "success"
        assert result["action"] == "query_workbooks"

    @pytest.mark.asyncio
    async def test_get_workbook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauGetWorkbookConfig(workbook_id="wb1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, json_data={"workbook": {"id": "wb1", "name": "Dashboard"}})
        assert result["status"] == "success"
        assert result["action"] == "get_workbook"
        assert result["data"]["workbook"]["id"] == "wb1"

    @pytest.mark.asyncio
    async def test_refresh_workbook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauRefreshWorkbookConfig(workbook_id="wb1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, json_data={"job": {"id": "job1", "mode": "Asynchronous"}})
        assert result["status"] == "success"
        assert result["action"] == "refresh_workbook"
        assert result["data"]["job"]["id"] == "job1"

    @pytest.mark.asyncio
    async def test_delete_workbook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauDeleteWorkbookConfig(workbook_id="wb1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_workbook"


# ============================================================================
# Views
# ============================================================================


class TestTableauViewsMock:
    @pytest.mark.asyncio
    async def test_query_views(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryViewsConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"views": {"view": [{"id": "v1"}]}})
        assert result["status"] == "success"
        assert result["action"] == "query_views"

    @pytest.mark.asyncio
    async def test_query_view_image(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauQueryViewImageConfig(view_id="v1", high_resolution="true"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, content=b"PNGDATA", content_type="image/png")
        assert result["status"] == "success"
        assert result["action"] == "query_view_image"
        assert result["data"]["content_type"] == "image/png"
        assert result["data"]["content_length"] == len(b"PNGDATA")

    @pytest.mark.asyncio
    async def test_query_view_pdf(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauQueryViewPdfConfig(view_id="v1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, content=b"%PDF-1.4", content_type="application/pdf")
        assert result["status"] == "success"
        assert result["action"] == "query_view_pdf"
        assert result["data"]["content_type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_query_view_data(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauQueryViewDataConfig(view_id="v1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, content=b"a,b\n1,2\n", content_type="text/csv")
        assert result["status"] == "success"
        assert result["action"] == "query_view_data"
        assert result["data"]["content_type"] == "text/csv"


# ============================================================================
# Data Sources
# ============================================================================


class TestTableauDataSourcesMock:
    @pytest.mark.asyncio
    async def test_query_datasources(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryDataSourcesConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"datasources": {"datasource": [{"id": "ds1"}]}})
        assert result["status"] == "success"
        assert result["action"] == "query_datasources"

    @pytest.mark.asyncio
    async def test_get_datasource(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauGetDataSourceConfig(datasource_id="ds1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, json_data={"datasource": {"id": "ds1", "name": "Orders"}})
        assert result["status"] == "success"
        assert result["action"] == "get_datasource"
        assert result["data"]["datasource"]["id"] == "ds1"

    @pytest.mark.asyncio
    async def test_refresh_datasource(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauRefreshDataSourceConfig(datasource_id="ds1"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, json_data={"job": {"id": "job2"}})
        assert result["status"] == "success"
        assert result["action"] == "refresh_datasource"
        assert result["data"]["job"]["id"] == "job2"

    @pytest.mark.asyncio
    async def test_delete_datasource(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauDeleteDataSourceConfig(datasource_id="ds1"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_datasource"


# ============================================================================
# Users & Groups
# ============================================================================


class TestTableauUsersGroupsMock:
    @pytest.mark.asyncio
    async def test_get_users(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauGetUsersConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"users": {"user": [{"id": "u1", "name": "jsmith"}]}})
        assert result["status"] == "success"
        assert result["action"] == "get_users"

    @pytest.mark.asyncio
    async def test_add_user(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauAddUserConfig(user_name="newuser@example.com", site_role="Viewer"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, status_code=201, json_data={"user": {"id": "u2"}})
        assert result["status"] == "success"
        assert result["action"] == "add_user"
        assert result["data"]["user"]["id"] == "u2"

    @pytest.mark.asyncio
    async def test_query_groups(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryGroupsConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"groups": {"group": [{"id": "g1", "name": "Admins"}]}})
        assert result["status"] == "success"
        assert result["action"] == "query_groups"

    @pytest.mark.asyncio
    async def test_add_user_to_group(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauAddUserToGroupConfig(group_id="g1", user_id="u1"),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, json_data={"user": {"id": "u1"}})
        assert result["status"] == "success"
        assert result["action"] == "add_user_to_group"


# ============================================================================
# Webhooks (management)
# ============================================================================


class TestTableauWebhooksMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(config=TableauListWebhooksConfig(), credentials=pat_credentials)
        )
        result = await run_op(node, json_data={"webhooks": {"webhook": [{"id": "wh1"}]}})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauCreateWebhookConfig(
                    name="My hook",
                    destination_url="https://example.com/hook",
                    event="WorkbookRefreshFailed",
                ),
                credentials=pat_credentials,
            )
        )
        result = await run_op(node, status_code=201, json_data={"webhook": {"id": "wh2"}})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["webhook"]["id"] == "wh2"

    @pytest.mark.asyncio
    async def test_test_webhook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauTestWebhookConfig(webhook_id="wh1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, json_data={"webhookTestResult": {"status": 200}})
        assert result["status"] == "success"
        assert result["action"] == "test_webhook"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauDeleteWebhookConfig(webhook_id="wh1"), credentials=pat_credentials
            )
        )
        result = await run_op(node, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


# ============================================================================
# Trigger
# ============================================================================


class TestTableauTriggerMock:
    @pytest.mark.asyncio
    async def test_per_event_trigger_passthrough(self):
        """Each per-event trigger passes the inbound payload through, tagged with its event."""
        cls = _TRIGGER_CLS["on_workbook_refresh_failed"]
        config = TableauNodeConfig(
            config=cls(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_tableau_node(config)
        payload = {"event_type": "WorkbookRefreshFailed", "resource_luid": "wb1"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_workbook_refresh_failed"
        assert result["data"]["resource_luid"] == "wb1"
        assert result["data"]["event"] == "WorkbookRefreshFailed"

    def test_trigger_count_and_uniqueness(self):
        """One trigger op per event, all discoverable, all marked as triggers."""
        assert len(TABLEAU_TRIGGER_CONFIGS) == len(_TABLEAU_TRIGGER_EVENT_BY_OP)
        assert len(TABLEAU_TRIGGER_CONFIGS) == 20  # live-validated: Tableau rejects SiteCreated/SiteUpdated
        for c in TABLEAU_TRIGGER_CONFIGS:
            op = c.model_fields["operation"].default
            extra = c.model_fields["operation"].json_schema_extra
            assert extra.get("x-is-trigger") is True
            assert op in _TABLEAU_TRIGGER_EVENT_BY_OP
            assert c.model_config.get("json_schema_extra", {}).get("x-requires-webhook") is True

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        credential = {
            "server_url": "https://10ax.online.tableau.com",
            "site_content_url": "MarketingTeam",
            "pat_name": "tok",
            "pat_secret": "sec",
        }
        with patch(
            "nodes.tableau_node._tableau_signin", return_value=dict(SIGNIN_OK)
        ), patch(
            "nodes.tableau_node._tableau_request",
            return_value={"status": "success", "data": {"webhook": {"id": "wh-ext"}}},
        ) as mock_req:
            extra = await TableauNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential=credential,
                config={"event": "WorkbookRefreshFailed"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh-ext"
        # Tableau doesn't sign webhooks, so no signing secret is stored.
        assert "signing_secret" not in extra

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        credential = {
            "server_url": "https://10ax.online.tableau.com",
            "site_content_url": "MarketingTeam",
            "pat_name": "tok",
            "pat_secret": "sec",
        }
        with patch(
            "nodes.tableau_node._tableau_signin", return_value=dict(SIGNIN_OK)
        ), patch(
            "nodes.tableau_node._tableau_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await TableauNode._unregister_external_webhook(
                credential=credential,
                config={"external_webhook_id": "wh-ext"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        # Tableau does not sign webhook deliveries — the unguessable per-node URL
        # is the secret, so any delivery reaching the trigger URL is accepted.
        body = b'{"event_type":"WorkbookRefreshFailed"}'
        assert TableauNode.verify_webhook_signature(body, {}, {})
        assert TableauNode.verify_webhook_signature(body, {"x-anything": "x"}, {"external_webhook_id": "wh"})


# ============================================================================
# Error handling
# ============================================================================


class TestTableauErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_signin_error(self, pat_credentials):
        """A failed sign-in surfaces as an error result without running the op."""
        node = create_tableau_node(
            TableauNodeConfig(config=TableauQueryProjectsConfig(), credentials=pat_credentials)
        )
        signin_err = {
            "status": "error",
            "action": "signin",
            "error": "Invalid personal access token",
            "status_code": 401,
            "timing_ms": {"api_request": 5.0},
        }
        with patch("nodes.tableau_node._tableau_signin", return_value=signin_err):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "token" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_api_error(self, pat_credentials):
        node = create_tableau_node(
            TableauNodeConfig(
                config=TableauGetWorkbookConfig(workbook_id="missing"), credentials=pat_credentials
            )
        )
        result = await run_op(
            node, status_code=404, json_data={"error": {"detail": "Workbook not found"}}
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = TableauNodeConfig(config=TableauQueryProjectsConfig(), credentials=None)
        node = create_tableau_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestTableauDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_project_options(self):
        credential = {
            "server_url": "https://10ax.online.tableau.com",
            "site_content_url": "MarketingTeam",
            "pat_name": "tok",
            "pat_secret": "sec",
        }
        with patch(
            "nodes.tableau_node._tableau_signin", return_value=dict(SIGNIN_OK)
        ), patch(
            "nodes.tableau_node._tableau_request",
            return_value={
                "status": "success",
                "data": {"projects": {"project": [{"id": "p1", "name": "Sales"}]}},
            },
        ):
            # New load_field_options contract: credential arrives already decrypted.
            result = await TableauNode.load_field_options("project_id", credential)
        assert result["options"][0]["value"] == "p1"
        assert result["options"][0]["label"] == "Sales"

    @pytest.mark.asyncio
    async def test_load_group_options(self):
        credential = {
            "server_url": "https://10ax.online.tableau.com",
            "site_content_url": "MarketingTeam",
            "pat_name": "tok",
            "pat_secret": "sec",
        }
        with patch(
            "nodes.tableau_node._tableau_signin", return_value=dict(SIGNIN_OK)
        ), patch(
            "nodes.tableau_node._tableau_request",
            return_value={
                "status": "success",
                "data": {"groups": {"group": [{"id": "g1", "name": "Admins"}]}},
            },
        ):
            result = await TableauNode.load_field_options("group_id", credential)
        assert result["options"][0]["value"] == "g1"
        assert result["options"][0]["label"] == "Admins"


class TestTableauOperationRegistry:
    """Structural integrity of the full REST-API operation registry."""

    def test_every_config_has_a_handler_and_names_unique(self):
        from nodes.tableau_node import OPERATION_CONFIGS, OPERATION_HANDLERS
        import inspect
        cfg_ops = [c.model_fields["operation"].default for c in OPERATION_CONFIGS]
        assert len(cfg_ops) == len(set(cfg_ops)), "duplicate operation in registry configs"
        assert set(cfg_ops) == set(OPERATION_HANDLERS), "config/handler op mismatch"
        for op, fn in OPERATION_HANDLERS.items():
            assert inspect.iscoroutinefunction(fn), f"{op} handler is not async"

    def test_full_union_unique_and_large(self):
        import typing
        from nodes.tableau_node import TableauConfig
        members = typing.get_args(typing.get_args(TableauConfig)[0])
        ops = [m.model_fields["operation"].default for m in members]
        assert len(ops) == len(set(ops)), "duplicate op in discriminated union"
        assert len(ops) >= 300, f"expected the full REST surface, got {len(ops)}"

    def test_config_schema_builds(self):
        assert isinstance(TableauNode.get_config_schema(), dict)

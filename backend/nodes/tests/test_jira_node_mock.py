"""Mock tests for Jira node - APIs that can't be integration tested.

This file contains mock tests ONLY for operations that fail or can't be
integrated due to reasons beyond our control:
1. Projects - API token doesn't have permission to see projects
2. Boards/Sprints - Requires Jira Software license (401)
3. Workflows - Requires admin permissions (401)
"""
import httpx
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from nodes.jira_node import (
    JiraNode,
    JiraNodeFullConfig,
    JiraAPITokenCredential,
    JiraOAuthCredential,
    JiraListProjectsConfig,
    JiraGetProjectConfig,
    JiraGetAllBoardsConfig,
    JiraGetBoardSprintsConfig,
    JiraGetEpicIssuesConfig,
    JiraGetWorkflowConfig,
    JiraGetWorkflowsConfig,
    JiraDownloadAttachmentConfig,
    JiraCreateIssueConfig,
    JiraCreateStatusConfig,
)


def mock_response(data: dict, status_code: int = 200):
    """Create mock httpx response."""
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


def mock_binary_response(content: bytes, content_type: str, status_code: int = 200):
    """Create mock httpx response carrying raw binary body."""
    mock = MagicMock()
    mock.content = content
    mock.headers = {"content-type": content_type}
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


def create_node(config):
    """Helper to create a JiraNode instance with test credentials."""
    credentials = JiraAPITokenCredential(
        email="test@example.com",
        api_token="fake_token",
        domain="test.atlassian.net"
    )
    node_config = JiraNodeFullConfig(config=config, credentials=credentials)
    return JiraNode("test", "automation-jira", {}, node_config, None, None, "wf")


def create_oauth_node(config, *, scope: str):
    """Helper to create a JiraNode instance with OAuth credentials."""
    credentials = JiraOAuthCredential(
        access_token="oauth-token",
        refresh_token="refresh-token",
        expires_at="2999-01-01T00:00:00+00:00",
        cloud_id="cloud-123",
        email="test@example.com",
        site_name="Test Jira",
        site_url="https://test.atlassian.net",
        scope=scope,
    )
    node_config = JiraNodeFullConfig(config=config, credentials=credentials)
    return JiraNode("test", "automation-jira", {}, node_config, None, None, "wf")


# ============================================================================
# PROJECTS - Mock tests (permission issue)
# ============================================================================

class TestProjectOperationsMock:
    """Mock tests for project operations that require special permissions."""

    @pytest.mark.asyncio
    async def test_list_projects_mock(self):
        """Test listing projects with mocked response."""
        config = JiraListProjectsConfig()
        node = create_node(config)

        mock_data = {
            "self": "https://test.atlassian.net/rest/api/3/project/search?startAt=0&maxResults=50",
            "maxResults": 50,
            "startAt": 0,
            "total": 2,
            "isLast": True,
            "values": [
                {
                    "key": "TEST",
                    "name": "Test Project",
                    "id": "10000",
                    "projectTypeKey": "software"
                },
                {
                    "key": "DEMO",
                    "name": "Demo Project",
                    "id": "10001",
                    "projectTypeKey": "business"
                }
            ]
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response(mock_data)
            )
            result = await node.execute({})

        assert isinstance(result, dict)
        assert 'values' in result
        assert len(result['values']) == 2
        assert result['values'][0]['key'] == 'TEST'
        assert result['values'][1]['key'] == 'DEMO'
        assert result['total'] == 2

    @pytest.mark.asyncio
    async def test_get_project_mock(self):
        """Test getting a single project with mocked response."""
        config = JiraGetProjectConfig(project_key="TEST")
        node = create_node(config)

        mock_data = {
            "key": "TEST",
            "name": "Test Project",
            "id": "10000",
            "description": "A test project",
            "projectTypeKey": "software",
            "lead": {
                "accountId": "123456",
                "displayName": "Test User"
            }
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response(mock_data)
            )
            result = await node.execute({})

        assert result['key'] == 'TEST'
        assert result['name'] == 'Test Project'
        assert result['id'] == '10000'


# ============================================================================
# BOARDS/SPRINTS - Mock tests (Jira Software license required)
# ============================================================================

class TestBoardOperationsMock:
    """Mock tests for board operations that require Jira Software license."""

    @pytest.mark.asyncio
    async def test_get_all_boards_mock(self):
        """Test getting all boards with mocked response."""
        config = JiraGetAllBoardsConfig()
        node = create_node(config)

        mock_data = {
            "maxResults": 50,
            "startAt": 0,
            "total": 2,
            "isLast": True,
            "values": [
                {
                    "id": 1,
                    "name": "Test Board",
                    "type": "scrum",
                    "self": "https://test.atlassian.net/rest/agile/1.0/board/1"
                },
                {
                    "id": 2,
                    "name": "Kanban Board",
                    "type": "kanban",
                    "self": "https://test.atlassian.net/rest/agile/1.0/board/2"
                }
            ]
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response(mock_data)
            )
            result = await node.execute({})

        assert isinstance(result, dict)
        assert 'values' in result
        assert len(result['values']) == 2
        assert result['values'][0]['type'] == 'scrum'
        assert result['values'][1]['type'] == 'kanban'

    @pytest.mark.asyncio
    async def test_get_all_boards_oauth_missing_agile_scopes_requires_reconnect(self):
        """OAuth credentials without Jira Software scopes should fail before HTTP."""
        config = JiraGetAllBoardsConfig()
        node = create_oauth_node(
            config,
            scope="read:jira-work write:jira-work read:jira-user manage:jira-project offline_access",
        )

        with patch('httpx.AsyncClient') as mock_client:
            with pytest.raises(ValueError) as excinfo:
                await node.execute({})

        # The pre-flight names the Agile scopes JIRA_SCOPES requires for
        # list_boards and tells the user how to get them.
        message = str(excinfo.value)
        assert "read:board-scope:jira-software" in message
        assert "read:project:jira" in message
        assert "Reconnect the Jira account" in message
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_pre_flight_covers_classic_scopes_not_just_agile(self):
        """The pre-flight reads JIRA_SCOPES, so it covers every mapped operation.

        The isinstance chain it replaced only knew about the Agile config
        classes, so a credential missing a classic scope reached Jira and came
        back with an opaque 403.
        """
        config = JiraCreateIssueConfig(
            project_key="PROJ", summary="s", issue_type="Task"
        )
        node = create_oauth_node(config, scope="read:jira-work offline_access")

        with patch('httpx.AsyncClient') as mock_client:
            with pytest.raises(ValueError, match="write:jira-work"):
                await node.execute({})

        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmapped_operation_is_not_pre_flighted(self):
        """Operations in `unmapped` fall through to Jira rather than guessing.

        `get_workflow` calls a removed endpoint Atlassian documents no scope
        for, so there is nothing to pre-flight against; guessing one would
        blame the user's credential for a gap in the table.
        """
        from nodes.scopes.jira import JIRA_SCOPES

        assert "get_workflow" in JIRA_SCOPES.unmapped
        node = create_oauth_node(
            JiraGetWorkflowConfig(workflow_name="Default"),
            scope="read:jira-work offline_access",
        )
        # No requirement entry, so the pre-flight is a no-op.
        node._ensure_operation_scopes(node.config.credentials, node.config.config)

    @pytest.mark.asyncio
    async def test_configuration_operation_pre_flights_manage_scope(self):
        """The 52 configuration operations now declare manage:jira-configuration.

        They used to sit in `unmapped` because the node never requested the
        scope; now that it does, a credential minted before the change is
        caught here instead of returning an opaque 403 from Jira.
        """
        node = create_oauth_node(
            JiraCreateStatusConfig(name="Blocked", status_category="IN_PROGRESS"),
            scope="read:jira-work offline_access",
        )

        with patch('httpx.AsyncClient') as mock_client:
            with pytest.raises(ValueError, match="manage:jira-configuration"):
                await node.execute({})

        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_board_sprints_mock(self):
        """Test getting board sprints with mocked response."""
        config = JiraGetBoardSprintsConfig(board_id="1")
        node = create_node(config)

        mock_data = {
            "maxResults": 50,
            "startAt": 0,
            "isLast": True,
            "values": [
                {
                    "id": 1,
                    "name": "Sprint 1",
                    "state": "active",
                    "startDate": "2024-01-01T00:00:00.000Z",
                    "endDate": "2024-01-14T23:59:59.999Z",
                    "originBoardId": 1
                },
                {
                    "id": 2,
                    "name": "Sprint 2",
                    "state": "future",
                    "originBoardId": 1
                }
            ]
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response(mock_data)
            )
            result = await node.execute({})

        assert isinstance(result, dict)
        assert 'values' in result
        assert len(result['values']) == 2
        assert result['values'][0]['state'] == 'active'
        assert result['values'][1]['state'] == 'future'


class TestEpicOperationsMock:
    """Mock tests for epic operations that require Jira Software license."""

    @pytest.mark.asyncio
    async def test_get_epic_issues_uses_pagination_params(self):
        """Test listing epic issues sends maxResults and startAt."""
        config = JiraGetEpicIssuesConfig(
            epic_id_or_key="EPIC-1",
            max_results=25,
            start_at=10,
        )
        node = create_node(config)

        mock_data = {
            "maxResults": 25,
            "startAt": 10,
            "issues": [
                {"key": "TEST-1", "fields": {"summary": "First issue"}},
                {"key": "TEST-2", "fields": {"summary": "Second issue"}},
            ],
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_get = AsyncMock(return_value=mock_response(mock_data))
            mock_client.return_value.__aenter__.return_value.get = mock_get
            result = await node.execute({})

        assert result["issues"][0]["key"] == "TEST-1"
        mock_get.assert_awaited_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"maxResults": 25, "startAt": 10}
        assert kwargs["headers"]["Authorization"].startswith("Basic ")


# ============================================================================
# WORKFLOWS - Mock tests (admin permissions required)
# ============================================================================

class TestWorkflowOperationsMock:
    """Mock tests for workflow operations that require admin permissions."""

    @pytest.mark.asyncio
    async def test_get_workflows_mock(self):
        """Test getting workflows with mocked response."""
        config = JiraGetWorkflowsConfig()
        node = create_node(config)

        mock_data = {
            "maxResults": 50,
            "startAt": 0,
            "total": 2,
            "isLast": True,
            "values": [
                {
                    "id": {
                        "name": "Software Simplified Workflow",
                        "entityId": "workflow-1"
                    },
                    "description": "Default workflow for software projects",
                    "transitions": [
                        {"id": "11", "name": "To Do"},
                        {"id": "21", "name": "In Progress"},
                        {"id": "31", "name": "Done"}
                    ]
                },
                {
                    "id": {
                        "name": "Classic Default Workflow",
                        "entityId": "workflow-2"
                    },
                    "description": "Classic Jira workflow",
                    "transitions": [
                        {"id": "1", "name": "Open"},
                        {"id": "4", "name": "Resolved"},
                        {"id": "5", "name": "Closed"}
                    ]
                }
            ]
        }

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response(mock_data)
            )
            result = await node.execute({})

        assert isinstance(result, dict)
        assert 'values' in result
        assert len(result['values']) == 2
        assert result['values'][0]['id']['name'] == 'Software Simplified Workflow'
        assert result['values'][1]['id']['name'] == 'Classic Default Workflow'
        assert len(result['values'][0]['transitions']) == 3


# ============================================================================
# ATTACHMENTS - Mock tests (binary download -> stored file reference)
# ============================================================================

class TestAttachmentOperationsMock:
    """Mock tests for binary attachment download."""

    @pytest.mark.asyncio
    async def test_download_attachment_resolves_to_file_reference(self):
        """Binary attachment is stored via R2 and resolved to {url, ...}."""
        config = JiraDownloadAttachmentConfig(
            attachment_url="https://test.atlassian.net/rest/api/3/attachment/content/10001/report.pdf"
        )
        credentials = JiraAPITokenCredential(
            email="test@example.com",
            api_token="fake_token",
            domain="test.atlassian.net",
        )
        node_config = JiraNodeFullConfig(config=config, credentials=credentials)
        # workflow context (user_id + workflow_id) forces the R2 store path
        node = JiraNode(
            "test", "automation-jira", {}, node_config, None, None, "wf", "user-1"
        )

        body = b"%PDF-1.4 fake pdf bytes"

        with patch('httpx.AsyncClient') as mock_client, patch(
            'nodes.core.binary_output.create_resource_from_bytes',
            new=AsyncMock(return_value={
                "download_url": "https://r2.example/report.pdf",
                "mime_type": "application/pdf",
                "name": "report.pdf",
                "size_bytes": len(body),
            }),
        ) as mock_store:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_binary_response(body, "application/pdf")
            )
            result = await node.run({})

        assert result["content"] == {
            "url": "https://r2.example/report.pdf",
            "mime_type": "application/pdf",
            "name": "report.pdf",
            "size_bytes": len(body),
        }
        # the raw bytes were handed to the resolver unchanged
        store_kwargs = mock_store.await_args.kwargs
        assert store_kwargs["body"] == body
        assert store_kwargs["content_type"] == "application/pdf"
        assert store_kwargs["filename"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_download_attachment_returns_binary_output_marker(self):
        """Without workflow context, execute() yields a BinaryOutput marker."""
        from nodes.core.binary_output import BinaryOutput

        config = JiraDownloadAttachmentConfig(
            attachment_url="https://test.atlassian.net/rest/api/3/attachment/content/10001/logo.png"
        )
        node = create_node(config)

        body = b"\x89PNG fake image"

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_binary_response(body, "image/png")
            )
            result = await node.execute({})

        marker = result["content"]
        assert isinstance(marker, BinaryOutput)
        assert marker.data == body
        assert marker.content_type == "image/png"
        assert marker.filename == "logo.png"

    @pytest.mark.asyncio
    async def test_download_attachment_strips_auth_before_storage_redirect(self):
        """Jira auth is used once; signed storage receives no Jira headers."""
        source = (
            "https://test.atlassian.net/rest/api/3/attachment/"
            "content/10001/report.pdf"
        )
        storage = "https://storage.googleapis.com/jira/report.pdf?signature=signed"
        node = create_node(JiraDownloadAttachmentConfig(attachment_url=source))

        first_response = httpx.Response(
            303,
            headers={"location": storage},
            request=httpx.Request("GET", source),
        )
        storage_response = httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"pdf bytes",
            request=httpx.Request("GET", storage),
        )
        first_client = MagicMock()
        first_client.get = AsyncMock(return_value=first_response)
        first_client.__aenter__ = AsyncMock(return_value=first_client)
        first_client.__aexit__ = AsyncMock(return_value=None)
        storage_client = MagicMock()
        storage_client.get = AsyncMock(return_value=storage_response)
        storage_client.__aenter__ = AsyncMock(return_value=storage_client)
        storage_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "httpx.AsyncClient",
            side_effect=[first_client, storage_client],
        ) as client_factory:
            result = await node.execute({})

        first_kwargs = first_client.get.await_args.kwargs
        assert first_kwargs["headers"]["Authorization"].startswith("Basic ")
        assert first_kwargs["follow_redirects"] is False
        storage_client.get.assert_awaited_once_with(storage)
        assert client_factory.call_args_list[1].kwargs["follow_redirects"] is True
        assert result["content"].data == b"pdf bytes"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data",
            "https://test.atlassian.net.attacker.example/steal",
            "https://attacker.example/steal",
        ],
    )
    async def test_download_attachment_never_sends_auth_off_jira_origin(self, url):
        from utils.ssrf import SSRFError

        node = create_node(JiraDownloadAttachmentConfig(attachment_url=url))
        with patch("httpx.AsyncClient") as client:
            with pytest.raises(SSRFError, match="outside"):
                await node.execute({})
        client.assert_not_called()


if __name__ == "__main__":
    print("=" * 70)
    print("JIRA MOCK TESTS - Permission-Restricted APIs")
    print("=" * 70)
    print("These tests mock APIs that can't be integration tested due to:")
    print("1. Projects - API token permission issues")
    print("2. Boards/Sprints - Jira Software license required")
    print("3. Workflows - Admin permissions required")
    print("=" * 70)
    print("\nRun with: pytest nodes/tests/test_jira_node_mock.py -v")

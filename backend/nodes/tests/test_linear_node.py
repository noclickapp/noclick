"""
Unit tests for Linear API node using mocked responses.

Tests the complete Linear automation node functionality with mocked GraphQL responses.
No real API calls are made - all responses are simulated.

This allows tests to run in CI without API keys and without creating real data.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Import the node and config classes
from nodes.linear_node import (
    GRAPHQL_QUERIES,
    LinearNode,
    LinearNodeConfig,
    LinearPATCredential,
    LinearOAuthCredential,
    # Comment operations
    LinearListCommentsConfig,
    LinearCreateCommentConfig,
    LinearUpdateCommentConfig,
    LinearDeleteCommentConfig,
    # Cycle operations
    LinearListCyclesConfig,
    LinearCreateCycleConfig,
    LinearUpdateCycleConfig,
    LinearArchiveCycleConfig,
    # Document operations
    LinearGetDocumentConfig,
    LinearListDocumentsConfig,
    LinearCreateDocumentConfig,
    LinearUpdateDocumentConfig,
    LinearDeleteDocumentConfig,
    # Issue operations
    LinearGetIssueConfig,
    LinearListIssuesConfig,
    LinearCreateIssueConfig,
    LinearUpdateIssueConfig,
    LinearDeleteIssueConfig,
    LinearSearchIssuesConfig,
    LinearArchiveIssueConfig,
    LinearUnarchiveIssueConfig,
    # Workflow state operations
    LinearListWorkflowStatesConfig,
    # Issue label operations
    LinearListIssueLabelsConfig,
    LinearCreateIssueLabelConfig,
    LinearUpdateIssueLabelConfig,
    LinearDeleteIssueLabelConfig,
    # Project operations
    LinearListProjectsConfig,
    LinearGetProjectConfig,
    LinearCreateProjectConfig,
    LinearUpdateProjectConfig,
    LinearArchiveProjectConfig,
    LinearDeleteProjectConfig,
    # Project milestone operations
    LinearListProjectMilestonesConfig,
    LinearCreateProjectMilestoneConfig,
    LinearUpdateProjectMilestoneConfig,
    LinearDeleteProjectMilestoneConfig,
    # Team operations
    LinearListTeamsConfig,
    LinearGetTeamConfig,
    # User operations
    LinearListUsersConfig,
    LinearGetUserConfig,
    LinearGetViewerConfig,
    # Attachment operations
    LinearListAttachmentsConfig,
    LinearCreateAttachmentConfig,
    LinearDeleteAttachmentConfig,
    # Issue relation operations
    LinearListIssueRelationsConfig,
    LinearCreateIssueRelationConfig,
    LinearDeleteIssueRelationConfig,
    # Webhook operations
    LinearListWebhooksConfig,
    LinearCreateWebhookConfig,
    LinearDeleteWebhookConfig,
)


# ============================================================================
# Mock Response Factory
# ============================================================================


def mock_graphql_response(data: dict):
    """Create a mock httpx response with the given GraphQL data."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": data}
    return mock_response


def mock_graphql_error(message: str):
    """Create a mock httpx response with a GraphQL error."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"errors": [{"message": message}]}
    return mock_response


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock PAT credentials."""
    return LinearPATCredential(api_key="lin_api_test_mock_key")


@pytest.fixture
def mock_oauth_credentials():
    """Create mock OAuth credentials."""
    return LinearOAuthCredential(access_token="mock_oauth_token")


def create_node(config, credentials=None) -> LinearNode:
    """Create a LinearNode instance with the given config."""
    if credentials is None:
        credentials = LinearPATCredential(api_key="lin_api_test_mock_key")
    node_config = LinearNodeConfig(config=config, credentials=credentials)
    node = LinearNode(
        node_id="test-node",
        node_type="automation-linear",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Team Operations Tests
# ============================================================================


class TestTeamOperations:
    """Test team-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_teams(self):
        """Test listing teams in the workspace."""
        config = LinearListTeamsConfig()
        node = create_node(config)

        mock_data = {
            "teams": {
                "nodes": [
                    {
                        "id": "team-1",
                        "name": "Engineering",
                        "key": "ENG",
                        "description": "Engineering team",
                    },
                    {
                        "id": "team-2",
                        "name": "Design",
                        "key": "DES",
                        "description": "Design team",
                    },
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_teams"
        assert result["status"] == "success"
        assert len(result["data"]["teams"]["nodes"]) == 2
        assert result["data"]["teams"]["nodes"][0]["name"] == "Engineering"

    @pytest.mark.asyncio
    async def test_get_team(self):
        """Test getting a specific team."""
        config = LinearGetTeamConfig(id_="team-123")
        node = create_node(config)

        mock_data = {
            "team": {
                "id": "team-123",
                "name": "Engineering",
                "key": "ENG",
                "description": "Engineering team",
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_team"
        assert result["status"] == "success"
        assert result["data"]["team"]["id"] == "team-123"


# ============================================================================
# User Operations Tests
# ============================================================================


class TestUserOperations:
    """Test user-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_users(self):
        """Test listing users in the workspace."""
        config = LinearListUsersConfig()
        node = create_node(config)

        mock_data = {
            "users": {
                "nodes": [
                    {"id": "user-1", "name": "John Doe", "email": "john@example.com"},
                    {"id": "user-2", "name": "Jane Smith", "email": "jane@example.com"},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_users"
        assert result["status"] == "success"
        assert len(result["data"]["users"]["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_get_user(self):
        """Test getting a specific user."""
        config = LinearGetUserConfig(id_="user-123")
        node = create_node(config)

        mock_data = {
            "user": {"id": "user-123", "name": "John Doe", "email": "john@example.com"}
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_user"
        assert result["status"] == "success"
        assert result["data"]["user"]["id"] == "user-123"

    @pytest.mark.asyncio
    async def test_get_viewer(self):
        """Test getting the currently authenticated user."""
        config = LinearGetViewerConfig()
        node = create_node(config)

        mock_data = {
            "viewer": {
                "id": "viewer-123",
                "name": "Current User",
                "email": "me@example.com",
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_authenticated_user"
        assert result["status"] == "success"
        assert result["data"]["viewer"]["id"] == "viewer-123"


# ============================================================================
# Issue Operations Tests
# ============================================================================


class TestIssueOperations:
    """Test issue-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_issues(self):
        """Test listing issues in the workspace."""
        config = LinearListIssuesConfig(first=10)
        node = create_node(config)

        mock_data = {
            "issues": {
                "nodes": [
                    {
                        "id": "issue-1",
                        "identifier": "ENG-1",
                        "title": "Fix bug",
                        "state": {"name": "Todo"},
                    },
                    {
                        "id": "issue-2",
                        "identifier": "ENG-2",
                        "title": "Add feature",
                        "state": {"name": "In Progress"},
                    },
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_issues"
        assert result["status"] == "success"
        assert len(result["data"]["issues"]["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_get_issue(self):
        """Test getting a specific issue."""
        config = LinearGetIssueConfig(id_="issue-123")
        node = create_node(config)

        mock_data = {
            "issue": {
                "id": "issue-123",
                "identifier": "ENG-123",
                "title": "Test Issue",
                "description": "Description",
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_issue"
        assert result["status"] == "success"
        assert result["data"]["issue"]["id"] == "issue-123"

    @pytest.mark.asyncio
    async def test_search_issues(self):
        """Test searching issues."""
        config = LinearSearchIssuesConfig(query="bug fix")
        node = create_node(config)

        mock_data = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "issue-1",
                        "identifier": "ENG-1",
                        "title": "Bug fix for login",
                    },
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "search_issues"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_workflow_states(self):
        """Test listing workflow states for a team."""
        config = LinearListWorkflowStatesConfig(teamId="team-123")
        node = create_node(config)

        mock_data = {
            "workflowStates": {
                "nodes": [
                    {"id": "state-1", "name": "Todo", "type": "unstarted"},
                    {"id": "state-2", "name": "In Progress", "type": "started"},
                    {"id": "state-3", "name": "Done", "type": "completed"},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_team_workflow_states"
        assert result["status"] == "success"
        assert len(result["data"]["workflowStates"]["nodes"]) == 3

    @pytest.mark.asyncio
    async def test_create_issue(self):
        """Test creating an issue."""
        config = LinearCreateIssueConfig(
            teamId="team-123",
            title="New Test Issue",
            description="This is a test issue",
        )
        node = create_node(config)

        mock_data = {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "new-issue-123",
                    "identifier": "ENG-999",
                    "title": "New Test Issue",
                    "url": "https://linear.app/...",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_issue"
        assert result["status"] == "success"
        assert result["data"]["issueCreate"]["success"] is True
        assert result["data"]["issueCreate"]["issue"]["title"] == "New Test Issue"

    @pytest.mark.asyncio
    async def test_update_issue(self):
        """Test updating an issue."""
        config = LinearUpdateIssueConfig(
            id_="issue-123", title="Updated Title", description="Updated description"
        )
        node = create_node(config)

        mock_data = {
            "issueUpdate": {
                "success": True,
                "issue": {"id": "issue-123", "title": "Updated Title"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_issue"
        assert result["status"] == "success"
        assert result["data"]["issueUpdate"]["success"] is True

    @pytest.mark.asyncio
    async def test_delete_issue(self):
        """Test deleting an issue."""
        config = LinearDeleteIssueConfig(id_="issue-123")
        node = create_node(config)

        mock_data = {"issueDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_issue"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_archive_issue(self):
        """Test archiving an issue."""
        config = LinearArchiveIssueConfig(id_="issue-123")
        node = create_node(config)

        mock_data = {"issueArchive": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "archive_issue"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unarchive_issue(self):
        """Test unarchiving an issue."""
        config = LinearUnarchiveIssueConfig(id_="issue-123")
        node = create_node(config)

        mock_data = {"issueUnarchive": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "unarchive_issue"
        assert result["status"] == "success"


# ============================================================================
# Comment Operations Tests
# ============================================================================


class TestCommentOperations:
    """Test comment-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments for an issue."""
        config = LinearListCommentsConfig(issueId="issue-123")
        node = create_node(config)

        mock_data = {
            "issue": {
                "comments": {
                    "nodes": [
                        {
                            "id": "comment-1",
                            "body": "First comment",
                            "user": {"name": "John"},
                        },
                        {
                            "id": "comment-2",
                            "body": "Second comment",
                            "user": {"name": "Jane"},
                        },
                    ]
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_issue_comments"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment on an issue."""
        config = LinearCreateCommentConfig(
            issueId="issue-123", body="This is a test comment"
        )
        node = create_node(config)

        mock_data = {
            "commentCreate": {
                "success": True,
                "comment": {"id": "new-comment-123", "body": "This is a test comment"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_issue_comment"
        assert result["status"] == "success"
        assert result["data"]["commentCreate"]["success"] is True

    @pytest.mark.asyncio
    async def test_update_comment(self):
        """Test updating a comment."""
        config = LinearUpdateCommentConfig(
            id_="comment-123", body="Updated comment body"
        )
        node = create_node(config)

        mock_data = {
            "commentUpdate": {
                "success": True,
                "comment": {"id": "comment-123", "body": "Updated comment body"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_issue_comment"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment."""
        config = LinearDeleteCommentConfig(id_="comment-123")
        node = create_node(config)

        mock_data = {"commentDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_issue_comment"
        assert result["status"] == "success"


# ============================================================================
# Project Operations Tests
# ============================================================================


class TestProjectOperations:
    """Test project-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_projects(self):
        """Test listing projects in the workspace."""
        config = LinearListProjectsConfig()
        node = create_node(config)

        mock_data = {
            "projects": {
                "nodes": [
                    {"id": "proj-1", "name": "Project Alpha", "state": "started"},
                    {"id": "proj-2", "name": "Project Beta", "state": "planned"},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_projects"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_project(self):
        """Test getting a specific project."""
        config = LinearGetProjectConfig(id_="proj-123")
        node = create_node(config)

        mock_data = {
            "project": {
                "id": "proj-123",
                "name": "Test Project",
                "description": "A test project",
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_project"
        assert result["status"] == "success"
        assert result["data"]["project"]["id"] == "proj-123"

    @pytest.mark.asyncio
    async def test_create_project(self):
        """Test creating a project."""
        config = LinearCreateProjectConfig(
            name="New Project",
            teamIds=["team-123"],
            description="Test project description",
        )
        node = create_node(config)

        mock_data = {
            "projectCreate": {
                "success": True,
                "project": {"id": "new-proj-123", "name": "New Project"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_project"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_project(self):
        """Test updating a project."""
        config = LinearUpdateProjectConfig(id_="proj-123", name="Updated Name")
        node = create_node(config)

        mock_data = {
            "projectUpdate": {
                "success": True,
                "project": {"id": "proj-123", "name": "Updated Name"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_project"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_archive_project(self):
        """Test archiving a project."""
        config = LinearArchiveProjectConfig(id_="proj-123")
        node = create_node(config)

        mock_data = {"projectArchive": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "archive_project"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_project(self):
        """Test deleting a project."""
        config = LinearDeleteProjectConfig(id_="proj-123")
        node = create_node(config)

        mock_data = {"projectDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_project"
        assert result["status"] == "success"


# ============================================================================
# Document Operations Tests
# ============================================================================


class TestDocumentOperations:
    """Test document-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_documents(self):
        """Test listing documents in the workspace."""
        config = LinearListDocumentsConfig()
        node = create_node(config)

        mock_data = {
            "documents": {
                "nodes": [
                    {"id": "doc-1", "title": "Document 1", "content": "Content 1"},
                    {"id": "doc-2", "title": "Document 2", "content": "Content 2"},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_documents"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_document(self):
        """Test creating a document."""
        config = LinearCreateDocumentConfig(
            title="Test Document", content="Document content", teamId="team-123"
        )
        node = create_node(config)

        mock_data = {
            "documentCreate": {
                "success": True,
                "document": {"id": "new-doc-123", "title": "Test Document"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_document"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_document(self):
        """Test getting a specific document."""
        config = LinearGetDocumentConfig(id_="doc-123")
        node = create_node(config)

        mock_data = {
            "document": {"id": "doc-123", "title": "Test Doc", "content": "Content"}
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_document"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_document(self):
        """Test updating a document."""
        config = LinearUpdateDocumentConfig(id_="doc-123", title="Updated Title")
        node = create_node(config)

        mock_data = {
            "documentUpdate": {
                "success": True,
                "document": {"id": "doc-123", "title": "Updated Title"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_document"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_document(self):
        """Test deleting a document."""
        config = LinearDeleteDocumentConfig(id_="doc-123")
        node = create_node(config)

        mock_data = {"documentDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_document"
        assert result["status"] == "success"


# ============================================================================
# Cycle Operations Tests
# ============================================================================


class TestCycleOperations:
    """Test cycle-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_cycles(self):
        """Test listing cycles for a team."""
        config = LinearListCyclesConfig(teamId="team-123")
        node = create_node(config)

        mock_data = {
            "cycles": {
                "nodes": [
                    {"id": "cycle-1", "name": "Sprint 1", "number": 1},
                    {"id": "cycle-2", "name": "Sprint 2", "number": 2},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_team_cycles"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_cycle(self):
        """Test creating a cycle."""
        config = LinearCreateCycleConfig(
            teamId="team-123",
            name="Sprint 10",
            startsAt="2024-01-01",
            endsAt="2024-01-14",
        )
        node = create_node(config)

        mock_data = {
            "cycleCreate": {
                "success": True,
                "cycle": {"id": "new-cycle-123", "name": "Sprint 10", "number": 10},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_cycle"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_cycle(self):
        """Test updating a cycle."""
        config = LinearUpdateCycleConfig(id_="cycle-123", name="Updated Sprint")
        node = create_node(config)

        mock_data = {
            "cycleUpdate": {
                "success": True,
                "cycle": {"id": "cycle-123", "name": "Updated Sprint"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_cycle"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_archive_cycle(self):
        """Test archiving a cycle."""
        config = LinearArchiveCycleConfig(id_="cycle-123")
        node = create_node(config)

        mock_data = {"cycleArchive": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "archive_cycle"
        assert result["status"] == "success"


# ============================================================================
# Issue Label Operations Tests
# ============================================================================


class TestIssueLabelOperations:
    """Test issue label-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_issue_labels(self):
        """Test listing issue labels."""
        config = LinearListIssueLabelsConfig()
        node = create_node(config)

        mock_data = {
            "issueLabels": {
                "nodes": [
                    {"id": "label-1", "name": "Bug", "color": "#ff0000"},
                    {"id": "label-2", "name": "Feature", "color": "#00ff00"},
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_issue_labels"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_issue_label(self):
        """Test creating an issue label."""
        config = LinearCreateIssueLabelConfig(
            teamId="team-123", name="Urgent", color="#ff0000"
        )
        node = create_node(config)

        mock_data = {
            "issueLabelCreate": {
                "success": True,
                "issueLabel": {
                    "id": "new-label-123",
                    "name": "Urgent",
                    "color": "#ff0000",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_issue_label"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_issue_label(self):
        """Test updating an issue label."""
        config = LinearUpdateIssueLabelConfig(
            id_="label-123", name="Critical", color="#ff0000"
        )
        node = create_node(config)

        mock_data = {
            "issueLabelUpdate": {
                "success": True,
                "issueLabel": {
                    "id": "label-123",
                    "name": "Critical",
                    "color": "#ff0000",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_issue_label"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_issue_label(self):
        """Test deleting an issue label."""
        config = LinearDeleteIssueLabelConfig(id_="label-123")
        node = create_node(config)

        mock_data = {"issueLabelDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_issue_label"
        assert result["status"] == "success"


# ============================================================================
# Attachment Operations Tests
# ============================================================================


class TestAttachmentOperations:
    """Test attachment-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_attachments(self):
        """Test listing attachments for an issue."""
        config = LinearListAttachmentsConfig(issueId="issue-123")
        node = create_node(config)

        mock_data = {
            "issue": {
                "attachments": {
                    "nodes": [
                        {
                            "id": "attach-1",
                            "title": "Screenshot",
                            "url": "https://example.com/img.png",
                        },
                    ]
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_issue_attachments"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_attachment(self):
        """Test creating an attachment."""
        config = LinearCreateAttachmentConfig(
            issueId="issue-123", url="https://example.com/file.pdf", title="Document"
        )
        node = create_node(config)

        mock_data = {
            "attachmentCreate": {
                "success": True,
                "attachment": {
                    "id": "new-attach-123",
                    "title": "Document",
                    "url": "https://example.com/file.pdf",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_issue_attachment"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_attachment(self):
        """Test deleting an attachment."""
        config = LinearDeleteAttachmentConfig(id_="attach-123")
        node = create_node(config)

        mock_data = {"attachmentDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_attachment"
        assert result["status"] == "success"


# ============================================================================
# Issue Relation Operations Tests
# ============================================================================


class TestIssueRelationOperations:
    """Test issue relation-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_issue_relations(self):
        """Test listing issue relations."""
        config = LinearListIssueRelationsConfig(issueId="issue-123")
        node = create_node(config)

        mock_data = {
            "issue": {
                "relations": {
                    "nodes": [
                        {
                            "id": "rel-1",
                            "type": "blocks",
                            "relatedIssue": {
                                "id": "issue-456",
                                "identifier": "ENG-456",
                            },
                        },
                    ]
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_issue_relations"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_issue_relation(self):
        """Test creating an issue relation."""
        config = LinearCreateIssueRelationConfig(
            issueId="issue-123", relatedIssueId="issue-456", type="blocks"
        )
        node = create_node(config)

        mock_data = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "new-rel-123", "type": "blocks"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_issue_relation"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_issue_relation(self):
        """Test deleting an issue relation."""
        config = LinearDeleteIssueRelationConfig(id_="rel-123")
        node = create_node(config)

        mock_data = {"issueRelationDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_issue_relation"
        assert result["status"] == "success"


# ============================================================================
# Project Milestone Operations Tests
# ============================================================================


class TestProjectMilestoneOperations:
    """Test project milestone-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_project_milestones(self):
        """Test listing project milestones."""
        config = LinearListProjectMilestonesConfig(projectId="proj-123")
        node = create_node(config)

        mock_data = {
            "project": {
                "projectMilestones": {
                    "nodes": [
                        {
                            "id": "ms-1",
                            "name": "Alpha Release",
                            "targetDate": "2024-03-01",
                        },
                        {
                            "id": "ms-2",
                            "name": "Beta Release",
                            "targetDate": "2024-06-01",
                        },
                    ]
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_project_milestones"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_project_milestone(self):
        """Test creating a project milestone."""
        config = LinearCreateProjectMilestoneConfig(
            projectId="proj-123", name="Launch", targetDate="2024-12-01"
        )
        node = create_node(config)

        mock_data = {
            "projectMilestoneCreate": {
                "success": True,
                "projectMilestone": {
                    "id": "new-ms-123",
                    "name": "Launch",
                    "targetDate": "2024-12-01",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_project_milestone"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_project_milestone(self):
        """Test updating a project milestone."""
        config = LinearUpdateProjectMilestoneConfig(
            id_="ms-123", name="Updated Milestone"
        )
        node = create_node(config)

        mock_data = {
            "projectMilestoneUpdate": {
                "success": True,
                "projectMilestone": {"id": "ms-123", "name": "Updated Milestone"},
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_project_milestone"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_project_milestone(self):
        """Test deleting a project milestone."""
        config = LinearDeleteProjectMilestoneConfig(id_="ms-123")
        node = create_node(config)

        mock_data = {"projectMilestoneDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_project_milestone"
        assert result["status"] == "success"


# ============================================================================
# Webhook Operations Tests
# ============================================================================


class TestWebhookOperations:
    """Test webhook-related Linear API operations."""

    @pytest.mark.asyncio
    async def test_list_webhooks(self):
        """Test listing webhooks."""
        config = LinearListWebhooksConfig()
        node = create_node(config)

        mock_data = {
            "webhooks": {
                "nodes": [
                    {
                        "id": "hook-1",
                        "label": "CI/CD",
                        "url": "https://example.com/hook",
                        "enabled": True,
                    },
                ]
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_webhooks"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_webhook(self):
        """Test creating a webhook."""
        config = LinearCreateWebhookConfig(
            url="https://example.com/webhook", label="Test Webhook"
        )
        node = create_node(config)

        mock_data = {
            "webhookCreate": {
                "success": True,
                "webhook": {
                    "id": "new-hook-123",
                    "label": "Test Webhook",
                    "url": "https://example.com/webhook",
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_webhook"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        """Test deleting a webhook."""
        config = LinearDeleteWebhookConfig(id_="hook-123")
        node = create_node(config)

        mock_data = {"webhookDelete": {"success": True}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "delete_webhook"
        assert result["status"] == "success"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for Linear API operations."""

    @pytest.mark.asyncio
    async def test_graphql_error(self):
        """Test handling of GraphQL errors."""
        config = LinearGetIssueConfig(id_="nonexistent-issue")
        node = create_node(config)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_error("Entity not found: Issue")
            result = await node.execute({})

        assert result["status"] == "error"
        assert "Entity not found" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test that missing credentials raises an error."""
        config = LinearListTeamsConfig()
        node_config = LinearNodeConfig(config=config, credentials=None)
        node = LinearNode(
            node_id="test-node",
            node_type="automation-linear",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Authentication Tests
# ============================================================================


class TestAuthentication:
    """Test authentication handling for Linear API."""

    @pytest.mark.asyncio
    async def test_pat_authentication_header(self):
        """Test that PAT authentication uses correct header format."""
        config = LinearListTeamsConfig()
        credentials = LinearPATCredential(api_key="lin_api_test_key")
        node = create_node(config, credentials)

        mock_data = {"teams": {"nodes": []}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            await node.execute({})

            # Verify the Authorization header was set correctly (no Bearer prefix for PAT)
            call_args = mock_post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "lin_api_test_key"

    @pytest.mark.asyncio
    async def test_oauth_authentication_header(self):
        """Test that OAuth authentication uses Bearer prefix."""
        config = LinearListTeamsConfig()
        credentials = LinearOAuthCredential(access_token="oauth_token_123")
        node = create_node(config, credentials)

        mock_data = {"teams": {"nodes": []}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_graphql_response(mock_data)
            await node.execute({})

            # Verify the Authorization header uses Bearer prefix for OAuth
            call_args = mock_post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer oauth_token_123"


class TestDynamicOptions:
    """Test Linear dynamic dropdown schema and option loading."""

    def test_create_issue_schema_exposes_dynamic_options(self):
        schema = LinearNode.get_config_schema()
        props = schema["$defs"]["LinearCreateIssueConfig"]["properties"]

        assert props["teamId"]["x-dynamic-options"]["field_name"] == "team_id"
        assert props["assigneeId"]["x-dynamic-options"]["field_name"] == "user_id"
        assert props["projectId"]["x-dynamic-options"]["field_name"] == "project_id"
        assert props["stateId"]["x-dynamic-options"]["depends_on"] == "teamId"
        assert props["cycleId"]["x-dynamic-options"]["depends_on"] == "teamId"

    @pytest.mark.asyncio
    async def test_load_issue_options_filters_by_team_context(self):
        mock_data = {
            "issues": {
                "nodes": [
                    {"id": "issue-1", "identifier": "ENG-1", "title": "Fix login"},
                    {"id": "issue-2", "identifier": "ENG-2", "title": "Ship API"},
                ]
            }
        }

        with patch("nodes.linear_node._linear_graphql_call", new=AsyncMock(return_value=mock_data)) as mock_call:
            result = await LinearNode.load_field_options(
                "issue_id",
                {"api_key": "lin_api_test_key"},
                context={"teamId": "team-123"},
                search="login",
            )

        assert result["next_page_token"] is None
        assert result["options"] == [{"value": "issue-1", "label": "ENG-1: Fix login"}]
        variables = mock_call.await_args.args[2]
        assert variables["filter"] == {"team": {"id": {"eq": "team-123"}}}

    @pytest.mark.asyncio
    async def test_load_state_options_resolves_team_from_selected_issue(self):
        side_effect = [
            {"issue": {"team": {"id": "team-123"}}},
            {"team": {"states": {"nodes": [{"id": "state-1", "name": "In Progress", "type": "started"}]}}},
        ]

        with patch("nodes.linear_node._linear_graphql_call", new=AsyncMock(side_effect=side_effect)) as mock_call:
            result = await LinearNode.load_field_options(
                "state_id",
                {"api_key": "lin_api_test_key"},
                context={"id": "issue-123"},
            )

        assert result["options"] == [
            {
                "value": "state-1",
                "label": "In Progress",
                "metadata": {"type": "started"},
            }
        ]
        assert mock_call.await_args_list[0].args[2] == {"id": "issue-123"}
        assert mock_call.await_args_list[1].args[2] == {"teamId": "team-123"}

    @pytest.mark.asyncio
    async def test_load_project_options_uses_minimal_dynamic_query(self):
        mock_data = {
            "projects": {
                "nodes": [
                    {
                        "id": "project-1",
                        "name": "Roadmap",
                    }
                ]
            }
        }

        with patch(
            "nodes.linear_node._linear_graphql_call",
            new=AsyncMock(return_value=mock_data),
        ) as mock_call:
            result = await LinearNode.load_field_options(
                "project_id",
                {"api_key": "lin_api_test_key"},
            )

        assert result["options"] == [{"value": "project-1", "label": "Roadmap"}]
        assert mock_call.await_args.args[1] == GRAPHQL_QUERIES["dynamic_list_projects"]
        assert mock_call.await_args.args[2] == {}

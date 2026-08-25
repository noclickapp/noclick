"""
Integration tests for Jira API node - REAL API CALLS with CRUD operations.

These tests hit the actual Jira REST API using credentials from .env.
Tests create test data, verify all operations work, and clean up afterward.

Required Environment Variables:
- ATLASSIAN_API_KEY: Your Jira API token (already in .env)
- JIRA_EMAIL: Email associated with your Atlassian account
- JIRA_DOMAIN: Your Jira domain (e.g., yourcompany.atlassian.net)

Tests are organized to:
1. Create test resources at the start
2. Test all CRUD operations
3. Clean up resources at the end
"""

import asyncio
import os
import time
import pytest
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the node and config classes
from nodes.jira_node import (
    JiraNode,
    JiraNodeFullConfig,
    JiraAPITokenCredential,
    # Issue operations
    JiraGetIssueConfig,
    JiraSearchIssuesConfig,
    JiraCreateIssueConfig,
    JiraUpdateIssueConfig,
    JiraDeleteIssueConfig,
    JiraAssignIssueConfig,
    JiraListTransitionsConfig,
    JiraTransitionIssueConfig,
    # Comment operations
    JiraGetIssueCommentsConfig,
    JiraAddCommentConfig,
    JiraUpdateCommentConfig,
    JiraDeleteCommentConfig,
    # Attachment operations
    JiraGetAttachmentsForIssueConfig,
    JiraDeleteAttachmentConfig,
    # Project operations
    JiraListProjectsConfig,
    JiraGetProjectConfig,
    # User operations
    JiraSearchUsersConfig,
    # Board operations (Agile)
    JiraGetAllBoardsConfig,
    JiraGetBoardConfig,
    # Sprint operations (Agile)
    JiraGetBoardSprintsConfig,
    # Workflow operations
    JiraGetWorkflowsConfig,
)


# ============================================================================
# Test Configuration & Fixtures
# ============================================================================

# Global test state to share created resources across tests
TEST_STATE: Dict[str, Any] = {
    'issue_key': None,
    'comment_id': None,
    'project_key': None,
}


def get_credentials() -> Optional[JiraAPITokenCredential]:
    """Get credentials from environment variables."""
    # Try PAT first, fall back to API_KEY
    api_key = os.getenv('ATLASSIAN_PAT') or os.getenv('ATLASSIAN_API_KEY')
    email = os.getenv('JIRA_EMAIL')
    domain = os.getenv('JIRA_DOMAIN')

    if not all([api_key, email, domain]):
        return None

    return JiraAPITokenCredential(
        email=email,
        api_token=api_key,
        domain=domain
    )


# Skip all tests if credentials are not available, and mark as integration to
# exclude from the default CI run (pytest.ini: -m "not integration").
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        get_credentials() is None,
        reason="Jira credentials not configured. Set ATLASSIAN_PAT (or ATLASSIAN_API_KEY), JIRA_EMAIL, and JIRA_DOMAIN in .env"
    ),
]


def create_node(config) -> JiraNode:
    """Create a JiraNode instance with real credentials."""
    credentials = get_credentials()
    if not credentials:
        pytest.skip("Jira credentials not available")

    node_config = JiraNodeFullConfig(config=config, credentials=credentials)
    node = JiraNode(
        node_id="test-node",
        node_type="automation-jira",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async session fixtures."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_project_key():
    """Get the first available project key for testing."""
    config = JiraListProjectsConfig()
    node = create_node(config)

    result = await node.execute({})

    if not result or len(result) == 0:
        pytest.skip("No Jira projects found. Create a project first.")

    project_key = result[0]['key']
    TEST_STATE['project_key'] = project_key
    print(f"\n✓ Using test project: {project_key}")
    return project_key


# ============================================================================
# Project Operations Tests
# ============================================================================

class TestProjectOperations:
    """Test project-related Jira API operations."""

    @pytest.mark.asyncio
    async def test_01_list_projects(self):
        """Test listing all accessible projects."""
        config = JiraListProjectsConfig()
        node = create_node(config)

        result = await node.execute({})

        # Verify we got paginated response
        assert isinstance(result, dict)
        assert 'values' in result
        assert len(result['values']) > 0, "No projects found in Jira instance"

        # Verify project structure
        project = result['values'][0]
        assert 'key' in project
        assert 'name' in project
        assert 'id' in project

        # Save for other tests
        TEST_STATE['project_key'] = project['key']
        print(f"✓ Found {len(result['values'])} projects, using {project['key']} for tests")

    @pytest.mark.asyncio
    async def test_02_get_project(self):
        """Test getting a specific project."""
        assert TEST_STATE['project_key'], "No project key available"

        config = JiraGetProjectConfig(project_key=TEST_STATE['project_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify project details
        assert result['key'] == TEST_STATE['project_key']
        assert 'name' in result
        assert 'projectTypeKey' in result
        print(f"✓ Retrieved project: {result['name']}")


# ============================================================================
# Issue Operations Tests (FULL CRUD)
# ============================================================================

class TestIssueOperations:
    """Test issue-related Jira API operations with full CRUD."""

    @pytest.mark.asyncio
    async def test_01_create_issue(self):
        """Test creating a new issue."""
        assert TEST_STATE['project_key'], "No project key available"

        timestamp = int(time.time())
        config = JiraCreateIssueConfig(
            project_key=TEST_STATE['project_key'],
            summary=f"[TEST] Integration Test Issue {timestamp}",
            issue_type="Task",
            description="This is a test issue created by automated tests. Safe to delete."
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify issue was created
        assert 'key' in result
        assert 'id' in result

        # Save issue key for other tests
        TEST_STATE['issue_key'] = result['key']
        print(f"✓ Created test issue: {result['key']}")

    @pytest.mark.asyncio
    async def test_02_get_issue(self):
        """Test getting a specific issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraGetIssueConfig(issue_key=TEST_STATE['issue_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify issue structure
        assert result['key'] == TEST_STATE['issue_key']
        assert 'fields' in result
        assert 'summary' in result['fields']
        assert '[TEST]' in result['fields']['summary']
        print(f"✓ Retrieved issue: {result['fields']['summary']}")

    @pytest.mark.asyncio
    async def test_03_search_issues(self):
        """Test searching for issues using JQL.

        Jira's search index is eventually consistent — a freshly created issue
        can take a few seconds to appear in JQL results even when searched by
        key. Retry with backoff up to ~15s before failing so a normal indexing
        lag doesn't block CI.
        """
        import asyncio

        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraSearchIssuesConfig(
            jql=f"key = {TEST_STATE['issue_key']}",
            max_results=10
        )
        node = create_node(config)

        result = None
        attempts = 12  # capped backoff, ~60s ceiling for Jira's eventual-consistency lag
        for attempt in range(attempts):
            result = await node.execute({})
            assert 'issues' in result and 'total' in result
            assert isinstance(result['issues'], list)
            if result['total'] > 0 and any(
                issue.get('key') == TEST_STATE['issue_key'] for issue in result['issues']
            ):
                break
            if attempt < attempts - 1:
                # 1.5, 3, 4.5, then 5s steady — sum ≈ 54s
                await asyncio.sleep(min(5.0, 1.5 * (attempt + 1)))

        assert result is not None and result['total'] > 0, (
            f"Should find the created test issue {TEST_STATE['issue_key']} "
            f"within ~60s of creation (Jira index lag exceeded)"
        )
        assert any(issue.get('key') == TEST_STATE['issue_key'] for issue in result['issues']), (
            f"Search results should include {TEST_STATE['issue_key']}"
        )
        print(f"✓ Search returned {result['total']} issue(s), including {TEST_STATE['issue_key']}")

    @pytest.mark.asyncio
    async def test_04_update_issue(self):
        """Test updating an existing issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraUpdateIssueConfig(
            issue_key=TEST_STATE['issue_key'],
            summary=f"{TEST_STATE['issue_key']} - Updated by integration tests"
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify update succeeded
        assert result.get('success') is True or 'id' in result
        print(f"✓ Updated issue: {TEST_STATE['issue_key']}")

    @pytest.mark.asyncio
    async def test_05_list_transitions(self):
        """Test getting available transitions for an issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraListTransitionsConfig(issue_key=TEST_STATE['issue_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify transitions structure
        assert 'transitions' in result
        assert isinstance(result['transitions'], list)
        print(f"✓ Found {len(result['transitions'])} available transitions")

    @pytest.mark.asyncio
    async def test_06_transition_issue(self):
        """Test transitioning an issue to a new status."""
        assert TEST_STATE['issue_key'], "No test issue available"

        # First get available transitions
        list_config = JiraListTransitionsConfig(issue_key=TEST_STATE['issue_key'])
        list_node = create_node(list_config)
        transitions = await list_node.execute({})

        # Skip if no transitions available (issue might be at final state)
        if not transitions.get('transitions') or len(transitions['transitions']) == 0:
            pytest.skip("No transitions available - issue may be at final workflow state")

        # Use the first available transition
        transition = transitions['transitions'][0]
        transition_id = transition['id']
        transition_name = transition.get('name', 'Unknown')

        config = JiraTransitionIssueConfig(
            issue_key=TEST_STATE['issue_key'],
            transition_id=transition_id
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify transition succeeded (some transitions may not return success flag)
        assert result is not None
        print(f"✓ Transitioned issue to '{transition_name}' (ID: {transition_id})")


# ============================================================================
# Comment Operations Tests (FULL CRUD)
# ============================================================================

class TestCommentOperations:
    """Test comment-related Jira API operations with full CRUD."""

    @pytest.mark.asyncio
    async def test_01_add_comment(self):
        """Test adding a comment to an issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        timestamp = int(time.time())
        config = JiraAddCommentConfig(
            issue_key=TEST_STATE['issue_key'],
            body=f"Test comment added by automated tests at {timestamp}"
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify comment was created
        assert 'id' in result
        assert 'body' in result

        # Save comment ID for other tests
        TEST_STATE['comment_id'] = result['id']
        print(f"✓ Added comment: {result['id']}")

    @pytest.mark.asyncio
    async def test_02_get_comments(self):
        """Test getting comments for an issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraGetIssueCommentsConfig(issue_key=TEST_STATE['issue_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify comments structure
        assert 'comments' in result
        assert isinstance(result['comments'], list)
        assert len(result['comments']) > 0, "Should have at least our test comment"
        print(f"✓ Found {len(result['comments'])} comments")

    @pytest.mark.asyncio
    async def test_03_update_comment(self):
        """Test updating a comment."""
        assert TEST_STATE['issue_key'], "No test issue available"
        assert TEST_STATE['comment_id'], "No test comment available"

        config = JiraUpdateCommentConfig(
            issue_key=TEST_STATE['issue_key'],
            comment_id=TEST_STATE['comment_id'],
            body="Updated comment text - modified by automated tests"
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify update succeeded
        assert 'id' in result
        # Body is returned in ADF format (Atlassian Document Format), not plain text
        assert 'body' in result
        assert isinstance(result['body'], dict)
        print(f"✓ Updated comment: {TEST_STATE['comment_id']}")

    @pytest.mark.asyncio
    async def test_04_delete_comment(self):
        """Test deleting a comment."""
        assert TEST_STATE['issue_key'], "No test issue available"
        assert TEST_STATE['comment_id'], "No test comment available"

        config = JiraDeleteCommentConfig(
            issue_key=TEST_STATE['issue_key'],
            comment_id=TEST_STATE['comment_id']
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify deletion succeeded
        assert result.get('success') is True
        print(f"✓ Deleted comment: {TEST_STATE['comment_id']}")

        # Clear comment ID
        TEST_STATE['comment_id'] = None


# ============================================================================
# User Operations Tests
# ============================================================================

class TestUserOperations:
    """Test user-related Jira API operations."""

    @pytest.mark.asyncio
    async def test_search_users(self):
        """Test searching for users."""
        config = JiraSearchUsersConfig(query="")  # Empty query returns users
        node = create_node(config)

        result = await node.execute({})

        # Verify we got a list of users
        assert isinstance(result, list)
        if len(result) > 0:
            user = result[0]
            assert 'accountId' in user
            assert 'displayName' in user
            print(f"✓ Found {len(result)} users")


# ============================================================================
# Board Operations Tests (Agile - READ ONLY)
# ============================================================================

class TestBoardOperations:
    """Test board-related Jira Agile API operations."""

    @pytest.mark.asyncio
    async def test_get_all_boards(self):
        """Test getting all boards."""
        config = JiraGetAllBoardsConfig()
        node = create_node(config)

        result = await node.execute({})

        # Verify boards structure
        assert 'values' in result
        assert isinstance(result['values'], list)

        # Save board ID if available
        if len(result['values']) > 0:
            TEST_STATE['board_id'] = result['values'][0]['id']

        print(f"✓ Found {len(result['values'])} boards")

    @pytest.mark.asyncio
    async def test_get_board_sprints(self):
        """Test getting sprints for a board."""
        if not TEST_STATE.get('board_id'):
            pytest.skip("No board available for testing")

        config = JiraGetBoardSprintsConfig(board_id=str(TEST_STATE['board_id']))
        node = create_node(config)

        result = await node.execute({})

        # Verify sprints structure
        assert 'values' in result
        assert isinstance(result['values'], list)
        print(f"✓ Found {len(result['values'])} sprints")


# ============================================================================
# Attachment Operations Tests
# ============================================================================

class TestAttachmentOperations:
    """Test attachment-related Jira API operations."""

    @pytest.mark.asyncio
    async def test_get_attachments(self):
        """Test getting attachments for an issue."""
        assert TEST_STATE['issue_key'], "No test issue available"

        config = JiraGetAttachmentsForIssueConfig(issue_key=TEST_STATE['issue_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify attachments structure (may be empty)
        assert isinstance(result, dict)
        assert 'attachments' in result
        assert isinstance(result['attachments'], list)
        print(f"✓ Found {len(result['attachments'])} attachments")


# ============================================================================
# Workflow Operations Tests
# ============================================================================

class TestWorkflowOperations:
    """Test workflow-related Jira API operations."""

    @pytest.mark.asyncio
    async def test_get_workflows(self):
        """Test getting workflows."""
        config = JiraGetWorkflowsConfig()
        node = create_node(config)

        result = await node.execute({})

        # Verify we got workflow data
        assert isinstance(result, (list, dict))
        print(f"✓ Retrieved workflows")


# ============================================================================
# Cleanup Tests (Run Last)
# ============================================================================

class TestZZCleanup:
    """Cleanup test resources. Runs last due to ZZ prefix."""

    @pytest.mark.asyncio
    async def test_delete_test_issue(self):
        """Delete the test issue created during tests."""
        if not TEST_STATE.get('issue_key'):
            pytest.skip("No test issue to clean up")

        config = JiraDeleteIssueConfig(issue_key=TEST_STATE['issue_key'])
        node = create_node(config)

        result = await node.execute({})

        # Verify deletion succeeded
        assert result.get('success') is True
        print(f"✓ Cleaned up test issue: {TEST_STATE['issue_key']}")
        TEST_STATE['issue_key'] = None


if __name__ == "__main__":
    # Print credential status
    creds = get_credentials()

    print("\n" + "="*70)
    print("JIRA INTEGRATION TEST CONFIGURATION")
    print("="*70)
    print(f"Credentials configured: {'✓ YES' if creds else '✗ NO'}")
    if creds:
        print(f"  Email: {creds.email}")
        print(f"  Domain: {creds.domain}")
        print("  API Token: configured")
    print("\nTests will CREATE and DELETE test data in your Jira instance.")
    print("All test issues are marked with [TEST] prefix for easy identification.")
    print("="*70 + "\n")

# Comprehensive Test Generation Guide

This guide ensures that **EVERY operation** in the generated node has corresponding tests.

## Test Generation Principle

**CRITICAL**: For every `{Service}{Operation}Config` class in the node, there MUST be a corresponding test method.

## Systematic Test Generation Process

### Step 1: Extract All Operations

From the node file, identify ALL config classes:

```python
# Example from github_rest_node.py - 75 operations means 75+ test methods

# Repository operations (17)
GithubGetRepositoryConfig
GithubListRepositoriesConfig
GithubListOrganizationReposConfig
GithubForkRepositoryConfig
GithubListCollaboratorsConfig
GithubCreateRepoWebhookConfig
GithubListForksConfig
GithubListContributorsConfig
GithubGetRepoLanguagesConfig
GithubGetRepoTopicsConfig
GithubSetRepoTopicsConfig
GithubListStargazersConfig
GithubStarRepositoryConfig
GithubUnstarRepositoryConfig
GithubListRepoContentsConfig
GithubCreateRepoFromTemplateConfig
GithubListUserReposConfig

# Issue operations (11)
GithubListIssuesConfig
GithubGetIssueConfig
GithubCreateIssueConfig
GithubUpdateIssueConfig
GithubListIssueCommentsConfig
GithubCreateIssueCommentConfig
GithubAddLabelsToIssueConfig
GithubCreateIssueReactionConfig
GithubListMilestonesConfig
GithubCreateMilestoneConfig
GithubListAssigneesConfig

# ... and so on for ALL operations
```

### Step 2: Generate Test Class Per Category

Create a test class for each operation category:

```python
class TestRepositoryOperations:
    """Tests for ALL repository operations."""

    # One test method per operation
    async def test_get_repository(self): ...
    async def test_list_repositories(self): ...
    async def test_list_organization_repos(self): ...
    async def test_fork_repository(self): ...
    async def test_list_collaborators(self): ...
    async def test_create_repo_webhook(self): ...
    async def test_list_forks(self): ...
    async def test_list_contributors(self): ...
    async def test_get_repo_languages(self): ...
    async def test_get_repo_topics(self): ...
    async def test_set_repo_topics(self): ...
    async def test_list_stargazers(self): ...
    async def test_star_repository(self): ...
    async def test_unstar_repository(self): ...
    async def test_list_repo_contents(self): ...
    async def test_create_repo_from_template(self): ...
    async def test_list_user_repos(self): ...


class TestIssueOperations:
    """Tests for ALL issue operations."""

    async def test_list_issues(self): ...
    async def test_get_issue(self): ...
    async def test_create_issue(self): ...
    async def test_update_issue(self): ...
    async def test_list_issue_comments(self): ...
    async def test_create_issue_comment(self): ...
    async def test_add_labels_to_issue(self): ...
    async def test_create_issue_reaction(self): ...
    async def test_list_milestones(self): ...
    async def test_create_milestone(self): ...
    async def test_list_assignees(self): ...

# ... repeat for ALL categories
```

### Step 3: Test Method Template

Each test method follows this pattern:

```python
async def test_{action_name}(self):
    """Test {action_description}."""
    # 1. Create config with appropriate test values
    config = {Service}{Operation}Config(
        # Required fields with test values
        required_field="test_value",
        # Optional fields if needed for testing
        optional_field="optional_value"
    )

    # 2. Create and execute node
    node = self.create_node(config)
    result = await node.execute({})

    # 3. Assert expected behavior
    assert result["action"] == "{action_name}"

    # For read operations - expect success
    assert result["status"] == "success"
    assert isinstance(result["data"], (list, dict))

    # For write operations - track for cleanup
    if result["status"] == "success" and result.get("data", {}).get("id"):
        self.created_resources.append(("{resource_type}", result["data"]["id"]))
```

### Step 4: Operation Type Patterns

#### Read Operations (Safe - No Cleanup Needed)

```python
async def test_list_{resources}(self):
    """Test listing {resources}."""
    config = {Service}List{Resources}Config(per_page=5)
    node = self.create_node(config)
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "list_{resources}"
    assert isinstance(result["data"], list)

async def test_get_{resource}(self):
    """Test getting a single {resource}."""
    # May need to list first to get a valid ID
    list_result = await self._get_test_{resource}_id()
    if not list_result:
        return  # Skip if no test data

    config = {Service}Get{Resource}Config({resource}_id=list_result)
    node = self.create_node(config)
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "get_{resource}"
```

#### Write Operations (Require Cleanup)

```python
async def test_create_{resource}(self):
    """Test creating a {resource}."""
    config = {Service}Create{Resource}Config(
        name=f"Test {Resource} {int(time.time())}",
        # other required fields
    )
    node = self.create_node(config)
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_{resource}"

    # CRITICAL: Track for cleanup
    if result.get("data", {}).get("id"):
        self.created_resources.append(("{resource}", result["data"]["id"]))

async def test_update_{resource}(self):
    """Test updating a {resource}."""
    # First create a resource to update
    create_result = await self._create_test_{resource}()
    if not create_result:
        return  # Skip if creation failed

    config = {Service}Update{Resource}Config(
        {resource}_id=create_result["id"],
        name=f"Updated {int(time.time())}"
    )
    node = self.create_node(config)
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "update_{resource}"

async def test_delete_{resource}(self):
    """Test deleting a {resource}."""
    # Create a resource specifically for deletion
    create_result = await self._create_test_{resource}()
    if not create_result:
        return

    config = {Service}Delete{Resource}Config({resource}_id=create_result["id"])
    node = self.create_node(config)
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "delete_{resource}"
    # No cleanup needed - we just deleted it
```

#### Action Operations (May or May Not Need Cleanup)

```python
async def test_star_repository(self):
    """Test starring a repository (action that can be undone)."""
    config = {Service}StarRepositoryConfig(owner="octocat", repo="Hello-World")
    node = self.create_node(config)
    result = await node.execute({})

    # Star might succeed or already be starred
    assert result["action"] == "star_repository"

    # Cleanup: unstar
    if result["status"] == "success":
        await self._unstar_for_cleanup("octocat", "Hello-World")

async def test_trigger_workflow(self):
    """Test triggering a workflow (no undo possible)."""
    config = {Service}TriggerWorkflowConfig(
        owner="test-owner",
        repo="test-repo",
        workflow_id="ci.yml",
        ref="main"
    )
    node = self.create_node(config)
    result = await node.execute({})

    # Just verify the action was recognized
    assert result["action"] == "trigger_workflow"
    # May fail if repo doesn't exist - that's OK for testing
```

## Complete Test File Structure

```python
#!/usr/bin/env python3
"""
Comprehensive integration tests for {SERVICE_NAME} REST API node.

Tests ALL {N} operations organized by category.
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes.{service_name}_node import (
    {ServiceName}Node,
    {ServiceName}NodeConfig,
    {ServiceName}Credential,
    # Import ALL config classes - one per operation
    {ServiceName}GetRepositoryConfig,
    {ServiceName}ListRepositoriesConfig,
    # ... ALL other configs
)


class TestRunner:
    def __init__(self, api_key: str):
        self.credentials = {ServiceName}Credential(api_key=api_key)
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.created_resources = []

    def create_node(self, config):
        node_config = {ServiceName}NodeConfig(config=config, credentials=self.credentials)
        return {ServiceName}Node(
            node_id="test-node",
            node_type="automation-{service-name}",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

    async def run_test(self, name: str, test_func):
        try:
            await test_func()
            print(f"  PASS: {name}")
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {type(e).__name__}: {e}")
            self.failed += 1

    async def cleanup(self):
        """Clean up ALL created resources."""
        print("\n[Cleanup]")
        for resource_type, resource_id in reversed(self.created_resources):
            try:
                await self._delete_resource(resource_type, resource_id)
                print(f"  Deleted {resource_type}: {resource_id}")
            except Exception as e:
                print(f"  Warning: Failed to delete {resource_type} {resource_id}: {e}")

    async def _delete_resource(self, resource_type: str, resource_id: str):
        """Delete a resource by type and ID."""
        # Map resource types to delete configs
        delete_configs = {
            "repository": lambda id: {ServiceName}DeleteRepositoryConfig(repo_id=id),
            "issue": lambda id: {ServiceName}DeleteIssueConfig(issue_id=id),
            # ... map for all resource types
        }
        if resource_type in delete_configs:
            config = delete_configs[resource_type](resource_id)
            node = self.create_node(config)
            await node.execute({})

    async def run_all_tests(self):
        print("\n" + "=" * 70)
        print(f"{SERVICE_NAME} Node Integration Tests - {N} Operations")
        print("=" * 70 + "\n")

        try:
            # =========================================================
            # Category 1: Repository Operations ({n1} tests)
            # =========================================================
            print("\n[Repository Operations]")
            await self.run_test("get_repository", self.test_get_repository)
            await self.run_test("list_repositories", self.test_list_repositories)
            # ... ALL repository operation tests

            # =========================================================
            # Category 2: Issue Operations ({n2} tests)
            # =========================================================
            print("\n[Issue Operations]")
            await self.run_test("list_issues", self.test_list_issues)
            await self.run_test("get_issue", self.test_get_issue)
            await self.run_test("create_issue", self.test_create_issue)
            # ... ALL issue operation tests

            # =========================================================
            # Continue for ALL categories...
            # =========================================================

            # =========================================================
            # Error Handling Tests
            # =========================================================
            print("\n[Error Handling]")
            await self.run_test("invalid_resource", self.test_invalid_resource)
            await self.run_test("missing_credentials", self.test_missing_credentials)

            # =========================================================
            # Performance Tests
            # =========================================================
            print("\n[Performance]")
            await self.run_test("timing_information", self.test_timing_information)

        finally:
            await self.cleanup()

        # Summary
        total = self.passed + self.failed + self.skipped
        print("\n" + "=" * 70)
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped")
        print("=" * 70 + "\n")

        return self.failed == 0

    # =========================================================
    # Helper Methods for Test Data
    # =========================================================

    async def _get_test_resource_id(self, resource_type: str):
        """Get a valid resource ID for testing."""
        # List resources and return first ID
        pass

    async def _create_test_resource(self, resource_type: str):
        """Create a resource for testing and track for cleanup."""
        pass

    # =========================================================
    # Repository Operation Tests (ALL {n1} operations)
    # =========================================================

    async def test_get_repository(self):
        config = {ServiceName}GetRepositoryConfig(owner="test", repo="test")
        node = self.create_node(config)
        result = await node.execute({})
        assert result["action"] == "get_repository"

    async def test_list_repositories(self):
        config = {ServiceName}ListRepositoriesConfig(per_page=5)
        node = self.create_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_repositories"

    # ... implement ALL repository tests

    # =========================================================
    # Issue Operation Tests (ALL {n2} operations)
    # =========================================================

    async def test_list_issues(self):
        pass

    async def test_get_issue(self):
        pass

    async def test_create_issue(self):
        pass

    # ... implement ALL issue tests

    # =========================================================
    # Continue for ALL categories and ALL operations
    # =========================================================


async def main():
    api_key = os.environ.get("{SERVICE_UPPER}_API_KEY", "")
    if len(sys.argv) > 1:
        api_key = sys.argv[1]

    if not api_key:
        print("ERROR: API key required")
        sys.exit(1)

    runner = TestRunner(api_key)
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
```

## Test Coverage Verification

After generating tests, verify coverage:

```python
# At the end of the test file, add verification
EXPECTED_OPERATIONS = [
    # List ALL operations from the node
    "get_repository",
    "list_repositories",
    "list_organization_repos",
    # ... ALL operation names
]

IMPLEMENTED_TESTS = [
    method.replace("test_", "")
    for method in dir(TestRunner)
    if method.startswith("test_")
]

MISSING_TESTS = set(EXPECTED_OPERATIONS) - set(IMPLEMENTED_TESTS)
if MISSING_TESTS:
    print(f"WARNING: Missing tests for: {MISSING_TESTS}")
```

## Checklist for Complete Test Coverage

For EVERY operation in the node:

- [ ] Test method exists: `test_{action_name}`
- [ ] Config class imported at top of file
- [ ] Test creates appropriate config with valid test data
- [ ] Test executes node and checks result
- [ ] Test verifies correct action name in response
- [ ] Write operations track created resources for cleanup
- [ ] Delete operations create resource first, then delete
- [ ] Error cases handled appropriately (skip if test data unavailable)

## Example: Full Coverage for 75-Operation Node

For a node like GitHub REST with 75 operations:

```
Test File Structure:
├── Imports (ALL 75 config classes)
├── TestRunner class
│   ├── create_node()
│   ├── run_test()
│   ├── cleanup()
│   └── run_all_tests()
├── Repository Tests (17 methods)
├── Issue Tests (11 methods)
├── Pull Request Tests (9 methods)
├── Commit Tests (4 methods)
├── Branch Tests (4 methods)
├── File Tests (3 methods)
├── Release Tests (3 methods)
├── Label Tests (2 methods)
├── User Tests (4 methods)
├── Workflow Tests (6 methods)
├── Deployment Tests (2 methods)
├── Notification Tests (2 methods)
├── Organization Tests (2 methods)
├── Gist Tests (3 methods)
├── Search Tests (3 methods)
├── Error Handling Tests (2+ methods)
└── Performance Tests (1+ methods)

Total: 75+ test methods (one per operation + error/perf tests)
```

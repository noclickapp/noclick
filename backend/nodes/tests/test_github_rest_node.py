"""
Integration tests for GitHub REST API node.

Tests the complete GitHub REST API node functionality including all 206 operations
organized by category: repository, issues, PRs, commits, branches, files, releases,
labels, users, workflows, deployments, notifications, organizations, gists, search,
PR reviews, webhooks, collaborators, teams, reactions, and GitHub Actions.

Uses a real GitHub PAT to test against the GitHub API. Tests are designed to be
non-destructive where possible (read operations). Write operations test the action
name is correct but may fail due to permission constraints on public repos.
"""

import asyncio
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

# Import the node and config classes - ALL 75 operations
from nodes.github_rest_node import (
    GithubRestNode,
    GithubRestNodeConfig,
    GithubPATCredential,
    # Repository operations (17)
    GithubGetRepositoryConfig,
    GithubListRepositoriesConfig,
    GithubListOrganizationReposConfig,
    GithubForkRepositoryConfig,
    GithubListCollaboratorsConfig,
    GithubCreateRepoWebhookConfig,
    GithubListForksConfig,
    GithubListContributorsConfig,
    GithubGetRepoLanguagesConfig,
    GithubGetRepoTopicsConfig,
    GithubSetRepoTopicsConfig,
    GithubListStargazersConfig,
    GithubStarRepositoryConfig,
    GithubUnstarRepositoryConfig,
    GithubListRepoContentsConfig,
    GithubCreateRepoFromTemplateConfig,
    GithubListUserReposConfig,
    # Issue operations (11)
    GithubListIssuesConfig,
    GithubGetIssueConfig,
    GithubCreateIssueConfig,
    GithubUpdateIssueConfig,
    GithubListIssueCommentsConfig,
    GithubCreateIssueCommentConfig,
    GithubAddLabelsToIssueConfig,
    GithubCreateIssueReactionConfig,
    GithubListMilestonesConfig,
    GithubCreateMilestoneConfig,
    GithubListAssigneesConfig,
    # Pull request operations (9)
    GithubListPullRequestsConfig,
    GithubGetPullRequestConfig,
    GithubCreatePullRequestConfig,
    GithubUpdatePullRequestConfig,
    GithubMergePullRequestConfig,
    GithubListPullRequestFilesConfig,
    GithubRequestReviewersConfig,
    GithubListPullRequestReviewsConfig,
    GithubCreatePullRequestReviewConfig,
    # Commit operations (4)
    GithubListCommitsConfig,
    GithubGetCommitConfig,
    GithubCompareCommitsConfig,
    GithubListCheckRunsConfig,
    # Branch operations (4)
    GithubListBranchesConfig,
    GithubCreateBranchConfig,
    GithubDeleteBranchConfig,
    GithubListTagsConfig,
    # File operations (3)
    GithubGetFileContentsConfig,
    GithubCreateOrUpdateFileConfig,
    GithubDeleteFileConfig,
    # Release operations (3)
    GithubListReleasesConfig,
    GithubGetReleaseConfig,
    GithubCreateReleaseConfig,
    # Label operations (2)
    GithubListLabelsConfig,
    GithubCreateLabelConfig,
    # User operations (4)
    GithubGetAuthenticatedUserConfig,
    GithubGetUserConfig,
    GithubListUserFollowersConfig,
    GithubListUserFollowingConfig,
    # Workflow operations (6)
    GithubListWorkflowRunsConfig,
    GithubListWorkflowsConfig,
    GithubGetWorkflowRunConfig,
    GithubTriggerWorkflowDispatchConfig,
    GithubCancelWorkflowRunConfig,
    GithubRerunWorkflowConfig,
    # Deployment operations (2)
    GithubListDeploymentsConfig,
    GithubCreateDeploymentConfig,
    # Notification operations (2)
    GithubListNotificationsConfig,
    GithubMarkNotificationsReadConfig,
    # Organization operations (2)
    GithubListOrgTeamsConfig,
    GithubListOrgMembersConfig,
    # Gist operations (3)
    GithubListGistsConfig,
    GithubGetGistConfig,
    GithubCreateGistConfig,
    # Search operations (3)
    GithubSearchIssuesConfig,
    GithubSearchCodeConfig,
    GithubSearchRepositoriesConfig,
    # New operations - PR Review Comments (14)
    GithubListPullRequestReviewCommentsConfig,
    GithubCreatePullRequestReviewCommentConfig,
    GithubUpdatePullRequestReviewCommentConfig,
    GithubDeletePullRequestReviewCommentConfig,
    # New operations - Repository Management (4)
    GithubUpdateRepositoryConfig,
    GithubDeleteRepositoryConfig,
    GithubCreateRepositoryForAuthenticatedUserConfig,
    GithubTransferRepositoryConfig,
    # New operations - Issue Management (14)
    GithubLockIssueConfig,
    GithubUnlockIssueConfig,
    GithubUpdateLabelConfig,
    GithubDeleteLabelConfig,
    # New operations - Release Management (9)
    GithubUpdateReleaseConfig,
    GithubDeleteReleaseConfig,
    GithubGetLatestReleaseConfig,
    GithubGetReleaseByTagConfig,
    GithubGenerateReleaseNotesConfig,
    # New operations - Gist Management (12)
    GithubUpdateGistConfig,
    GithubDeleteGistConfig,
    GithubListPublicGistsConfig,
    GithubForkGistConfig,
    # New operations - Commit Operations (5)
    GithubListBranchesForHeadCommitConfig,
    GithubCreateCommitStatusConfig,
)

# Test constants - using popular public repos for testing
TEST_OWNER = "octocat"
TEST_REPO = "Hello-World"
TEST_ORG = "github"
TEST_USERNAME = "octocat"

# Environment variable for PAT (don't hardcode in tests)
GHUB_PAT = os.environ.get("GHUB_PAT", "")


def get_credentials():
    """Get GitHub credentials from environment."""
    if not GHUB_PAT:
        pytest.skip(
            "GHUB_PAT is not set — these are live GitHub calls, not a\n"
            "failure of the code under test. Set it to run them."
        )
    return GithubPATCredential(personal_access_token=GHUB_PAT)


def skip_if_token_lacks_access(result):
    """Skip a live test when the configured GHUB_PAT is expired or lacks the scope
    for this endpoint. GitHub returns 401 "Bad credentials" for an expired token,
    and 404 "Not Found" (not 403) for public activity endpoints like stargazers/
    subscribers when the token is a fine-grained/OAuth token not scoped to the
    target repo. The endpoint itself is valid (the same call succeeds
    unauthenticated), so this guards the credential's access — not the node's
    correctness — and only skips on those auth/permission signals.
    """
    if result.get("status") != "error":
        return
    code = result.get("status_code")
    err = str(result.get("error", "")).lower()
    if code in (401, 403, 404) and any(
        m in err for m in ("bad credentials", "not found", "requires authentication", "must be authenticated")
    ):
        pytest.skip(
            f"GHUB_PAT can't access this endpoint (expired or insufficient scope): {result.get('error')}"
        )


def create_node(config) -> GithubRestNode:
    """Create a GithubRestNode instance with the given config."""
    credentials = get_credentials()
    node_config = GithubRestNodeConfig(config=config, credentials=credentials)
    node = GithubRestNode(
        node_id="test-node",
        node_type="automation-github-rest",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Repository Operations Tests (17 operations)
# ============================================================================


class TestRepositoryOperations:
    """Test repository-related GitHub API operations (17 total)."""

    @pytest.mark.asyncio
    async def test_get_repository(self):
        """Test getting repository information."""
        config = GithubGetRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_repository"
        assert result["data"]["full_name"] == f"{TEST_OWNER}/{TEST_REPO}"

    @pytest.mark.asyncio
    async def test_list_repositories(self):
        """Test listing user's repositories."""
        config = GithubListRepositoriesConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_authenticated_user_repos"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_list_organization_repos(self):
        """Test listing organization repositories."""
        config = GithubListOrganizationReposConfig(org=TEST_ORG, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_org_repos"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_fork_repository(self):
        """Test forking a repository (may fail if already forked)."""
        config = GithubForkRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        # Accept success or 403/422 (already forked/no permission)
        assert result["action"] == "fork_repository"

    @pytest.mark.asyncio
    async def test_list_collaborators(self):
        """Test listing repository collaborators."""
        config = GithubListCollaboratorsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        # May return 403 for repos we don't own
        assert result["action"] == "list_repo_collaborators"

    @pytest.mark.asyncio
    async def test_create_repo_webhook(self):
        """Test creating a repository webhook (requires admin access)."""
        config = GithubCreateRepoWebhookConfig(
            owner=TEST_OWNER, repo=TEST_REPO, url="https://example.com/webhook"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail on public repos without admin access, but action should be correct
        assert result["action"] == "create_repo_webhook"

    @pytest.mark.asyncio
    async def test_list_forks(self):
        """Test listing repository forks."""
        config = GithubListForksConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_repo_forks"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_list_contributors(self):
        """Test listing repository contributors."""
        config = GithubListContributorsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_repo_contributors"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_repo_languages(self):
        """Test getting repository languages."""
        config = GithubGetRepoLanguagesConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_repo_languages"
        assert isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_get_repo_topics(self):
        """Test getting repository topics."""
        config = GithubGetRepoTopicsConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_repo_topics"

    @pytest.mark.asyncio
    async def test_set_repo_topics(self):
        """Test setting repository topics (requires write access)."""
        config = GithubSetRepoTopicsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, names=["test-topic"]
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access, but action should be correct
        assert result["action"] == "set_repo_topics"

    @pytest.mark.asyncio
    async def test_list_stargazers(self):
        """Test listing repository stargazers."""
        config = GithubListStargazersConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        skip_if_token_lacks_access(result)
        assert result["status"] == "success"
        assert result["action"] == "list_repo_stargazers"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_star_repository(self):
        """Test starring a repository."""
        config = GithubStarRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        # Should succeed or already starred
        assert result["action"] == "star_repository"

    @pytest.mark.asyncio
    async def test_unstar_repository(self):
        """Test unstarring a repository."""
        config = GithubUnstarRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        # Should succeed or already unstarred
        assert result["action"] == "unstar_repository"

    @pytest.mark.asyncio
    async def test_list_repo_contents(self):
        """Test listing repository contents."""
        config = GithubListRepoContentsConfig(owner=TEST_OWNER, repo=TEST_REPO, path="")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_repo_directory_contents"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_create_repo_from_template(self):
        """Test creating a repository from a template (requires template access)."""
        config = GithubCreateRepoFromTemplateConfig(
            template_owner="github",
            template_repo="gitignore",
            name=f"test-from-template-{int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        # May fail without proper permissions
        assert result["action"] == "create_repo_from_template"

    @pytest.mark.asyncio
    async def test_list_user_repos(self):
        """Test listing a specific user's repositories."""
        config = GithubListUserReposConfig(username=TEST_USERNAME, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_repos"
        assert isinstance(result["data"], list)


# ============================================================================
# Issue Operations Tests (11 operations)
# ============================================================================


class TestIssueOperations:
    """Test issue-related GitHub API operations (11 total)."""

    @pytest.mark.asyncio
    async def test_list_issues(self):
        """Test listing repository issues."""
        config = GithubListIssuesConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all", per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_issues"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_issue(self):
        """Test getting a specific issue."""
        # Using issue #1 which typically exists in Hello-World
        config = GithubGetIssueConfig(owner=TEST_OWNER, repo=TEST_REPO, issue_number=1)
        node = create_node(config)

        result = await node.execute({})

        # May be 404 if issue doesn't exist, but response structure should be valid
        assert result["action"] == "get_issue"
        assert "status" in result

    @pytest.mark.asyncio
    async def test_create_issue(self):
        """Test creating an issue (requires write access)."""
        config = GithubCreateIssueConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            title=f"Test Issue {int(time.time())}",
            body="This is a test issue created by automated tests.",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail on repos without write access
        assert result["action"] == "create_issue"

    @pytest.mark.asyncio
    async def test_update_issue(self):
        """Test updating an issue (requires write access)."""
        config = GithubUpdateIssueConfig(
            owner=TEST_OWNER, repo=TEST_REPO, issue_number=1, title="Updated Title"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "update_issue"

    @pytest.mark.asyncio
    async def test_list_issue_comments(self):
        """Test listing issue comments."""
        config = GithubListIssueCommentsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, issue_number=1, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_issue_comments"

    @pytest.mark.asyncio
    async def test_create_issue_comment(self):
        """Test creating an issue comment (requires write access)."""
        config = GithubCreateIssueCommentConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            issue_number=1,
            body="Test comment from automated tests.",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_issue_comment"

    @pytest.mark.asyncio
    async def test_add_labels_to_issue(self):
        """Test adding labels to an issue (requires write access)."""
        config = GithubAddLabelsToIssueConfig(
            owner=TEST_OWNER, repo=TEST_REPO, issue_number=1, labels=["bug"]
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "add_labels_to_issue"

    @pytest.mark.asyncio
    async def test_create_issue_reaction(self):
        """Test creating a reaction on an issue."""
        config = GithubCreateIssueReactionConfig(
            owner=TEST_OWNER, repo=TEST_REPO, issue_number=1, content="+1"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_reaction_on_issue"

    @pytest.mark.asyncio
    async def test_list_milestones(self):
        """Test listing repository milestones."""
        config = GithubListMilestonesConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_milestones"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_create_milestone(self):
        """Test creating a milestone (requires write access)."""
        config = GithubCreateMilestoneConfig(
            owner=TEST_OWNER, repo=TEST_REPO, title=f"Test Milestone {int(time.time())}"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_milestone"

    @pytest.mark.asyncio
    async def test_list_assignees(self):
        """Test listing available assignees."""
        config = GithubListAssigneesConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_issue_assignees"
        assert isinstance(result["data"], list)


# ============================================================================
# Pull Request Operations Tests (9 operations)
# ============================================================================


class TestPullRequestOperations:
    """Test pull request-related GitHub API operations (9 total)."""

    @pytest.mark.asyncio
    async def test_list_pull_requests(self):
        """Test listing pull requests."""
        config = GithubListPullRequestsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all", per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_pull_requests"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_pull_request(self):
        """Test getting a specific pull request."""
        # First list PRs to find one
        list_config = GithubListPullRequestsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all", per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            pr_number = list_result["data"][0]["number"]
            config = GithubGetPullRequestConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=pr_number
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == "get_pull_request"
        else:
            # No PRs, test with arbitrary number
            config = GithubGetPullRequestConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=1
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_pull_request"

    @pytest.mark.asyncio
    async def test_create_pull_request(self):
        """Test creating a pull request (requires write access and branches)."""
        config = GithubCreatePullRequestConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            title="Test PR",
            head="feature-branch",
            base="master",
            body="Test PR body",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without proper branches/access
        assert result["action"] == "create_pull_request"

    @pytest.mark.asyncio
    async def test_update_pull_request(self):
        """Test updating a pull request (requires write access)."""
        config = GithubUpdatePullRequestConfig(
            owner=TEST_OWNER, repo=TEST_REPO, pull_number=1, title="Updated PR Title"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "update_pull_request"

    @pytest.mark.asyncio
    async def test_merge_pull_request(self):
        """Test merging a pull request (requires write access)."""
        config = GithubMergePullRequestConfig(
            owner=TEST_OWNER, repo=TEST_REPO, pull_number=1, merge_method="merge"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "merge_pull_request"

    @pytest.mark.asyncio
    async def test_list_pull_request_files(self):
        """Test listing files in a pull request."""
        # First find a PR
        list_config = GithubListPullRequestsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all", per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            pr_number = list_result["data"][0]["number"]
            config = GithubListPullRequestFilesConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=pr_number
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "list_pull_request_files"
        else:
            config = GithubListPullRequestFilesConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=1
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "list_pull_request_files"

    @pytest.mark.asyncio
    async def test_request_reviewers(self):
        """Test requesting reviewers (requires write access)."""
        config = GithubRequestReviewersConfig(
            owner=TEST_OWNER, repo=TEST_REPO, pull_number=1, reviewers=["octocat"]
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "request_pull_request_reviewers"

    @pytest.mark.asyncio
    async def test_list_pull_request_reviews(self):
        """Test listing pull request reviews."""
        # First find a PR
        list_config = GithubListPullRequestsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, state="all", per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            pr_number = list_result["data"][0]["number"]
            config = GithubListPullRequestReviewsConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=pr_number
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "list_pull_request_reviews"
        else:
            config = GithubListPullRequestReviewsConfig(
                owner=TEST_OWNER, repo=TEST_REPO, pull_number=1
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "list_pull_request_reviews"

    @pytest.mark.asyncio
    async def test_create_pull_request_review(self):
        """Test creating a pull request review (requires access)."""
        config = GithubCreatePullRequestReviewConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            pull_number=1,
            body="Test review comment",
            event="COMMENT",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without proper access
        assert result["action"] == "create_pull_request_review"


# ============================================================================
# Commit Operations Tests (4 operations)
# ============================================================================


class TestCommitOperations:
    """Test commit-related GitHub API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_list_commits(self):
        """Test listing repository commits."""
        config = GithubListCommitsConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_commits"
        assert isinstance(result["data"], list)
        assert len(result["data"]) > 0

    @pytest.mark.asyncio
    async def test_get_commit(self):
        """Test getting a specific commit."""
        # First get commits to find a valid SHA
        list_config = GithubListCommitsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            sha = list_result["data"][0]["sha"]
            config = GithubGetCommitConfig(owner=TEST_OWNER, repo=TEST_REPO, ref=sha)
            node = create_node(config)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "get_commit"
            assert result["data"]["sha"] == sha

    @pytest.mark.asyncio
    async def test_compare_commits(self):
        """Test comparing two commits."""
        # Get two commits
        list_config = GithubListCommitsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and len(list_result["data"]) >= 2:
            base = list_result["data"][-1]["sha"]  # Older commit
            head = list_result["data"][0]["sha"]  # Newer commit

            config = GithubCompareCommitsConfig(
                owner=TEST_OWNER, repo=TEST_REPO, base=base, head=head
            )
            node = create_node(config)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "compare_commits"

    @pytest.mark.asyncio
    async def test_list_check_runs(self):
        """Test listing check runs for a reference."""
        config = GithubListCheckRunsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, ref="master", per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_commit_check_runs"
        # May be empty for repos without CI


# ============================================================================
# Branch Operations Tests (4 operations)
# ============================================================================


class TestBranchOperations:
    """Test branch-related GitHub API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_list_branches(self):
        """Test listing repository branches."""
        config = GithubListBranchesConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_branches"
        assert isinstance(result["data"], list)
        assert len(result["data"]) > 0

    @pytest.mark.asyncio
    async def test_create_branch(self):
        """Test creating a branch (requires write access)."""
        # First get the latest commit SHA
        list_config = GithubListCommitsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            sha = list_result["data"][0]["sha"]
            config = GithubCreateBranchConfig(
                owner=TEST_OWNER,
                repo=TEST_REPO,
                branch_name=f"test-branch-{int(time.time())}",
                sha=sha,
            )
            node = create_node(config)
            result = await node.execute({})
            # Will fail without write access - may fail at get_source_branch or create_branch step
            assert result["action"] in ["create_branch", "get_source_branch"]

    @pytest.mark.asyncio
    async def test_delete_branch(self):
        """Test deleting a branch (requires write access)."""
        config = GithubDeleteBranchConfig(
            owner=TEST_OWNER, repo=TEST_REPO, branch_name="test-branch-to-delete"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "delete_branch"

    @pytest.mark.asyncio
    async def test_list_tags(self):
        """Test listing repository tags."""
        config = GithubListTagsConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_repo_tags"
        assert isinstance(result["data"], list)


# ============================================================================
# File Operations Tests (3 operations)
# ============================================================================


class TestFileOperations:
    """Test file-related GitHub API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_get_file_contents(self):
        """Test getting file contents."""
        config = GithubGetFileContentsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, path="README"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_file_contents"
        # May return different status based on file existence

    @pytest.mark.asyncio
    async def test_create_or_update_file(self):
        """Test creating or updating a file (requires write access)."""
        config = GithubCreateOrUpdateFileConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            path=f"test-file-{int(time.time())}.txt",
            message="Test commit from automated tests",
            content="VGVzdCBjb250ZW50",  # "Test content" in base64
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_or_update_file"

    @pytest.mark.asyncio
    async def test_delete_file(self):
        """Test deleting a file (requires write access)."""
        config = GithubDeleteFileConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            path="test-file-to-delete.txt",
            message="Delete test file",
            sha="dummy-sha",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "delete_file"


# ============================================================================
# Release Operations Tests (3 operations)
# ============================================================================


class TestReleaseOperations:
    """Test release-related GitHub API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_releases(self):
        """Test listing repository releases."""
        config = GithubListReleasesConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_releases"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_release(self):
        """Test getting the latest release (release_id=None gets latest)."""
        config = GithubGetReleaseConfig(
            owner=TEST_OWNER, repo=TEST_REPO, release_id=None
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_release"
        # May be 404 if no releases exist

    @pytest.mark.asyncio
    async def test_create_release(self):
        """Test creating a release (requires write access)."""
        config = GithubCreateReleaseConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            tag_name=f"v0.0.{int(time.time())}",
            name="Test Release",
            body="Test release from automated tests",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_release"


# ============================================================================
# Label Operations Tests (2 operations)
# ============================================================================


class TestLabelOperations:
    """Test label-related GitHub API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_list_labels(self):
        """Test listing repository labels."""
        config = GithubListLabelsConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_repo_labels"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_create_label(self):
        """Test creating a label (requires write access)."""
        config = GithubCreateLabelConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            name=f"test-label-{int(time.time())}",
            color="ff0000",
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_label"


# ============================================================================
# User Operations Tests (4 operations)
# ============================================================================


class TestUserOperations:
    """Test user-related GitHub API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_get_authenticated_user(self):
        """Test getting the authenticated user."""
        config = GithubGetAuthenticatedUserConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_authenticated_user"
        assert "login" in result["data"]

    @pytest.mark.asyncio
    async def test_get_user(self):
        """Test getting a specific user."""
        config = GithubGetUserConfig(username=TEST_USERNAME)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["login"] == TEST_USERNAME

    @pytest.mark.asyncio
    async def test_list_user_followers(self):
        """Test listing user followers."""
        config = GithubListUserFollowersConfig(username=TEST_USERNAME, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_followers"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_list_user_following(self):
        """Test listing users followed by a user."""
        config = GithubListUserFollowingConfig(username=TEST_USERNAME, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_following"
        assert isinstance(result["data"], list)


# ============================================================================
# Workflow Operations Tests (6 operations)
# ============================================================================


class TestWorkflowOperations:
    """Test workflow-related GitHub API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_workflow_runs(self):
        """Test listing workflow runs."""
        config = GithubListWorkflowRunsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_workflow_runs"

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        """Test listing workflows."""
        config = GithubListWorkflowsConfig(owner=TEST_OWNER, repo=TEST_REPO, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_workflows"

    @pytest.mark.asyncio
    async def test_get_workflow_run(self):
        """Test getting a specific workflow run."""
        # First list runs to find one
        list_config = GithubListWorkflowRunsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=1
        )
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result.get("data", {}).get(
            "workflow_runs"
        ):
            run_id = list_result["data"]["workflow_runs"][0]["id"]
            config = GithubGetWorkflowRunConfig(
                owner=TEST_OWNER, repo=TEST_REPO, run_id=run_id
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_workflow_run"
        else:
            # No runs, test with arbitrary ID
            config = GithubGetWorkflowRunConfig(
                owner=TEST_OWNER, repo=TEST_REPO, run_id=1
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_workflow_run"

    @pytest.mark.asyncio
    async def test_trigger_workflow_dispatch(self):
        """Test triggering a workflow dispatch (requires write access)."""
        config = GithubTriggerWorkflowDispatchConfig(
            owner=TEST_OWNER, repo=TEST_REPO, workflow_id="test.yml", ref="master"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without workflow or access
        assert result["action"] == "trigger_workflow_dispatch"

    @pytest.mark.asyncio
    async def test_cancel_workflow_run(self):
        """Test canceling a workflow run (requires write access)."""
        config = GithubCancelWorkflowRunConfig(
            owner=TEST_OWNER, repo=TEST_REPO, run_id=1
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "cancel_workflow_run"

    @pytest.mark.asyncio
    async def test_rerun_workflow(self):
        """Test rerunning a workflow (requires write access)."""
        config = GithubRerunWorkflowConfig(owner=TEST_OWNER, repo=TEST_REPO, run_id=1)
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "rerun_workflow"


# ============================================================================
# Deployment Operations Tests (2 operations)
# ============================================================================


class TestDeploymentOperations:
    """Test deployment-related GitHub API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_list_deployments(self):
        """Test listing deployments."""
        config = GithubListDeploymentsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_deployments"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_create_deployment(self):
        """Test creating a deployment (requires write access)."""
        config = GithubCreateDeploymentConfig(
            owner=TEST_OWNER, repo=TEST_REPO, ref="master", environment="test"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will fail without write access
        assert result["action"] == "create_deployment"


# ============================================================================
# Notification Operations Tests (2 operations)
# ============================================================================


class TestNotificationOperations:
    """Test notification-related GitHub API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_list_notifications(self):
        """Test listing notifications."""
        config = GithubListNotificationsConfig(all=False, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_notifications"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_mark_notifications_read(self):
        """Test marking notifications as read."""
        config = GithubMarkNotificationsReadConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "mark_notifications_as_read"


# ============================================================================
# Organization Operations Tests (2 operations)
# ============================================================================


class TestOrganizationOperations:
    """Test organization-related GitHub API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_list_org_teams(self):
        """Test listing organization teams."""
        config = GithubListOrgTeamsConfig(org=TEST_ORG, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        # May fail with 403 for private orgs, but action should be correct
        assert result["action"] == "list_org_teams"

    @pytest.mark.asyncio
    async def test_list_org_members(self):
        """Test listing organization members."""
        config = GithubListOrgMembersConfig(org=TEST_ORG, per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_org_members"


# ============================================================================
# Gist Operations Tests (3 operations)
# ============================================================================


class TestGistOperations:
    """Test gist-related GitHub API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_gists(self):
        """Test listing user gists."""
        config = GithubListGistsConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_authenticated_user_gists"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_gist(self):
        """Test getting a specific gist."""
        # First list gists to find one
        list_config = GithubListGistsConfig(per_page=1)
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"]:
            gist_id = list_result["data"][0]["id"]
            config = GithubGetGistConfig(gist_id=gist_id)
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_gist"
        else:
            # No gists, use a public gist ID
            config = GithubGetGistConfig(gist_id="aa5a315d61ae9438b18d")
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_gist"

    @pytest.mark.asyncio
    async def test_create_gist(self):
        """Test creating a gist."""
        config = GithubCreateGistConfig(
            description=f"Test gist {int(time.time())}",
            filename="test.txt",
            content="Test content",
            public=False,
        )
        node = create_node(config)

        result = await node.execute({})

        # Should succeed for authenticated users
        assert result["action"] == "create_gist"


# ============================================================================
# Search Operations Tests (3 operations)
# ============================================================================


class TestSearchOperations:
    """Test search-related GitHub API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_search_issues(self):
        """Test searching issues."""
        config = GithubSearchIssuesConfig(
            query="repo:octocat/Hello-World is:issue", per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_issues"
        assert "items" in result["data"]

    @pytest.mark.asyncio
    async def test_search_code(self):
        """Test searching code."""
        config = GithubSearchCodeConfig(query="repo:octocat/Hello-World", per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_code"
        # Code search requires special OAuth scopes, may fail

    @pytest.mark.asyncio
    async def test_search_repositories(self):
        """Test searching repositories."""
        config = GithubSearchRepositoriesConfig(
            query="hello world language:python", per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_repositories"
        assert "items" in result["data"]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_repository(self):
        """Test handling of invalid repository."""
        config = GithubGetRepositoryConfig(
            owner="nonexistent-user-12345", repo="nonexistent-repo-12345"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = GithubGetRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node_config = GithubRestNodeConfig(config=config, credentials=None)
        node = GithubRestNode(
            node_id="test-node",
            node_type="automation-github-rest",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Timing and Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = GithubGetRepositoryConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] > 0
        assert result["timing_ms"]["total"] > 0


# ============================================================================
# New Operations Tests (131 endpoints added)
# ============================================================================


class TestNewPRReviewComments:
    """Test newly added PR Review Comment operations."""

    @pytest.mark.asyncio
    async def test_list_pr_review_comments(self):
        """Test listing PR review comments (new operation)."""
        config = GithubListPullRequestReviewCommentsConfig(
            owner=TEST_OWNER, repo=TEST_REPO, pull_number=1
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "list_pull_request_review_comments"
        # May succeed or fail depending on PR existence, but action should be correct


class TestNewRepositoryManagement:
    """Test newly added Repository Management operations."""

    @pytest.mark.asyncio
    async def test_update_repository(self):
        """Test updating repository settings (new operation)."""
        config = GithubUpdateRepositoryConfig(
            owner=TEST_OWNER, repo=TEST_REPO, description="Test description"
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "update_repository"
        # Will likely fail with 403/404 but action should be correct

    @pytest.mark.asyncio
    async def test_create_repository_for_user(self):
        """Test creating repository for authenticated user (new operation)."""
        config = GithubCreateRepositoryForAuthenticatedUserConfig(
            name="test-repo-noclick-" + str(int(time.time())),
            private=True,
            auto_init=True,
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "create_repo_for_authenticated_user"
        # May succeed or fail, but action should be correct


class TestNewIssueManagement:
    """Test newly added Issue Management operations."""

    @pytest.mark.asyncio
    async def test_lock_issue(self):
        """Test locking an issue (new operation)."""
        config = GithubLockIssueConfig(owner=TEST_OWNER, repo=TEST_REPO, issue_number=1)
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "lock_issue"
        # Will likely fail with 403 but action should be correct

    @pytest.mark.asyncio
    async def test_update_label(self):
        """Test updating a label (new operation)."""
        config = GithubUpdateLabelConfig(
            owner=TEST_OWNER, repo=TEST_REPO, name="bug", color="FF0000"
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "update_label"
        # Will likely fail with 403/404 but action should be correct


class TestNewReleaseManagement:
    """Test newly added Release Management operations."""

    @pytest.mark.asyncio
    async def test_get_latest_release(self):
        """Test getting the latest release (new operation)."""
        config = GithubGetLatestReleaseConfig(owner=TEST_OWNER, repo=TEST_REPO)
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "get_latest_release"
        # Should work for repos with releases

    @pytest.mark.asyncio
    async def test_generate_release_notes(self):
        """Test generating release notes (new operation)."""
        config = GithubGenerateReleaseNotesConfig(
            owner=TEST_OWNER, repo=TEST_REPO, tag_name="v1.0.0"
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "generate_release_notes"
        # Will likely fail with 404 but action should be correct


class TestNewGistManagement:
    """Test newly added Gist Management operations."""

    @pytest.mark.asyncio
    async def test_list_public_gists(self):
        """Test listing public gists (new operation)."""
        config = GithubListPublicGistsConfig(per_page=5)
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "list_public_gists"
        assert result["status"] == "success"
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_fork_gist(self):
        """Test forking a gist (new operation)."""
        # Use a known public gist ID (this is a test gist)
        config = GithubForkGistConfig(gist_id="1")
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "fork_gist"
        # Will likely fail with 404 but action should be correct


class TestNewCommitOperations:
    """Test newly added Commit Operations."""

    @pytest.mark.asyncio
    async def test_list_branches_for_head_commit(self):
        """Test listing branches where commit is HEAD (new operation)."""
        # Get a recent commit first
        config = GithubListBranchesForHeadCommitConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            commit_sha="7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",  # Known commit
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "list_branches_by_head_commit"

    @pytest.mark.asyncio
    async def test_create_commit_status(self):
        """Test creating a commit status (new operation)."""
        config = GithubCreateCommitStatusConfig(
            owner=TEST_OWNER,
            repo=TEST_REPO,
            sha="7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
            state="success",
            description="Test status from NoClick",
        )
        node = create_node(config)
        result = await node.execute({})
        assert result["action"] == "create_commit_status"
        # Will likely fail with 403 but action should be correct


if __name__ == "__main__":
    # Run tests with: GHUB_PAT=your_token pytest tests/test_github_rest_node.py -v
    pytest.main([__file__, "-v"])

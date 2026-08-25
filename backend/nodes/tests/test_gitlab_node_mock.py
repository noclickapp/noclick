"""
Mock tests for the GitLab REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Projects: list, get, create, list members
- Issues: list, get, create, update, comment
- Merge Requests: list, get, create, update, merge
- Repository: branches (list/create/delete), commits (list/create), files
  (get/upsert), tags
- CI/CD: list pipelines, create pipeline, list pipeline jobs
- Releases: create release
- Groups / Search / User
- Trigger: on_project_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: project dropdown
"""

import hashlib

import pytest
from unittest.mock import Mock, patch

from nodes.gitlab_node import (
    GitLabNode,
    GitLabNodeConfig,
    GitLabAccessTokenCredential,
    GitLabListProjectsConfig,
    GitLabGetProjectConfig,
    GitLabCreateProjectConfig,
    GitLabListMembersConfig,
    GitLabListIssuesConfig,
    GitLabGetIssueConfig,
    GitLabCreateIssueConfig,
    GitLabUpdateIssueConfig,
    GitLabCreateNoteConfig,
    GitLabListMergeRequestsConfig,
    GitLabGetMergeRequestConfig,
    GitLabCreateMergeRequestConfig,
    GitLabUpdateMergeRequestConfig,
    GitLabMergeMergeRequestConfig,
    GitLabListBranchesConfig,
    GitLabCreateBranchConfig,
    GitLabDeleteBranchConfig,
    GitLabListCommitsConfig,
    GitLabCreateCommitConfig,
    GitLabGetFileConfig,
    GitLabUpsertFileConfig,
    GitLabCreateTagConfig,
    GitLabListPipelinesConfig,
    GitLabCreatePipelineConfig,
    GitLabListPipelineJobsConfig,
    GitLabCreateReleaseConfig,
    GitLabListGroupsConfig,
    GitLabSearchConfig,
    GitLabGetUserConfig,
    GitLabHookTriggerConfig,
    GitLabGroupHookTriggerConfig,
    GitLabGetPipelineConfig,
    GitLabRetryPipelineConfig,
    GitLabCancelPipelineConfig,
    GitLabGetJobConfig,
    GitLabGetJobLogConfig,
    GitLabRetryJobConfig,
    GitLabPlayJobConfig,
    GitLabCancelJobConfig,
    GitLabListVariablesConfig,
    GitLabCreateVariableConfig,
    GitLabUpdateVariableConfig,
    GitLabDeleteVariableConfig,
    GitLabApproveMergeRequestConfig,
    GitLabUnapproveMergeRequestConfig,
    GitLabListNotesConfig,
    GitLabDeleteIssueConfig,
    GitLabListLabelsConfig,
    GitLabCreateLabelConfig,
    GitLabDeleteLabelConfig,
    GitLabListMilestonesConfig,
    GitLabCreateMilestoneConfig,
    GitLabAddMemberConfig,
    GitLabRemoveMemberConfig,
    GitLabListReleasesConfig,
    GitLabGetReleaseConfig,
    GitLabSetCommitStatusConfig,
    GitLabListEnvironmentsConfig,
    GitLabCreateEnvironmentConfig,
    GitLabStopEnvironmentConfig,
    GitLabDeleteEnvironmentConfig,
    GitLabListDeploymentsConfig,
    GitLabGetDeploymentConfig,
    GitLabCreateDeploymentConfig,
    GitLabListWikisConfig,
    GitLabGetWikiConfig,
    GitLabCreateWikiConfig,
    GitLabUpdateWikiConfig,
    GitLabDeleteWikiConfig,
    GitLabListProtectedBranchesConfig,
    GitLabProtectBranchConfig,
    GitLabUnprotectBranchConfig,
    GitLabListTodosConfig,
    GitLabMarkTodoDoneConfig,
    GitLabMarkAllTodosDoneConfig,
    GitLabListHooksConfig,
    GitLabCreateHookConfig,
    GitLabDeleteHookConfig,
    GitLabUpdateReleaseConfig,
    GitLabDeleteReleaseConfig,
    GitLabListEpicsConfig,
    GitLabCreateEpicConfig,
    GitLabUpdateEpicConfig,
    GITLAB_EVENT_TYPES,
)


@pytest.fixture
def token_credentials():
    return GitLabAccessTokenCredential(access_token="glpat-test-token-12345")


def create_gitlab_node(config):
    return GitLabNode(
        node_id="test-gitlab-node",
        node_type="automation-gitlab",
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


class TestGitLabProjectsMock:
    @pytest.mark.asyncio
    async def test_list_projects(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListProjectsConfig(search="repo", per_page="10"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1}, {"id": 2}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_projects"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_project(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetProjectConfig(project_id="mygroup/myrepo"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"id": 5, "name": "myrepo"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_project"
        assert result["data"]["id"] == 5

    @pytest.mark.asyncio
    async def test_create_project(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateProjectConfig(name="newrepo", visibility="private"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"id": 9, "name": "newrepo"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_project"
        assert result["data"]["name"] == "newrepo"

    @pytest.mark.asyncio
    async def test_list_members(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListMembersConfig(project_id="42"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "username": "ada"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_members"


class TestGitLabIssuesMock:
    @pytest.mark.asyncio
    async def test_list_issues(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListIssuesConfig(project_id="42", state="opened"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"iid": 1, "title": "bug"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_issues"

    @pytest.mark.asyncio
    async def test_get_issue(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetIssueConfig(project_id="42", issue_iid="7"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"iid": 7, "title": "An issue"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_issue"
        assert result["data"]["iid"] == 7

    @pytest.mark.asyncio
    async def test_create_issue(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateIssueConfig(
                project_id="42", title="New bug", labels="bug,urgent", assignee_ids="3,4"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"iid": 10, "title": "New bug"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_issue"
        assert result["data"]["iid"] == 10

    @pytest.mark.asyncio
    async def test_update_issue(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabUpdateIssueConfig(
                project_id="42", issue_iid="7", state_event="close"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"iid": 7, "state": "closed"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_issue"
        assert result["data"]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_create_note(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateNoteConfig(
                project_id="42", noteable_type="issues", noteable_iid="7", body="LGTM"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"id": 100, "body": "LGTM"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_note"
        assert result["data"]["body"] == "LGTM"


class TestGitLabMergeRequestsMock:
    @pytest.mark.asyncio
    async def test_list_merge_requests(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListMergeRequestsConfig(project_id="42", state="opened"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"iid": 1}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_merge_requests"

    @pytest.mark.asyncio
    async def test_get_merge_request(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetMergeRequestConfig(project_id="42", merge_request_iid="3"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"iid": 3, "title": "Feature"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_merge_request"
        assert result["data"]["iid"] == 3

    @pytest.mark.asyncio
    async def test_create_merge_request(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateMergeRequestConfig(
                project_id="42",
                source_branch="feature",
                target_branch="main",
                title="Add feature",
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"iid": 4, "title": "Add feature"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_merge_request"
        assert result["data"]["iid"] == 4

    @pytest.mark.asyncio
    async def test_update_merge_request(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabUpdateMergeRequestConfig(
                project_id="42", merge_request_iid="4", title="Renamed"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"iid": 4, "title": "Renamed"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_merge_request"
        assert result["data"]["title"] == "Renamed"

    @pytest.mark.asyncio
    async def test_merge_merge_request(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabMergeMergeRequestConfig(
                project_id="42", merge_request_iid="4", squash="true"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"iid": 4, "state": "merged"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "merge_merge_request"
        assert result["data"]["state"] == "merged"


class TestGitLabRepositoryMock:
    @pytest.mark.asyncio
    async def test_list_branches(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListBranchesConfig(project_id="42"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"name": "main"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_branches"

    @pytest.mark.asyncio
    async def test_create_branch(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateBranchConfig(project_id="42", branch="feature", ref="main"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"name": "feature"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_branch"
        assert result["data"]["name"] == "feature"

    @pytest.mark.asyncio
    async def test_delete_branch(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabDeleteBranchConfig(project_id="42", branch="feature"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_branch"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_list_commits(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListCommitsConfig(project_id="42", ref_name="main"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": "abc123"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_commits"

    @pytest.mark.asyncio
    async def test_create_commit(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateCommitConfig(
                project_id="42",
                branch="main",
                commit_message="Add file",
                file_path="README.md",
                content="# Hello",
                action="create",
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"id": "def456", "message": "Add file"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_commit"
        assert result["data"]["id"] == "def456"

    @pytest.mark.asyncio
    async def test_get_file(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetFileConfig(project_id="42", file_path="README.md", ref="main"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"file_path": "README.md", "content": "IyBI"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_file"
        assert result["data"]["file_path"] == "README.md"

    @pytest.mark.asyncio
    async def test_upsert_file_create(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabUpsertFileConfig(
                project_id="42",
                file_path="docs/new.md",
                branch="main",
                content="# New",
                commit_message="Add doc",
                mode="create",
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"file_path": "docs/new.md", "branch": "main"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upsert_file"
        assert result["data"]["file_path"] == "docs/new.md"

    @pytest.mark.asyncio
    async def test_create_tag(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateTagConfig(project_id="42", tag_name="v1.0.0", ref="main"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"name": "v1.0.0"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_tag"
        assert result["data"]["name"] == "v1.0.0"


class TestGitLabCICDMock:
    @pytest.mark.asyncio
    async def test_list_pipelines(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListPipelinesConfig(project_id="42", status="success"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "status": "success"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_pipelines"

    @pytest.mark.asyncio
    async def test_create_pipeline(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreatePipelineConfig(project_id="42", ref="main"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"id": 12, "ref": "main"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_pipeline"
        assert result["data"]["id"] == 12

    @pytest.mark.asyncio
    async def test_list_pipeline_jobs(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListPipelineJobsConfig(project_id="42", pipeline_id="12"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "name": "build"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_pipeline_jobs"


class TestGitLabReleasesMock:
    @pytest.mark.asyncio
    async def test_create_release(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabCreateReleaseConfig(
                project_id="42", tag_name="v1.0.0", name="First release"
            ),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(201, {"tag_name": "v1.0.0", "name": "First release"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_release"
        assert result["data"]["tag_name"] == "v1.0.0"


class TestGitLabMiscMock:
    @pytest.mark.asyncio
    async def test_list_groups(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabListGroupsConfig(search="eng"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "name": "Engineering"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_groups"

    @pytest.mark.asyncio
    async def test_search(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabSearchConfig(scope="issues", search_term="login bug"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, [{"id": 1, "title": "login bug"}])
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search"

    @pytest.mark.asyncio
    async def test_get_user(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetUserConfig(),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(200, {"id": 1, "username": "ada"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["username"] == "ada"


class TestGitLabTriggerMock:
    @pytest.mark.asyncio
    async def test_on_project_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = GitLabNodeConfig(
            config=GitLabHookTriggerConfig(
                project_id="42", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_gitlab_node(config)
        payload = {"object_kind": "merge_request", "project": {"id": 42}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_project_event"
        assert result["data"]["object_kind"] == "merge_request"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={"status": "success", "data": {"id": 99}},
        ) as mock_req:
            extra = await GitLabNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "glpat-test", "host": "https://gitlab.com"},
                config={"project_id": "42"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "99"
        assert extra["signing_secret"]
        # No event_types in config -> defaults to ALL events: every flag True.
        body = mock_req.call_args.kwargs["json_body"]
        for spec in GITLAB_EVENT_TYPES.values():
            assert body[spec["flag"]] is True

    @pytest.mark.asyncio
    async def test_register_external_webhook_subscribes_selected_events(self):
        """The hook is created with only the selected event flags enabled."""
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={"status": "success", "data": {"id": 77}},
        ) as mock_req:
            await GitLabNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "glpat-test", "host": "https://gitlab.com"},
                config={"project_id": "42", "event_types": "merge_request,pipeline"},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        # Selected flags on...
        assert body["merge_requests_events"] is True
        assert body["pipeline_events"] is True
        # ...all other event flags explicitly off so a re-register narrows scope.
        assert body["push_events"] is False
        assert body["issues_events"] is False
        assert body["note_events"] is False
        assert body["releases_events"] is False
        assert body["job_events"] is False

    def test_filter_trigger_payload_skips_non_selected(self):
        """A delivery whose object_kind isn't selected is filtered out."""
        config = {"event_types": "merge_request"}
        # Selected event passes.
        assert GitLabNode.filter_trigger_payload(
            {"object_kind": "merge_request"}, config
        )
        # Non-selected events are skipped.
        assert not GitLabNode.filter_trigger_payload({"object_kind": "push"}, config)
        assert not GitLabNode.filter_trigger_payload({"object_kind": "pipeline"}, config)

    def test_filter_trigger_payload_job_object_kind_build(self):
        """GitLab job events arrive with object_kind 'build'."""
        config = {"event_types": "job"}
        assert GitLabNode.filter_trigger_payload({"object_kind": "build"}, config)
        assert not GitLabNode.filter_trigger_payload({"object_kind": "push"}, config)

    def test_filter_trigger_payload_all_events_accepts_anything(self):
        """The '*' default (and empty) selection accepts every delivery."""
        for cfg in ({"event_types": "*"}, {"event_types": ""}, {}):
            assert GitLabNode.filter_trigger_payload({"object_kind": "push"}, cfg)
            assert GitLabNode.filter_trigger_payload({"object_kind": "release"}, cfg)
            assert GitLabNode.filter_trigger_payload({"object_kind": "wiki_page"}, cfg)

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await GitLabNode._unregister_external_webhook(
                credential={"access_token": "glpat-test", "host": "https://gitlab.com"},
                config={"external_webhook_id": "99", "project_id": "42"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"object_kind":"push"}'
        assert GitLabNode.verify_webhook_signature(
            body, {"x-gitlab-token": secret}, {"signing_secret": secret}
        )
        assert not GitLabNode.verify_webhook_signature(
            body, {"x-gitlab-token": "wrong"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert GitLabNode.verify_webhook_signature(body, {}, {})


class TestGitLabErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, token_credentials):
        config = GitLabNodeConfig(
            config=GitLabGetProjectConfig(project_id="missing/repo"),
            credentials=token_credentials,
        )
        node = create_gitlab_node(config)
        mock_client = create_mock_client(404, {"message": "404 Project Not Found"})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = GitLabNodeConfig(config=GitLabGetUserConfig(), credentials=None)
        node = create_gitlab_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestGitLabDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_project_options(self):
        # Matches the real caller contract: credential already loaded, passed as
        # credential_data; no user_id/pool/credential_ids.
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={
                "status": "success",
                "data": [
                    {"id": 7, "path_with_namespace": "mygroup/myrepo", "name": "myrepo"}
                ],
            },
        ):
            result = await GitLabNode.load_field_options(
                "project_id",
                credential_data={"access_token": "glpat-test", "host": "https://gitlab.com"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "7"
        assert result["options"][0]["label"] == "mygroup/myrepo"

    @pytest.mark.asyncio
    async def test_load_field_options_accepts_caller_kwargs(self):
        """Regression: the FE caller passes credential_data/context/page_token/
        search — the signature must accept them (was 'unexpected keyword
        argument credential_data')."""
        with patch("nodes.gitlab_node._gitlab_request", return_value={"status": "success", "data": []}):
            result = await GitLabNode.load_field_options(
                field_name="project_id",
                credential_data={"access_token": "t"},
                context=None,
                page_token=None,
                search="repo",
            )
        assert result == {"options": []}


# ============================================================================
# Request-capturing client (verifies method + endpoint for the added ops)
# ============================================================================


def create_capturing_client(captured, status_code=200, json_data=None):
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        captured.update(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run_capture(op_config, token_credentials, status_code=200, json_data=None):
    config = GitLabNodeConfig(config=op_config, credentials=token_credentials)
    captured = {}
    client = create_capturing_client(captured, status_code, json_data if json_data is not None else {})
    with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=client):
        result = await create_gitlab_node(config).execute({})
    return result, captured


PROJ = "grp/repo"
ENC = "grp%2Frepo"


class TestGitLabPipelineControlMock:
    @pytest.mark.asyncio
    async def test_get_pipeline(self, token_credentials):
        r, cap = await _run_capture(GitLabGetPipelineConfig(project_id=PROJ, pipeline_id="42"), token_credentials, 200, {"id": 42, "status": "success"})
        assert r["status"] == "success" and r["action"] == "get_pipeline"
        assert cap["method"] == "GET"
        assert cap["url"].endswith(f"/projects/{ENC}/pipelines/42")

    @pytest.mark.asyncio
    async def test_retry_pipeline(self, token_credentials):
        r, cap = await _run_capture(GitLabRetryPipelineConfig(project_id=PROJ, pipeline_id="42"), token_credentials, 201, {"id": 42})
        assert r["action"] == "retry_pipeline"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/pipelines/42/retry")

    @pytest.mark.asyncio
    async def test_cancel_pipeline(self, token_credentials):
        r, cap = await _run_capture(GitLabCancelPipelineConfig(project_id=PROJ, pipeline_id="42"), token_credentials, 201, {"id": 42})
        assert r["action"] == "cancel_pipeline"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/pipelines/42/cancel")

    @pytest.mark.asyncio
    async def test_create_pipeline_with_variables(self, token_credentials):
        r, cap = await _run_capture(
            GitLabCreatePipelineConfig(project_id=PROJ, ref="main", variables="ENV=prod\nDEBUG=1"),
            token_credentials, 201, {"id": 1},
        )
        assert r["action"] == "create_pipeline"
        assert cap["json"]["ref"] == "main"
        assert cap["json"]["variables"] == [{"key": "ENV", "value": "prod"}, {"key": "DEBUG", "value": "1"}]


class TestGitLabJobControlMock:
    @pytest.mark.asyncio
    async def test_get_job(self, token_credentials):
        r, cap = await _run_capture(GitLabGetJobConfig(project_id=PROJ, job_id="7"), token_credentials, 200, {"id": 7})
        assert r["action"] == "get_job"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/projects/{ENC}/jobs/7")

    @pytest.mark.asyncio
    async def test_get_job_log(self, token_credentials):
        r, cap = await _run_capture(GitLabGetJobLogConfig(project_id=PROJ, job_id="7"), token_credentials, 200, {})
        assert r["action"] == "get_job_log"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/jobs/7/trace")

    @pytest.mark.asyncio
    async def test_retry_job(self, token_credentials):
        r, cap = await _run_capture(GitLabRetryJobConfig(project_id=PROJ, job_id="7"), token_credentials, 201, {"id": 7})
        assert r["action"] == "retry_job"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/jobs/7/retry")

    @pytest.mark.asyncio
    async def test_play_job(self, token_credentials):
        r, cap = await _run_capture(GitLabPlayJobConfig(project_id=PROJ, job_id="7"), token_credentials, 200, {"id": 7})
        assert r["action"] == "play_job"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/jobs/7/play")

    @pytest.mark.asyncio
    async def test_cancel_job(self, token_credentials):
        r, cap = await _run_capture(GitLabCancelJobConfig(project_id=PROJ, job_id="7"), token_credentials, 201, {"id": 7})
        assert r["action"] == "cancel_job"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/jobs/7/cancel")


class TestGitLabVariablesMock:
    @pytest.mark.asyncio
    async def test_list_variables(self, token_credentials):
        r, cap = await _run_capture(GitLabListVariablesConfig(project_id=PROJ), token_credentials, 200, [{"key": "K"}])
        assert r["action"] == "list_variables"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/projects/{ENC}/variables")

    @pytest.mark.asyncio
    async def test_create_variable(self, token_credentials):
        r, cap = await _run_capture(
            GitLabCreateVariableConfig(project_id=PROJ, key="API_KEY", value="secret", masked="true"),
            token_credentials, 201, {"key": "API_KEY"},
        )
        assert r["action"] == "create_variable"
        assert cap["method"] == "POST"
        assert cap["json"]["key"] == "API_KEY" and cap["json"]["masked"] is True

    @pytest.mark.asyncio
    async def test_update_variable(self, token_credentials):
        r, cap = await _run_capture(GitLabUpdateVariableConfig(project_id=PROJ, key="API_KEY", value="new"), token_credentials, 200, {"key": "API_KEY"})
        assert r["action"] == "update_variable"
        assert cap["method"] == "PUT" and cap["url"].endswith(f"/variables/API_KEY")
        assert cap["json"]["value"] == "new"

    @pytest.mark.asyncio
    async def test_delete_variable(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteVariableConfig(project_id=PROJ, key="API_KEY"), token_credentials, 204, None)
        assert r["action"] == "delete_variable"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/variables/API_KEY")


class TestGitLabReviewMock:
    @pytest.mark.asyncio
    async def test_approve_merge_request(self, token_credentials):
        r, cap = await _run_capture(GitLabApproveMergeRequestConfig(project_id=PROJ, merge_request_iid="3"), token_credentials, 201, {"id": 3})
        assert r["action"] == "approve_merge_request"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/merge_requests/3/approve")

    @pytest.mark.asyncio
    async def test_unapprove_merge_request(self, token_credentials):
        r, cap = await _run_capture(GitLabUnapproveMergeRequestConfig(project_id=PROJ, merge_request_iid="3"), token_credentials, 201, {"id": 3})
        assert r["action"] == "unapprove_merge_request"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/merge_requests/3/unapprove")

    @pytest.mark.asyncio
    async def test_list_notes_mr(self, token_credentials):
        r, cap = await _run_capture(GitLabListNotesConfig(project_id=PROJ, noteable_type="merge_requests", noteable_iid="3"), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_notes"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/merge_requests/3/notes")


class TestGitLabIssuesExtraMock:
    @pytest.mark.asyncio
    async def test_delete_issue(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteIssueConfig(project_id=PROJ, issue_iid="5"), token_credentials, 204, None)
        assert r["action"] == "delete_issue"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/issues/5")


class TestGitLabLabelsMock:
    @pytest.mark.asyncio
    async def test_list_labels(self, token_credentials):
        r, cap = await _run_capture(GitLabListLabelsConfig(project_id=PROJ), token_credentials, 200, [{"name": "bug"}])
        assert r["action"] == "list_labels"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/projects/{ENC}/labels")

    @pytest.mark.asyncio
    async def test_create_label(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateLabelConfig(project_id=PROJ, name="bug", color="#FF0000"), token_credentials, 201, {"name": "bug"})
        assert r["action"] == "create_label"
        assert cap["method"] == "POST" and cap["json"]["name"] == "bug" and cap["json"]["color"] == "#FF0000"

    @pytest.mark.asyncio
    async def test_delete_label(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteLabelConfig(project_id=PROJ, label_id="bug"), token_credentials, 204, None)
        assert r["action"] == "delete_label"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/labels/bug")


class TestGitLabMilestonesMock:
    @pytest.mark.asyncio
    async def test_list_milestones(self, token_credentials):
        r, cap = await _run_capture(GitLabListMilestonesConfig(project_id=PROJ, state="active"), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_milestones"
        assert cap["method"] == "GET" and cap["params"]["state"] == "active"

    @pytest.mark.asyncio
    async def test_create_milestone(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateMilestoneConfig(project_id=PROJ, title="v1.0", due_date="2026-12-31"), token_credentials, 201, {"id": 1})
        assert r["action"] == "create_milestone"
        assert cap["method"] == "POST" and cap["json"]["title"] == "v1.0" and cap["json"]["due_date"] == "2026-12-31"


class TestGitLabMembersMock:
    @pytest.mark.asyncio
    async def test_add_member(self, token_credentials):
        r, cap = await _run_capture(GitLabAddMemberConfig(project_id=PROJ, user_id="99", access_level="40"), token_credentials, 201, {"id": 99})
        assert r["action"] == "add_member"
        assert cap["method"] == "POST"
        assert cap["json"]["user_id"] == 99 and cap["json"]["access_level"] == 40

    @pytest.mark.asyncio
    async def test_remove_member(self, token_credentials):
        r, cap = await _run_capture(GitLabRemoveMemberConfig(project_id=PROJ, user_id="99"), token_credentials, 204, None)
        assert r["action"] == "remove_member"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/members/99")


class TestGitLabReleasesReadMock:
    @pytest.mark.asyncio
    async def test_list_releases(self, token_credentials):
        r, cap = await _run_capture(GitLabListReleasesConfig(project_id=PROJ), token_credentials, 200, [{"tag_name": "v1"}])
        assert r["action"] == "list_releases"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/projects/{ENC}/releases")

    @pytest.mark.asyncio
    async def test_get_release(self, token_credentials):
        r, cap = await _run_capture(GitLabGetReleaseConfig(project_id=PROJ, tag_name="v1.0"), token_credentials, 200, {"tag_name": "v1.0"})
        assert r["action"] == "get_release"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/releases/v1.0")


class TestGitLabCommitStatusMock:
    @pytest.mark.asyncio
    async def test_set_commit_status(self, token_credentials):
        r, cap = await _run_capture(
            GitLabSetCommitStatusConfig(project_id=PROJ, sha="abc123", state="success", name="ci/ext"),
            token_credentials, 201, {"id": 1, "status": "success"},
        )
        assert r["action"] == "set_commit_status"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/statuses/abc123")
        assert cap["json"]["state"] == "success" and cap["json"]["name"] == "ci/ext"


from nodes.gitlab_node import GitLabOAuthCredential


class TestGitLabAuthHeaderMock:
    """Every token type must ride Authorization: Bearer — GitLab rejects OAuth
    tokens sent via PRIVATE-TOKEN."""

    @pytest.mark.asyncio
    async def test_pat_uses_bearer(self, token_credentials):
        r, cap = await _run_capture(GitLabGetUserConfig(), token_credentials, 200, {"id": 1})
        assert cap["headers"]["Authorization"] == "Bearer glpat-test-token-12345"
        assert "PRIVATE-TOKEN" not in cap["headers"]

    @pytest.mark.asyncio
    async def test_oauth_uses_bearer(self):
        oauth = GitLabOAuthCredential(access_token="oauth-access-tok")
        config = GitLabNodeConfig(config=GitLabGetUserConfig(), credentials=oauth)
        captured = {}
        client = create_capturing_client(captured, 200, {"id": 1})
        with patch("nodes.gitlab_node.httpx.AsyncClient", return_value=client):
            result = await create_gitlab_node(config).execute({})
        assert result["status"] == "success"
        assert captured["headers"]["Authorization"] == "Bearer oauth-access-tok"
        assert "PRIVATE-TOKEN" not in captured["headers"]


class TestGitLabDevOpsExtraMock:
    @pytest.mark.asyncio
    async def test_list_environments(self, token_credentials):
        r, cap = await _run_capture(GitLabListEnvironmentsConfig(project_id=PROJ), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_environments"
        assert cap["method"] == "GET" and cap["url"].endswith(f"/projects/{ENC}/environments")

    @pytest.mark.asyncio
    async def test_create_environment(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateEnvironmentConfig(project_id=PROJ, name="production", external_url="https://x"), token_credentials, 201, {"id": 1})
        assert r["action"] == "create_environment"
        assert cap["method"] == "POST" and cap["json"]["name"] == "production"

    @pytest.mark.asyncio
    async def test_stop_environment(self, token_credentials):
        r, cap = await _run_capture(GitLabStopEnvironmentConfig(project_id=PROJ, environment_id="9"), token_credentials, 200, {"id": 9})
        assert r["action"] == "stop_environment"
        assert cap["method"] == "POST" and cap["url"].endswith(f"/environments/9/stop")

    @pytest.mark.asyncio
    async def test_delete_environment(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteEnvironmentConfig(project_id=PROJ, environment_id="9"), token_credentials, 204, None)
        assert r["action"] == "delete_environment"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/environments/9")

    @pytest.mark.asyncio
    async def test_list_deployments(self, token_credentials):
        r, cap = await _run_capture(GitLabListDeploymentsConfig(project_id=PROJ, environment="production"), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_deployments"
        assert cap["method"] == "GET" and cap["params"]["environment"] == "production"

    @pytest.mark.asyncio
    async def test_get_deployment(self, token_credentials):
        r, cap = await _run_capture(GitLabGetDeploymentConfig(project_id=PROJ, deployment_id="5"), token_credentials, 200, {"id": 5})
        assert r["action"] == "get_deployment"
        assert cap["url"].endswith(f"/deployments/5")

    @pytest.mark.asyncio
    async def test_create_deployment(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateDeploymentConfig(project_id=PROJ, environment="production", sha="abc", ref="main", status="success"), token_credentials, 201, {"id": 1})
        assert r["action"] == "create_deployment"
        assert cap["json"]["environment"] == "production" and cap["json"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_wikis(self, token_credentials):
        r, cap = await _run_capture(GitLabListWikisConfig(project_id=PROJ), token_credentials, 200, [{"slug": "home"}])
        assert r["action"] == "list_wikis"
        assert cap["url"].endswith(f"/projects/{ENC}/wikis")

    @pytest.mark.asyncio
    async def test_get_wiki(self, token_credentials):
        r, cap = await _run_capture(GitLabGetWikiConfig(project_id=PROJ, slug="home"), token_credentials, 200, {"slug": "home"})
        assert r["action"] == "get_wiki"
        assert cap["url"].endswith(f"/wikis/home")

    @pytest.mark.asyncio
    async def test_create_wiki(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateWikiConfig(project_id=PROJ, title="Home", content="hi"), token_credentials, 201, {"slug": "home"})
        assert r["action"] == "create_wiki"
        assert cap["method"] == "POST" and cap["json"]["title"] == "Home"

    @pytest.mark.asyncio
    async def test_update_wiki(self, token_credentials):
        r, cap = await _run_capture(GitLabUpdateWikiConfig(project_id=PROJ, slug="home", content="v2"), token_credentials, 200, {"slug": "home"})
        assert r["action"] == "update_wiki"
        assert cap["method"] == "PUT" and cap["url"].endswith(f"/wikis/home")

    @pytest.mark.asyncio
    async def test_delete_wiki(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteWikiConfig(project_id=PROJ, slug="home"), token_credentials, 204, None)
        assert r["action"] == "delete_wiki"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/wikis/home")

    @pytest.mark.asyncio
    async def test_list_protected_branches(self, token_credentials):
        r, cap = await _run_capture(GitLabListProtectedBranchesConfig(project_id=PROJ), token_credentials, 200, [{"name": "main"}])
        assert r["action"] == "list_protected_branches"
        assert cap["url"].endswith(f"/projects/{ENC}/protected_branches")

    @pytest.mark.asyncio
    async def test_protect_branch(self, token_credentials):
        r, cap = await _run_capture(GitLabProtectBranchConfig(project_id=PROJ, name="main"), token_credentials, 201, {"name": "main"})
        assert r["action"] == "protect_branch"
        assert cap["method"] == "POST" and cap["params"]["name"] == "main"

    @pytest.mark.asyncio
    async def test_unprotect_branch(self, token_credentials):
        r, cap = await _run_capture(GitLabUnprotectBranchConfig(project_id=PROJ, name="main"), token_credentials, 204, None)
        assert r["action"] == "unprotect_branch"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/protected_branches/main")

    @pytest.mark.asyncio
    async def test_list_todos(self, token_credentials):
        r, cap = await _run_capture(GitLabListTodosConfig(state="pending"), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_todos"
        assert cap["url"].endswith("/todos") and cap["params"]["state"] == "pending"

    @pytest.mark.asyncio
    async def test_mark_todo_done(self, token_credentials):
        r, cap = await _run_capture(GitLabMarkTodoDoneConfig(todo_id="5"), token_credentials, 200, {"id": 5})
        assert r["action"] == "mark_todo_done"
        assert cap["method"] == "POST" and cap["url"].endswith("/todos/5/mark_as_done")

    @pytest.mark.asyncio
    async def test_mark_all_todos_done(self, token_credentials):
        r, cap = await _run_capture(GitLabMarkAllTodosDoneConfig(), token_credentials, 204, None)
        assert r["action"] == "mark_all_todos_done"
        assert cap["method"] == "POST" and cap["url"].endswith("/todos/mark_as_done")

    @pytest.mark.asyncio
    async def test_list_hooks(self, token_credentials):
        r, cap = await _run_capture(GitLabListHooksConfig(project_id=PROJ), token_credentials, 200, [{"id": 1}])
        assert r["action"] == "list_hooks"
        assert cap["url"].endswith(f"/projects/{ENC}/hooks")

    @pytest.mark.asyncio
    async def test_create_hook(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateHookConfig(project_id=PROJ, url="https://x", token="sec"), token_credentials, 201, {"id": 1})
        assert r["action"] == "create_hook"
        assert cap["method"] == "POST" and cap["json"]["url"] == "https://x" and cap["json"]["push_events"] is True

    @pytest.mark.asyncio
    async def test_delete_hook(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteHookConfig(project_id=PROJ, hook_id="3"), token_credentials, 204, None)
        assert r["action"] == "delete_hook"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/hooks/3")

    @pytest.mark.asyncio
    async def test_update_release(self, token_credentials):
        r, cap = await _run_capture(GitLabUpdateReleaseConfig(project_id=PROJ, tag_name="v1.0", name="v1.0.1"), token_credentials, 200, {"tag_name": "v1.0"})
        assert r["action"] == "update_release"
        assert cap["method"] == "PUT" and cap["url"].endswith(f"/releases/v1.0")

    @pytest.mark.asyncio
    async def test_delete_release(self, token_credentials):
        r, cap = await _run_capture(GitLabDeleteReleaseConfig(project_id=PROJ, tag_name="v1.0"), token_credentials, 200, {"tag_name": "v1.0"})
        assert r["action"] == "delete_release"
        assert cap["method"] == "DELETE" and cap["url"].endswith(f"/releases/v1.0")

    @pytest.mark.asyncio
    async def test_list_epics(self, token_credentials):
        r, cap = await _run_capture(GitLabListEpicsConfig(group_id="mygroup", state="opened"), token_credentials, 200, [{"iid": 1}])
        assert r["action"] == "list_epics"
        assert cap["url"].endswith("/groups/mygroup/epics") and cap["params"]["state"] == "opened"

    @pytest.mark.asyncio
    async def test_create_epic(self, token_credentials):
        r, cap = await _run_capture(GitLabCreateEpicConfig(group_id="mygroup", title="Q3"), token_credentials, 201, {"iid": 1})
        assert r["action"] == "create_epic"
        assert cap["method"] == "POST" and cap["json"]["title"] == "Q3"

    @pytest.mark.asyncio
    async def test_update_epic(self, token_credentials):
        r, cap = await _run_capture(GitLabUpdateEpicConfig(group_id="mygroup", epic_iid="2", state_event="close"), token_credentials, 200, {"iid": 2})
        assert r["action"] == "update_epic"
        assert cap["method"] == "PUT" and cap["url"].endswith("/groups/mygroup/epics/2")
        assert cap["json"]["state_event"] == "close"


class TestGitLabTodosStateMock:
    @pytest.mark.asyncio
    async def test_list_todos_empty_state_not_sent(self, token_credentials):
        # GitLab 400s on state="" — the node must omit it, not forward it.
        r, cap = await _run_capture(GitLabListTodosConfig(state=""), token_credentials, 200, [])
        assert r["action"] == "list_todos"
        assert cap["params"].get("state") in (None, ...) or "state" not in cap["params"]

    @pytest.mark.asyncio
    async def test_list_todos_valid_state_sent(self, token_credentials):
        r, cap = await _run_capture(GitLabListTodosConfig(state="pending"), token_credentials, 200, [])
        assert cap["params"]["state"] == "pending"


class TestGitLabGroupTriggerMock:
    @pytest.mark.asyncio
    async def test_on_group_event_passthrough(self):
        config = GitLabNodeConfig(
            config=GitLabGroupHookTriggerConfig(group_id="mygroup", webhook_url="https://x.hooks.example.test"),
            credentials=None,
        )
        result = await create_gitlab_node(config).execute({"object_kind": "push"})
        assert result["status"] == "success"
        assert result["action"] == "on_group_event"
        assert result["data"]["object_kind"] == "push"

    @pytest.mark.asyncio
    async def test_group_register_uses_groups_endpoint(self):
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={"status": "success", "data": {"id": 55}},
        ) as mock_req:
            extra = await GitLabNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "glpat-test", "host": "https://gitlab.com"},
                config={"operation": "on_group_event", "group_id": "mygroup", "event_types": "member,subgroup"},
                node_id="node-1",
            )
        assert extra["external_webhook_id"] == "55"
        endpoint = mock_req.call_args.args[3]
        assert endpoint == "/groups/mygroup/hooks"
        body = mock_req.call_args.kwargs["json_body"]
        assert body["member_events"] is True and body["subgroup_events"] is True
        assert body["project_events"] is False and body["push_events"] is False

    @pytest.mark.asyncio
    async def test_group_unregister_uses_groups_endpoint(self):
        with patch("nodes.gitlab_node._gitlab_request", return_value={"status": "success", "data": {}}) as mock_req:
            await GitLabNode._unregister_external_webhook(
                credential={"access_token": "t", "host": "https://gitlab.com"},
                config={"operation": "on_group_event", "group_id": "mygroup", "external_webhook_id": "55"},
                node_id="node-1",
            )
        assert mock_req.call_args.args[3] == "/groups/mygroup/hooks/55"

    def test_group_filter_event_name_member(self):
        config = {"operation": "on_group_event", "event_types": "member"}
        assert GitLabNode.filter_trigger_payload({"event_name": "user_add_to_group"}, config)
        assert not GitLabNode.filter_trigger_payload({"event_name": "subgroup_create"}, config)

    def test_group_filter_standard_object_kind(self):
        config = {"operation": "on_group_event", "event_types": "push,subgroup"}
        assert GitLabNode.filter_trigger_payload({"object_kind": "push"}, config)
        assert GitLabNode.filter_trigger_payload({"event_name": "subgroup_destroy"}, config)
        assert not GitLabNode.filter_trigger_payload({"object_kind": "pipeline"}, config)

    @pytest.mark.asyncio
    async def test_project_register_includes_confidential_and_new_flags(self):
        with patch(
            "nodes.gitlab_node._gitlab_request",
            return_value={"status": "success", "data": {"id": 1}},
        ) as mock_req:
            await GitLabNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "t", "host": "https://gitlab.com"},
                config={"project_id": "42", "event_types": "issue,emoji"},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        # selecting issue also subscribes confidential issues
        assert body["issues_events"] is True
        assert body["confidential_issues_events"] is True
        assert body["emoji_events"] is True
        assert body["push_events"] is False

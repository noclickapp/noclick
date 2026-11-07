"""
Mock tests for the Cursor REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Cloud Agents: create / list / get / archive / unarchive / delete / usage /
  list artifacts / download artifact
- Runs: add / list / get / cancel
- Discovery: list models / list repositories / get me
- Admin (Team): members / audit logs / daily usage / spend / usage events /
  set spend limit / remove member
- Analytics: team agent-edits / tabs / dau / models; per-user; ai commits / changes
- Trigger: on_agent_status_change passthrough + signature verification
- Error handling: API errors, missing credentials
- Dynamic options: repository + model dropdowns
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

from nodes.cursor_node import (
    CursorNode,
    CursorNodeConfig,
    CursorApiKeyCredential,
    CursorCreateAgentConfig,
    CursorListAgentsConfig,
    CursorGetAgentConfig,
    CursorArchiveAgentConfig,
    CursorUnarchiveAgentConfig,
    CursorDeleteAgentConfig,
    CursorAddRunConfig,
    CursorListRunsConfig,
    CursorGetRunConfig,
    CursorCancelRunConfig,
    CursorGetAgentUsageConfig,
    CursorListArtifactsConfig,
    CursorDownloadArtifactConfig,
    CursorListModelsConfig,
    CursorListRepositoriesConfig,
    CursorGetMeConfig,
    CursorListTeamMembersConfig,
    CursorGetAuditLogsConfig,
    CursorGetDailyUsageConfig,
    CursorGetTeamSpendConfig,
    CursorGetUsageEventsConfig,
    CursorSetUserSpendLimitConfig,
    CursorRemoveTeamMemberConfig,
    CursorTeamAgentEditsConfig,
    CursorTeamTabsConfig,
    CursorTeamDauConfig,
    CursorTeamModelsConfig,
    CursorPerUserAnalyticsConfig,
    CursorAiCommitsConfig,
    CursorAiChangesConfig,
    CursorAgentStatusTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return CursorApiKeyCredential(api_key="crsr_test_key_12345")


def create_cursor_node(config):
    return CursorNode(
        node_id="test-cursor-node",
        node_type="automation-cursor",
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


def create_mock_client(status_code=200, json_data=None, calls=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        if calls is not None:
            calls.append(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(config_obj, credentials, status_code, json_data, calls=None):
    config = CursorNodeConfig(config=config_obj, credentials=credentials)
    node = create_cursor_node(config)
    mock_client = create_mock_client(status_code, json_data, calls)
    with patch("nodes.cursor_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


class TestCursorCloudAgentsMock:
    @pytest.mark.asyncio
    async def test_create_agent(self, api_key_credentials):
        calls = []
        result = await _run(
            CursorCreateAgentConfig(
                prompt_text="Fix the bug",
                repository="https://github.com/org/repo",
                model="claude-4",
                branch="main",
            ),
            api_key_credentials,
            200,
            {"agent": {"id": "agent_1"}, "run": {"id": "run_1", "status": "CREATING"}},
            calls,
        )
        assert result["status"] == "success"
        assert result["action"] == "create_agent"
        assert result["data"]["agent"]["id"] == "agent_1"
        assert calls[0]["json"] == {
            "prompt": {"text": "Fix the bug"},
            "repos": [{"url": "https://github.com/org/repo", "startingRef": "main"}],
            "model": {"id": "claude-4"},
        }

    @pytest.mark.asyncio
    async def test_list_agents(self, api_key_credentials):
        calls = []
        result = await _run(
            CursorListAgentsConfig(cursor="bc-next", limit=10),
            api_key_credentials,
            200,
            {"items": [{"id": "a1"}, {"id": "a2"}], "nextCursor": "bc-next-2"},
            calls,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_agents"
        assert len(result["data"]["items"]) == 2
        assert result["data"]["nextCursor"] == "bc-next-2"
        assert calls[0]["params"] == {"cursor": "bc-next", "limit": 10}

    @pytest.mark.asyncio
    async def test_get_agent(self, api_key_credentials):
        result = await _run(
            CursorGetAgentConfig(agent_id="agent_1"),
            api_key_credentials,
            200,
            {"id": "agent_1", "status": "RUNNING"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_agent"
        assert result["data"]["id"] == "agent_1"

    @pytest.mark.asyncio
    async def test_archive_agent(self, api_key_credentials):
        result = await _run(
            CursorArchiveAgentConfig(agent_id="agent_1"),
            api_key_credentials,
            200,
            {"id": "agent_1", "archived": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "archive_agent"

    @pytest.mark.asyncio
    async def test_unarchive_agent(self, api_key_credentials):
        result = await _run(
            CursorUnarchiveAgentConfig(agent_id="agent_1"),
            api_key_credentials,
            200,
            {"id": "agent_1", "archived": False},
        )
        assert result["status"] == "success"
        assert result["action"] == "unarchive_agent"

    @pytest.mark.asyncio
    async def test_delete_agent(self, api_key_credentials):
        result = await _run(
            CursorDeleteAgentConfig(agent_id="agent_1"),
            api_key_credentials,
            204,
            None,
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_agent"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_agent_usage(self, api_key_credentials):
        result = await _run(
            CursorGetAgentUsageConfig(agent_id="agent_1"),
            api_key_credentials,
            200,
            {"totalUsage": {"inputTokens": 100, "outputTokens": 50}, "runs": []},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_agent_usage"
        assert result["data"]["totalUsage"]["inputTokens"] == 100

    @pytest.mark.asyncio
    async def test_list_artifacts(self, api_key_credentials):
        result = await _run(
            CursorListArtifactsConfig(agent_id="agent_1"),
            api_key_credentials,
            200,
            {"items": [{"path": "artifacts/out.txt"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_artifacts"

    @pytest.mark.asyncio
    async def test_download_artifact(self, api_key_credentials):
        result = await _run(
            CursorDownloadArtifactConfig(agent_id="agent_1", path="artifacts/out.txt"),
            api_key_credentials,
            200,
            {"url": "https://signed.example/out.txt"},
        )
        assert result["status"] == "success"
        assert result["action"] == "download_artifact"
        assert result["data"]["url"].startswith("https://")


class TestCursorRunsMock:
    @pytest.mark.asyncio
    async def test_add_run(self, api_key_credentials):
        result = await _run(
            CursorAddRunConfig(agent_id="agent_1", prompt_text="Also add tests"),
            api_key_credentials,
            200,
            {"run": {"id": "run_1", "status": "CREATING"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "add_run"
        assert result["data"]["run"]["status"] == "CREATING"

    @pytest.mark.asyncio
    async def test_list_runs(self, api_key_credentials):
        calls = []
        result = await _run(
            CursorListRunsConfig(agent_id="agent_1", cursor="run-next", limit=10),
            api_key_credentials,
            200,
            {"items": [{"id": "run_1"}], "nextCursor": "run-next-2"},
            calls,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_runs"
        assert result["data"]["items"][0]["id"] == "run_1"
        assert calls[0]["params"] == {"cursor": "run-next", "limit": 10}

    @pytest.mark.asyncio
    async def test_get_run(self, api_key_credentials):
        result = await _run(
            CursorGetRunConfig(agent_id="agent_1", run_id="run_1"),
            api_key_credentials,
            200,
            {"id": "run_1", "status": "FINISHED", "git": {"prUrl": "https://github.com/org/repo/pull/1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_run"
        assert result["data"]["git"]["prUrl"].endswith("/pull/1")

    @pytest.mark.asyncio
    async def test_cancel_run(self, api_key_credentials):
        result = await _run(
            CursorCancelRunConfig(agent_id="agent_1", run_id="run_1"),
            api_key_credentials,
            200,
            {"id": "run_1", "status": "CANCELLED"},
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_run"


class TestCursorDiscoveryMock:
    @pytest.mark.asyncio
    async def test_list_models(self, api_key_credentials):
        result = await _run(
            CursorListModelsConfig(),
            api_key_credentials,
            200,
            {"items": [{"id": "claude-4"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_models"

    @pytest.mark.asyncio
    async def test_list_repositories(self, api_key_credentials):
        result = await _run(
            CursorListRepositoriesConfig(),
            api_key_credentials,
            200,
            {"items": [{"url": "https://github.com/org/repo"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_repositories"

    @pytest.mark.asyncio
    async def test_get_me(self, api_key_credentials):
        calls = []
        result = await _run(
            CursorGetMeConfig(),
            api_key_credentials,
            200,
            {"apiKeyName": "Production", "userEmail": "dev@example.com"},
            calls,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["apiKeyName"] == "Production"
        assert calls[0]["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record,expected_label",
    [
        ({"apiKeyName": "Developer", "userEmail": "dev@example.com"}, "dev@example.com"),
        ({"apiKeyName": "Team Admin", "createdAt": "2026-04-13T18:30:00.000Z"}, "Team Admin"),
    ],
)
async def test_connection_evidence_accepts_cloud_and_team_keys(record, expected_label):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.credential_connect import validate_for_connect

    calls = []
    mock_client = create_mock_client(200, record, calls)
    with patch("nodes.cursor_node.httpx.AsyncClient", return_value=mock_client):
        evidence = await collect_evidence(
            node_type="automation-cursor",
            credential_data={"api_key": "opaque_key"},
            user_id="test-user",
        )
        verdict = await validate_for_connect(
            credential_type="cursor_api_key",
            credential_data={"api_key": "opaque_key"},
            user_id="test-user",
        )

    assert evidence.reachable is True
    assert evidence.account_label == expected_label
    assert verdict.ok
    assert verdict.evidence is not None
    assert verdict.evidence.account_label == expected_label
    assert len(calls) == 2
    assert all(call["url"] == "https://api.cursor.com/v1/me" for call in calls)
    assert all(call["headers"]["Authorization"].startswith("Basic ") for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [{}, [], {"apiKeyName": ""}])
async def test_connection_evidence_does_not_confirm_malformed_identity(record):
    from nodes.core.connection_evidence import collect_evidence

    mock_client = create_mock_client(200, record)
    with patch("nodes.cursor_node.httpx.AsyncClient", return_value=mock_client):
        evidence = await collect_evidence(
            node_type="automation-cursor",
            credential_data={"api_key": "opaque_key"},
            user_id="test-user",
        )

    assert evidence.reachable is None
    assert evidence.account_label is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_connection_evidence_rejects_refused_identity(status_code):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.credential_connect import validate_for_connect

    mock_client = create_mock_client(status_code, {"error": "provider body with secret"})
    with patch("nodes.cursor_node.httpx.AsyncClient", return_value=mock_client):
        evidence = await collect_evidence(
            node_type="automation-cursor",
            credential_data={"api_key": "opaque_key"},
            user_id="test-user",
        )
        verdict = await validate_for_connect(
            credential_type="cursor_api_key",
            credential_data={"api_key": "opaque_key"},
            user_id="test-user",
        )

    assert evidence.reachable is False
    assert str(status_code) in evidence.error
    assert "provider body" not in evidence.error
    assert not verdict.ok


class TestCursorAdminMock:
    @pytest.mark.asyncio
    async def test_list_team_members(self, api_key_credentials):
        result = await _run(
            CursorListTeamMembersConfig(),
            api_key_credentials,
            200,
            {"teamMembers": [{"email": "a@b.com", "role": "member"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_team_members"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "config_cls, operation, fields",
        [
            (CursorGetAuditLogsConfig, "get_audit_logs", {"start_date": "startTime", "end_date": "endTime"}),
            (CursorGetDailyUsageConfig, "get_daily_usage", {"start_date": "startDate", "end_date": "endDate"}),
            (CursorGetTeamSpendConfig, "get_team_spend", {"search": "searchTerm", "page": "page", "page_size": "pageSize"}),
            (CursorGetUsageEventsConfig, "get_usage_events", {"start_date": "startDate", "end_date": "endDate", "page": "page", "page_size": "pageSize"}),
            (CursorSetUserSpendLimitConfig, "set_user_spend_limit", {"user_email": "userEmail", "spend_limit_dollars": "spendLimitDollars"}),
            (CursorRemoveTeamMemberConfig, "remove_team_member", {"user_email": "email"}),
        ],
    )
    async def test_documented_admin_request(self, api_key_credentials, config_cls, operation, fields):
        examples = json.loads((Path(__file__).parent / "fixtures/cursor/admin_examples.json").read_text())
        example = examples[operation]
        request = example["request"]
        calls = []
        result = await _run(
            config_cls(**{field: str(request[key]) for field, key in fields.items()}),
            api_key_credentials,
            200,
            example["response"],
            calls,
        )
        assert result["status"] == "success"
        assert result["action"] == operation
        assert result["data"] == example["response"]
        payload = "params" if operation == "get_audit_logs" else "json"
        assert calls[0][payload] == {key: request[key] for key in fields.values()}

    @pytest.mark.asyncio
    async def test_optional_admin_numbers_are_omitted(self, api_key_credentials):
        examples = json.loads((Path(__file__).parent / "fixtures/cursor/admin_examples.json").read_text())
        for config_obj in (
            CursorGetTeamSpendConfig(page=None, page_size=None),
            CursorGetUsageEventsConfig(page=None, page_size=None),
        ):
            calls = []
            await _run(config_obj, api_key_credentials, 200, examples[config_obj.operation]["response"], calls)
            assert calls[0]["json"] == {}


class TestCursorAnalyticsMock:
    @pytest.mark.asyncio
    async def test_team_agent_edits(self, api_key_credentials):
        result = await _run(
            CursorTeamAgentEditsConfig(start_date="1700000000000", end_date="1700100000000"),
            api_key_credentials,
            200,
            {"acceptedLines": 120},
        )
        assert result["status"] == "success"
        assert result["action"] == "team_agent_edits"

    @pytest.mark.asyncio
    async def test_team_tabs(self, api_key_credentials):
        result = await _run(
            CursorTeamTabsConfig(start_date="1700000000000", end_date="1700100000000"),
            api_key_credentials,
            200,
            {"acceptedSuggestions": 80},
        )
        assert result["status"] == "success"
        assert result["action"] == "team_tabs"

    @pytest.mark.asyncio
    async def test_team_dau(self, api_key_credentials):
        result = await _run(
            CursorTeamDauConfig(start_date="1700000000000", end_date="1700100000000"),
            api_key_credentials,
            200,
            {"dau": [{"date": "2026-01-01", "count": 12}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "team_dau"

    @pytest.mark.asyncio
    async def test_team_models(self, api_key_credentials):
        result = await _run(
            CursorTeamModelsConfig(start_date="1700000000000", end_date="1700100000000"),
            api_key_credentials,
            200,
            {"models": [{"name": "claude-4", "requests": 100}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "team_models"

    @pytest.mark.asyncio
    async def test_per_user_analytics(self, api_key_credentials):
        result = await _run(
            CursorPerUserAnalyticsConfig(metric="tabs", page="1", page_size="20"),
            api_key_credentials,
            200,
            {"users": [{"email": "ada@b.com", "tabs": 30}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "per_user_analytics"

    @pytest.mark.asyncio
    async def test_ai_commits(self, api_key_credentials):
        result = await _run(
            CursorAiCommitsConfig(start_date="1700000000000", page="1", page_size="20"),
            api_key_credentials,
            200,
            {"commits": [{"sha": "abc123", "tabLines": 10}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "ai_commits"

    @pytest.mark.asyncio
    async def test_ai_changes(self, api_key_credentials):
        result = await _run(
            CursorAiChangesConfig(start_date="1700000000000", page="1", page_size="20"),
            api_key_credentials,
            200,
            {"changes": [{"changeId": "ch_1", "files": ["a.py"]}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "ai_changes"


class TestCursorTriggerMock:
    @pytest.mark.asyncio
    async def test_on_agent_status_change_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = CursorNodeConfig(
            config=CursorAgentStatusTriggerConfig(
                webhook_url="https://abc.hooks.example.test", signing_secret="s" * 32
            ),
            credentials=None,
        )
        node = create_cursor_node(config)
        payload = {"event": "statusChange", "status": "FINISHED", "id": "agent_1"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_agent_status_change"
        assert result["data"]["status"] == "FINISHED"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_nonterminal_or_other_webhook_event_does_not_fire(self):
        config = CursorNodeConfig(
            config=CursorAgentStatusTriggerConfig(signing_secret="s" * 32),
            credentials=None,
        )
        node = create_cursor_node(config)
        for payload in (
            {"event": "statusChange", "status": "RUNNING"},
            {"event": "other", "status": "FINISHED"},
        ):
            assert not CursorNode.filter_trigger_payload(payload, {})
            result = await node.execute(payload)
            assert node.trigger_produced_no_event(result)
            assert result["data"] == {}

    def test_verify_webhook_signature(self):
        secret = "s" * 32
        body = b'{"event":"statusChange","status":"FINISHED"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # signed form: sha256=<hex>
        assert CursorNode.verify_webhook_signature(
            body, {"x-webhook-signature": f"sha256={good_sig}"}, {"signing_secret": secret}
        )
        # The documented signature format includes the sha256= prefix.
        assert not CursorNode.verify_webhook_signature(
            body, {"x-webhook-signature": good_sig}, {"signing_secret": secret}
        )
        # wrong signature rejected
        assert not CursorNode.verify_webhook_signature(
            body, {"x-webhook-signature": "sha256=deadbeef"}, {"signing_secret": secret}
        )
        assert not CursorNode.verify_webhook_signature(
            body, {"x-webhook-signature": "sha256=" + "é" * 64}, {"signing_secret": secret}
        )
        assert not CursorNode.verify_webhook_signature(
            body, {"x-webhook-signature": "sha256=" + "g" * 64}, {"signing_secret": secret}
        )
        # missing header but secret configured -> reject
        assert not CursorNode.verify_webhook_signature(body, {}, {"signing_secret": secret})
        # No secret means the inbound delivery cannot be authenticated.
        assert not CursorNode.verify_webhook_signature(body, {}, {})


class TestCursorErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_non_json_success_does_not_expose_response_body(self, api_key_credentials):
        response = create_mock_response()
        response.text = "private response crsr_test_key_12345"
        response.json = Mock(side_effect=ValueError("invalid JSON"))
        client = create_mock_client()

        async def request(*args, **kwargs):
            return response

        client.request = request
        node = create_cursor_node(CursorNodeConfig(
            config=CursorGetAgentConfig(agent_id="agent_1"),
            credentials=api_key_credentials,
        ))
        with patch("nodes.cursor_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["error"] == "Cursor returned a non-JSON response"
        assert "crsr_test_key" not in str(result)

    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        result = await _run(
            CursorGetAgentConfig(agent_id="missing"),
            api_key_credentials,
            404,
            {"error": {"message": "Agent not found; key=crsr_test_key_12345"}},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert result["error"] == "Cursor API request failed (HTTP 404)"
        assert "crsr_test_key" not in result["error"]

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = CursorNodeConfig(config=CursorGetMeConfig(), credentials=None)
        node = create_cursor_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestCursorDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_repository_options(self):
        async def fake_request(*args, **kwargs):
            return {"status": "success", "data": {"items": [{"url": "https://github.com/org/repo"}]}}

        with patch("nodes.cursor_node._cursor_request", side_effect=fake_request):
            result = await CursorNode.load_field_options(
                "repository", {"api_key": "crsr_test"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "https://github.com/org/repo"
        assert result["options"][0]["label"] == "org/repo"

    @pytest.mark.asyncio
    async def test_load_model_options(self):
        async def fake_request(*args, **kwargs):
            return {"status": "success", "data": {"items": [{"id": "claude-4", "displayName": "Claude 4"}]}}

        with patch("nodes.cursor_node._cursor_request", side_effect=fake_request):
            result = await CursorNode.load_field_options(
                "model", {"api_key": "crsr_test"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "claude-4"
        assert result["options"][0]["label"] == "Claude 4"

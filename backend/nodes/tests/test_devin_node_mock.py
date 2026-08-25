"""
Mock tests for the Devin REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Sessions: create, list, get, send message, update tags, terminate
- Attachments: upload
- Knowledge: list, create, update, delete
- Playbooks: list, get, create
- Secrets: list, create, delete
- Account: get self
- Error handling: API errors, missing credentials
- Dynamic options: session + playbook dropdowns
"""

import pytest
from unittest.mock import Mock, patch

from nodes.devin_node import (
    DevinNode,
    DevinNodeConfig,
    DevinApiKeyCredential,
    DevinCreateSessionConfig,
    DevinListSessionsConfig,
    DevinGetSessionConfig,
    DevinSendMessageConfig,
    DevinUpdateTagsConfig,
    DevinTerminateSessionConfig,
    DevinUploadAttachmentConfig,
    DevinListKnowledgeConfig,
    DevinCreateKnowledgeConfig,
    DevinUpdateKnowledgeConfig,
    DevinDeleteKnowledgeConfig,
    DevinListPlaybooksConfig,
    DevinGetPlaybookConfig,
    DevinCreatePlaybookConfig,
    DevinListSecretsConfig,
    DevinCreateSecretConfig,
    DevinDeleteSecretConfig,
    DevinGetSelfConfig,
    DevinOnSessionFinishedConfig,
)


@pytest.fixture
def api_key_credentials():
    return DevinApiKeyCredential(api_key="apk_test_key_12345")


def create_devin_node(config):
    return DevinNode(
        node_id="test-devin-node",
        node_type="automation-devin",
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


class TestDevinSessionsMock:
    @pytest.mark.asyncio
    async def test_create_session(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinCreateSessionConfig(
                prompt="Fix the failing test in repo X",
                title="CI fix",
                tags="ci,bug",
                max_acu_limit="20",
            ),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"session_id": "devin-abc", "status": "running"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_session"
        assert result["data"]["session_id"] == "devin-abc"

    @pytest.mark.asyncio
    async def test_create_session_invalid_schema(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinCreateSessionConfig(prompt="do x", output_schema="{not json"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        # No HTTP call should be needed; bad JSON short-circuits to error.
        result = await node.execute({})
        assert result["status"] == "error"
        assert "JSON" in str(result["error"])

    @pytest.mark.asyncio
    async def test_list_sessions(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinListSessionsConfig(limit="10"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(
            200, {"sessions": [{"session_id": "devin-1"}, {"session_id": "devin-2"}]}
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_sessions"
        assert len(result["data"]["sessions"]) == 2

    @pytest.mark.asyncio
    async def test_get_session(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinGetSessionConfig(session_id="devin-abc"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(
            200, {"session_id": "devin-abc", "status": "finished", "structured_output": {"ok": True}}
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_session"
        assert result["data"]["status"] == "finished"

    @pytest.mark.asyncio
    async def test_send_message(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinSendMessageConfig(session_id="devin-abc", message="Also update the docs"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_message"

    @pytest.mark.asyncio
    async def test_update_tags(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinUpdateTagsConfig(session_id="devin-abc", tags="done,reviewed"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"tags": ["done", "reviewed"]})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_tags"

    @pytest.mark.asyncio
    async def test_terminate_session(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinTerminateSessionConfig(session_id="devin-abc"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "terminate_session"


class TestDevinAttachmentsMock:
    @pytest.mark.asyncio
    async def test_upload_attachment(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinUploadAttachmentConfig(file_name="spec.txt", content="hello world"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        # Devin returns a plain JSON string (the URL), not a JSON object.
        mock_client = create_mock_client(
            200, "https://api.devin.ai/v1/attachments/uuid/spec.txt"
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_attachment"
        assert "url" in result["data"]
        assert result["data"]["url"] == "https://api.devin.ai/v1/attachments/uuid/spec.txt"


class TestDevinKnowledgeMock:
    @pytest.mark.asyncio
    async def test_list_knowledge(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinListKnowledgeConfig(), credentials=api_key_credentials
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"notes": [{"id": "k1"}]})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_knowledge"

    @pytest.mark.asyncio
    async def test_create_knowledge(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinCreateKnowledgeConfig(
                name="Deploy steps",
                body="Run deployment command",
                trigger_description="When deploying",
            ),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"id": "k2", "name": "Deploy steps"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_knowledge"
        assert result["data"]["id"] == "k2"

    @pytest.mark.asyncio
    async def test_update_knowledge(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinUpdateKnowledgeConfig(note_id="k2", body="Updated body", trigger_description="When deploying"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"id": "k2"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_knowledge"

    @pytest.mark.asyncio
    async def test_delete_knowledge(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinDeleteKnowledgeConfig(note_id="k2"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_knowledge"


class TestDevinPlaybooksMock:
    @pytest.mark.asyncio
    async def test_list_playbooks(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinListPlaybooksConfig(), credentials=api_key_credentials
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"playbooks": [{"playbook_id": "p1"}]})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_playbooks"

    @pytest.mark.asyncio
    async def test_get_playbook(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinGetPlaybookConfig(playbook_id="p1"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"playbook_id": "p1", "title": "Refactor"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_playbook"
        assert result["data"]["playbook_id"] == "p1"

    @pytest.mark.asyncio
    async def test_create_playbook(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinCreatePlaybookConfig(title="QA pass", body="Run the test suite"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"playbook_id": "p2", "title": "QA pass"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_playbook"


class TestDevinSecretsMock:
    @pytest.mark.asyncio
    async def test_list_secrets(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinListSecretsConfig(), credentials=api_key_credentials
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"secrets": [{"id": "s1", "key": "GH_TOKEN"}]})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_secrets"

    @pytest.mark.asyncio
    async def test_create_secret(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinCreateSecretConfig(key="GH_TOKEN", value="ghp_xxx", secret_type="key-value", note="GitHub token", sensitive="true"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"id": "s2", "key": "GH_TOKEN"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_secret"
        assert result["data"]["id"] == "s2"

    @pytest.mark.asyncio
    async def test_delete_secret(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinDeleteSecretConfig(secret_id="s2"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_secret"


class TestDevinAccountMock:
    @pytest.mark.asyncio
    async def test_get_self(self, api_key_credentials):
        config = DevinNodeConfig(config=DevinGetSelfConfig(), credentials=api_key_credentials)
        node = create_devin_node(config)
        mock_client = create_mock_client(200, {"principal": "service-user", "org_id": "org-1"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_self"
        assert result["data"]["org_id"] == "org-1"


class TestDevinErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = DevinNodeConfig(
            config=DevinGetSessionConfig(session_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(404, {"error": "Session not found"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = DevinNodeConfig(config=DevinGetSelfConfig(), credentials=None)
        node = create_devin_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestDevinDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_session_options(self):
        with patch(
            "nodes.devin_node._devin_request",
            return_value={
                "status": "success",
                "data": {"sessions": [{"session_id": "devin-1", "title": "Fix bug"}]},
            },
        ):
            result = await DevinNode.load_field_options(
                "session_id", {"api_key": "apk_test"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "devin-1"
        assert "Fix bug" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_playbook_options(self):
        with patch(
            "nodes.devin_node._devin_request",
            return_value={
                "status": "success",
                "data": {"playbooks": [{"playbook_id": "p1", "title": "Refactor"}]},
            },
        ):
            result = await DevinNode.load_field_options(
                "playbook_id", {"api_key": "apk_test"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "p1"
        assert "Refactor" in result["options"][0]["label"]


def _bind_devin_state(node, initial=None):
    """Back the node's seen-set with an in-memory node-state store (the dedup
    set now lives in workflow_node_state, not config)."""
    store = dict(initial or {})

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(store))
        if new_state is not None:
            store.clear()
            store.update(new_state)
        return result

    node._update_node_state = _update
    return store


class TestDevinTriggerMock:
    def test_resolve_trigger_payload_poll_returns_none(self):
        """Poll trigger must return None so execute() runs and polls the API."""
        out = DevinNode.resolve_trigger_payload(
            {"foo": "bar"}, {"operation": "on_session_finished"}
        )
        assert out is None

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        """Non-trigger ops pass the payload through unchanged."""
        payload = {"foo": "bar"}
        out = DevinNode.resolve_trigger_payload(payload, {"operation": "get_session"})
        assert out == payload

    @pytest.mark.asyncio
    async def test_poll_baselines_on_first_run(self, api_key_credentials):
        """First poll records the currently-finished sessions and emits NOTHING,
        so enabling the trigger doesn't fire the whole backlog."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        store = _bind_devin_state(node)
        mock_client = create_mock_client(
            200,
            {
                "sessions": [
                    {"session_id": "devin-1", "status": "finished"},
                    {"session_id": "devin-3", "status": "blocked"},
                ]
            },
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True
        # Baseline recorded the finished sessions in node state.
        assert set(store["seen_session_keys"]) == {"devin-1:finished", "devin-3:blocked"}

    @pytest.mark.asyncio
    async def test_poll_emits_only_terminal_sessions(self, api_key_credentials):
        """Only sessions in a terminal status are emitted; running ones are skipped."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        store = _bind_devin_state(node, {"seen_session_keys": []})  # baselined, empty
        mock_client = create_mock_client(
            200,
            {
                "sessions": [
                    {"session_id": "devin-1", "status": "finished"},
                    {"session_id": "devin-2", "status": "running"},
                    {"session_id": "devin-3", "status": "blocked"},
                ]
            },
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_session_finished"
        assert result["new_count"] == 2
        emitted_ids = {s["session_id"] for s in result["items"]}
        assert emitted_ids == {"devin-1", "devin-3"}
        # Node state now records both terminal sessions; running never enters it.
        assert "devin-1:finished" in store["seen_session_keys"]
        assert "devin-3:blocked" in store["seen_session_keys"]
        assert not any(k.startswith("devin-2") for k in store["seen_session_keys"])

    @pytest.mark.asyncio
    async def test_poll_dedupes_via_cursor(self, api_key_credentials):
        """A session already in the seen-set must NOT be re-emitted."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        store = _bind_devin_state(node, {"seen_session_keys": ["devin-1:finished"]})
        mock_client = create_mock_client(
            200,
            {
                "sessions": [
                    {"session_id": "devin-1", "status": "finished"},
                    {"session_id": "devin-2", "status": "expired"},
                ]
            },
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        # devin-1 already seen -> only devin-2 is new.
        assert result["new_count"] == 1
        assert result["items"][0]["session_id"] == "devin-2"
        # Seen-set keeps the previously-seen key AND the newly-seen one.
        assert "devin-1:finished" in store["seen_session_keys"]
        assert "devin-2:expired" in store["seen_session_keys"]

    @pytest.mark.asyncio
    async def test_poll_status_change_refires(self, api_key_credentials):
        """If a session transitions to a NEW terminal status, it fires again
        because the seen-set key includes the status."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        _bind_devin_state(node, {"seen_session_keys": ["devin-1:blocked"]})
        mock_client = create_mock_client(
            200, {"sessions": [{"session_id": "devin-1", "status": "finished"}]}
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert result["items"][0]["status"] == "finished"

    @pytest.mark.asyncio
    async def test_poll_filters_by_tags(self, api_key_credentials):
        """When tags are configured, only sessions carrying all of them fire."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(tags="release"),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        _bind_devin_state(node, {"seen_session_keys": []})  # baselined, empty
        mock_client = create_mock_client(
            200,
            {
                "sessions": [
                    {"session_id": "devin-1", "status": "finished", "tags": ["release", "ci"]},
                    {"session_id": "devin-2", "status": "finished", "tags": ["ci"]},
                ]
            },
        )
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert result["items"][0]["session_id"] == "devin-1"

    @pytest.mark.asyncio
    async def test_poll_api_error_surfaces(self, api_key_credentials):
        """An API error during polling surfaces as an error result (nothing fired)."""
        config = DevinNodeConfig(
            config=DevinOnSessionFinishedConfig(),
            credentials=api_key_credentials,
        )
        node = create_devin_node(config)
        mock_client = create_mock_client(429, {"error": "rate limited"})
        with patch("nodes.devin_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 429

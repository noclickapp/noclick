"""
Mock tests for the PhantomBuster REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Account: get user
- Agents: list, get, launch, launch-soon, launch-sync, stop, save, delete
- Containers: list, get, get output
- Scripts: list, get, get code, save, delete
- Organization: get org, get org resources
- Org storage: save leads, list lead lists, save lead list
- AI / utilities: AI completion, solve hCaptcha, IP geolocation
- Trigger: receive_webhook passthrough
- Error handling: API errors, missing credentials
- Dynamic options: agent dropdown
"""

import pytest
from unittest.mock import Mock, patch

from nodes.phantombuster_node import (
    PhantomBusterNode,
    PhantomBusterNodeConfig,
    PhantomBusterApiKeyCredential,
    PhantomBusterGetUserConfig,
    PhantomBusterListAgentsConfig,
    PhantomBusterGetAgentConfig,
    PhantomBusterLaunchAgentConfig,
    PhantomBusterLaunchAgentSoonConfig,
    PhantomBusterLaunchAgentSyncConfig,
    PhantomBusterStopAgentConfig,
    PhantomBusterSaveAgentConfig,
    PhantomBusterDeleteAgentConfig,
    PhantomBusterListContainersConfig,
    PhantomBusterGetContainerConfig,
    PhantomBusterGetContainerOutputConfig,
    PhantomBusterListScriptsConfig,
    PhantomBusterGetScriptConfig,
    PhantomBusterGetScriptCodeConfig,
    PhantomBusterSaveScriptConfig,
    PhantomBusterDeleteScriptConfig,
    PhantomBusterGetOrgConfig,
    PhantomBusterGetOrgResourcesConfig,
    PhantomBusterSaveLeadsConfig,
    PhantomBusterListLeadListsConfig,
    PhantomBusterSaveLeadListConfig,
    PhantomBusterAiCompletionConfig,
    PhantomBusterSolveHcaptchaConfig,
    PhantomBusterIpLocationConfig,
    PhantomBusterReceiveWebhookConfig,
    PhantomBusterUpdateUserConfig,
    PhantomBusterGetAgentOutputConfig,
    PhantomBusterListDeletedAgentsConfig,
    PhantomBusterGetContainerResultObjectConfig,
    PhantomBusterListRunningContainersConfig,
    PhantomBusterListAgentGroupsConfig,
    PhantomBusterSaveManyLeadsConfig,
    PhantomBusterDeleteLeadsConfig,
    PhantomBusterGetLeadsByListConfig,
    PhantomBusterGetLeadListConfig,
    PhantomBusterDeleteLeadListConfig,
    PhantomBusterAiAdviceConfig,
    PhantomBusterAiTaskConfig,
    PhantomBusterSolveRecaptchaConfig,
    PhantomBusterUnscheduleAllConfig,
    PhantomBusterAttachContainerConfig,
    PhantomBusterListBranchesConfig,
    PhantomBusterCreateBranchConfig,
    PhantomBusterListIcpsConfig,
    PhantomBusterListBuyerPersonasConfig,
    PhantomBusterGenerateIdentityTokenConfig,
    PhantomBusterSaveIdentityConfig,
    PhantomBusterSerpSearchConfig,
    PhantomBusterGetCrmAccessConfig,
)


@pytest.fixture
def api_key_credentials():
    return PhantomBusterApiKeyCredential(api_key="pb_test_key_12345")


def create_phantombuster_node(config):
    return PhantomBusterNode(
        node_id="test-phantombuster-node",
        node_type="automation-phantombuster",
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


def _run(config, status_code, json_data):
    """Build a node, patch the AsyncClient, and execute."""
    node = create_phantombuster_node(config)
    mock_client = create_mock_client(status_code, json_data)
    return node, mock_client


class TestPhantomBusterAccountMock:
    @pytest.mark.asyncio
    async def test_get_user(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetUserConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"id": "u1", "plan": "growth"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["plan"] == "growth"


class TestPhantomBusterAgentsMock:
    @pytest.mark.asyncio
    async def test_list_agents(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterListAgentsConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, [{"id": "a1"}, {"id": "a2"}])
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_agents"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_agent(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetAgentConfig(agent_id="a1"), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"id": "a1", "name": "LinkedIn Scraper"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_agent"
        assert result["data"]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_launch_agent(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterLaunchAgentConfig(agent_id="a1", argument='{"foo": "bar"}'),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"containerId": "c1"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "launch_agent"
        assert result["data"]["containerId"] == "c1"

    @pytest.mark.asyncio
    async def test_launch_agent_soon(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterLaunchAgentSoonConfig(agent_id="a1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"containerId": "c2"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "launch_agent_soon"

    @pytest.mark.asyncio
    async def test_launch_agent_sync(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterLaunchAgentSyncConfig(agent_id="a1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"containerId": "c3", "output": "done"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "launch_agent_sync"
        assert result["data"]["output"] == "done"

    @pytest.mark.asyncio
    async def test_stop_agent(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterStopAgentConfig(agent_id="a1"), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"status": "stopped"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "stop_agent"

    @pytest.mark.asyncio
    async def test_save_agent(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterSaveAgentConfig(agent_payload='{"name": "New Phantom"}'),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"id": "a99"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "save_agent"
        assert result["data"]["id"] == "a99"

    @pytest.mark.asyncio
    async def test_delete_agent(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterDeleteAgentConfig(agent_id="a1"), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"success": True})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_agent"


class TestPhantomBusterContainersMock:
    @pytest.mark.asyncio
    async def test_list_containers(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterListContainersConfig(agent_id="a1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, [{"id": "c1"}, {"id": "c2"}])
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_containers"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_container(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetContainerConfig(container_id="c1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"id": "c1", "status": "finished"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_container"
        assert result["data"]["status"] == "finished"

    @pytest.mark.asyncio
    async def test_get_container_output(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetContainerOutputConfig(container_id="c1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"output": "log lines", "resultObject": "url"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_container_output"
        assert result["data"]["resultObject"] == "url"


class TestPhantomBusterScriptsMock:
    @pytest.mark.asyncio
    async def test_list_scripts(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterListScriptsConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, [{"id": "s1"}])
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_scripts"

    @pytest.mark.asyncio
    async def test_get_script(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetScriptConfig(script_id="s1"), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"id": "s1", "name": "scraper.js"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_script"

    @pytest.mark.asyncio
    async def test_get_script_code(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetScriptCodeConfig(script_id="s1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"code": "console.log('hi')"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_script_code"
        assert "console.log" in result["data"]["code"]

    @pytest.mark.asyncio
    async def test_save_script(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterSaveScriptConfig(script_payload='{"name": "s.js", "code": "x"}'),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"id": "s9"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "save_script"

    @pytest.mark.asyncio
    async def test_delete_script(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterDeleteScriptConfig(script_id="s1"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"success": True})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_script"


class TestPhantomBusterOrgMock:
    @pytest.mark.asyncio
    async def test_get_org(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetOrgConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"id": "org1", "name": "Acme"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_org"
        assert result["data"]["name"] == "Acme"

    @pytest.mark.asyncio
    async def test_get_org_resources(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetOrgResourcesConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, {"executionTime": 1200})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_org_resources"


class TestPhantomBusterOrgStorageMock:
    @pytest.mark.asyncio
    async def test_save_leads(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterSaveLeadsConfig(leads_payload='[{"email": "a@b.com"}]'),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"saved": 1})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "save_leads"
        assert result["data"]["saved"] == 1

    @pytest.mark.asyncio
    async def test_list_lead_lists(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterListLeadListsConfig(), credentials=api_key_credentials
        )
        node, mock_client = _run(config, 200, [{"id": "l1"}])
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_lead_lists"

    @pytest.mark.asyncio
    async def test_save_lead_list(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterSaveLeadListConfig(list_payload='{"name": "My List"}'),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"id": "l9"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "save_lead_list"


class TestPhantomBusterAiUtilsMock:
    @pytest.mark.asyncio
    async def test_ai_completion(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterAiCompletionConfig(prompt="Hello"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"completion": "Hi there"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "ai_completion"
        assert result["data"]["completion"] == "Hi there"

    @pytest.mark.asyncio
    async def test_solve_hcaptcha(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterSolveHcaptchaConfig(
                site_key="sk_123", page_url="https://example.com"
            ),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"token": "tok_abc"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "solve_hcaptcha"
        assert result["data"]["token"] == "tok_abc"

    @pytest.mark.asyncio
    async def test_ip_location(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterIpLocationConfig(ip="8.8.8.8"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 200, {"country": "US", "city": "Mountain View"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "ip_location"
        assert result["data"]["country"] == "US"


class TestPhantomBusterTriggerMock:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = PhantomBusterNodeConfig(
            config=PhantomBusterReceiveWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_phantombuster_node(config)
        payload = {"exitCode": 0, "containerId": "c1", "resultObject": "https://s3/result.csv"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["data"]["containerId"] == "c1"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"


class TestPhantomBusterErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetAgentConfig(agent_id="missing"),
            credentials=api_key_credentials,
        )
        node, mock_client = _run(config, 404, {"error": "Agent not found"})
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = PhantomBusterNodeConfig(
            config=PhantomBusterGetUserConfig(), credentials=None
        )
        node = create_phantombuster_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


def create_capturing_client(status_code=200, json_data=None):
    """Mock client that records the request's method/url/params/json for path assertions."""
    mock_response = create_mock_response(status_code, json_data if json_data is not None else {"ok": True})
    captured: dict = {}
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        captured["method"] = kwargs.get("method")
        captured["url"] = kwargs.get("url")
        captured["params"] = kwargs.get("params")
        captured["json"] = kwargs.get("json")
        return mock_response

    mock_client.request = async_request
    mock_client.__aenter__ = lambda self: _aident(mock_client)
    mock_client.__aexit__ = lambda self, *a: _anone()
    return mock_client, captured


async def _aident(v):
    return v


async def _anone():
    return None


class TestPhantomBusterEndpointPaths:
    """Assert each operation hits the correct v2 endpoint — locks in the fixes
    for get_user (was /user), solve_hcaptcha (was /captcha/hcaptcha), and the
    launch-soon `minutes` param, plus the newly-added endpoints."""

    async def _capture(self, op, creds):
        node = create_phantombuster_node(
            PhantomBusterNodeConfig(config=op, credentials=creds)
        )
        client, cap = create_capturing_client()
        with patch("nodes.phantombuster_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        return result, cap

    @pytest.mark.asyncio
    async def test_get_user_uses_v2_path(self, api_key_credentials):
        _, cap = await self._capture(PhantomBusterGetUserConfig(), api_key_credentials)
        assert cap["method"] == "GET" and cap["url"].endswith("/api/v2/users/fetch-me")

    @pytest.mark.asyncio
    async def test_solve_hcaptcha_path_and_body(self, api_key_credentials):
        # Live-verified: /hcaptcha needs {"key","url"}, not {"siteKey","pageUrl"}.
        _, cap = await self._capture(
            PhantomBusterSolveHcaptchaConfig(site_key="s", page_url="u"), api_key_credentials
        )
        assert cap["method"] == "POST" and cap["url"].endswith("/api/v2/hcaptcha")
        assert cap["json"] == {"key": "s", "url": "u"}

    @pytest.mark.asyncio
    async def test_solve_recaptcha_path_and_body(self, api_key_credentials):
        # Live-verified: /recaptcha needs {"key","url","type"}.
        _, cap = await self._capture(
            PhantomBusterSolveRecaptchaConfig(site_key="s", page_url="u", version="v2"),
            api_key_credentials,
        )
        assert cap["url"].endswith("/api/v2/recaptcha")
        assert cap["json"] == {"key": "s", "url": "u", "type": "v2"}

    @pytest.mark.asyncio
    async def test_launch_soon_sends_minutes(self, api_key_credentials):
        _, cap = await self._capture(
            PhantomBusterLaunchAgentSoonConfig(agent_id="a1", minutes="5"), api_key_credentials
        )
        assert cap["url"].endswith("/agents/launch-soon")
        assert cap["json"]["minutes"] == 5

    @pytest.mark.asyncio
    async def test_get_container_result_object(self, api_key_credentials):
        _, cap = await self._capture(
            PhantomBusterGetContainerResultObjectConfig(container_id="c1"), api_key_credentials
        )
        assert cap["url"].endswith("/containers/fetch-result-object")
        assert cap["params"] == {"id": "c1"}

    @pytest.mark.asyncio
    async def test_get_agent_output(self, api_key_credentials):
        _, cap = await self._capture(
            PhantomBusterGetAgentOutputConfig(agent_id="a1"), api_key_credentials
        )
        assert cap["url"].endswith("/agents/fetch-output")
        assert cap["params"] == {"id": "a1"}

    @pytest.mark.asyncio
    async def test_new_endpoint_paths(self, api_key_credentials):
        cases = [
            (PhantomBusterUpdateUserConfig(user_payload='{"firstName":"A"}'), "POST", "/users/update-me"),
            (PhantomBusterListDeletedAgentsConfig(), "GET", "/agents/fetch-deleted"),
            (PhantomBusterListRunningContainersConfig(), "GET", "/orgs/fetch-running-containers"),
            (PhantomBusterListAgentGroupsConfig(), "GET", "/orgs/fetch-agent-groups"),
            (PhantomBusterSaveManyLeadsConfig(leads_payload='{"leads":[]}'), "POST", "/org-storage/leads/save-many"),
            (PhantomBusterDeleteLeadsConfig(leads_payload='{"ids":[]}'), "POST", "/org-storage/leads/delete-many"),
            (PhantomBusterGetLeadsByListConfig(list_id="L1"), "POST", "/org-storage/leads/by-list/L1"),
            (PhantomBusterGetLeadListConfig(list_id="L1"), "GET", "/org-storage/lists/fetch"),
            (PhantomBusterDeleteLeadListConfig(list_id="L1"), "POST", "/org-storage/lists/delete"),
            (PhantomBusterAiAdviceConfig(payload="{}"), "POST", "/ai/advice"),
            (PhantomBusterAiTaskConfig(payload="{}"), "POST", "/ai/tasks"),
            (PhantomBusterSolveRecaptchaConfig(site_key="s", page_url="u"), "POST", "/recaptcha"),
        ]
        for op, method, suffix in cases:
            _, cap = await self._capture(op, api_key_credentials)
            assert cap["method"] == method, f"{op.operation}: method {cap['method']}"
            assert cap["url"].endswith(suffix), f"{op.operation}: url {cap['url']}"

    @pytest.mark.asyncio
    async def test_ai_completion_sends_messages_body(self, api_key_credentials):
        # Live-verified: /ai/completions requires a chat `messages` array, not {"prompt": ...}.
        _, cap = await self._capture(
            PhantomBusterAiCompletionConfig(prompt="hello"), api_key_credentials
        )
        assert cap["url"].endswith("/ai/completions")
        assert cap["json"] == {"messages": [{"role": "user", "content": "hello"}]}

    @pytest.mark.asyncio
    async def test_beta_endpoint_paths(self, api_key_credentials):
        cases = [
            (PhantomBusterUnscheduleAllConfig(), "POST", "/agents/unschedule-all"),
            (PhantomBusterAttachContainerConfig(container_id="c1"), "GET", "/containers/attach"),
            (PhantomBusterListBranchesConfig(), "GET", "/branches/fetch-all"),
            (PhantomBusterCreateBranchConfig(payload='{"name":"x"}'), "POST", "/branches/create"),
            (PhantomBusterListIcpsConfig(), "GET", "/icps/fetch-all"),
            (PhantomBusterListBuyerPersonasConfig(), "GET", "/buyers-personas/fetch-all"),
            (PhantomBusterGenerateIdentityTokenConfig(), "POST", "/identities/generate-token"),
            (PhantomBusterSaveIdentityConfig(payload="{}"), "POST", "/identities/save"),
            (PhantomBusterSerpSearchConfig(query_params='{"q":"x"}'), "GET", "/brightdata/serp"),
            (PhantomBusterGetCrmAccessConfig(), "GET", "/orgs/fetch-crm-access"),
        ]
        for op, method, suffix in cases:
            _, cap = await self._capture(op, api_key_credentials)
            assert cap["method"] == method, f"{op.operation}: method {cap['method']}"
            assert cap["url"].endswith(suffix), f"{op.operation}: url {cap['url']}"


class TestPhantomBusterDynamicOptionsMock:
    """load_field_options must use the canonical (field_name, credential_data,
    context, page_token, search) signature the handler calls with — passing
    credential_data as a kwarg previously raised a TypeError in the UI."""

    @pytest.mark.asyncio
    async def test_load_agent_options_canonical_signature(self):
        with patch(
            "nodes.phantombuster_node._phantombuster_request",
            return_value={"status": "success", "data": [{"id": "a1", "name": "LinkedIn Scraper"}]},
        ):
            result = await PhantomBusterNode.load_field_options(
                field_name="agent_id",
                credential_data={"api_key": "pb_test"},
                context={},
                page_token=None,
                search=None,
            )
        assert result["options"][0] == {"value": "a1", "label": "LinkedIn Scraper"}

    @pytest.mark.asyncio
    async def test_load_script_and_list_options(self):
        captured = {}

        async def fake_request(api_key, method, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            return {"status": "success", "data": [{"id": "x1", "name": "Row"}]}

        for field in ("script_id", "list_id"):
            with patch("nodes.phantombuster_node._phantombuster_request", side_effect=fake_request):
                result = await PhantomBusterNode.load_field_options(
                    field_name=field, credential_data={"api_key": "k"}
                )
            assert result["options"][0]["value"] == "x1"
        # last call was list_id -> lead-lists endpoint
        assert captured["endpoint"] == "/org-storage/lists/fetch-all"

    @pytest.mark.asyncio
    async def test_load_options_unknown_field_and_no_credential(self):
        assert await PhantomBusterNode.load_field_options(
            field_name="container_id", credential_data={"api_key": "k"}
        ) == {"options": []}
        assert await PhantomBusterNode.load_field_options(
            field_name="agent_id", credential_data={}
        ) == {"options": []}

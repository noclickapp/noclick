"""An MCP step's output never holds its server's sign-in; an agent wired to it still signs in.

The step's output is saved as its run's output, which the canvas, the builder, ``/v1`` run reads and logs read back,
so each tool carries a signed reference (``nodes.agent.mcp_auth``) and the token, key or headers are resolved as the
agent's runner when a call is made, from the credential as it is then, never from the output.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from coder.openai_agent.mcp import _build_headers
from nodes.agent import mcp_auth
from nodes.agent.tool_execution import execute_tool
from nodes.agent_node import AgentNode
from nodes.mcp_server_node import MCPServerConfig, MCPServerCredentials, MCPServerNode, MCPServerNodeConfig
from nodes.noclick_node import NoClickNode

WF, OTHER_WF, STEP, AGENT, RUNNER = "wf-1", "wf-2", "mcp-1", "agent-1", "runner-1"
URL = "https://mcp.example.com/mcp"
TOKEN, KEY, HEADER = "oauth-access-SECRET-1", "api-key-SECRET-2", "header-SECRET-3"
SECRETS = (TOKEN, KEY, HEADER)
DISCOVERED = [{"name": "search", "description": "Search",
               "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]

# Each credential as the store holds it, by id: an MCP sign-in, an API key, and the headers-only key the
# platform's tool_servers make (``{"auth_type": "api_key", "custom_headers": ...}``).
STORED = {
    "cred-oauth": {"credential_type": "mcp_oauth", "access_token": TOKEN, "server_url": URL},
    "cred-key": {"credential_type": "mcp_api_key", "api_key": KEY, "custom_headers": {"X-Workspace": HEADER}},
    "cred-headers": {"credential_type": "mcp_api_key", "auth_type": "api_key",
                     "custom_headers": {"Authorization": f"Bearer {KEY}", "X-Workspace": HEADER}},
}


class _Store:
    """The credentials table as ``resolve_credential_with_owner_fallback`` reads it, with who asked."""

    def __init__(self):
        self.rows = {cid: dict(blob) for cid, blob in STORED.items()}
        self.asked = []

    async def resolve(self, credential_id, user_id, pool=None, *, org_id=None, workflow_id=None, **_):
        self.asked.append((credential_id, user_id, workflow_id))
        row = self.rows.get(credential_id)
        return dict(row) if row is not None else None


@pytest.fixture
def store():
    store = _Store()
    with patch("nodes.core.run_op.resolve_credential_with_owner_fallback", new=store.resolve):
        yield store


def _step(*, credential_id=None, credentials=None, workflow_id=WF):
    """The MCP step as the executor builds it: credentials resolved from ``credential_id`` (when it has one)."""
    if credential_id:
        credentials = MCPServerNodeConfig.model_validate(
            {"config": {}, "credentials": dict(STORED[credential_id])}).credentials
    config = MCPServerNodeConfig(config=MCPServerConfig(server_url=URL, tool_prefix="ext_"), credentials=credentials)
    return MCPServerNode(node_id=STEP, node_type="mcp-server",
                         node_data={"credential_id": credential_id} if credential_id else {},
                         config=config, workflow_id=workflow_id, user_id=RUNNER)


async def _run_step(step):
    with patch("coder.openai_agent.mcp.discover_tools", new=AsyncMock(return_value=DISCOVERED)) as discover:
        output = await step.execute({})
    assert output.get("error") is None, output
    return output, discover.await_args.args[0]


def _agent(*, workflow_id=WF, step_config=None):
    agent = AgentNode(node_id=AGENT, node_type="agent", node_data={}, config=None, workflow_id=workflow_id,
                      user_id=RUNNER)
    nodes = [{"id": STEP, "type": "mcp-server", "config": {"server_url": URL, **(step_config or {})}},
             {"id": AGENT, "type": "agent", "config": {}}]
    agent.set_workflow_context(None, nodes, [{"source": STEP, "target": AGENT, "targetHandle": "bottom"}])
    return agent


async def _call(agent, output, tool="ext_search"):
    """One call of the step's tool by the agent wired to it, through the one tool choke point; the server config the
    call was made with (None: nothing was sent)."""
    _, tool_configs, _ = agent._collect_tool_definitions({STEP: output})
    with patch("coder.openai_agent.mcp.call_tool",
               new=AsyncMock(return_value={"success": True, "result": "found"})) as call:
        result = await execute_tool(agent, tool, {"q": "billing"}, tool_configs)
    return result, (call.await_args.args[0] if call.await_args else None)


def _held(text, *values):
    return [value for value in values if value in text]


# ── the output holds no value, whatever signs in ─────────────────────────────


@pytest.mark.parametrize("credential_id,sent", [
    ("cred-oauth", {"Authorization": f"Bearer {TOKEN}"}),
    ("cred-key", {"Authorization": f"Bearer {KEY}", "X-Workspace": HEADER}),
    ("cred-headers", {"Authorization": f"Bearer {KEY}", "X-Workspace": HEADER}),
])
async def test_the_output_names_its_credential_and_the_agent_signs_in_with_it(store, credential_id, sent):
    output, discovered_with = await _run_step(_step(credential_id=credential_id))

    assert _held(json.dumps(output), *SECRETS) == []
    [tool] = output["tools"]
    assert tool["mcp_server_config"] == {"url": URL, "transport_type": "shttp", "auth": "credential",
                                         "credential_id": credential_id,
                                         "signature": tool["mcp_server_config"]["signature"]}
    # Discovery signed in as the runner, through the shared resolver.
    assert store.asked == [(credential_id, RUNNER, WF)]
    assert sent.items() <= _build_headers(api_key=discovered_with.get("api_key"),
                                          access_token=discovered_with.get("access_token"),
                                          custom_headers=discovered_with.get("custom_headers")).items()

    result, called_with = await _call(_agent(), output)
    assert result == {"success": True, "result": "found"}
    assert called_with["url"] == URL
    assert sent.items() <= _build_headers(api_key=called_with.get("api_key"),
                                          access_token=called_with.get("access_token"),
                                          custom_headers=called_with.get("custom_headers")).items()
    assert store.asked[-1] == (credential_id, RUNNER, WF)


async def test_a_sign_in_typed_into_the_step_is_read_from_the_graph_not_the_output(store):
    typed = {"auth_type": "oauth", "access_token": TOKEN, "custom_headers": {"X-Workspace": HEADER}}
    output, discovered_with = await _run_step(_step(credentials=MCPServerCredentials(**typed)))

    assert _held(json.dumps(output), *SECRETS) == []
    assert output["tools"][0]["mcp_server_config"]["auth"] == "step"
    assert discovered_with["access_token"] == TOKEN

    _, called_with = await _call(_agent(step_config={"credentials": typed}), output)
    assert called_with["access_token"] == TOKEN and called_with["custom_headers"] == {"X-Workspace": HEADER}

    # Its settings changed since the step ran: the output no longer matches, and nothing is sent.
    changed = {**typed, "access_token": "another-token"}
    result, called_with = await _call(_agent(step_config={"credentials": changed}), output)
    assert called_with is None and result["success"] is False and "Run the MCP step again" in result["error"]


async def test_a_server_with_no_sign_in_needs_no_credential(store):
    output, discovered_with = await _run_step(_step())

    assert output["tools"][0]["mcp_server_config"] == {"url": URL, "transport_type": "shttp"}
    _, called_with = await _call(_agent(), output)
    assert called_with == {"url": URL, "transport_type": "shttp"} == discovered_with
    assert store.asked == []


# ── a later run reads the earlier output ─────────────────────────────────────


async def test_a_later_run_resolves_the_earlier_output_as_the_credential_stands_then(store):
    output, _ = await _run_step(_step(credential_id="cred-oauth"))
    preloaded = json.loads(json.dumps(output))  # as the next run reads it back from the run store

    # The credential moved on (a refresh elsewhere) after the step ran.
    store.rows["cred-oauth"]["access_token"] = "rotated-token"
    later = _agent()
    later.execution_id = "a-response-run"
    result, called_with = await _call(later, preloaded)

    assert result["success"] is True
    assert called_with["access_token"] == "rotated-token"


async def test_an_expired_oauth_token_is_refreshed_before_the_call(store):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    output, _ = await _run_step(_step(credential_id="cred-oauth"))
    # It expired after the step ran: the call refreshes it through the refresh choke point, which persists it.
    store.rows["cred-oauth"].update(refresh_token="r1", token_endpoint="https://srv/token", client_id="client-1",
                                    expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    fresh = SimpleNamespace(access_token="fresh-token", refresh_token="r2", scope=None, token_type="Bearer",
                            expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with patch("nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock(return_value=fresh)) as refresh, \
            patch("utils.credential_loader.load_credential",
                  new=AsyncMock(side_effect=lambda *_a, **_k: dict(store.rows["cred-oauth"]))), \
            patch("utils.credentials.update_credential_data_detailed",
                  new=AsyncMock(return_value=(1, None))) as persisted:
        _, called_with = await _call(_agent(), output)

    refresh.assert_awaited_once()
    persisted.assert_awaited()
    assert called_with["access_token"] == "fresh-token"


async def test_a_credential_gone_since_fails_the_call_saying_so(store):
    output, _ = await _run_step(_step(credential_id="cred-key"))
    del store.rows["cred-key"]

    result, called_with = await _call(_agent(), output)
    assert called_with is None
    assert result["success"] is False and "Reconnect it on the MCP step this tool comes from" in result["error"]


# ── an output that isn't its step's resolves nothing ─────────────────────────


@pytest.mark.parametrize("change", [
    {"url": "https://elsewhere.example.net/mcp"},
    {"credential_id": "cred-key"},
    {"auth": "noclick"},
    {"signature": "0" * 64},
])
async def test_a_changed_reference_sends_no_credential(store, change):
    output, _ = await _run_step(_step(credential_id="cred-oauth"))
    forged = json.loads(json.dumps(output))
    forged["tools"][0]["mcp_server_config"].update(change)
    asked = len(store.asked)

    result, called_with = await _call(_agent(), forged)
    assert called_with is None
    assert result["success"] is False and "doesn't match the MCP step it came from" in result["error"]
    assert len(store.asked) == asked


async def test_a_reference_from_another_workflow_sends_no_credential(store):
    output, _ = await _run_step(_step(credential_id="cred-oauth", workflow_id=OTHER_WF))

    result, called_with = await _call(_agent(workflow_id=WF), output)
    assert called_with is None and result["success"] is False


async def test_an_output_saved_before_references_is_never_signed_in_from(store):
    legacy = {"type": "mcp_tool_definitions", "tools": [{
        "type": "tool_definition", "tool_type": "mcp", "tool_name": "ext_search", "original_tool_name": "search",
        "tool_description": "Search", "parameters": [],
        "mcp_server_config": {"url": URL, "transport_type": "shttp", "auth_type": "oauth", "access_token": TOKEN}}]}

    result, called_with = await _call(_agent(), legacy)
    assert called_with is None
    assert result["success"] is False and "Run the MCP step again" in result["error"]


async def test_the_call_runs_through_the_one_tool_choke_point(store):
    output, _ = await _run_step(_step(credential_id="cred-key"))
    agent = _agent()
    _, tool_configs, _ = agent._collect_tool_definitions({STEP: output})
    with patch("coder.openai_agent.mcp.call_tool",
               new=AsyncMock(return_value={"success": True, "result": "found"})) as call:
        result = await execute_tool(agent, "ext_search", {"q": "billing"}, tool_configs)

    assert result == {"success": True, "result": "found"}
    assert call.await_args.args[0]["api_key"] == KEY
    # The tool configs the agent built hold no secret either.
    assert _held(json.dumps(tool_configs, default=str), *SECRETS) == []


# ── the NoClick step ─────────────────────────────────────────────────────────


async def test_the_noclick_step_carries_no_token_and_each_call_mints_one_for_the_runner(store):
    from unittest.mock import MagicMock

    from mcp_adapter.auth.tokens import verify_mcp_token

    tool = MagicMock()
    tool.description = "List workflows"
    tool.to_mcp_tool.return_value = MagicMock(inputSchema={"type": "object", "properties": {}})
    server = MagicMock()
    server.mcp.get_tools = AsyncMock(return_value={"list_workflows": tool})
    step = NoClickNode(node_id=STEP, node_type="noclick", node_data={}, config=None, user_id=RUNNER, workflow_id=WF)
    with patch("mcp_server.get_mcp_server", return_value=server), \
            patch.object(step, "_get_mcp_server_url", return_value="http://localhost:8000/mcp"):
        output = await step.execute({})

    config = output["tools"][0]["mcp_server_config"]
    assert set(config) == {"url", "transport_type", "auth", "signature"} and config["auth"] == "noclick"
    _, tool_configs, _ = _agent()._collect_tool_definitions({STEP: output})
    signed = await mcp_auth.server_for(_agent(), tool_configs["noclick_list_workflows"])
    assert signed["url"] == "http://localhost:8000/mcp"
    assert verify_mcp_token(signed["access_token"])["sub"] == RUNNER

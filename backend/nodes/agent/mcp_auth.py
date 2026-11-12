"""How an agent signs in to the MCP server an MCP step (or the NoClick step) gave it tools from, while the step's
output holds no secret.

A step's output is saved as its run's output, and people and models read it back: the canvas, the builder's
``<get_output>``, ``/v1`` run reads, run views, logs. So each tool an MCP step outputs carries a reference to how its
server signs in (``reference``), never a token, key or header, and the secret is resolved here, as the agent's runner,
when it is used (``server_config``): by each tool call on NoClick's runtime and by each coding harness's MCP config. A
later run reading the step's output as preloaded context resolves it the same way.

A reference names the credential the step ran with (``credential``: resolved through the shared owner-fallback policy,
an OAuth sign-in refreshed through the refresh choke point), a sign-in typed into the step's own settings (``step``:
read from the graph the agent runs on), or NoClick's own MCP server (``noclick``: a token minted for the runner). An
output can also come from somewhere other than its step (a mock, inputs a caller injects, preloaded context), so a
reference is signed with NoClick's key over its workflow, its step, its server and what signs in: a changed one
resolves nothing, and can't send a credential to another server.

``SIGNED_IN`` is a server config already resolved in this process (NoClick's own tool pool, a harness's servers once
signed in): a key no step output carries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Optional

CREDENTIAL, STEP, NOCLICK = "credential", "step", "noclick"
SIGNED_IN = "mcp_server_auth"
# What a tool's server config held before it was a reference (an output saved then still does, or the mark the
# cleanup left in their place).
_SECRETS = ("access_token", "api_key", "custom_headers")

SAVED_BEFORE = ("This tool comes from an MCP step output saved before NoClick kept sign-ins out of step outputs. "
                "Run the MCP step again, and its tools sign in.")
NOT_ITS_STEP = ("This tool's MCP sign-in doesn't match the MCP step it came from (the output was changed, or the "
                "step's sign-in changed since it ran). Run the MCP step again.")


def _signs_in(credentials: Any) -> bool:
    """Whether a step's credentials send anything (as its discovery did): an API key's, or an OAuth token."""
    auth = credentials.auth_type or "none"
    return auth == "api_key" or (auth == "oauth" and bool(credentials.access_token))


def _signature(ref: Dict[str, Any], *, workflow_id: Any, step_id: Any, step: Any = None) -> str:
    from mcp_adapter.auth.tokens import get_mcp_signing_key

    material = ["mcp-step-sign-in/1", str(workflow_id or ""), str(step_id or ""), ref.get("url") or "",
                ref.get("transport_type") or "shttp", ref.get("auth") or "", ref.get("credential_id") or "",
                step.model_dump(mode="json") if step is not None else None]
    return hmac.new(get_mcp_signing_key().encode(), json.dumps(material, sort_keys=True).encode(),
                    hashlib.sha256).hexdigest()


def reference(*, workflow_id: Any, step_id: Any, url: Optional[str], transport_type: Optional[str],
              credential_id: Optional[str] = None, step: Any = None, noclick: bool = False) -> Dict[str, Any]:
    """The server config a step's tools carry: its URL and transport, and what signs in to it, signed.
    ``credential_id`` is the credential the step ran with; ``step`` its parsed ``MCPServerCredentials``, which
    sign in themselves only when no credential row holds them."""
    ref: Dict[str, Any] = {"url": url, "transport_type": transport_type or "shttp"}
    if noclick:
        ref["auth"] = NOCLICK
    elif credential_id:
        ref.update(auth=CREDENTIAL, credential_id=str(credential_id))
    elif step is not None and _signs_in(step):
        ref["auth"] = STEP
    else:
        return ref
    ref["signature"] = _signature(ref, workflow_id=workflow_id, step_id=step_id,
                                  step=step if ref["auth"] == STEP else None)
    return ref


def _credentials_of(stored: Dict[str, Any]) -> Any:
    """A stored credential as the MCP step reads it (its sign-in kind inferred as the step infers it)."""
    from nodes.mcp_server_node import MCPServerNodeConfig

    return MCPServerNodeConfig.model_validate({"config": {}, "credentials": dict(stored)}).credentials


async def _stored(credential_id: str, *, user_id: Any, organization_id: Any, workflow_id: Any) -> Dict[str, Any]:
    from nodes.core.run_op import resolve_operation_credential

    return dict(await resolve_operation_credential(
        str(credential_id), user_id, organization_id=organization_id, workflow_id=workflow_id,
        where="the MCP step this tool comes from"))


async def _token(stored: Dict[str, Any], *, credential_id: str, user_id: Any) -> Optional[str]:
    """The stored OAuth credential's access token, refreshed first when it expires and it can be."""
    from nodes.core import vendor_mcp

    return (await vendor_mcp.fresh_credential(stored, credential_id=credential_id, user_id=user_id)).get(
        "access_token")


async def server_config(ref: Dict[str, Any], *, workflow_id: Any, step_id: Any, user_id: Any,
                        organization_id: Any = None, step: Any = None) -> Dict[str, Any]:
    """The ``coder.openai_agent.mcp`` server config for a reference, signed in as ``user_id``. ``step``: the step's
    own credentials, for a ``step`` reference. Raises ValueError, saying what to do, for an output saved before
    references, a reference that isn't its step's, or a credential that no longer resolves."""
    config: Dict[str, Any] = {"url": ref.get("url"), "transport_type": ref.get("transport_type") or "shttp"}
    auth = ref.get("auth")
    if not auth:
        if any(ref.get(key) for key in _SECRETS):
            raise ValueError(SAVED_BEFORE)
        return config
    expected = _signature(ref, workflow_id=workflow_id, step_id=step_id, step=step if auth == STEP else None)
    if auth not in (CREDENTIAL, STEP, NOCLICK) or not hmac.compare_digest(str(ref.get("signature") or ""), expected):
        raise ValueError(NOT_ITS_STEP)
    if auth == NOCLICK:
        from mcp_adapter.auth.tokens import issue_mcp_token

        return {**config, "access_token": issue_mcp_token(
            user_id=user_id, client_id="noclick-workflow-node", scopes=["mcp:tools"], expiry_hours=1)}
    if auth == CREDENTIAL:
        stored = await _stored(ref["credential_id"], user_id=user_id, organization_id=organization_id,
                               workflow_id=workflow_id)
        credentials, row = _credentials_of(stored), (ref["credential_id"], stored)
    else:
        credentials, row = step, None
        if step.oauth_credential_id:
            # The sign-in the step's settings point at: refreshed and persisted on its row.
            row = (step.oauth_credential_id, await _stored(
                step.oauth_credential_id, user_id=user_id, organization_id=organization_id, workflow_id=workflow_id))
    kind = credentials.auth_type or "none"
    if kind == "oauth" and credentials.access_token:
        token = await _token(row[1], credential_id=row[0], user_id=user_id) if row else credentials.access_token
        return {**config, "access_token": token, "custom_headers": credentials.custom_headers}
    if kind == "api_key":
        return {**config, "api_key": credentials.api_key, "custom_headers": credentials.custom_headers}
    return config


def _step_credentials(node: Any, step_id: Any) -> Any:
    """The credentials typed into an MCP step's own settings, as the graph the agent runs on holds them."""
    from nodes.mcp_server_node import MCPServerNode
    from utils.graph_nodes import node_config

    found = next((n for n in getattr(node, "_workflow_nodes", None) or [] if str(n.get("id")) == str(step_id)), None)
    typed = node_config(found).get("credentials") if found else None
    if not isinstance(typed, dict):
        return None
    return MCPServerNode.parse_config({"config": {}, "credentials": dict(typed)}).credentials


async def server_for(node: Any, tool_info: Dict[str, Any]) -> Dict[str, Any]:
    """The server config one of an agent's MCP tools calls, signed in as the agent's runner."""
    if tool_info.get(SIGNED_IN):
        return tool_info[SIGNED_IN]
    ref = tool_info.get("mcp_server_config") or {}
    step_id = tool_info.get("node_id")
    return await server_config(
        ref, workflow_id=getattr(node, "workflow_id", None), step_id=step_id, user_id=getattr(node, "user_id", None),
        organization_id=getattr(node, "organization_id", None),
        step=_step_credentials(node, step_id) if ref.get("auth") == STEP else None)


async def sign_in(node: Any, tool_configs: Optional[Dict[str, Dict[str, Any]]]) -> None:
    """Sign in to each MCP server the turn's tools reach, once each, onto those tools as ``SIGNED_IN``: a coding
    harness writes them into its MCP config as its sandbox starts. Raises as ``server_config`` does."""
    signed: Dict[str, Dict[str, Any]] = {}
    for tool_info in (tool_configs or {}).values():
        if tool_info.get("tool_type") != "mcp" or tool_info.get(SIGNED_IN):
            continue
        key = json.dumps([tool_info.get("node_id"), tool_info.get("mcp_server_config")], sort_keys=True, default=str)
        if key not in signed:
            signed[key] = await server_for(node, tool_info)
        tool_info[SIGNED_IN] = signed[key]

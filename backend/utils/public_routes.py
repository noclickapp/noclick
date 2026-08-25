"""
Public HTTP routes for unauthenticated access to shared resources.

These routes provide read-only access to publicly shared workflows,
with sanitization to remove sensitive data like credentials and API keys.
"""

import json
import re
import logging
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Response

from utils.database_pool import get_native_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])






# Runtime state and credential pointers: dropped wherever they appear.
_PUBLIC_DROP_KEYS = {
    "credentialid", "credentialids", "mockedoutput", "output",
    "outputstoredlocally", "outputsizebytes", "executionstate",
}
# Containers whose whole value is credential material — a header map holds the
# API key in its VALUE, under a name ("X-API-Key") no key-name rule can predict.
_PUBLIC_REDACT_KEYS = {
    "auth", "authentication", "credential", "credentials", "env",
    "environment", "headers", "headerparameters", "requestheaders",
}
_PUBLIC_SECRET_TERMS = (
    "secret", "password", "token", "apikey", "privatekey",
    "authorization", "cookie", "signingkey", "connectionstring",
)


def _normalized_public_key(key) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _sanitize_public_value(value):
    """Recursively remove runtime state and redact credential-shaped fields."""
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    clean = {}
    for key, nested in value.items():
        normalized = _normalized_public_key(key)
        if normalized in _PUBLIC_DROP_KEYS or normalized == "disabled":
            continue
        if normalized in _PUBLIC_REDACT_KEYS or any(
            term in normalized for term in _PUBLIC_SECRET_TERMS
        ):
            clean[key] = "[REDACTED]"
        else:
            clean[key] = _sanitize_public_value(nested)
    return clean


def _sanitize_workflow_for_public(workflow: dict) -> dict:
    """Return a deep, recursively sanitized workflow for public viewing.

    Recursive on purpose. The previous pass walked `nodes[].data.config` one
    level deep and matched key NAMES, so a value nested one step further — the
    common `config.headers = {"X-API-Key": "..."}` of an HTTP request node —
    was published verbatim on the template and share pages.
    """
    if not workflow:
        return workflow
    return _sanitize_public_value(json.loads(json.dumps(workflow)))


@router.get("/oauth-app/{provider}")
async def instance_oauth_app(provider: str):
    """This instance's OAuth client id for a provider, for the authorize route.

    The frontend server builds the provider's consent URL and needs the client
    id; it is public by nature (it travels in that URL in plain sight). The
    SECRET never leaves the backend, so there is nothing here the redirect
    wouldn't reveal a moment later.

    It comes from the backend rather than the frontend reading the table itself
    because the Remix process has no service-role key on a self-hosted install —
    and handing it one, so it could read a table whose only useful column is
    already public, would be the wrong trade.

    Self-hosted only: hosted installs configure their own apps by environment.
    """
    from utils.edition import is_local_edition

    if not is_local_edition():
        raise HTTPException(status_code=404, detail="Not found")
    import os

    from utils.instance_oauth import _env_names

    client_id_var, _ = _env_names(provider)
    client_id = os.environ.get(client_id_var)
    if not client_id:
        raise HTTPException(status_code=404, detail="No OAuth app configured for this provider")
    return {"provider": provider, "client_id": client_id}


@router.get("/instance-status")
async def instance_status():
    """Whether this instance needs its first account, and what it can do.

    Lets a fresh self-hosted install land on the signup form instead of a
    login wall — the difference between "set up your instance" and the
    confusing "log in to the thing you just installed". Reveals only whether
    any account exists, and only for a local edition; hosted always reports
    configured."""
    from utils.edition import is_local_edition

    import os

    # Capabilities the UI must not guess at. Report optional operator-provided
    # services so unavailable controls can stay hidden.
    capabilities = {
        # send_system_alert logs "RESEND_API_KEY not configured" and returns
        # False, so notification preferences would toggle for mail that never
        # sends. Config-based, not edition-based: a self-hoster who sets a key
        # gets working email.
        "email": bool(os.getenv("RESEND_API_KEY")),
        # Managed publishing and checkout are not part of this edition.
        "publishing": False,
    }

    if not is_local_edition():
        return {"needs_setup": False, "capabilities": capabilities}
    try:
        async with get_native_pool().acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM auth.users")
        return {"needs_setup": (count or 0) == 0, "capabilities": capabilities}
    except Exception as e:
        logger.debug(f"[public] instance-status check failed: {e}")
        return {"needs_setup": False, "capabilities": capabilities}


@router.get("/workflow/{workflow_id}")
async def get_public_workflow(workflow_id: str, response: Response):
    """
    Fetch a publicly shared workflow without authentication.

    Returns workflow data with sensitive information redacted.
    Requires an active public share record for the workflow.
    """
    pool = get_native_pool()

    # Check for public share record
    row = await pool.fetchrow(
        """
        SELECT w.id, w.name, w.description, w.workflow, w.display_metadata,
               u.raw_user_meta_data->>'name' as owner_name
        FROM workflows w
        JOIN auth.users u ON u.id = w.owner_id
        JOIN resource_shares rs ON rs.resource_id = w.id
            AND rs.resource_type = 'workflow'
            AND rs.target_type = 'public'
        WHERE w.id = $1
        """,
        workflow_id,
    )

    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Set cache headers for CDN/edge caching
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=60"

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "workflow_data": _sanitize_workflow_for_public(row["workflow"]),
        "display_metadata": row["display_metadata"],
        "owner_name": row["owner_name"],
    }


@router.get("/invite/{token}")
async def get_invite_preview(token: str, response: Response):
    """
    Preview a workflow invite link without authentication.

    Returns just enough for the "<owner> shared a workflow with you" screen —
    NOT the workflow data (redemption happens authenticated, over the socket).
    """
    pool = get_native_pool()

    row = await pool.fetchrow(
        """
        SELECT w.id AS workflow_id, w.name AS workflow_name,
               u.raw_user_meta_data->>'name' AS owner_name,
               u.raw_user_meta_data->>'avatar_url' AS owner_avatar_url
        FROM workflow_invite_links il
        JOIN workflows w ON w.id = il.workflow_id AND w.deleted_at IS NULL
        JOIN auth.users u ON u.id = w.owner_id
        WHERE il.token = $1 AND il.is_active = true
          -- Links are owner-minted; mirror the redemption defense so a forged link
          -- (creator != workflow owner) can't leak the victim owner's name/avatar.
          AND il.created_by = w.owner_id
        """,
        token,
    )

    if not row:
        raise HTTPException(status_code=404, detail="Invite link not found or no longer active")

    # No caching — the link can be revoked or the workflow renamed at any time.
    response.headers["Cache-Control"] = "no-store"

    return {
        "workflow_id": str(row["workflow_id"]),
        "workflow_name": row["workflow_name"],
        "owner_name": row["owner_name"],
        "owner_avatar_url": row["owner_avatar_url"],
    }


def node_merged_config(node: Dict[str, Any]) -> Dict[str, Any]:
    """Return a node's config across the supported saved-graph shapes."""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if isinstance(data.get("config"), dict):
        return {**data, **data["config"], "config": data["config"]}
    return node.get("config") or data or {}


# Structural tool surfaces that count as agent tools without op-tool support.
_STRUCTURAL_TOOL_TYPES = {"tool", "mcp-server", "alarm", "filesystem"}


def _agent_link_tools(workflow_config, node_id: str) -> list:
    """Wired tool providers for the shared agent — type + display label ONLY
    (no operations, config values, or credential ids leave this endpoint).
    Same wiring predicate as AgentNode: edges into the agent's bottom handle."""
    from nodes.agent.node_op_tools import node_supports_op_tools

    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except (ValueError, TypeError):
            return []
    nodes = (workflow_config or {}).get("nodes", []) or []
    edges = (workflow_config or {}).get("edges", []) or []
    nodes_by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}

    tools = []
    for edge in edges:
        if edge.get("target") != node_id or edge.get("targetHandle") != "bottom":
            continue
        pnode = nodes_by_id.get(edge.get("source"))
        if not pnode or pnode.get("data", {}).get("disabled") or pnode.get("disabled"):
            continue
        ptype = pnode.get("type", "")
        if not (node_supports_op_tools(ptype) or ptype in _STRUCTURAL_TOOL_TYPES):
            continue
        config = node_merged_config(pnode)
        label = (
            pnode.get("data", {}).get("label")
            or config.get("label")
            or ptype.replace("automation-", "").replace("-", " ").title()
        )
        tools.append({"node_type": ptype, "label": label})
    return tools


@router.get("/agent-link/{link_id}")
async def get_agent_link_preview(link_id: str, response: Response):
    """
    Public metadata for a shared agent chat page (/a/{link_id}).

    The link id is the capability — this returns only what the public page
    needs to render its header: agent label/model, wired tool provider
    types+labels, and the conversation prefix the FE composes thread ids
    from. Never credentials, config values, or operation lists.
    """
    from repositories.shared_agent_link import SharedAgentLinkRepo

    link = await SharedAgentLinkRepo(get_native_pool()).load_for_visit(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Agent link not found or no longer active")

    workflow_config = link["workflow_config"]
    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except (ValueError, TypeError):
            workflow_config = {}
    agent_node = next(
        (n for n in (workflow_config or {}).get("nodes", []) or []
         if isinstance(n, dict) and n.get("id") == link["node_id"]),
        None,
    )
    if not agent_node or agent_node.get("type") != "agent":
        raise HTTPException(status_code=404, detail="Agent link not found or no longer active")

    owner_row = await get_native_pool().fetchrow(
        "SELECT raw_user_meta_data->>'name' AS owner_name FROM auth.users WHERE id = $1",
        link["owner_id"],
    )

    config = node_merged_config(agent_node)
    # No caching — rotate / set_active must apply immediately.
    response.headers["Cache-Control"] = "no-store"

    return {
        "workflow_name": link["workflow_name"],
        "owner_name": owner_row["owner_name"] if owner_row else None,
        "agent": {
            "label": agent_node.get("data", {}).get("label") or config.get("label") or "Agent",
            "model": config.get("model"),
        },
        "tools": _agent_link_tools(workflow_config, link["node_id"]),
        "conversation_prefix": f"ck:{link['workflow_id']}:{link['node_id']}:share:{link['id']}",
        "is_active": True,
    }


@router.get("/run-link/{link_id}")
async def get_run_link(link_id: str, response: Response):
    """
    Public snapshot for a shared Test Run result page (/r/{link_id}).

    The link id is the capability. The snapshot was allowlisted to display
    fields at mint (run_share:create) — it carries names and the rendered
    run, never workflow/node ids or config.
    """
    from repositories.shared_run_link import SharedRunLinkRepo

    link = await SharedRunLinkRepo(get_native_pool()).load_for_view(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Run link not found or no longer active")

    snapshot = link["snapshot"]
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (ValueError, TypeError):
            snapshot = {}

    # No caching — a future revoke must apply immediately.
    response.headers["Cache-Control"] = "no-store"
    return {
        "title": link["title"],
        "workflow_name": link["workflow_name"],
        "created_at": link["created_at"].isoformat() if link["created_at"] else None,
        "snapshot": snapshot,
    }



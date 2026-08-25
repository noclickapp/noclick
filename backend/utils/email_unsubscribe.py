"""
One-click disable for workflow notification emails (the send-email node).

Every branded notification carries a signed disable link (and RFC 8058
List-Unsubscribe headers); hitting it flips the sending node's ``disabled``
flag in the workflow blob, so the kill switch works without a NoClick login.
The signature is HMAC over workflow_id|node_id keyed on ``EMAIL_RELAY_SECRET``
and never expires — a disable link in an old email must keep working.
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Optional
from urllib.parse import urlencode

from utils.hosted_defaults import frontend_url

logger = logging.getLogger(__name__)

# The frontend proxies /email/* to the email routes. Resolve that frontend via
# the installation-aware endpoint seam so self-hosted unsubscribe links never
# point at the hosted service. EMAIL_DISABLE_BASE_URL remains an explicit
# override for split-origin deployments.
DISABLE_LINK_BASE = (
    os.getenv("EMAIL_DISABLE_BASE_URL") or frontend_url()
).rstrip("/")


def _relay_secret() -> str:
    secret = os.getenv("EMAIL_RELAY_SECRET")
    if not secret:
        raise RuntimeError("EMAIL_RELAY_SECRET is not configured")
    return secret


def mint_disable_sig(workflow_id: str, node_id: str) -> str:
    msg = f"disable|{workflow_id}|{node_id}"
    return hmac.new(_relay_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_disable_sig(workflow_id: str, node_id: str, sig: str) -> bool:
    if not workflow_id or not node_id or not sig:
        return False
    return hmac.compare_digest(mint_disable_sig(workflow_id, node_id), str(sig))


def build_disable_url(workflow_id: str, node_id: str) -> str:
    query = urlencode({
        "wf": workflow_id,
        "node": node_id,
        "sig": mint_disable_sig(workflow_id, node_id),
    })
    return f"{DISABLE_LINK_BASE}/email/disable?{query}"


async def disable_node_in_workflow(workflow_id: str, node_id: str) -> Optional[str]:
    """Set the node's disabled flag in the saved workflow blob.

    Returns the workflow name on success, None when the workflow or node no
    longer exists (deleted workflow, removed node — the link in an old email
    outlived its source).
    """
    from coder.workflow.workflow_ops import set_node_disabled
    from utils.database_pool import get_native_pool

    pool = get_native_pool()
    row = await pool.fetchrow(
        "SELECT name, workflow FROM workflows WHERE id = $1 AND deleted_at IS NULL",
        workflow_id,
    )
    if not row:
        return None
    blob = row["workflow"]
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except json.JSONDecodeError:
            return None
    nodes = (blob or {}).get("nodes") or []
    node = next((n for n in nodes if n.get("id") == node_id), None)
    if node is None:
        return None
    set_node_disabled(node.setdefault("config", {}), True)
    # Dict passed raw — the runtime pool's jsonb codec serializes it
    # (mirrors mcp_server's workflow save; json.dumps here double-encodes).
    await pool.execute(
        "UPDATE workflows SET workflow = $1, updated_at = NOW() WHERE id = $2",
        blob, workflow_id,
    )
    logger.info(f"[EmailUnsubscribe] Disabled node {node_id} in workflow {workflow_id}")
    return row["name"] or "your workflow"

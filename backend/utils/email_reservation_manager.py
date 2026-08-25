"""
Email reservation lifecycle for the inbound-email trigger node.

Mirrors WebhookManager: reserves a unique inbound address on the configured
inbound domain for a workflow node and releases it when
the node is removed. The reservation row maps an inbound address back to its
(workflow_id, node_id) so the inbound-email route can resolve and dispatch the
right workflow when mail arrives. Unlike webhooks the address is user-chosen,
so reservation is an explicit commit (see ``email:reserve_address``) guarded by
the ``email_reservations`` UNIQUE constraints.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

def get_inbound_email_domain() -> Optional[str]:
    """Domain this installation owns and routes into ``/email/inbound``.

    The hosted service retains its own default. A community installation must
    opt in explicitly; otherwise all inbound/reply address minting is disabled
    so it can never hand a user an address on somebody else's mail system.
    """
    from utils.edition import is_local_edition

    configured = (os.getenv("INBOUND_EMAIL_DOMAIN") or "").strip().lower().lstrip("@")
    if configured:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", configured):
            logger.error("INBOUND_EMAIL_DOMAIN is not a valid DNS domain; inbound email disabled")
            return None
        if is_local_edition() and configured == "noclick.app":
            logger.error(
                "INBOUND_EMAIL_DOMAIN cannot use NoClick's hosted mail domain in the "
                "community edition; inbound email disabled"
            )
            return None
        return configured

    return None if is_local_edition() else "noclick.app"


def require_inbound_email_domain() -> str:
    domain = get_inbound_email_domain()
    if not domain:
        raise RuntimeError(
            "Inbound email is disabled; set INBOUND_EMAIL_DOMAIN to a domain "
            "whose provider forwards mail to this installation's /email/inbound route"
        )
    return domain


# Local-part: lowercase alnum segments separated by . _ - (no leading/trailing separator).
# Mirrors the DB CHECK constraint in 20260609000000_email_reservations.sql.
_LOCAL_PART_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
_MAX_LOCAL_PART_LEN = 64

# Local-parts that must not be claimed by user workflows (system / role addresses).
RESERVED_LOCAL_PARTS = {
    "abuse", "admin", "administrator", "billing", "contact", "help", "hello",
    "hostmaster", "info", "mail", "mailer-daemon", "noclick", "no-reply",
    "noreply",
    # The send-email node's From address (nodes/send_email_node.py) — never
    # claimable as a trigger inbox.
    "notifications",
    "postmaster", "root", "sales", "security", "support", "team",
    "webmaster",
}


def build_email_address(local_part: str, domain: Optional[str] = None) -> str:
    """Compose the full inbound address from a local-part and domain."""
    return f"{local_part}@{domain or require_inbound_email_domain()}"


def validate_local_part(local_part: str) -> tuple[bool, str]:
    """Validate an inbound-email local-part. Returns (is_valid, error_message)."""
    if not local_part:
        return False, "Address is required"
    if len(local_part) > _MAX_LOCAL_PART_LEN:
        return False, f"Address must be {_MAX_LOCAL_PART_LEN} characters or less"
    if not _LOCAL_PART_RE.match(local_part):
        return False, (
            "Use lowercase letters, numbers, dots, hyphens, and underscores "
            "(cannot start or end with a separator)"
        )
    if local_part in RESERVED_LOCAL_PARTS:
        return False, "This address is reserved"
    return True, ""


class EmailReservationManager:
    """Lifecycle for inbound-email address reservations (analog of WebhookManager)."""

    @staticmethod
    async def is_available(
        pool,
        local_part: str,
        domain: Optional[str] = None,
        *,
        exclude_workflow_id: Optional[str] = None,
        exclude_node_id: Optional[str] = None,
    ) -> bool:
        """True if the address is free. An address already held by the excluded
        node still counts as available to it (idempotent re-check on edit)."""
        domain = domain or require_inbound_email_domain()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT workflow_id, node_id FROM email_reservations WHERE domain = $1 AND local_part = $2",
                domain,
                local_part,
            )
        if not row:
            return True
        if exclude_workflow_id is not None and exclude_node_id is not None:
            return (
                str(row["workflow_id"]) == str(exclude_workflow_id)
                and row["node_id"] == exclude_node_id
            )
        return False

    @staticmethod
    async def get_for_node(pool, workflow_id, node_id: str) -> Optional[Dict[str, Any]]:
        """Return the existing reservation for a node, or None."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, local_part, domain FROM email_reservations WHERE workflow_id = $1 AND node_id = $2",
                UUID(str(workflow_id)),
                node_id,
            )
        if not row:
            return None
        return {
            "reservation_id": str(row["id"]),
            "local_part": row["local_part"],
            "domain": row["domain"],
            "email_address": build_email_address(row["local_part"], row["domain"]),
        }

    @staticmethod
    async def reserve(
        pool,
        user_id: str,
        workflow_id,
        node_id: str,
        local_part: str,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reserve (or re-point) the inbound address for a node. Idempotent per
        (workflow_id, node_id). Raises ValueError if the local-part is invalid or
        already taken by another node."""
        domain = domain or require_inbound_email_domain()
        local_part = (local_part or "").strip().lower()
        is_valid, err = validate_local_part(local_part)
        if not is_valid:
            raise ValueError(err)

        workflow_uuid = UUID(str(workflow_id))
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO email_reservations (user_id, workflow_id, node_id, local_part, domain)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (workflow_id, node_id)
                    DO UPDATE SET local_part = EXCLUDED.local_part,
                                  domain = EXCLUDED.domain,
                                  is_active = true
                    RETURNING id, local_part, domain
                    """,
                    user_id,
                    workflow_uuid,
                    node_id,
                    local_part,
                    domain,
                )
        except asyncpg.UniqueViolationError:
            # email_reservations_address_unique — the address is held by another node.
            raise ValueError("This address is already taken")

        logger.info(
            f"[EMAIL] Reserved {build_email_address(local_part, domain)} for "
            f"workflow={workflow_uuid} node={node_id}"
        )
        return {
            "reservation_id": str(row["id"]),
            "local_part": row["local_part"],
            "domain": row["domain"],
            "email_address": build_email_address(row["local_part"], row["domain"]),
        }

    @staticmethod
    async def reserve_from_config(
        pool,
        user_id: str,
        workflow_id,
        node_id: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Reserve ``config['local_part']`` for this node and return the config
        patch to apply: the normalized ``local_part`` plus the derived
        ``email_address`` and ``reservation_id`` (the same shape the FE reserve
        flow stamps). Raises ``ValueError`` if the address is invalid or already
        taken — callers surface the message so the AI builder / MCP can pick
        another. Used by the non-interactive write paths (AI builder, MCP
        server) so an AI-chosen inbox is validated and claimed, never just
        written to config where it would collide at runtime."""
        reserved = await EmailReservationManager.reserve(
            pool, user_id, workflow_id, node_id, config.get("local_part") or ""
        )
        return {
            "local_part": reserved["local_part"],
            "email_address": reserved["email_address"],
            "reservation_id": reserved["reservation_id"],
        }

    @staticmethod
    async def release(pool, workflow_id, node_id: str) -> bool:
        """Release the reservation for a single node. Returns True if a row was removed."""
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM email_reservations WHERE workflow_id = $1 AND node_id = $2",
                UUID(str(workflow_id)),
                node_id,
            )
        removed = result != "DELETE 0"
        if removed:
            logger.info(f"[EMAIL] Released reservation for workflow={workflow_id} node={node_id}")
        return removed

    @staticmethod
    async def release_many(pool, workflow_id, node_ids: List[str]) -> int:
        """Release reservations for a batch of removed nodes in one query."""
        if not node_ids:
            return 0
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM email_reservations WHERE workflow_id = $1 AND node_id = ANY($2)",
                UUID(str(workflow_id)),
                list(node_ids),
            )
        try:
            count = int(result.split()[-1])
        except (ValueError, IndexError):
            count = 0
        if count:
            logger.info(f"[EMAIL] Released {count} reservation(s) for workflow={workflow_id}")
        return count

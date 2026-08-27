"""Shopify mandatory privacy-webhook handling.

Public Shopify apps must accept three compliance topics:
``customers/data_request``, ``customers/redact``, and ``shop/redact``.  This
module keeps the HTTP seam small and testable while the processing code owns
the database transaction.

The privacy ledger deliberately stores no raw webhook payload and no customer
email address.  It retains only the identifiers needed to prove and operate
the request, plus a SHA-256 email fingerprint for correlation.  Workflow
outputs and conversations are purged broadly for every workflow connected to
the affected shop; broad deletion is preferable to retaining a customer's
Shopify data because a generic automation platform cannot reliably infer every
place a merchant may have used a value in an arbitrary workflow result.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import uuid as uuid_module
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException, Request

from utils.database_pool import get_native_pool

logger = logging.getLogger(__name__)

COMPLIANCE_TOPICS = frozenset(
    {"customers/data_request", "customers/redact", "shop/redact"}
)
_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_MAX_BODY_BYTES = 1_000_000


def verify_shopify_hmac(body: bytes, supplied_hmac: str, secret: str) -> bool:
    """Verify Shopify's base64-encoded HMAC-SHA256 over the raw request body."""
    if not (body and supplied_hmac and secret):
        return False
    import base64

    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, supplied_hmac.strip())


def _canonical_shop(value: Any) -> str:
    shop = str(value or "").strip().lower()
    if not _SHOP_RE.fullmatch(shop):
        raise HTTPException(status_code=400, detail="Invalid Shopify shop domain")
    return shop


def _email_fingerprint(value: Any) -> Optional[str]:
    email = str(value or "").strip().lower()
    return hashlib.sha256(email.encode("utf-8")).hexdigest() if email else None


def _text_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _uuid_strings(rows: Iterable[Any], key: str) -> list[str]:
    return [str(row[key]) for row in rows if row[key] is not None]


def _uuid_values(values: Iterable[str]) -> list[uuid_module.UUID]:
    return [uuid_module.UUID(str(value)) for value in values]


async def _shop_context(conn, shop_domain: str) -> tuple[list[str], list[str]]:
    """Return (credential ids, workflow ids) connected to a canonical shop."""
    credentials = await conn.fetch(
        """
        SELECT id
        FROM credentials
        WHERE credential_type = 'shopify_oauth'
          AND lower(COALESCE(metadata->>'myshopify_domain', '')) = $1
        """,
        shop_domain,
    )
    credential_ids = _uuid_strings(credentials, "id")
    if not credential_ids:
        return [], []

    # Credential references are UUID strings nested in the workflow JSON.  The
    # exact-string JSON containment forms have varied over time, so this query
    # uses jsonb's textual representation while the UUID values themselves are
    # server-derived (never interpolated into SQL).
    workflows = await conn.fetch(
        """
        SELECT DISTINCT id
        FROM workflows
        WHERE EXISTS (
            SELECT 1 FROM unnest($1::text[]) AS credential_id
            WHERE workflow::text LIKE '%' || credential_id || '%'
        )
        """,
        credential_ids,
    )
    return credential_ids, _uuid_strings(workflows, "id")


async def _delete_execution_history(conn, workflow_ids: list[str]) -> Dict[str, int]:
    """Delete persisted run/customer payloads for the supplied workflows."""
    if not workflow_ids:
        return {"executions": 0, "conversations": 0, "tool_calls": 0}

    execution_rows = await conn.fetch(
        "SELECT id FROM workflow_executions WHERE workflow_id = ANY($1::uuid[])",
        _uuid_values(workflow_ids),
    )
    execution_ids = _uuid_strings(execution_rows, "id")
    if execution_ids:
        # CAS tables intentionally have no FK to workflow_executions.  Remove
        # their references first; the daily CAS sweep then deletes orphaned R2
        # objects after its race-safety grace period.
        await conn.execute(
            "DELETE FROM cas_refs WHERE execution_id = ANY($1::uuid[])",
            _uuid_values(execution_ids),
        )
        await conn.execute(
            "DELETE FROM cas_manifests WHERE execution_id = ANY($1::uuid[])",
            _uuid_values(execution_ids),
        )

    tool_status = await conn.execute(
        "DELETE FROM tool_call_events WHERE workflow_id = ANY($1::uuid[])",
        _uuid_values(workflow_ids),
    )
    conversation_status = await conn.execute(
        "DELETE FROM conversations WHERE workflow_id = ANY($1::uuid[])",
        _uuid_values(workflow_ids),
    )
    execution_status = await conn.execute(
        "DELETE FROM workflow_executions WHERE workflow_id = ANY($1::uuid[])",
        _uuid_values(workflow_ids),
    )

    def count(status: str) -> int:
        try:
            return int(status.rsplit(" ", 1)[-1])
        except (AttributeError, ValueError):
            return 0

    return {
        "executions": count(execution_status),
        "conversations": count(conversation_status),
        "tool_calls": count(tool_status),
    }


async def process_compliance_webhook(
    *,
    topic: str,
    webhook_id: Optional[str],
    shop_domain: str,
    payload: Dict[str, Any],
    pool=None,
) -> Dict[str, Any]:
    """Persist and process one verified Shopify compliance webhook."""
    if topic not in COMPLIANCE_TOPICS:
        raise HTTPException(status_code=400, detail="Unsupported Shopify topic")

    body_shop = _canonical_shop(payload.get("shop_domain") or shop_domain)
    header_shop = _canonical_shop(shop_domain)
    if body_shop != header_shop:
        raise HTTPException(status_code=400, detail="Shopify shop domain mismatch")

    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    customer_id = _text_id(customer.get("id"))
    customer_email_hash = _email_fingerprint(customer.get("email"))
    shop_id = _text_id(payload.get("shop_id"))
    orders_requested = payload.get("orders_requested")
    if not isinstance(orders_requested, list):
        orders_requested = []

    pool = pool or get_native_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Shopify retries deliveries.  A duplicate webhook id must be a
            # no-op, especially for destructive redaction topics.
            if webhook_id:
                existing = await conn.fetchrow(
                    "SELECT id, status FROM shopify_privacy_requests WHERE webhook_id = $1",
                    webhook_id,
                )
                if existing:
                    return {
                        "accepted": True,
                        "duplicate": True,
                        "request_id": str(existing["id"]),
                        "status": existing["status"],
                    }

            status = "pending" if topic == "customers/data_request" else "processing"
            row = await conn.fetchrow(
                """
                INSERT INTO shopify_privacy_requests (
                    webhook_id, topic, shop_domain, shop_id, customer_id,
                    customer_email_hash, orders_requested, status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                webhook_id,
                topic,
                header_shop,
                shop_id,
                customer_id,
                customer_email_hash,
                orders_requested,
                status,
            )
            request_id = str(row["id"])

            credential_ids, workflow_ids = await _shop_context(conn, header_shop)
            result: Dict[str, Any] = {
                "credentials_matched": len(credential_ids),
                "workflows_matched": len(workflow_ids),
            }

            if topic == "customers/data_request":
                # Data-access requests require human delivery back to the
                # merchant.  The durable pending row is the work queue; it has
                # enough identifiers to find the shop without duplicating the
                # customer's email address into another store.
                await conn.execute(
                    """
                    UPDATE shopify_privacy_requests
                    SET result = $2, updated_at = now()
                    WHERE id = $1::uuid
                    """,
                    request_id,
                    result,
                )
            else:
                result.update(await _delete_execution_history(conn, workflow_ids))
                if topic == "shop/redact" and credential_ids:
                    credential_status = await conn.execute(
                        "DELETE FROM credentials WHERE id = ANY($1::uuid[])",
                        _uuid_values(credential_ids),
                    )
                    try:
                        result["credentials_deleted"] = int(
                            credential_status.rsplit(" ", 1)[-1]
                        )
                    except (AttributeError, ValueError):
                        result["credentials_deleted"] = 0

                await conn.execute(
                    """
                    UPDATE shopify_privacy_requests
                    SET status = 'completed', result = $2,
                        processed_at = now(), updated_at = now()
                    WHERE id = $1::uuid
                    """,
                    request_id,
                    result,
                )

    logger.info(
        "[ShopifyCompliance] processed topic=%s shop=%s request_id=%s status=%s",
        topic,
        header_shop,
        request_id,
        "pending" if topic == "customers/data_request" else "completed",
    )
    return {
        "accepted": True,
        "duplicate": False,
        "request_id": request_id,
        "status": "pending" if topic == "customers/data_request" else "completed",
    }


async def receive_compliance_webhook(request: Request) -> Dict[str, Any]:
    """Validate the HTTP request before handing it to the processor."""
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook body too large")

    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    supplied_hmac = request.headers.get("x-shopify-hmac-sha256", "")
    if not verify_shopify_hmac(body, supplied_hmac, secret):
        raise HTTPException(status_code=401, detail="Invalid Shopify signature")

    topic = request.headers.get("x-shopify-topic", "").strip().lower()
    shop_domain = request.headers.get("x-shopify-shop-domain", "")
    webhook_id = request.headers.get("x-shopify-webhook-id")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    return await process_compliance_webhook(
        topic=topic,
        webhook_id=webhook_id,
        shop_domain=shop_domain,
        payload=payload,
    )

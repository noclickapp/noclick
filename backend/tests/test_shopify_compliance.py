import base64
import hashlib
import hmac
import json
import uuid

import pytest

from utils.shopify_compliance import (
    _delete_execution_history,
    process_compliance_webhook,
    verify_shopify_hmac,
)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def test_verify_shopify_hmac_uses_raw_body():
    body = b'{"shop_domain":"acme.myshopify.com"}'
    secret = "secret"
    signature = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()

    assert verify_shopify_hmac(body, signature, secret) is True
    assert verify_shopify_hmac(body + b" ", signature, secret) is False
    assert verify_shopify_hmac(body, "wrong", secret) is False


@pytest.mark.asyncio
async def test_delete_execution_history_deletes_cas_before_execution_rows():
    workflow_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    class Conn:
        def __init__(self):
            self.calls = []

        async def fetch(self, sql, *args):
            self.calls.append(("fetch", sql, args))
            return [{"id": execution_id}]

        async def execute(self, sql, *args):
            self.calls.append(("execute", sql, args))
            if "tool_call_events" in sql:
                return "DELETE 2"
            if "conversations" in sql:
                return "DELETE 3"
            if "workflow_executions" in sql:
                return "DELETE 4"
            return "DELETE 1"

    conn = Conn()
    result = await _delete_execution_history(conn, [str(workflow_id)])

    statements = [sql for kind, sql, _ in conn.calls if kind == "execute"]
    assert "cas_refs" in statements[0]
    assert "cas_manifests" in statements[1]
    assert "workflow_executions" in statements[-1]
    assert result == {"executions": 4, "conversations": 3, "tool_calls": 2}
    # asyncpg UUID arrays receive UUID objects rather than untrusted strings.
    assert all(isinstance(v, uuid.UUID) for v in conn.calls[0][2][0])


@pytest.mark.asyncio
async def test_data_request_ledger_hashes_email_and_does_not_store_raw_payload():
    request_id = uuid.uuid4()

    class Conn:
        def __init__(self):
            self.insert_args = None

        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            if "SELECT id, status" in sql:
                return None
            if "INSERT INTO shopify_privacy_requests" in sql:
                self.insert_args = args
                return {"id": request_id}
            return None

        async def fetch(self, sql, *args):
            # No credential is connected to this test shop.
            return []

        async def execute(self, sql, *args):
            return "UPDATE 1"

    conn = Conn()
    raw_email = "Buyer@Example.com"
    result = await process_compliance_webhook(
        topic="customers/data_request",
        webhook_id="webhook-1",
        shop_domain="acme.myshopify.com",
        payload={
            "shop_domain": "acme.myshopify.com",
            "shop_id": 12,
            "customer": {"id": 34, "email": raw_email},
            "orders_requested": [56],
        },
        pool=_Pool(conn),
    )

    assert result["status"] == "pending"
    assert conn.insert_args is not None
    assert raw_email not in json.dumps(conn.insert_args)
    assert conn.insert_args[5] == hashlib.sha256(
        raw_email.lower().encode()
    ).hexdigest()


@pytest.mark.asyncio
async def test_duplicate_compliance_delivery_is_idempotent():
    request_id = uuid.uuid4()

    class Conn:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            return {"id": request_id, "status": "completed"}

    result = await process_compliance_webhook(
        topic="shop/redact",
        webhook_id="same-delivery",
        shop_domain="acme.myshopify.com",
        payload={"shop_domain": "acme.myshopify.com", "shop_id": 12},
        pool=_Pool(Conn()),
    )

    assert result == {
        "accepted": True,
        "duplicate": True,
        "request_id": str(request_id),
        "status": "completed",
    }

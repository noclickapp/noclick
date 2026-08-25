"""
Tests for the inbound-email trigger node: local-part validation, the
EmailReservationManager lifecycle (mocked pool), the inbound-route pure helpers
(MIME parse, sender filter, resource-type mapping), and the end-to-end inbound
route dispatch (mocked DB + execution).
"""

import json
import os
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.email_reservation_manager import (
    EmailReservationManager,
    build_email_address,
    validate_local_part,
)
from tests.mocks.mock_asyncpg import MockNativePool
from utils import email_routes

INBOUND_DOMAIN = os.environ["INBOUND_EMAIL_DOMAIN"]


def _make_pool(conn):
    """Build a mock pool whose `async with pool.acquire() as conn` yields `conn`."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# Local-part validation
# ---------------------------------------------------------------------------

class TestValidateLocalPart:
    @pytest.mark.parametrize("lp", ["invoices", "inv.oices", "a", "team-2025", "a_b", "x1.y2-z3"])
    def test_valid(self, lp):
        ok, err = validate_local_part(lp)
        assert ok is True and err == ""

    @pytest.mark.parametrize("lp", ["", "-bad", "bad-", ".bad", "bad.", "Bad", "has space", "a..b", "with@at"])
    def test_invalid_format(self, lp):
        ok, _ = validate_local_part(lp)
        assert ok is False

    @pytest.mark.parametrize("lp", ["admin", "support", "noreply", "postmaster", "noclick"])
    def test_reserved(self, lp):
        ok, err = validate_local_part(lp)
        assert ok is False and "reserved" in err.lower()

    def test_too_long(self):
        ok, _ = validate_local_part("a" * 65)
        assert ok is False

    def test_build_address(self):
        assert build_email_address("invoices") == f"invoices@{INBOUND_DOMAIN}"
        assert build_email_address("x", "example.com") == "x@example.com"

    def test_unconfigured_local_install_never_mints_hosted_address(self, monkeypatch):
        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.delenv("INBOUND_EMAIL_DOMAIN")
        with pytest.raises(RuntimeError, match="INBOUND_EMAIL_DOMAIN"):
            build_email_address("invoices")

    def test_local_install_rejects_hosted_domain_even_if_set(self, monkeypatch):
        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "noclick.app")
        with pytest.raises(RuntimeError, match="INBOUND_EMAIL_DOMAIN"):
            build_email_address("invoices")


# ---------------------------------------------------------------------------
# EmailReservationManager (mocked pool)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEmailReservationManager:
    async def test_reserve_success(self):
        rid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": rid, "local_part": "invoices", "domain": "noclick.app"})
        result = await EmailReservationManager.reserve(
            _make_pool(conn), str(uuid4()), uuid4(), "node-1", "Invoices"  # mixed case -> normalized
        )
        assert result["email_address"] == "invoices@noclick.app"
        assert result["reservation_id"] == str(rid)
        # Normalized to lowercase before insert
        assert conn.fetchrow.call_args.args[4] == "invoices"

    async def test_reserve_invalid_raises(self):
        conn = AsyncMock()
        with pytest.raises(ValueError):
            await EmailReservationManager.reserve(_make_pool(conn), str(uuid4()), uuid4(), "n1", "-bad-")
        conn.fetchrow.assert_not_called()

    async def test_reserve_reserved_word_raises(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="reserved"):
            await EmailReservationManager.reserve(_make_pool(conn), str(uuid4()), uuid4(), "n1", "admin")

    async def test_reserve_address_taken_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError("dup"))
        with pytest.raises(ValueError, match="already taken"):
            await EmailReservationManager.reserve(_make_pool(conn), str(uuid4()), uuid4(), "n1", "invoices")

    async def test_is_available_free(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        assert await EmailReservationManager.is_available(_make_pool(conn), "invoices") is True

    async def test_is_available_taken(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"workflow_id": uuid4(), "node_id": "other"})
        assert await EmailReservationManager.is_available(_make_pool(conn), "invoices") is False

    async def test_is_available_excludes_own_node(self):
        wf = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"workflow_id": wf, "node_id": "mine"})
        assert await EmailReservationManager.is_available(
            _make_pool(conn), "invoices", exclude_workflow_id=str(wf), exclude_node_id="mine"
        ) is True

    async def test_release(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 1")
        assert await EmailReservationManager.release(_make_pool(conn), uuid4(), "n1") is True

    async def test_release_many_counts(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 3")
        assert await EmailReservationManager.release_many(_make_pool(conn), uuid4(), ["a", "b", "c"]) == 3

    async def test_release_many_empty_noop(self):
        conn = AsyncMock()
        assert await EmailReservationManager.release_many(_make_pool(conn), uuid4(), []) == 0
        conn.execute.assert_not_called()


@pytest.mark.asyncio
class TestReserveFromConfig:
    """The chokepoint the AI builder + MCP server use to validate/claim an
    AI-chosen inbox before it lands in a node config."""

    async def test_returns_config_patch_on_success(self):
        rid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": rid, "local_part": "invoices", "domain": "noclick.app"})
        patch_out = await EmailReservationManager.reserve_from_config(
            _make_pool(conn), str(uuid4()), uuid4(), "node-1", {"local_part": "Invoices"},
        )
        assert patch_out == {
            "local_part": "invoices",
            "email_address": "invoices@noclick.app",
            "reservation_id": str(rid),
        }

    async def test_taken_address_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError("dup"))
        with pytest.raises(ValueError, match="already taken"):
            await EmailReservationManager.reserve_from_config(
                _make_pool(conn), str(uuid4()), uuid4(), "n1", {"local_part": "invoices"},
            )

    async def test_invalid_address_raises_without_db(self):
        conn = AsyncMock()
        with pytest.raises(ValueError):
            await EmailReservationManager.reserve_from_config(
                _make_pool(conn), str(uuid4()), uuid4(), "n1", {"local_part": "admin"},
            )
        conn.fetchrow.assert_not_called()


# ---------------------------------------------------------------------------
# Inbound-route pure helpers
# ---------------------------------------------------------------------------

class TestRouteHelpers:
    def test_resource_type_mapping(self):
        # The mime->resource_type mapping moved into the shared resource_store writer.
        from utils.resource_store import resource_type_for_mime

        assert resource_type_for_mime("image/png") == "image"
        assert resource_type_for_mime("video/mp4") == "video"
        assert resource_type_for_mime("audio/mpeg") == "audio"
        assert resource_type_for_mime("application/pdf") == "document"
        assert resource_type_for_mime("application/octet-stream") == "file"

    def test_sender_allowed_open_by_default(self):
        assert email_routes._sender_allowed("anyone@x.com", None) is True
        assert email_routes._sender_allowed("anyone@x.com", "  ") is True

    def test_sender_allowed_exact(self):
        assert email_routes._sender_allowed("a@x.com", "a@x.com, b@y.com") is True
        assert email_routes._sender_allowed("c@x.com", "a@x.com, b@y.com") is False

    def test_sender_allowed_domain(self):
        assert email_routes._sender_allowed("anyone@trusted.com", "@trusted.com") is True
        assert email_routes._sender_allowed("anyone@evil.com", "@trusted.com") is False

    def test_parse_mime_text_html_attachment(self):
        msg = EmailMessage()
        msg["From"] = "alice@example.com"
        msg["To"] = "invoices@noclick.app"
        msg["Subject"] = "Hi"
        msg.set_content("plain body here")
        msg.add_alternative("<p>html body here</p>", subtype="html")
        msg.add_attachment(b"file-bytes", maintype="application", subtype="pdf", filename="doc.pdf")

        parsed = email_routes._parse_mime(msg.as_bytes())
        assert "plain body here" in parsed["text"]
        assert "html body here" in parsed["html"]
        assert len(parsed["attachments"]) == 1
        att = parsed["attachments"][0]
        assert att["filename"] == "doc.pdf"
        assert att["content_type"] == "application/pdf"
        assert att["data"] == b"file-bytes"


# ---------------------------------------------------------------------------
# Inbound route dispatch (mocked DB + execution)
# ---------------------------------------------------------------------------

@pytest.fixture
def email_client(monkeypatch):
    monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-secret")
    app = FastAPI()
    app.include_router(email_routes.router)
    return TestClient(app)


class TestInboundRoute:
    def _post(self, client, body: dict, secret="test-secret"):
        return client.post(
            "/email/inbound",
            content=json.dumps(body),
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        )

    def test_rejects_bad_auth(self, email_client):
        resp = self._post(email_client, {"to": "x@noclick.app"}, secret="wrong")
        assert resp.status_code == 401

    def test_unknown_address_404(self, email_client):
        with patch.object(email_routes, "get_email_config", AsyncMock(return_value=None)):
            resp = self._post(email_client, {"to": "ghost@noclick.app", "from": "a@b.com"})
        assert resp.status_code == 404

    def test_triggers_workflow_and_injects_payload(self, email_client):
        wf_id = str(uuid4())
        node_id = "email-trigger-1"
        config = {
            "id": uuid4(),
            "user_id": UUID(int=1),
            "workflow_id": UUID(wf_id),
            "node_id": node_id,
            "is_active": True,
            "organization_id": None,
            "workflow_config": {
                "nodes": [{"id": node_id, "type": "trigger-email", "config": {}}],
                "edges": [],
            },
        }
        exec_mock = AsyncMock()
        pool = MockNativePool()
        with patch.object(email_routes, "get_email_config", AsyncMock(return_value=config)), \
             patch.object(email_routes, "_execute_workflow_with_relay", exec_mock), \
            patch.object(email_routes, "get_native_pool", lambda: pool):
            resp = self._post(email_client, {
                "to": f"Invoices <invoices@{INBOUND_DOMAIN}>",
                "from": "Alice <alice@example.com>",
                "subject": "Order #42",
                "headers": {"message-id": "<abc>"},
                "spfPass": True,
            })
        assert resp.status_code == 200
        assert resp.json()["triggered"] is True
        exec_mock.assert_awaited_once()
        kwargs = exec_mock.await_args.kwargs
        assert kwargs["start_node_id"] == node_id
        assert kwargs["workflow_id"] == wf_id
        trigger_node = next(n for n in kwargs["nodes"] if n["id"] == node_id)
        payload = trigger_node["config"]["_triggerPayload"]
        assert payload["type"] == "email-trigger"
        assert payload["from"] == "alice@example.com"
        assert payload["subject"] == "Order #42"
        assert payload["spf_pass"] is True
        # The minted reply token authorizes the agent's locked email__reply
        # tool for THIS email (utils/email_reply.py).
        from utils.email_reply import verify_reply_token
        assert verify_reply_token(
            payload["reply_token"],
            to_addr=payload["to"],
            sender=payload["from"],
            message_id="<abc>",
            timestamp=payload["timestamp"],
        )

    def test_disallowed_sender_skips(self, email_client):
        node_id = "n1"
        config = {
            "id": uuid4(),
            "user_id": UUID(int=1),
            "workflow_id": uuid4(),
            "node_id": node_id,
            "is_active": True,
            "organization_id": None,
            "workflow_config": {
                "nodes": [{"id": node_id, "type": "trigger-email", "config": {"allowed_senders": "@trusted.com"}}],
                "edges": [],
            },
        }
        exec_mock = AsyncMock()
        with patch.object(email_routes, "get_email_config", AsyncMock(return_value=config)), \
             patch.object(email_routes, "_execute_workflow_with_relay", exec_mock):
            resp = self._post(email_client, {"to": f"n1@{INBOUND_DOMAIN}", "from": "evil@spam.com"})
        assert resp.status_code == 200
        assert resp.json()["triggered"] is False
        exec_mock.assert_not_awaited()

    def test_unconfigured_local_install_disables_inbound_route(self, email_client, monkeypatch):
        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.delenv("INBOUND_EMAIL_DOMAIN")
        resp = self._post(email_client, {"to": "x@noclick.app", "from": "a@b.com"})
        assert resp.status_code == 503


@pytest.mark.asyncio
class TestStoreAttachments:
    async def test_attachment_cap_matches_direct_resource_upload_cap(self):
        from wss.handlers.resource_handler import MAX_UPLOAD_SIZE_BYTES

        assert email_routes.MAX_ATTACHMENT_BYTES == MAX_UPLOAD_SIZE_BYTES
        assert email_routes.MAX_ATTACHMENT_BYTES == 100 * 1024 * 1024

    async def test_attachments_over_cap_are_skipped(self, monkeypatch):
        monkeypatch.setattr(email_routes, "MAX_ATTACHMENT_BYTES", 4)
        with patch.object(
            email_routes, "create_resource_from_bytes", AsyncMock()
        ) as create_resource:
            out = await email_routes._store_attachments(
                uuid4(), None, uuid4(), "node-1",
                [{
                    "filename": "too-large.bin",
                    "content_type": "application/octet-stream",
                    "data": b"12345",
                }],
            )

        assert out == []
        create_resource.assert_not_awaited()

    async def test_metadata_passed_as_dict_not_json_string(self):
        """metadata must reach the INSERT as a dict, not json.dumps'd. The runtime pool's
        jsonb codec serializes dicts; pre-serializing double-encodes it into a JSON string
        scalar that reads back as str, fails ResourceInfo validation, and breaks the whole
        resource:list for the workflow (the email-trigger Resources-tab bug). The INSERT now
        lives in the shared resource_store writer, so patch there."""
        from utils import resource_store

        pool = MockNativePool()
        with patch.object(resource_store, "get_native_pool", lambda: pool), \
             patch.object(resource_store, "upload_bytes_to_r2_async", AsyncMock()), \
             patch.object(resource_store, "get_public_download_url", lambda key: f"https://assets/{key}"):
            out = await email_routes._store_attachments(
                uuid4(), None, uuid4(), "node-1",
                [{"filename": "a.pdf", "content_type": "application/pdf", "data": b"hello"}],
            )
        assert len(out) == 1
        # metadata is the last positional arg of the INSERT (after the query string).
        metadata_arg = pool.execute.await_args.args[-1]
        assert isinstance(metadata_arg, dict), f"metadata must be a dict, got {type(metadata_arg).__name__}"
        assert metadata_arg == {"source": "email"}

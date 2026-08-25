"""Phase 1 webhook-trigger framework tests, exercised end-to-end via the
Typeform ``on_new_form_response`` trigger.

Covers the shared plumbing introduced in Phase 1:
- ``utils.webhook_signatures`` HMAC primitives
- ``WorkflowNode`` base hooks (verify_webhook_signature / handle_webhook_handshake)
- ``ExternalWebhookTriggerMixin`` registration + cleanup flow
- ``webhook_routes._apply_trigger_node_hooks`` receiver dispatch
- Typeform node: trigger config, register/unregister, signature verification

Run: pytest nodes/tests/test_typeform_trigger.py -v
"""

import base64
import hashlib
import hmac
import uuid

import pytest
from unittest.mock import AsyncMock, patch

from nodes.core.base import WorkflowNode
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.typeform_node import (
    TypeformNode,
    TypeformOnNewResponseConfig,
    _typeform_token_from_credential,
    _typeform_webhook_tag,
)
from utils.webhook_signatures import (
    verify_hmac_sha256_base64,
    verify_hmac_sha256_hex,
)


def _typeform_signature(body: bytes, secret: str) -> str:
    """Build a `Typeform-Signature` header value for *body*."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return "sha256=" + base64.b64encode(digest).decode()


# ---------------------------------------------------------------------------
# webhook_signatures primitives
# ---------------------------------------------------------------------------


class TestSignaturePrimitives:
    def test_hmac_base64_roundtrip(self):
        body, secret = b'{"event": 1}', "topsecret"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        sig = base64.b64encode(digest).decode()
        assert verify_hmac_sha256_base64(body, secret, sig) is True

    def test_hmac_base64_rejects_wrong_secret(self):
        body = b'{"event": 1}'
        digest = hmac.new(b"topsecret", body, hashlib.sha256).digest()
        sig = base64.b64encode(digest).decode()
        assert verify_hmac_sha256_base64(body, "wrong", sig) is False

    def test_hmac_base64_rejects_tampered_body(self):
        secret = "topsecret"
        digest = hmac.new(secret.encode(), b"original", hashlib.sha256).digest()
        sig = base64.b64encode(digest).decode()
        assert verify_hmac_sha256_base64(b"tampered", secret, sig) is False

    def test_hmac_base64_rejects_empty(self):
        assert verify_hmac_sha256_base64(b"x", "", "sig") is False
        assert verify_hmac_sha256_base64(b"x", "secret", "") is False

    def test_hmac_hex_with_prefix(self):
        body, secret = b"payload", "secret"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # GitHub-style: header carries a "sha256=" prefix.
        assert verify_hmac_sha256_hex(
            body, secret, f"sha256={expected}", prefix="sha256="
        ) is True
        # A bare-hex signature fails when a prefix is expected.
        assert verify_hmac_sha256_hex(
            body, secret, expected, prefix="sha256="
        ) is False
        # Prefix-less verification of a bare-hex signature.
        assert verify_hmac_sha256_hex(body, secret, expected) is True
        assert verify_hmac_sha256_hex(body, secret, "deadbeef") is False


# ---------------------------------------------------------------------------
# WorkflowNode base hook defaults
# ---------------------------------------------------------------------------


class TestBaseHookDefaults:
    def test_default_verify_accepts(self):
        # A non-trigger node inherits the permissive base default.
        from nodes.log_node import LogNode

        assert LogNode.verify_webhook_signature(b"x", {}, {}) is True

    def test_default_handshake_is_none(self):
        from nodes.log_node import LogNode

        assert LogNode.handle_webhook_handshake(b"x", {}) is None

    def test_default_ack_response_is_none(self):
        from nodes.log_node import LogNode

        assert LogNode.webhook_ack_response() is None


# ---------------------------------------------------------------------------
# Typeform trigger config + helpers
# ---------------------------------------------------------------------------


class TestTypeformTriggerConfig:
    def test_trigger_op_in_schema_marked_as_trigger(self):
        schema = TypeformNode.get_config_schema()
        defs = schema["$defs"]
        op = defs["TypeformOnNewResponseConfig"]["properties"]["operation"]
        assert op["const"] == "on_new_form_response"
        assert op["x-is-trigger"] is True

    def test_node_uses_webhook_trigger_mixin(self):
        assert issubclass(TypeformNode, ExternalWebhookTriggerMixin)
        assert issubclass(TypeformNode, WorkflowNode)

    def test_webhook_tag_is_deterministic(self):
        assert _typeform_webhook_tag("node-7") == "noclick-node-7"
        assert _typeform_webhook_tag("node-7") == _typeform_webhook_tag("node-7")

    def test_token_extraction_pat_and_oauth(self):
        assert _typeform_token_from_credential({"personal_access_token": "pat"}) == "pat"
        assert _typeform_token_from_credential({"access_token": "oauth"}) == "oauth"
        assert _typeform_token_from_credential({}) is None


# ---------------------------------------------------------------------------
# Typeform signature verification
# ---------------------------------------------------------------------------


class TestTypeformSignatureVerification:
    def test_valid_signature_accepted(self):
        body, secret = b'{"event_type": "form_response"}', "abc123"
        headers = {"typeform-signature": _typeform_signature(body, secret)}
        config = {"signing_secret": secret}
        assert TypeformNode.verify_webhook_signature(body, headers, config) is True

    def test_invalid_signature_rejected(self):
        body, secret = b'{"event_type": "form_response"}', "abc123"
        headers = {"typeform-signature": _typeform_signature(b"other", secret)}
        config = {"signing_secret": secret}
        assert TypeformNode.verify_webhook_signature(body, headers, config) is False

    def test_missing_secret_rejected(self):
        # No persisted secret means the trigger was never registered — reject
        # rather than fail open.
        body = b"{}"
        headers = {"typeform-signature": _typeform_signature(body, "x")}
        assert TypeformNode.verify_webhook_signature(body, headers, {}) is False

    def test_missing_header_rejected(self):
        config = {"signing_secret": "abc123"}
        assert TypeformNode.verify_webhook_signature(b"{}", {}, config) is False


# ---------------------------------------------------------------------------
# Typeform external registration / cleanup
# ---------------------------------------------------------------------------


class TestTypeformRegistration:
    async def test_register_calls_provider_and_returns_secret(self):
        with patch(
            "nodes.typeform_node.register_typeform_webhook", new=AsyncMock()
        ) as mock_register:
            result = await TypeformNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={"personal_access_token": "pat-token"},
                config={"form_id": "FORM123"},
                node_id="node-1",
            )
        assert "signing_secret" in result and result["signing_secret"]
        mock_register.assert_awaited_once()
        args = mock_register.await_args.args
        # (token, form_id, tag, webhook_url, secret)
        assert args[0] == "pat-token"
        assert args[1] == "FORM123"
        assert args[2] == "noclick-node-1"
        assert args[3] == "https://wh.hooks.example.test/abc"
        assert args[4] == result["signing_secret"]

    async def test_register_reuses_existing_secret(self):
        with patch(
            "nodes.typeform_node.register_typeform_webhook", new=AsyncMock()
        ):
            result = await TypeformNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={"access_token": "oauth-token"},
                config={"form_id": "FORM123", "signing_secret": "preexisting"},
                node_id="node-1",
            )
        assert result["signing_secret"] == "preexisting"

    async def test_register_without_form_id_raises(self):
        with pytest.raises(ValueError, match="Form ID"):
            await TypeformNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={"personal_access_token": "pat"},
                config={},
                node_id="node-1",
            )

    async def test_register_without_token_raises(self):
        with pytest.raises(ValueError, match="access token"):
            await TypeformNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={},
                config={"form_id": "FORM123"},
                node_id="node-1",
            )

    async def test_unregister_calls_provider(self):
        with patch(
            "nodes.typeform_node.unregister_typeform_webhook", new=AsyncMock()
        ) as mock_unregister:
            await TypeformNode._unregister_external_webhook(
                credential={"personal_access_token": "pat"},
                config={"form_id": "FORM123"},
                node_id="node-1",
            )
        mock_unregister.assert_awaited_once_with("pat", "FORM123", "noclick-node-1")

    async def test_unregister_noop_without_form_or_token(self):
        with patch(
            "nodes.typeform_node.unregister_typeform_webhook", new=AsyncMock()
        ) as mock_unregister:
            await TypeformNode._unregister_external_webhook(
                credential={}, config={"form_id": "FORM123"}, node_id="node-1"
            )
        mock_unregister.assert_not_awaited()


# ---------------------------------------------------------------------------
# ExternalWebhookTriggerMixin.load_field_value flow
# ---------------------------------------------------------------------------


class TestLoadFieldValueFlow:
    async def test_provisions_url_and_registers(self):
        webhook_data = {
            "webhook_id": "wh-1",
            "webhook_url": "https://wh.hooks.example.test/wh-1",
            "relay_connected": True,
            "is_production": True,
        }
        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=AsyncMock(return_value=webhook_data),
        ), patch(
            "utils.webhook_manager.WebhookManager.persist_registration_state",
            new=AsyncMock(),
        ) as mock_persist, patch(
            "nodes.core.webhook_trigger.load_credential",
            new=AsyncMock(return_value={"personal_access_token": "pat"}),
        ), patch(
            "nodes.typeform_node.register_typeform_webhook", new=AsyncMock()
        ) as mock_register:
            result = await TypeformNode.load_field_value(
                field_name="webhook_url",
                user_id="user-1",
                workflow_id=uuid.uuid4(),
                node_id="node-1",
                pool=object(),
                context={"form_id": "FORM123", "operation": "on_response"},
                credential_ids={"typeform_pat": "cred-1"},
            )
        values = result["values"]
        assert values["webhook_id"] == "wh-1"
        assert values["webhook_url"] == "https://wh.hooks.example.test/wh-1"
        assert values["trigger_registered"] is True
        assert values["trigger_error"] is None
        assert values["signing_secret"]
        mock_register.assert_awaited_once()
        # Registration state lands on the webhooks row synchronously — the
        # system of record for the guard, verification, and deregistration.
        mock_persist.assert_awaited_once()
        persist_kwargs = mock_persist.await_args.kwargs
        assert persist_kwargs["registered_operation"] == "on_response"
        assert persist_kwargs["registered_credential_id"] == "cred-1"
        assert persist_kwargs["signing_secret"]

    async def test_no_credential_yields_unregistered(self):
        webhook_data = {
            "webhook_id": "wh-1",
            "webhook_url": "https://wh.hooks.example.test/wh-1",
            "relay_connected": False,
            "is_production": False,
        }
        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=AsyncMock(return_value=webhook_data),
        ), patch(
            "nodes.core.webhook_trigger.load_credential",
            new=AsyncMock(return_value=None),
        ):
            result = await TypeformNode.load_field_value(
                field_name="webhook_url",
                user_id="user-1",
                workflow_id=uuid.uuid4(),
                node_id="node-1",
                pool=object(),
                context={"form_id": "FORM123"},
                credential_ids=None,
            )
        values = result["values"]
        assert values["webhook_url"] == "https://wh.hooks.example.test/wh-1"
        assert values["trigger_registered"] is False
        assert "credentials" in values["trigger_error"].lower()

    async def test_registration_failure_surfaced_as_error(self):
        webhook_data = {
            "webhook_id": "wh-1",
            "webhook_url": "https://wh.hooks.example.test/wh-1",
            "relay_connected": True,
            "is_production": True,
        }
        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=AsyncMock(return_value=webhook_data),
        ), patch(
            "nodes.core.webhook_trigger.load_credential",
            new=AsyncMock(return_value={"personal_access_token": "pat"}),
        ):
            # context has no form_id -> _register_external_webhook raises
            result = await TypeformNode.load_field_value(
                field_name="webhook_url",
                user_id="user-1",
                workflow_id=uuid.uuid4(),
                node_id="node-1",
                pool=object(),
                context={},
                credential_ids={"typeform_pat": "cred-1"},
            )
        values = result["values"]
        assert values["trigger_registered"] is False
        assert "Form ID" in values["trigger_error"]

    async def test_ignores_non_webhook_field(self):
        result = await TypeformNode.load_field_value(
            field_name="form_id",
            user_id="user-1",
            workflow_id=uuid.uuid4(),
            node_id="node-1",
            pool=object(),
            context={},
            credential_ids=None,
        )
        assert result == {"value": None}


# ---------------------------------------------------------------------------
# Receiver hook dispatch
# ---------------------------------------------------------------------------


class TestReceiverHookDispatch:
    @pytest.mark.asyncio
    async def test_valid_signature_proceeds(self):
        from utils.webhook_routes import _apply_trigger_node_hooks

        body, secret = b'{"event_type": "form_response"}', "abc123"
        trigger_node = {
            "id": "node-1",
            "type": "automation-typeform",
            "config": {"signing_secret": secret},
        }
        headers = {"Typeform-Signature": _typeform_signature(body, secret)}
        # Returns None -> caller proceeds with normal dispatch.
        assert await _apply_trigger_node_hooks(trigger_node, body, headers) is None

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        from fastapi import HTTPException
        from utils.webhook_routes import _apply_trigger_node_hooks

        body, secret = b'{"event_type": "form_response"}', "abc123"
        trigger_node = {
            "id": "node-1",
            "type": "automation-typeform",
            "config": {"signing_secret": secret},
        }
        headers = {"Typeform-Signature": _typeform_signature(b"forged", secret)}
        with pytest.raises(HTTPException) as exc:
            await _apply_trigger_node_hooks(trigger_node, body, headers)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_node_type_is_passthrough(self):
        from utils.webhook_routes import _apply_trigger_node_hooks

        trigger_node = {"id": "n", "type": "not-a-real-node", "config": {}}
        assert await _apply_trigger_node_hooks(trigger_node, b"{}", {}) is None


# ---------------------------------------------------------------------------
# Manual-run output
# ---------------------------------------------------------------------------


class TestManualRunOutput:
    def test_manual_run_returns_placeholder(self):
        node = TypeformNode(
            node_id="node-1",
            node_type="automation-typeform",
            node_data={},
            config=None,
        )
        cfg = TypeformOnNewResponseConfig(form_id="FORM123")
        result = node._trigger_on_new_response(cfg)
        assert result["form_id"] == "FORM123"
        assert "fires" in result["message"]

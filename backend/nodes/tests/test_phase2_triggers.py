"""Phase 2 webhook-trigger tests — GitHub, Shopify, Linear, Twilio.

Each provider has a distinct wrinkle these tests pin down:
- GitHub: per-webhook generated secret, X-Hub-Signature-256 hex, `ping` handshake
- Shopify: secret sourced from the credential's API secret key, base64 HMAC
- Linear: secret returned by the webhookCreate mutation, Linear-Signature hex
- Twilio: SmsUrl registration, X-Twilio-Signature SHA1, TwiML ack response

Run: pytest nodes/tests/test_phase2_triggers.py -v
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import AsyncMock, patch

from nodes.github_rest_node import GithubRestNode
from nodes.shopify_node import ShopifyNode
from nodes.linear_node import LinearNode, _linear_auth_header
from nodes.twilio_node import TwilioNode, TwilioOnIncomingSmsConfig
from utils.webhook_signatures import verify_twilio_signature


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class TestGithubTrigger:
    def test_valid_signature_accepted(self):
        body, secret = b'{"action": "opened"}', "ghsecret"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        config = {"signing_secret": secret}
        assert GithubRestNode.verify_webhook_signature(body, {"x-hub-signature-256": sig}, config) is True

    def test_invalid_signature_rejected(self):
        config = {"signing_secret": "ghsecret"}
        bad = "sha256=" + hmac.new(b"ghsecret", b"other", hashlib.sha256).hexdigest()
        assert GithubRestNode.verify_webhook_signature(b'{"a":1}', {"x-hub-signature-256": bad}, config) is False

    def test_missing_secret_rejected(self):
        assert GithubRestNode.verify_webhook_signature(b"{}", {"x-hub-signature-256": "sha256=x"}, {}) is False

    def test_ping_handshake(self):
        assert GithubRestNode.handle_webhook_handshake(b"{}", {"x-github-event": "ping"}) == {"msg": "pong"}

    def test_non_ping_proceeds(self):
        assert GithubRestNode.handle_webhook_handshake(b"{}", {"x-github-event": "push"}) is None

    def test_per_event_trigger_ops_in_schema(self):
        # The generic on_repository_event was split into per-event triggers.
        schema = GithubRestNode.get_config_schema()
        defs = schema["$defs"]
        trigger_ops = sorted(
            v["properties"]["operation"]["const"]
            for v in defs.values()
            if v.get("properties", {}).get("operation", {}).get("x-is-trigger")
        )
        assert trigger_ops == sorted(GithubRestNode._trigger_event_map)

    async def test_register_creates_hook(self):
        # Repository comes as a single owner/name field; events derive from the op.
        with patch("nodes.github_rest_node.register_github_webhook", new=AsyncMock(return_value=99)) as mock_reg:
            result = await GithubRestNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"personal_access_token": "pat"},
                config={"operation": "on_push", "repository": "acme/site"},
                node_id="n1",
            )
        assert result["external_webhook_id"] == 99
        assert result["signing_secret"]
        args = mock_reg.await_args.args
        assert args[1] == "acme" and args[2] == "site"
        assert args[5] == ["push"]  # events derived from the on_push operation

    async def test_register_without_repo_raises(self):
        with pytest.raises(ValueError, match="Select a repository"):
            await GithubRestNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"personal_access_token": "pat"},
                config={"operation": "on_push"},
                node_id="n1",
            )

    async def test_register_drops_stale_hook(self):
        with patch("nodes.github_rest_node.register_github_webhook", new=AsyncMock(return_value=100)), patch(
            "nodes.github_rest_node.unregister_github_webhook", new=AsyncMock()
        ) as mock_unreg:
            await GithubRestNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"access_token": "oauth"},
                config={"operation": "on_issue_opened", "repository": "acme/site", "external_webhook_id": 55},
                node_id="n1",
            )
        mock_unreg.assert_awaited_once()

    async def test_unregister_calls_provider(self):
        with patch("nodes.github_rest_node.unregister_github_webhook", new=AsyncMock()) as mock_unreg:
            await GithubRestNode._unregister_external_webhook(
                credential={"personal_access_token": "pat"},
                config={"operation": "on_push", "repository": "acme/site", "external_webhook_id": 77},
                node_id="n1",
            )
        mock_unreg.assert_awaited_once_with("pat", "acme", "site", 77)

    async def test_resolve_trigger_credential_refreshes_expired_oauth(self):
        cred = {
            "access_token": "stale-token",
            "refresh_token": "refresh-1",
            "expires_at": "2000-01-01T00:00:00+00:00",
        }
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=cred),
        ), patch(
            "nodes.oauth.github_oauth.refresh_access_token",
            new=AsyncMock(
                return_value=type(
                    "T",
                    (),
                    {
                        "access_token": "fresh-token",
                        "refresh_token": "refresh-2",
                        "expires_at": "2999-01-01T00:00:00+00:00",
                    },
                )()
            ),
        ), patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ) as mock_persist:
            resolved = await GithubRestNode._resolve_trigger_credential(
                pool=object(),
                user_id="u1",
                credential_ids={"github_oauth": "cid"},
            )
        assert resolved["access_token"] == "fresh-token"
        assert resolved["refresh_token"] == "refresh-2"
        mock_persist.assert_awaited_once()


# ---------------------------------------------------------------------------
# Shopify
# ---------------------------------------------------------------------------


class TestShopifyTrigger:
    def test_valid_signature_accepted(self):
        body, secret = b'{"id": 1}', "shop_app_secret"
        sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        config = {"signing_secret": secret}
        assert ShopifyNode.verify_webhook_signature(body, {"x-shopify-hmac-sha256": sig}, config) is True

    def test_invalid_signature_rejected(self):
        config = {"signing_secret": "shop_app_secret"}
        assert ShopifyNode.verify_webhook_signature(b'{"id":1}', {"x-shopify-hmac-sha256": "bogus"}, config) is False

    def test_per_event_trigger_ops_in_schema(self):
        # The generic on_store_event was split into per-topic triggers.
        schema = ShopifyNode.get_config_schema()
        defs = schema["$defs"]
        trigger_ops = sorted(
            v["properties"]["operation"]["const"]
            for v in defs.values()
            if v.get("properties", {}).get("operation", {}).get("x-is-trigger")
        )
        assert trigger_ops == sorted(ShopifyNode._trigger_event_map)

    async def test_register_uses_api_secret_as_signing_secret(self):
        # The Shopify topic is derived from the chosen trigger operation.
        with patch("nodes.shopify_node.register_shopify_webhook", new=AsyncMock(return_value=42)) as mock_reg:
            result = await ShopifyNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={
                    "access_token": "tok",
                    "store_name": "demo",
                    "api_secret_key": "the_app_secret",
                },
                config={"operation": "on_order_created"},
                node_id="n1",
            )
        assert result["signing_secret"] == "the_app_secret"
        assert result["external_webhook_id"] == 42
        assert mock_reg.await_args.args[2] == "orders/create"  # topic from the op

    async def test_register_without_api_secret_raises(self):
        with pytest.raises(ValueError, match="API secret key"):
            await ShopifyNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"access_token": "tok", "store_name": "demo"},
                config={"operation": "on_order_created"},
                node_id="n1",
            )

    async def test_register_unknown_operation_raises(self):
        with pytest.raises(ValueError, match="topic"):
            await ShopifyNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"access_token": "tok", "store_name": "demo", "api_secret_key": "s"},
                config={},
                node_id="n1",
            )

    async def test_unregister_calls_provider(self):
        with patch("nodes.shopify_node.unregister_shopify_webhook", new=AsyncMock()) as mock_unreg:
            await ShopifyNode._unregister_external_webhook(
                credential={"access_token": "tok", "store_name": "demo"},
                config={"external_webhook_id": 42},
                node_id="n1",
            )
        mock_unreg.assert_awaited_once_with("demo", "tok", 42)


# ---------------------------------------------------------------------------
# Linear
# ---------------------------------------------------------------------------


class TestLinearTrigger:
    def test_auth_header_pat_vs_oauth(self):
        assert _linear_auth_header({"api_key": "lin_xxx"}) == "lin_xxx"
        assert _linear_auth_header({"access_token": "tok"}) == "Bearer tok"
        assert _linear_auth_header({}) is None

    def test_valid_signature_accepted(self):
        body, secret = b'{"action": "create"}', "lin_secret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        config = {"signing_secret": secret}
        assert LinearNode.verify_webhook_signature(body, {"linear-signature": sig}, config) is True

    def test_invalid_signature_rejected(self):
        config = {"signing_secret": "lin_secret"}
        assert LinearNode.verify_webhook_signature(b'{"a":1}', {"linear-signature": "deadbeef"}, config) is False

    async def test_register_returns_id_and_secret(self):
        with patch(
            "nodes.linear_node.register_linear_webhook",
            new=AsyncMock(return_value=("wh-123", "lin_generated_secret")),
        ):
            result = await LinearNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={"api_key": "lin_xxx"},
                config={"operation": "on_issue_created"},
                node_id="n1",
            )
        assert result["external_webhook_id"] == "wh-123"
        assert result["signing_secret"] == "lin_generated_secret"

    async def test_register_without_secret_raises(self):
        with patch(
            "nodes.linear_node.register_linear_webhook",
            new=AsyncMock(return_value=("wh-123", None)),
        ):
            with pytest.raises(ValueError, match="signing secret"):
                await LinearNode._register_external_webhook(
                    webhook_url="https://wh.hooks.example.test/a",
                    credential={"api_key": "lin_xxx"},
                    config={"operation": "on_issue_created"},
                    node_id="n1",
                )

    async def test_register_without_credential_raises(self):
        with pytest.raises(ValueError, match="API key or access token"):
            await LinearNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/a",
                credential={},
                config={"operation": "on_issue_created"},
                node_id="n1",
            )

    async def test_unregister_calls_provider(self):
        with patch("nodes.linear_node.unregister_linear_webhook", new=AsyncMock()) as mock_unreg:
            await LinearNode._unregister_external_webhook(
                credential={"api_key": "lin_xxx"},
                config={"external_webhook_id": "wh-123"},
                node_id="n1",
            )
        mock_unreg.assert_awaited_once_with("lin_xxx", "wh-123")


# ---------------------------------------------------------------------------
# Twilio
# ---------------------------------------------------------------------------


def _twilio_signature(url: str, params: dict, auth_token: str) -> str:
    signing = url + "".join(k + str(params[k]) for k in sorted(params))
    return base64.b64encode(
        hmac.new(auth_token.encode(), signing.encode(), hashlib.sha1).digest()
    ).decode()


class TestTwilioTrigger:
    def test_signature_primitive(self):
        url = "https://wh.hooks.example.test/abc"
        params = {"From": "+12025550106", "Body": "hello"}
        sig = _twilio_signature(url, params, "auth_tok")
        assert verify_twilio_signature(url, params, "auth_tok", sig) is True
        assert verify_twilio_signature(url, params, "wrong", sig) is False

    def test_verify_webhook_signature(self):
        url = "https://wh.hooks.example.test/abc"
        body = b"From=%2B12025550106&Body=hello"
        params = {"From": "+12025550106", "Body": "hello"}
        sig = _twilio_signature(url, params, "auth_tok")
        config = {"signing_secret": "auth_tok", "webhook_url": url}
        assert TwilioNode.verify_webhook_signature(body, {"x-twilio-signature": sig}, config) is True

    def test_verify_rejects_tampered_body(self):
        url = "https://wh.hooks.example.test/abc"
        params = {"From": "+12025550106", "Body": "hello"}
        sig = _twilio_signature(url, params, "auth_tok")
        config = {"signing_secret": "auth_tok", "webhook_url": url}
        assert TwilioNode.verify_webhook_signature(b"From=%2B1&Body=evil", {"x-twilio-signature": sig}, config) is False

    def test_verify_without_config_rejected(self):
        assert TwilioNode.verify_webhook_signature(b"x", {"x-twilio-signature": "s"}, {}) is False

    def test_resolve_trigger_payload_parses_form(self):
        payload = {"raw": "From=%2B12025550106&Body=hi+there", "_webhook": {"id": "w"}}
        result = TwilioNode.resolve_trigger_payload(payload, {})
        assert result["From"] == "+12025550106"
        assert result["Body"] == "hi there"
        assert result["_webhook"] == {"id": "w"}

    def test_ack_response_is_twiml(self):
        ack = TwilioNode.webhook_ack_response()
        assert ack["media_type"] == "application/xml"
        assert "<Response>" in ack["content"]

    async def test_register_sets_sms_url(self):
        with patch("nodes.twilio_node.set_twilio_sms_webhook", new=AsyncMock()) as mock_set:
            result = await TwilioNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={"account_sid": "ACxxx", "auth_token": "tok"},
                config={"phone_number_sid": "PNxxx"},
                node_id="n1",
            )
        assert result["signing_secret"] == "tok"
        mock_set.assert_awaited_once_with("ACxxx", "tok", "PNxxx", "https://wh.hooks.example.test/abc")

    async def test_register_without_account_credential_raises(self):
        with pytest.raises(ValueError, match="Account SID"):
            await TwilioNode._register_external_webhook(
                webhook_url="https://wh.hooks.example.test/abc",
                credential={"api_key_sid": "SKxxx"},
                config={"phone_number_sid": "PNxxx"},
                node_id="n1",
            )

    async def test_unregister_clears_sms_url(self):
        with patch("nodes.twilio_node.set_twilio_sms_webhook", new=AsyncMock()) as mock_set:
            await TwilioNode._unregister_external_webhook(
                credential={"account_sid": "ACxxx", "auth_token": "tok"},
                config={"phone_number_sid": "PNxxx"},
                node_id="n1",
            )
        mock_set.assert_awaited_once_with("ACxxx", "tok", "PNxxx", "")


# ---------------------------------------------------------------------------
# Receiver dispatch — handshake + ack
# ---------------------------------------------------------------------------


class TestReceiverDispatch:
    @pytest.mark.asyncio
    async def test_github_ping_handshake_short_circuits(self):
        from utils.webhook_routes import _apply_trigger_node_hooks

        node = {"id": "n1", "type": "automation-github-rest", "config": {"signing_secret": "s"}}
        result = await _apply_trigger_node_hooks(node, b"{}", {"X-GitHub-Event": "ping"})
        assert result == {"msg": "pong"}

    def test_twilio_ack_response_is_twiml(self):
        from utils.webhook_routes import _webhook_ack_for_node

        node = {"id": "n1", "type": "automation-twilio", "config": {}}
        ack = _webhook_ack_for_node(node)
        assert ack is not None
        assert ack.media_type == "application/xml"

    def test_github_node_has_no_ack_override(self):
        from utils.webhook_routes import _webhook_ack_for_node

        node = {"id": "n1", "type": "automation-github-rest", "config": {}}
        assert _webhook_ack_for_node(node) is None

"""
Mock tests for the Brandfetch REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Brand: by domain, ticker, ISIN, crypto, auto-detect
- Context: JSON, Markdown
- Search: search_brands
- Transaction: identify_transaction
- Logo CDN URL builders: by domain, ticker, crypto, ISIN, themed
- Trigger: receive_webhook passthrough
- Error handling: API errors, missing credentials, missing client_id for Logo/Search

Run: pytest nodes/tests/test_brandfetch_node_mock.py -q
"""

import base64
import hashlib
import hmac
import time

import pytest
from unittest.mock import Mock, patch

from nodes.brandfetch_node import (
    BrandfetchNode,
    BrandfetchNodeConfig,
    BrandfetchApiKeyCredential,
    BrandfetchGetBrandByDomainConfig,
    BrandfetchGetBrandByTickerConfig,
    BrandfetchGetBrandByIsinConfig,
    BrandfetchGetBrandByCryptoConfig,
    BrandfetchGetBrandConfig,
    BrandfetchGetContextJsonConfig,
    BrandfetchGetContextMarkdownConfig,
    BrandfetchSearchConfig,
    BrandfetchTransactionConfig,
    BrandfetchLogoByDomainConfig,
    BrandfetchLogoByTickerConfig,
    BrandfetchLogoByCryptoConfig,
    BrandfetchLogoByIsinConfig,
    BrandfetchThemedLogoConfig,
    BrandfetchReceiveWebhookConfig,
    BRANDFETCH_WEBHOOK_EVENTS,
    BRANDFETCH_WEBHOOK_EVENT_ALL,
)


@pytest.fixture
def credentials():
    return BrandfetchApiKeyCredential(api_key="bf_test_key_123", client_id="pub_client_123")


@pytest.fixture
def credentials_no_client_id():
    return BrandfetchApiKeyCredential(api_key="bf_test_key_123")


def create_brandfetch_node(config):
    return BrandfetchNode(
        node_id="test-brandfetch-node",
        node_type="automation-brandfetch",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, text=""):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


class TestBrandfetchBrandMock:
    @pytest.mark.asyncio
    async def test_get_brand_by_domain(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByDomainConfig(domain="nike.com", allow_nsfw="false"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Nike", "domain": "nike.com"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_brand_by_domain"
        assert result["data"]["name"] == "Nike"

    @pytest.mark.asyncio
    async def test_get_brand_by_ticker(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByTickerConfig(ticker="NKE"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Nike", "ticker": "NKE"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_brand_by_ticker"
        assert result["data"]["ticker"] == "NKE"

    @pytest.mark.asyncio
    async def test_get_brand_by_isin(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByIsinConfig(isin="US6541061031"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Nike", "isin": "US6541061031"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_brand_by_isin"

    @pytest.mark.asyncio
    async def test_get_brand_by_crypto(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByCryptoConfig(symbol="BTC"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Bitcoin", "symbol": "BTC"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_brand_by_crypto"

    @pytest.mark.asyncio
    async def test_get_brand_auto_detect(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandConfig(identifier="nike.com"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Nike"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_brand"


class TestBrandfetchContextMock:
    @pytest.mark.asyncio
    async def test_get_context_json(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetContextJsonConfig(domain="nike.com"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"identity": {"tagline": "Just Do It"}})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_context_json"
        assert result["data"]["identity"]["tagline"] == "Just Do It"

    @pytest.mark.asyncio
    async def test_get_context_markdown(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetContextMarkdownConfig(domain="nike.com"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, json_data=None, text="# Nike\nJust Do It")
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_context_markdown"
        assert "# Nike" in result["data"]["markdown"]


class TestBrandfetchSearchMock:
    @pytest.mark.asyncio
    async def test_search_brands(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchSearchConfig(name="Nike"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, [{"name": "Nike", "domain": "nike.com"}])
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_brands"
        assert result["data"][0]["domain"] == "nike.com"

    @pytest.mark.asyncio
    async def test_search_requires_client_id(self, credentials_no_client_id):
        config = BrandfetchNodeConfig(
            config=BrandfetchSearchConfig(name="Nike"),
            credentials=credentials_no_client_id,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "client id" in str(result["error"]).lower()


class TestBrandfetchTransactionMock:
    @pytest.mark.asyncio
    async def test_identify_transaction(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchTransactionConfig(
                transaction_label="SQ *COFFEE SHOP", country_code="US"
            ),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(200, {"name": "Coffee Shop", "domain": "coffeeshop.com"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "identify_transaction"
        assert result["data"]["name"] == "Coffee Shop"


class TestBrandfetchLogoMock:
    @pytest.mark.asyncio
    async def test_logo_by_domain(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchLogoByDomainConfig(domain="nike.com", logo_type="icon"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logo_by_domain"
        url = result["data"]["logo_url"]
        assert "cdn.brandfetch.io/nike.com/icon" in url
        assert "c=pub_client_123" in url

    @pytest.mark.asyncio
    async def test_logo_by_ticker(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchLogoByTickerConfig(ticker="NKE", logo_type="logo"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logo_by_ticker"
        assert "cdn.brandfetch.io/ticker/NKE/logo" in result["data"]["logo_url"]

    @pytest.mark.asyncio
    async def test_logo_by_crypto(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchLogoByCryptoConfig(symbol="BTC", logo_type="symbol"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logo_by_crypto"
        assert "cdn.brandfetch.io/crypto/BTC/symbol" in result["data"]["logo_url"]

    @pytest.mark.asyncio
    async def test_logo_by_isin(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchLogoByIsinConfig(isin="US6541061031", logo_type="logo"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logo_by_isin"
        assert "cdn.brandfetch.io/isin/US6541061031/logo" in result["data"]["logo_url"]

    @pytest.mark.asyncio
    async def test_logo_themed(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchThemedLogoConfig(
                domain="nike.com",
                logo_type="logo",
                theme="dark",
                width="200",
                height="100",
                image_format="png",
                fallback="lettermark",
            ),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "logo_themed"
        url = result["data"]["logo_url"]
        # CDN uses path segments for all transform params, not query params.
        # Expected: /nike.com/w/200/h/100/theme/dark/fallback/lettermark/logo.png?c=...
        assert "cdn.brandfetch.io/nike.com" in url
        assert "/w/200" in url
        assert "/h/100" in url
        assert "/theme/dark" in url
        assert "/fallback/lettermark" in url
        assert "/logo.png" in url
        assert "c=pub_client_123" in url
        # transform params must NOT appear as query params
        assert "theme=" not in url
        assert "format=" not in url
        assert "fallback=" not in url

    @pytest.mark.asyncio
    async def test_logo_requires_client_id(self, credentials_no_client_id):
        config = BrandfetchNodeConfig(
            config=BrandfetchLogoByDomainConfig(domain="nike.com", logo_type="logo"),
            credentials=credentials_no_client_id,
        )
        node = create_brandfetch_node(config)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "client id" in str(result["error"]).lower()


class TestBrandfetchTriggerMock:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = BrandfetchNodeConfig(
            config=BrandfetchReceiveWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_brandfetch_node(config)
        payload = {"type": "brand.updated", "urn": "urn:brand:nike", "data": {"object": {}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["data"]["type"] == "brand.updated"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"


class TestBrandfetchTriggerEventFilter:
    """Event-type selection on the webhook trigger.

    Brandfetch posts every event to a single endpoint, so the trigger filters
    inbound deliveries by their ``type`` against the user-selected ``event_type``
    both in ``resolve_trigger_payload`` (the dispatch decision) and in the
    trigger ``execute`` path (the emitted output).
    """

    def test_event_type_enum_exposes_all_brandfetch_events(self):
        """The schema enum exposes the actual Brandfetch webhook event types."""
        schema = BrandfetchReceiveWebhookConfig.model_json_schema()
        enum = schema["properties"]["event_type"]["enum"]
        assert enum == BRANDFETCH_WEBHOOK_EVENTS
        for event in (
            "brand.updated",
            "brand.company.updated",
            "brand.claimed",
            "brand.verified",
            "brand.deleted",
        ):
            assert event in enum
        # Default is "all events" so the trigger fires on every delivery unless narrowed.
        assert BrandfetchReceiveWebhookConfig().event_type == BRANDFETCH_WEBHOOK_EVENT_ALL

    def test_resolve_trigger_payload_passes_selected_event(self):
        """A selected event is dispatched: resolve returns the payload unchanged."""
        payload = {"type": "brand.updated", "urn": "urn:brand:nike"}
        config = {"operation": "receive_webhook", "event_type": "brand.updated"}
        resolved = BrandfetchNode.resolve_trigger_payload(payload, config)
        assert resolved == payload

    def test_resolve_trigger_payload_skips_non_selected_event(self):
        """A non-selected event is filtered out: resolve returns None (skip)."""
        payload = {"type": "brand.company.updated", "urn": "urn:brand:nike"}
        config = {"operation": "receive_webhook", "event_type": "brand.updated"}
        resolved = BrandfetchNode.resolve_trigger_payload(payload, config)
        assert resolved is None

    def test_resolve_trigger_payload_all_events_passes_everything(self):
        """The '*' (all events) selection lets every event through."""
        config = {"operation": "receive_webhook", "event_type": BRANDFETCH_WEBHOOK_EVENT_ALL}
        for event in ("brand.updated", "brand.deleted", "brand.verified"):
            payload = {"type": event}
            assert BrandfetchNode.resolve_trigger_payload(payload, config) == payload

    def test_resolve_trigger_payload_reads_event_from_header(self):
        """When the body lacks a ``type``, the event is read from the webhook header."""
        payload = {
            "_webhook": {"headers": {"X-Brandfetch-Event": "brand.verified"}},
        }
        selected = {"operation": "receive_webhook", "event_type": "brand.verified"}
        assert BrandfetchNode.resolve_trigger_payload(payload, selected) == payload
        rejected = {"operation": "receive_webhook", "event_type": "brand.updated"}
        assert BrandfetchNode.resolve_trigger_payload(payload, rejected) is None

    @pytest.mark.asyncio
    async def test_execute_passes_selected_event(self):
        """The trigger execute path emits the event payload for a selected event."""
        config = BrandfetchNodeConfig(
            config=BrandfetchReceiveWebhookConfig(
                webhook_url="https://abc.hooks.example.test", event_type="brand.updated"
            ),
            credentials=None,
        )
        node = create_brandfetch_node(config)
        payload = {"type": "brand.updated", "urn": "urn:brand:nike", "data": {"object": {}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["event_type"] == "brand.updated"
        assert result["data"]["type"] == "brand.updated"

    @pytest.mark.asyncio
    async def test_execute_skips_non_selected_event(self):
        """The trigger execute path emits a skipped result for a non-selected event."""
        config = BrandfetchNodeConfig(
            config=BrandfetchReceiveWebhookConfig(
                webhook_url="https://abc.hooks.example.test", event_type="brand.updated"
            ),
            credentials=None,
        )
        node = create_brandfetch_node(config)
        payload = {"type": "brand.deleted", "urn": "urn:brand:nike"}
        result = await node.execute(payload)
        assert result["status"] == "skipped"
        assert result["action"] == "receive_webhook"
        assert result["data"]["event_type"] == "brand.deleted"
        # The skipped delivery must not leak brand data downstream.
        assert "urn" not in result["data"]


class TestBrandfetchWebhookSignatureMock:
    """Webhook Svix signature verification.

    Brandfetch delivers webhooks via Svix. Secret format: ``whsec_{base64}``.
    Signed string: ``{webhook-id}.{webhook-timestamp}.{raw-body}``.
    Signature header: space-separated ``v1,{base64sig}`` entries.
    Includes 5-minute replay protection.
    """

    # whsec_ prefix + base64-encoded 24-byte key
    _RAW_KEY = b"brandfetch-test-secret-key-xyz!!"  # 32 bytes
    SECRET = "whsec_" + base64.b64encode(_RAW_KEY).decode()

    def _make_sig(self, webhook_id: str, timestamp: str, body: bytes) -> str:
        to_sign = f"{webhook_id}.{timestamp}.".encode() + body
        digest = hmac.new(self._RAW_KEY, to_sign, hashlib.sha256).digest()
        return "v1," + base64.b64encode(digest).decode()

    def _now_ts(self) -> str:
        return str(int(time.time()))

    def test_valid_signature_passes(self):
        body = b'{"type":"brand.updated","urn":"urn:brandfetch:brand:123"}'
        webhook_id = "wh_01ABCDEF"
        timestamp = self._now_ts()
        sig = self._make_sig(webhook_id, timestamp, body)
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": sig,
        }
        assert BrandfetchNode.verify_webhook_signature(body, headers, {"webhook_secret": self.SECRET}) is True

    def test_tampered_body_fails(self):
        body = b'{"type":"brand.updated","urn":"urn:brandfetch:brand:123"}'
        webhook_id = "wh_01ABCDEF"
        timestamp = self._now_ts()
        sig = self._make_sig(webhook_id, timestamp, body)
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": sig,
        }
        tampered = b'{"type":"brand.deleted","urn":"urn:brandfetch:brand:123"}'
        assert BrandfetchNode.verify_webhook_signature(tampered, headers, {"webhook_secret": self.SECRET}) is False

    def test_wrong_secret_fails(self):
        body = b'{"type":"brand.updated"}'
        webhook_id = "wh_01ABCDEF"
        timestamp = self._now_ts()
        sig = self._make_sig(webhook_id, timestamp, body)
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": sig,
        }
        wrong_secret = "whsec_" + base64.b64encode(b"completely-different-key-xxxxxx!").decode()
        assert BrandfetchNode.verify_webhook_signature(body, headers, {"webhook_secret": wrong_secret}) is False

    def test_no_secret_bypasses_verification(self):
        """When no secret is configured the check passes (trial mode)."""
        body = b'{"type":"brand.updated"}'
        headers = {
            "webhook-id": "wh_01",
            "webhook-timestamp": self._now_ts(),
            "webhook-signature": "v1,badsig",
        }
        assert BrandfetchNode.verify_webhook_signature(body, headers, {}) is True
        assert BrandfetchNode.verify_webhook_signature(body, headers, None) is True

    def test_missing_required_headers_fails(self):
        """Missing webhook-id or webhook-timestamp rejects the delivery."""
        body = b'{"type":"brand.updated"}'
        config = {"webhook_secret": self.SECRET}
        assert BrandfetchNode.verify_webhook_signature(
            body,
            {"webhook-timestamp": self._now_ts(), "webhook-signature": "v1,x"},
            config,
        ) is False
        assert BrandfetchNode.verify_webhook_signature(
            body,
            {"webhook-id": "wh_01", "webhook-timestamp": self._now_ts()},
            config,
        ) is False

    def test_expired_timestamp_fails(self):
        """Deliveries older than 5 minutes are rejected (replay protection)."""
        body = b'{"type":"brand.updated"}'
        webhook_id = "wh_01ABCDEF"
        old_ts = str(int(time.time()) - 400)  # 6+ minutes ago
        sig = self._make_sig(webhook_id, old_ts, body)
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": old_ts,
            "webhook-signature": sig,
        }
        assert BrandfetchNode.verify_webhook_signature(body, headers, {"webhook_secret": self.SECRET}) is False


class TestBrandfetchErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByDomainConfig(domain="missing.invalid"),
            credentials=credentials,
        )
        node = create_brandfetch_node(config)
        mock_client = create_mock_client(404, {"message": "Brand not found"})
        with patch("nodes.brandfetch_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = BrandfetchNodeConfig(
            config=BrandfetchGetBrandByDomainConfig(domain="nike.com"), credentials=None
        )
        node = create_brandfetch_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

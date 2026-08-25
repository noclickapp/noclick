"""
Mock tests for the Mailgun REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Messages: send message, send MIME, get stored message
- Analytics: list events, query logs, get metrics
- Domains: list, create, get, verify, delete
- Mailing Lists: list, create, list members, add member, bulk add, delete member
- Templates: list, create, get, create version
- Routes: list, create, delete
- Webhooks: list
- Suppressions: list bounces, add unsubscribe
- Validation: validate address
- Trigger: on_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: domain dropdown
"""

import hashlib
import hmac
import json

import pytest
from unittest.mock import Mock, patch

from nodes.mailgun_node import (
    MailgunNode,
    MailgunNodeConfig,
    MailgunApiKeyCredential,
    MailgunSendMessageConfig,
    MailgunSendMimeConfig,
    MailgunGetStoredMessageConfig,
    MailgunListEventsConfig,
    MailgunQueryLogsConfig,
    MailgunGetMetricsConfig,
    MailgunListDomainsConfig,
    MailgunCreateDomainConfig,
    MailgunGetDomainConfig,
    MailgunVerifyDomainConfig,
    MailgunDeleteDomainConfig,
    MailgunListMailingListsConfig,
    MailgunCreateMailingListConfig,
    MailgunListMembersConfig,
    MailgunAddMemberConfig,
    MailgunBulkAddMembersConfig,
    MailgunDeleteMemberConfig,
    MailgunListTemplatesConfig,
    MailgunCreateTemplateConfig,
    MailgunGetTemplateConfig,
    MailgunCreateTemplateVersionConfig,
    MailgunListRoutesConfig,
    MailgunCreateRouteConfig,
    MailgunDeleteRouteConfig,
    MailgunListWebhooksConfig,
    MailgunListBouncesConfig,
    MailgunAddUnsubscribesConfig,
    MailgunValidateAddressConfig,
    MailgunOnDeliveredConfig,
    MailgunOnInboundEmailConfig,
)


@pytest.fixture
def api_key_credentials():
    return MailgunApiKeyCredential(
        api_key="key-test-12345", region="us", webhook_signing_key="whsk-test"
    )


def create_mailgun_node(config):
    return MailgunNode(
        node_id="test-mailgun-node",
        node_type="automation-mailgun",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
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


async def _run(node, status_code, json_data):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.mailgun_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Messages
# ============================================================================


class TestMailgunMessagesMock:
    @pytest.mark.asyncio
    async def test_send_message(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunSendMessageConfig(
                domain="mg.example.com",
                from_address="Excited User <mailgun@mg.example.com>",
                to="alice@example.com, bob@example.com",
                subject="Hello",
                text="Testing",
                variables='{"name": "Ada"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"id": "<msg@mg.example.com>", "message": "Queued"})
        assert result["status"] == "success"
        assert result["action"] == "send_message"
        assert result["data"]["id"].startswith("<msg")

    @pytest.mark.asyncio
    async def test_send_mime(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunSendMimeConfig(
                domain="mg.example.com", to="alice@example.com", message="From: a\n\nbody"
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"id": "<mime@mg>", "message": "Queued"})
        assert result["status"] == "success"
        assert result["action"] == "send_mime"

    @pytest.mark.asyncio
    async def test_get_stored_message(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunGetStoredMessageConfig(domain="mg.example.com", storage_key="abc123"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"subject": "Re: hi", "from": "x@y.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_stored_message"
        assert result["data"]["subject"] == "Re: hi"


# ============================================================================
# Analytics
# ============================================================================


class TestMailgunAnalyticsMock:
    @pytest.mark.asyncio
    async def test_list_events(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListEventsConfig(domain="mg.example.com", event="delivered", limit="50"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"event": "delivered"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_events"
        assert result["data"]["items"][0]["event"] == "delivered"

    @pytest.mark.asyncio
    async def test_query_logs(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunQueryLogsConfig(
                start="Mon, 01 Jun 2026 00:00:00 GMT",
                end="Mon, 08 Jun 2026 00:00:00 GMT",
                filter_json='{"AND": []}',
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": []})
        assert result["status"] == "success"
        assert result["action"] == "query_logs"

    @pytest.mark.asyncio
    async def test_get_metrics(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunGetMetricsConfig(
                start="Mon, 01 Jun 2026 00:00:00 GMT",
                end="Mon, 08 Jun 2026 00:00:00 GMT",
                metrics_json='["delivered_count"]',
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"delivered_count": 42}]})
        assert result["status"] == "success"
        assert result["action"] == "get_metrics"


# ============================================================================
# Domains
# ============================================================================


class TestMailgunDomainsMock:
    @pytest.mark.asyncio
    async def test_list_domains(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListDomainsConfig(limit="50"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"name": "mg.example.com"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_domains"

    @pytest.mark.asyncio
    async def test_create_domain(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunCreateDomainConfig(name="mg.new.com"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"domain": {"name": "mg.new.com", "state": "unverified"}})
        assert result["status"] == "success"
        assert result["action"] == "create_domain"

    @pytest.mark.asyncio
    async def test_get_domain(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunGetDomainConfig(name="mg.example.com"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"domain": {"name": "mg.example.com", "state": "active"}})
        assert result["status"] == "success"
        assert result["action"] == "get_domain"

    @pytest.mark.asyncio
    async def test_verify_domain(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunVerifyDomainConfig(name="mg.example.com"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"domain": {"state": "active"}})
        assert result["status"] == "success"
        assert result["action"] == "verify_domain"

    @pytest.mark.asyncio
    async def test_delete_domain(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunDeleteDomainConfig(name="mg.old.com"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"message": "Domain has been deleted"})
        assert result["status"] == "success"
        assert result["action"] == "delete_domain"


# ============================================================================
# Mailing Lists
# ============================================================================


class TestMailgunMailingListsMock:
    @pytest.mark.asyncio
    async def test_list_mailing_lists(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListMailingListsConfig(limit="50"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"address": "team@example.com"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_mailing_lists"

    @pytest.mark.asyncio
    async def test_create_mailing_list(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunCreateMailingListConfig(address="team@example.com", name="Team"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"list": {"address": "team@example.com"}})
        assert result["status"] == "success"
        assert result["action"] == "create_mailing_list"

    @pytest.mark.asyncio
    async def test_list_members(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListMembersConfig(list_address="team@example.com", limit="50"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"address": "a@example.com"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_members"

    @pytest.mark.asyncio
    async def test_add_member(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunAddMemberConfig(
                list_address="team@example.com",
                address="new@example.com",
                name="New",
                vars_json='{"plan": "pro"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"member": {"address": "new@example.com"}})
        assert result["status"] == "success"
        assert result["action"] == "add_member"

    @pytest.mark.asyncio
    async def test_bulk_add_members(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunBulkAddMembersConfig(
                list_address="team@example.com",
                members_json='[{"address": "a@x.com"}, {"address": "b@x.com"}]',
                upsert="yes",
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"message": "Mailing list has been updated"})
        assert result["status"] == "success"
        assert result["action"] == "bulk_add_members"

    @pytest.mark.asyncio
    async def test_delete_member(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunDeleteMemberConfig(
                list_address="team@example.com", member_address="a@example.com"
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"message": "Mailing list member has been deleted"})
        assert result["status"] == "success"
        assert result["action"] == "delete_member"


# ============================================================================
# Templates
# ============================================================================


class TestMailgunTemplatesMock:
    @pytest.mark.asyncio
    async def test_list_templates(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListTemplatesConfig(domain="mg.example.com", limit="50"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"name": "welcome"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_templates"

    @pytest.mark.asyncio
    async def test_create_template(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunCreateTemplateConfig(
                domain="mg.example.com", name="welcome", template="<h1>Hi {{name}}</h1>"
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"template": {"name": "welcome"}})
        assert result["status"] == "success"
        assert result["action"] == "create_template"

    @pytest.mark.asyncio
    async def test_get_template(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunGetTemplateConfig(domain="mg.example.com", template_name="welcome"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"template": {"name": "welcome", "version": {"tag": "v1"}}})
        assert result["status"] == "success"
        assert result["action"] == "get_template"

    @pytest.mark.asyncio
    async def test_create_template_version(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunCreateTemplateVersionConfig(
                domain="mg.example.com", template_name="welcome", tag="v2", template="<h1>v2</h1>"
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"template": {"version": {"tag": "v2"}}})
        assert result["status"] == "success"
        assert result["action"] == "create_template_version"


# ============================================================================
# Routes
# ============================================================================


class TestMailgunRoutesMock:
    @pytest.mark.asyncio
    async def test_list_routes(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListRoutesConfig(limit="50"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"id": "r1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_routes"

    @pytest.mark.asyncio
    async def test_create_route(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunCreateRouteConfig(
                expression='match_recipient(".*@example.com")',
                action='forward("https://example.com/hook"), stop()',
                priority="1",
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"route": {"id": "r2"}})
        assert result["status"] == "success"
        assert result["action"] == "create_route"

    @pytest.mark.asyncio
    async def test_delete_route(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunDeleteRouteConfig(route_id="r1"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"message": "Route has been deleted"})
        assert result["status"] == "success"
        assert result["action"] == "delete_route"


# ============================================================================
# Webhooks + Suppressions + Validation
# ============================================================================


class TestMailgunMiscMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListWebhooksConfig(domain="mg.example.com"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"webhooks": {"delivered": {"urls": ["https://x"]}}})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_list_bounces(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunListBouncesConfig(domain="mg.example.com", limit="50"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"items": [{"address": "bad@x.com"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_bounces"

    @pytest.mark.asyncio
    async def test_add_unsubscribe(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunAddUnsubscribesConfig(
                domain="mg.example.com", address="user@x.com", tag="*"
            ),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"message": "Address has been added to the unsubscribes table"})
        assert result["status"] == "success"
        assert result["action"] == "add_unsubscribe"

    @pytest.mark.asyncio
    async def test_validate_address(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunValidateAddressConfig(address="user@example.com"),
            credentials=api_key_credentials,
        )
        node = create_mailgun_node(config)
        result = await _run(node, 200, {"address": "user@example.com", "result": "deliverable"})
        assert result["status"] == "success"
        assert result["action"] == "validate_address"
        assert result["data"]["result"] == "deliverable"


# ============================================================================
# Trigger
# ============================================================================


class TestMailgunTriggerMock:
    @pytest.mark.asyncio
    async def test_event_trigger_passthrough(self):
        """A granular event trigger passes the inbound payload through as output."""
        config = MailgunNodeConfig(
            config=MailgunOnDeliveredConfig(domain="mg.example.com", webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_mailgun_node(config)
        payload = {"event-data": {"event": "delivered", "message": {"headers": {}}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_delivered"
        assert result["data"]["event-data"]["event"] == "delivered"

    @pytest.mark.asyncio
    async def test_register_event_webhook(self):
        captured = {}

        async def fake_request(api_key, region, method, endpoint, **kwargs):
            captured.update(method=method, endpoint=endpoint, data=kwargs.get("data"))
            return {"status": "success", "data": {"webhook": {"urls": ["https://x"]}}}

        with patch("nodes.mailgun_node._mailgun_request", side_effect=fake_request):
            extra = await MailgunNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "k", "region": "us", "webhook_signing_key": "whsk"},
                config={"domain": "mg.example.com", "operation": "on_hard_bounce"},
                node_id="node-1",
            )
        assert captured["endpoint"] == "/v3/domains/mg.example.com/webhooks"
        assert captured["data"] == {"id": "permanent_fail", "url": "https://abc.hooks.example.test"}
        assert extra["external_webhook_id"] == "permanent_fail"
        assert extra["signing_secret"] == "whsk"

    @pytest.mark.asyncio
    async def test_register_inbound_route(self):
        captured = {}

        async def fake_request(api_key, region, method, endpoint, **kwargs):
            captured.update(method=method, endpoint=endpoint, data=kwargs.get("data"))
            return {"status": "success", "data": {"route": {"id": "route_123"}}}

        with patch("nodes.mailgun_node._mailgun_request", side_effect=fake_request):
            extra = await MailgunNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test/in",
                credential={"api_key": "k", "region": "us", "webhook_signing_key": "whsk"},
                config={"domain": "mg.example.com", "operation": "on_inbound_email"},
                node_id="node-1",
            )
        assert captured["endpoint"] == "/v3/routes"
        assert 'match_recipient(".*@mg.example.com")' == captured["data"]["expression"]
        assert captured["data"]["action"] == 'forward("https://abc.hooks.example.test/in")'
        assert extra["external_webhook_id"] == "route_123"

    @pytest.mark.asyncio
    async def test_unregister_event_vs_route(self):
        calls = []

        async def fake_request(api_key, region, method, endpoint, **kwargs):
            calls.append((method, endpoint))
            return {"status": "success", "data": {}}

        with patch("nodes.mailgun_node._mailgun_request", side_effect=fake_request):
            await MailgunNode._unregister_external_webhook(
                credential={"api_key": "k", "region": "us"},
                config={"domain": "mg.example.com", "operation": "on_delivered", "external_webhook_id": "delivered"},
                node_id="n",
            )
            await MailgunNode._unregister_external_webhook(
                credential={"api_key": "k", "region": "us"},
                config={"operation": "on_inbound_email", "external_webhook_id": "route_123"},
                node_id="n",
            )
        assert ("DELETE", "/v3/domains/mg.example.com/webhooks/delivered") in calls
        assert ("DELETE", "/v3/routes/route_123") in calls

    def test_verify_event_webhook_signature(self):
        secret, ts, token = "topsecret", "1700000000", "abctoken"
        good = hmac.new(secret.encode(), f"{ts}{token}".encode(), hashlib.sha256).hexdigest()
        body = json.dumps({"signature": {"timestamp": ts, "token": token, "signature": good}}).encode()
        assert MailgunNode.verify_webhook_signature(body, {}, {"signing_secret": secret, "operation": "on_delivered"})
        bad = json.dumps({"signature": {"timestamp": ts, "token": token, "signature": "deadbeef"}}).encode()
        assert not MailgunNode.verify_webhook_signature(bad, {}, {"signing_secret": secret, "operation": "on_delivered"})
        assert MailgunNode.verify_webhook_signature(body, {}, {})  # no secret -> accept (not armed)

    def test_verify_inbound_signature_urlencoded(self):
        from urllib.parse import urlencode
        secret, ts, token = "whsk", "1700000000", "abctoken"
        good = hmac.new(secret.encode(), f"{ts}{token}".encode(), hashlib.sha256).hexdigest()
        body = urlencode({"timestamp": ts, "token": token, "signature": good, "recipient": "a@b.com", "body-plain": "hi"}).encode()
        cfg = {"signing_secret": secret, "operation": "on_inbound_email"}
        hdr = {"Content-Type": "application/x-www-form-urlencoded"}
        assert MailgunNode.verify_webhook_signature(body, hdr, cfg)
        # tamper
        bad = urlencode({"timestamp": ts, "token": token, "signature": "deadbeef", "recipient": "a@b.com"}).encode()
        assert not MailgunNode.verify_webhook_signature(bad, hdr, cfg)

    def test_verify_inbound_signature_multipart(self):
        secret, ts, token = "whsk", "1700000000", "abctoken"
        good = hmac.new(secret.encode(), f"{ts}{token}".encode(), hashlib.sha256).hexdigest()
        b = "BOUND"
        parts = []
        for name, val in [("timestamp", ts), ("token", token), ("signature", good), ("subject", "Hello")]:
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n')
        body = ("".join(parts) + f"--{b}--\r\n").encode()
        cfg = {"signing_secret": secret, "operation": "on_inbound_email"}
        hdr = {"Content-Type": f"multipart/form-data; boundary={b}"}
        assert MailgunNode.verify_webhook_signature(body, hdr, cfg)


# ============================================================================
# Error handling
# ============================================================================


class TestMailgunErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = MailgunNodeConfig(
            config=MailgunGetDomainConfig(name="missing.com"), credentials=api_key_credentials
        )
        node = create_mailgun_node(config)
        result = await _run(node, 404, {"message": "Domain not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = MailgunNodeConfig(config=MailgunListDomainsConfig(), credentials=None)
        node = create_mailgun_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestMailgunDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_domain_options(self):
        async def fake_request(*args, **kwargs):
            return {"status": "success", "data": {"items": [{"name": "mg.example.com", "state": "active"}]}}

        with patch("nodes.mailgun_node._mailgun_request", side_effect=fake_request):
            result = await MailgunNode.load_field_options(
                "domain", {"api_key": "key-test", "region": "us"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "mg.example.com"
        assert "active" in result["options"][0]["label"]

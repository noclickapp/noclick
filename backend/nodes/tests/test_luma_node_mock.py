"""
Mock tests for the Luma (lu.ma) REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Account: get self
- Events: list, get, create, update, cancel, lookup
- Guests: list, get, add, update status, send invites
- Hosts: add, update, remove
- Ticket Types: list, create, update
- Coupons: create/list event coupons, create/list calendar coupons
- Calendar: get, update, list admins, list contacts, import contacts, create event tag
- Webhooks: list, create
- Trigger: on_luma_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: event dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.luma_node import (
    LumaNode,
    LumaNodeConfig,
    LumaApiKeyCredential,
    LumaGetSelfConfig,
    LumaListEventsConfig,
    LumaGetEventConfig,
    LumaCreateEventConfig,
    LumaUpdateEventConfig,
    LumaCancelEventConfig,
    LumaLookupEventConfig,
    LumaListGuestsConfig,
    LumaGetGuestConfig,
    LumaAddGuestsConfig,
    LumaUpdateGuestStatusConfig,
    LumaSendInvitesConfig,
    LumaAddHostConfig,
    LumaUpdateHostConfig,
    LumaRemoveHostConfig,
    LumaListTicketTypesConfig,
    LumaCreateTicketTypeConfig,
    LumaUpdateTicketTypeConfig,
    LumaCreateEventCouponConfig,
    LumaListEventCouponsConfig,
    LumaCreateCalendarCouponConfig,
    LumaListCalendarCouponsConfig,
    LumaGetCalendarConfig,
    LumaUpdateCalendarConfig,
    LumaListCalendarAdminsConfig,
    LumaListContactsConfig,
    LumaImportContactsConfig,
    LumaCreateEventTagConfig,
    LumaListWebhooksConfig,
    LumaCreateWebhookConfig,
    LumaWebhookTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return LumaApiKeyCredential(api_key="luma_test_key_12345")


def create_luma_node(config):
    return LumaNode(
        node_id="test-luma-node",
        node_type="automation-luma",
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


async def _run(node, status_code=200, json_data=None):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.luma_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Account
# ============================================================================


class TestLumaAccountMock:
    @pytest.mark.asyncio
    async def test_get_self(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(config=LumaGetSelfConfig(), credentials=api_key_credentials)
        )
        result = await _run(node, 200, {"id": "usr-1", "name": "Ada", "email": "ada@example.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_self"
        assert result["data"]["id"] == "usr-1"


# ============================================================================
# Events
# ============================================================================


class TestLumaEventsMock:
    @pytest.mark.asyncio
    async def test_list_events(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListEventsConfig(pagination_limit="10"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"entries": [{"event": {"api_id": "evt-1"}}]})
        assert result["status"] == "success"
        assert result["action"] == "list_events"
        assert len(result["data"]["entries"]) == 1

    @pytest.mark.asyncio
    async def test_get_event(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaGetEventConfig(event_api_id="evt-123"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"event": {"api_id": "evt-123", "name": "Launch"}})
        assert result["status"] == "success"
        assert result["action"] == "get_event"
        assert result["data"]["event"]["api_id"] == "evt-123"

    @pytest.mark.asyncio
    async def test_create_event(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateEventConfig(
                    name="Launch Party",
                    start_at="2026-07-01T18:00:00Z",
                    timezone="America/New_York",
                    require_rsvp_approval="true",
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"event": {"api_id": "evt-new"}})
        assert result["status"] == "success"
        assert result["action"] == "create_event"
        assert result["data"]["event"]["api_id"] == "evt-new"

    @pytest.mark.asyncio
    async def test_update_event(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaUpdateEventConfig(event_api_id="evt-123", name="Renamed"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"event": {"api_id": "evt-123"}})
        assert result["status"] == "success"
        assert result["action"] == "update_event"

    @pytest.mark.asyncio
    async def test_cancel_event(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCancelEventConfig(
                    event_api_id="evt-123", cancellation_token="tok-1"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "cancel_event"

    @pytest.mark.asyncio
    async def test_lookup_event(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaLookupEventConfig(url="https://lu.ma/launch"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"exists": True})
        assert result["status"] == "success"
        assert result["action"] == "lookup_event"


# ============================================================================
# Guests
# ============================================================================


class TestLumaGuestsMock:
    @pytest.mark.asyncio
    async def test_list_guests(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListGuestsConfig(
                    event_api_id="evt-1", approval_status="approved"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "gst-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_guests"

    @pytest.mark.asyncio
    async def test_get_guest(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaGetGuestConfig(event_api_id="evt-1", email="ada@example.com"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"guest": {"api_id": "gst-1"}})
        assert result["status"] == "success"
        assert result["action"] == "get_guest"

    @pytest.mark.asyncio
    async def test_add_guests(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaAddGuestsConfig(
                    event_api_id="evt-1", emails="a@example.com, b@example.com"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "add_guests"

    @pytest.mark.asyncio
    async def test_update_guest_status(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaUpdateGuestStatusConfig(
                    event_api_id="evt-1", guest_api_id="gst-1", status="approved"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "update_guest_status"

    @pytest.mark.asyncio
    async def test_send_invites(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaSendInvitesConfig(
                    event_api_id="evt-1", emails="a@example.com"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "send_invites"


# ============================================================================
# Hosts
# ============================================================================


class TestLumaHostsMock:
    @pytest.mark.asyncio
    async def test_add_host(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaAddHostConfig(
                    event_api_id="evt-1", email="host@example.com", access_level="manager"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "add_host"

    @pytest.mark.asyncio
    async def test_update_host(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaUpdateHostConfig(
                    event_api_id="evt-1", email="host@example.com", access_level="none"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "update_host"

    @pytest.mark.asyncio
    async def test_remove_host(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaRemoveHostConfig(event_api_id="evt-1", email="host@example.com"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "remove_host"


# ============================================================================
# Ticket Types
# ============================================================================


class TestLumaTicketTypesMock:
    @pytest.mark.asyncio
    async def test_list_ticket_types(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListTicketTypesConfig(event_api_id="evt-1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "tt-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_ticket_types"

    @pytest.mark.asyncio
    async def test_create_ticket_type(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateTicketTypeConfig(
                    event_api_id="evt-1", name="VIP", cents="5000", currency="USD"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"ticket_type": {"api_id": "tt-new"}})
        assert result["status"] == "success"
        assert result["action"] == "create_ticket_type"

    @pytest.mark.asyncio
    async def test_update_ticket_type(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaUpdateTicketTypeConfig(
                    event_api_id="evt-1", ticket_type_api_id="tt-1", name="VIP+"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "update_ticket_type"


# ============================================================================
# Coupons
# ============================================================================


class TestLumaCouponsMock:
    @pytest.mark.asyncio
    async def test_create_event_coupon(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateEventCouponConfig(
                    event_api_id="evt-1",
                    name="Early Bird",
                    code="EARLY",
                    discount_type="percent",
                    discount_value="20",
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"coupon": {"api_id": "cpn-1"}})
        assert result["status"] == "success"
        assert result["action"] == "create_event_coupon"

    @pytest.mark.asyncio
    async def test_list_event_coupons(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListEventCouponsConfig(event_api_id="evt-1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "cpn-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_event_coupons"

    @pytest.mark.asyncio
    async def test_create_calendar_coupon(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateCalendarCouponConfig(
                    name="Member", code="MEMBER", discount_type="amount", discount_value="500"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"coupon": {"api_id": "cpn-2"}})
        assert result["status"] == "success"
        assert result["action"] == "create_calendar_coupon"

    @pytest.mark.asyncio
    async def test_list_calendar_coupons(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListCalendarCouponsConfig(), credentials=api_key_credentials
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "cpn-2"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_calendar_coupons"


# ============================================================================
# Calendar
# ============================================================================


class TestLumaCalendarMock:
    @pytest.mark.asyncio
    async def test_get_calendar(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(config=LumaGetCalendarConfig(), credentials=api_key_credentials)
        )
        result = await _run(node, 200, {"calendar": {"api_id": "cal-1"}})
        assert result["status"] == "success"
        assert result["action"] == "get_calendar"

    @pytest.mark.asyncio
    async def test_update_calendar(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaUpdateCalendarConfig(calendar_id="cal-1", name="New Name"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "update_calendar"

    @pytest.mark.asyncio
    async def test_list_calendar_admins(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListCalendarAdminsConfig(), credentials=api_key_credentials
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "adm-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_calendar_admins"

    @pytest.mark.asyncio
    async def test_list_contacts(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaListContactsConfig(pagination_limit="20"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"entries": [{"api_id": "ctc-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_contacts"

    @pytest.mark.asyncio
    async def test_import_contacts(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaImportContactsConfig(emails="a@example.com, b@example.com"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "import_contacts"

    @pytest.mark.asyncio
    async def test_create_event_tag(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateEventTagConfig(name="Workshop"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"event_tag": {"api_id": "tag-1"}})
        assert result["status"] == "success"
        assert result["action"] == "create_event_tag"


# ============================================================================
# Webhooks
# ============================================================================


class TestLumaWebhooksMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(config=LumaListWebhooksConfig(), credentials=api_key_credentials)
        )
        result = await _run(node, 200, {"entries": [{"api_id": "whk-1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaCreateWebhookConfig(
                    url="https://abc.hooks.example.test", event_types="event.created, guest.registered"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"webhook": {"api_id": "whk-new"}})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"


# ============================================================================
# Trigger
# ============================================================================


class TestLumaTriggerMock:
    @pytest.mark.asyncio
    async def test_on_luma_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = LumaNodeConfig(
            config=LumaWebhookTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_luma_node(config)
        payload = {"event_type": "guest.registered", "data": {"api_id": "gst-x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_luma_event"
        assert result["data"]["event_type"] == "guest.registered"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.luma_node._luma_request",
            return_value={"status": "success", "data": {"api_id": "whk-99"}},
        ) as mock_req:
            extra = await LumaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "luma_test"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "whk-99"
        assert extra["signing_secret"]

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.luma_node._luma_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await LumaNode._unregister_external_webhook(
                credential={"api_key": "luma_test"},
                config={"external_webhook_id": "whk-99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event_type":"guest.registered"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert LumaNode.verify_webhook_signature(
            body, {"luma-signature": good_sig}, {"signing_secret": secret}
        )
        assert not LumaNode.verify_webhook_signature(
            body, {"luma-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert LumaNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestLumaErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        node = create_luma_node(
            LumaNodeConfig(
                config=LumaGetEventConfig(event_api_id="evt-missing"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 404, {"message": "Event not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = LumaNodeConfig(config=LumaGetSelfConfig(), credentials=None)
        node = create_luma_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestLumaDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_event_options(self):
        with patch(
            "utils.credential_loader.load_credential", return_value={"api_key": "luma_test"}
        ), patch(
            "nodes.luma_node._luma_request",
            return_value={
                "status": "success",
                "data": {
                    "entries": [
                        {"event": {"api_id": "evt-1", "name": "Launch Party"}},
                        {"event": {"api_id": "evt-2", "name": "Workshop"}},
                    ]
                },
            },
        ):
            result = await LumaNode.load_field_options(
                "event_api_id", "user-1", {}, credential_ids={"luma": "cred-1"}, pool=Mock()
            )
        assert "options" in result
        assert result["options"][0]["value"] == "evt-1"
        assert result["options"][0]["label"] == "Launch Party"
        assert len(result["options"]) == 2


# Regression coverage for request fields rejected by the pinned Luma OpenAPI spec.
# The request helper is mocked: these cases make no claims about provider responses.
@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,location,expected", [
    (LumaGetEventConfig(event_api_id="evt-123"), "GET", "/v1/events/get", "params", {"event_id": "evt-123"}),
    (LumaListGuestsConfig(event_api_id="evt-123"), "GET", "/v1/events/guests/list", "params", {"event_id": "evt-123"}),
    (LumaGetGuestConfig(event_api_id="evt-123", email="ada@example.com"), "GET", "/v1/events/guests/get", "params", {"event_id": "evt-123", "id": "ada@example.com"}),
    (LumaGetGuestConfig(event_api_id="evt-123", api_id="gst-1"), "GET", "/v1/events/guests/get", "params", {"event_id": "evt-123", "id": "gst-1"}),
    (LumaUpdateEventConfig(event_api_id="evt-123", name="Standard"), "POST", "/v1/events/update", "json_body", {"event_id": "evt-123", "name": "Standard"}),
    (LumaCancelEventConfig(event_api_id="evt-123", cancellation_token="tok-1"), "POST", "/v1/events/cancel", "json_body", {"event_id": "evt-123", "cancellation_token": "tok-1"}),
    (LumaAddGuestsConfig(event_api_id="evt-123", emails="ada@example.com"), "POST", "/v1/events/guests/add", "json_body", {"event_id": "evt-123", "guests": [{"email": "ada@example.com"}]}),
    (LumaSendInvitesConfig(event_api_id="evt-123", emails="ada@example.com"), "POST", "/v1/events/guests/send-invites", "json_body", {"event_id": "evt-123", "guests": [{"email": "ada@example.com"}]}),
    (LumaUpdateGuestStatusConfig(event_api_id="evt-123", guest_api_id="gst-1", status="waitlist"), "POST", "/v1/events/guests/update-status", "json_body", {"event_id": "evt-123", "guest_id": "gst-1", "status": "waitlist"}),
    (LumaAddHostConfig(event_api_id="evt-123", email="host@example.com", access_level="check-in"), "POST", "/v1/events/hosts/add", "json_body", {"event_id": "evt-123", "access_level": "check-in"}),
    (LumaUpdateHostConfig(event_api_id="evt-123", email="host@example.com", access_level="none"), "POST", "/v1/events/hosts/update", "json_body", {"event_id": "evt-123", "access_level": "none"}),
    (LumaRemoveHostConfig(event_api_id="evt-123", email="host@example.com"), "POST", "/v1/events/hosts/remove", "json_body", {"event_id": "evt-123"}),
    (LumaListTicketTypesConfig(event_api_id="evt-123"), "GET", "/v1/events/ticket-types/list", "params", {"event_id": "evt-123"}),
    (LumaCreateTicketTypeConfig(event_api_id="evt-123", name="Standard"), "POST", "/v1/events/ticket-types/create", "json_body", {"event_id": "evt-123", "type": "free"}),
    (LumaCreateTicketTypeConfig(event_api_id="evt-123", name="Standard", cents="2500", currency="USD"), "POST", "/v1/events/ticket-types/create", "json_body", {"event_id": "evt-123", "type": "paid", "cents": 2500, "currency": "usd"}),
    (LumaUpdateTicketTypeConfig(event_api_id="evt-123", ticket_type_api_id="tt-1", name="Standard"), "POST", "/v1/events/ticket-types/update", "json_body", {"event_ticket_type_id": "tt-1"}),
    (LumaListEventCouponsConfig(event_api_id="evt-123"), "GET", "/v1/events/coupons/list", "params", {"event_id": "evt-123"}),
    (LumaCreateEventCouponConfig(event_api_id="evt-123", code="EARLY", discount_type="percent", discount_value="20.5"), "POST", "/v1/events/coupons/create", "json_body", {"event_id": "evt-123", "discount": {"discount_type": "percent", "percent_off": 20.5}}),
    (LumaCreateCalendarCouponConfig(code="MEMBER", discount_type="amount", discount_value="500", currency="USD"), "POST", "/v1/calendars/coupons/create", "json_body", {"discount": {"discount_type": "amount", "cents_off": 500, "currency": "usd"}}),
    (LumaUpdateCalendarConfig(calendar_id="cal-1", name="Standard"), "POST", "/v1/calendars/update", "json_body", {"calendar_id": "cal-1"}),
    (LumaCreateEventConfig(name="Standard", start_at="2022-10-19T03:27:13.673Z", timezone="America/New_York", require_rsvp_approval="true"), "POST", "/v1/events/create", "json_body", {"ticket_types": [{"name": "Standard", "type": "free", "require_approval": True}]}),
])
async def test_current_api_request_fields(config, method, path, location, expected, api_key_credentials):
    node = create_luma_node(LumaNodeConfig(config=config, credentials=api_key_credentials))
    with patch("nodes.luma_node._luma_request", new_callable=AsyncMock, return_value={}) as request:
        await node.execute({})
    assert request.call_args.args == (api_key_credentials.api_key, method, path)
    payload = request.call_args.kwargs[location]
    assert expected.items() <= payload.items()
    assert not {"event_api_id", "guest_api_id", "ticket_type_api_id", "discount_value", "require_rsvp_approval"} & payload.keys()


@pytest.mark.parametrize("field", ["start_at", "end_at"])
@pytest.mark.parametrize("value", ["1", "2026-02-30T18:00:00Z", "2026-07-01T18:00:00"])
def test_event_updates_reject_invalid_datetime(field, value):
    with pytest.raises(ValueError, match="date-time with a timezone"):
        LumaUpdateEventConfig(event_api_id="evt-123", **{field: value})


def test_event_times_keep_the_supplied_timezone_and_precision():
    stamp = "2022-10-19T03:27:13.673Z"
    config = LumaCreateEventConfig(name="Standard", start_at=stamp, end_at=stamp,
                                  timezone="America/New_York")
    assert config.start_at == stamp
    assert config.end_at == stamp


@pytest.mark.parametrize("value", ["1", "/relative", "ftp://example.com/hook", "https://"])
def test_webhook_creation_requires_absolute_http_url(value):
    with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
        LumaCreateWebhookConfig(url=value)


def test_webhook_url_keeps_callback_path_and_query():
    url = "https://example.com/hooks/luma?target=events"
    assert LumaCreateWebhookConfig(url=url).url == url


class TestLumaConnectionEvidence:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("name, label", [("Ada", "Ada"), (None, "ada@example.com")])
    async def test_connect_names_authenticated_account(self, name, label):
        from nodes.core.connection_evidence import collect_evidence

        client = create_mock_client(200, {"id": "usr-1", "name": name, "email": "ada@example.com"})
        client.request = AsyncMock(wraps=client.request)
        with patch("nodes.luma_node.httpx.AsyncClient", return_value=client):
            result = await collect_evidence(
                node_type="automation-luma", user_id="test-user",
                credential_data={"credential_type": "luma_api_key", "api_key": "test-key"},
            )
        assert result.reachable is True
        assert result.account_label == label
        assert result.noun == "account"
        request = client.request.await_args.kwargs
        assert request["method"] == "GET"
        assert request["url"] == "https://public-api.luma.com/v1/users/get-self"
        assert request["headers"]["x-luma-api-key"] == "test-key"
        assert client.request.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_connect_rejected_key_is_not_working(self, status):
        from nodes.core.connection_evidence import collect_evidence

        client = create_mock_client(status, {"message": "Invalid API key"})
        with patch("nodes.luma_node.httpx.AsyncClient", return_value=client):
            result = await collect_evidence(
                node_type="automation-luma", user_id="test-user",
                credential_data={"credential_type": "luma_api_key", "api_key": "bad-key"},
            )
        assert result.reachable is False
        assert result.account_label is None
        assert "Invalid API key" in result.error

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [{}, {"message": "not a user"}, {"id": "usr-1", "email": None}])
    async def test_connect_malformed_user_is_unverified(self, data):
        from nodes.core.connection_evidence import collect_evidence

        client = create_mock_client(200, data)
        with patch("nodes.luma_node.httpx.AsyncClient", return_value=client):
            result = await collect_evidence(
                node_type="automation-luma", user_id="test-user",
                credential_data={"credential_type": "luma_api_key", "api_key": "test-key"},
            )
        assert result.reachable is None
        assert result.account_label is None

    @pytest.mark.asyncio
    async def test_connect_timeout_is_unverified(self):
        import httpx
        from nodes.core.connection_evidence import collect_evidence

        client = create_mock_client()
        client.request = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
        with patch("nodes.luma_node.httpx.AsyncClient", return_value=client):
            result = await collect_evidence(
                node_type="automation-luma", user_id="test-user",
                credential_data={"credential_type": "luma_api_key", "api_key": "test-key"},
            )
        assert result.reachable is None

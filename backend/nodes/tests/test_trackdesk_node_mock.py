"""Trackdesk wire-contract, credential boundary and failure regressions.

These tests use synthetic responses and never sign into a provider account.
The separate conformance harness validates every action against the pinned API.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import trackdesk_node as native
from nodes.core.registry import NodeFactory

ID = "11111111-1111-4111-8111-111111111111"
KEY = "synthetic-trackdesk-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {"credential_type": "trackdesk_api_key", "tenant_id": "my-program", "api_key": KEY, **changes}


def node(config):
    return NodeFactory.create_node(node_id="trackdesk-test", node_type="automation-trackdesk",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.parametrize("value", ["https://my-program.trackdesk.com/", "my-program"])
def test_trackdesk_tenant_url_normalization(value):
    assert native.TrackdeskAPIKeyCredential(**credential(tenant_id=value)).tenant_id == "my-program"


@pytest.mark.parametrize("value", ["https://trackdesk.com", "https://evil.test", "my-program.trackdesk.com.evil.test", "https://my-program.trackdesk.com@evil.test", "https://my-program.trackdesk.com:443", "https://my-program.trackdesk.com/api", "../other", "a.b", "https://my-program.trackdesk.com?key=x"])
def test_trackdesk_rejects_non_tenant_destinations(value):
    with pytest.raises(ValidationError):
        native.TrackdeskAPIKeyCredential(**credential(tenant_id=value))


@pytest.mark.parametrize("value", ["https://example.com/key", "<token>", "key\r\nX-Evil: yes"])
def test_trackdesk_rejects_placeholder_url_and_header_secrets(value):
    with pytest.raises(ValidationError):
        native.TrackdeskAPIKeyCredential(**credential(api_key=value))


@pytest.mark.asyncio
async def test_trackdesk_account_specific_evidence_uses_tag_read(monkeypatch):
    response = json.loads((Path(__file__).parent / "fixtures/trackdesk/tags.json").read_text())
    requests = transport(monkeypatch, httpx.Response(200, json=response))
    result = await node({"operation": "list_tags"}).execute({})
    assert result == {"status": "success", "data": response}
    request = requests[0]
    assert str(request.url) == "https://my-program.trackdesk.com/api/node/tags/v1"
    assert request.method == "GET" and not request.content
    assert request.headers["X-Api-Key"] == KEY
    from nodes.core.connection_evidence import _rows_from_operation
    assert _rows_from_operation(result)[0]["name"] == "VIP affiliates"
    assert native.TrackdeskNode.connection_evidence.operation == "list_tags"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "list_affiliates", "limit": 100, "offset": 200}, "POST", "/api/node/affiliates/v1", {"pagination": {"limit": 100, "offset": 200}}),
    ({"operation": "list_offers", "name": "Partner", "limit": 5}, "POST", "/api/node/offers/v1/list", {"name": "Partner", "pagination": {"limit": 5, "offset": 0}}),
    ({"operation": "list_coupons", "source_id": ID, "offer_id": ID}, "POST", "/api/node/coupons/v1/list", {"pagination": {"limit": 50, "offset": 0}, "sourceIds": [ID], "offerIds": [ID]}),
    ({"operation": "create_coupon", "source_id": ID, "offer_id": ID, "code": "VIP20"}, "POST", "/api/node/coupons/v1", {"source": {"id": ID}, "offerId": ID, "code": "VIP20", "status": "COUPON_STATUS_ACTIVE"}),
    ({"operation": "set_affiliate_status", "public_id": "my-affiliate", "status": "ACCOUNT_STATUS_ENABLED"}, "PUT", "/api/node/affiliates/v1/my-affiliate/status", {"status": "ACCOUNT_STATUS_ENABLED"}),
    ({"operation": "set_affiliate_tier", "public_id": "my-affiliate", "tier_id": ID}, "PUT", "/api/node/affiliates/v1/my-affiliate/tier", {"tierId": ID}),
    ({"operation": "set_conversion_status", "conversion_id": ID, "status": "CONVERSION_STATUS_APPROVED"}, "PUT", f"/api/node/conversions/v1/{ID}/status", {"status": "CONVERSION_STATUS_APPROVED"}),
    ({"operation": "create_account_note", "account_id": ID, "note": "Contacted"}, "POST", "/api/node/account-notes/v1", {"accountId": ID, "note": "Contacted"}),
    ({"operation": "create_tag", "name": "VIP", "hex_color_code": "#FF0000", "tag_scope": "TAG_SCOPE_AFFILIATES"}, "POST", "/api/node/tags/v1", {"name": "VIP", "hexColorCode": "#FF0000", "scopes": ["TAG_SCOPE_AFFILIATES"]}),
    ({"operation": "build_tracking_link", "source_id": ID, "offer_id": ID, "landing_page_id": ID}, "POST", "/api/node/tracking-links/v1/build", {"sourceId": ID, "offerId": ID, "target": {"direct": {"landingPageId": ID}}}),
    ({"operation": "create_conversion", "cid": ID, "conversion_type_code": "sale", "amount": "49.99", "currency": "USD", "external_id": "order-123"}, "POST", "/tracking/conversion/v1", {"cid": ID, "conversionTypeCode": "sale", "amount": {"value": "49.99"}, "currency": {"code": "USD"}, "externalId": "order-123", "status": "CONVERSION_STATUS_PENDING"}),
    ({"operation": "delete_coupon", "coupon_id": ID}, "DELETE", f"/api/node/coupons/v1/{ID}", None),
])
async def test_trackdesk_wire_mapping(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, httpx.Response(200, json={}))
    await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("welcome", [False, True])
async def test_trackdesk_affiliate_welcome_email_is_explicit(monkeypatch, welcome):
    requests = transport(monkeypatch, httpx.Response(200, json={}))
    config = {"operation": "create_affiliate", "email": "affiliate@example.com", "name": "Affiliate", "public_id": "partner-one"}
    if welcome:
        config["should_send_welcome_email"] = True
    await node(config).execute({})
    assert json.loads(requests[0].content) == {"email": "affiliate@example.com", "name": "Affiliate", "publicId": {"value": "partner-one"}, "status": "ACCOUNT_STATUS_PENDING", "shouldSendWelcomeEmail": welcome}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_trackdesk_provider_errors_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text="Provider rejected " + KEY, headers={"Location": "https://evil.test"}))
    result = await node({"operation": "list_tags"}).execute({})
    assert result == {"status": "error", "error": "Provider rejected [redacted]", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_trackdesk_keeps_provider_pagination(monkeypatch):
    response = {"affiliates": [], "pagination": {"totalCount": 123}}
    transport(monkeypatch, httpx.Response(200, json=response))
    assert (await node({"operation": "list_affiliates"}).execute({}))["data"] == response


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], "unexpected"])
async def test_trackdesk_rejects_wrong_success_shape(monkeypatch, response):
    transport(monkeypatch, httpx.Response(200, json=response))
    with pytest.raises(ValueError, match="unexpected JSON"):
        await node({"operation": "list_tags"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"tags": "wrong"}, {"tags": [{}]}])
async def test_trackdesk_invalid_evidence_response_is_not_a_connection(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="unexpected tag list"):
        await node({"operation": "list_tags"}).execute({})

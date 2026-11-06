"""Regressions for outbound requests rejected by Instantly's API v2 contract."""
import json

import httpx
import pytest

from nodes import instantly_node
from nodes.instantly_node import InstantlyAPIKeyCredential, InstantlyNode, InstantlyNodeConfig
from tests.nodes.test_instantly_node_mock import ACCOUNT_SETTINGS, CAMPAIGN_SCHEDULE


@pytest.mark.asyncio
@pytest.mark.parametrize("config, method, path, query, body", [
    ({"operation": "create_email_account", "email": "user@example.com", "first_name": "John",
      "last_name": "Doe", **ACCOUNT_SETTINGS}, "POST", "/accounts", {}, {
          "email": "user@example.com", "first_name": "John", "last_name": "Doe",
          "provider_code": 1, **ACCOUNT_SETTINGS, "imap_port": 993, "smtp_port": 587}),
    ({"operation": "create_campaign", "name": "My First Campaign",
      "campaign_schedule": json.dumps(CAMPAIGN_SCHEDULE)}, "POST", "/campaigns", {}, {
          "name": "My First Campaign", "campaign_schedule": CAMPAIGN_SCHEDULE}),
    ({"operation": "pause_campaign", "campaign_id": "campaign"},
     "POST", "/campaigns/campaign/pause", {}, None),
    ({"operation": "search_campaigns_by_contact_email", "email": "lead-email@example.com"},
     "GET", "/campaigns/search-by-contact", {"search": "lead-email@example.com"}, None),
    ({"operation": "list_leads", "campaign_id": "campaign", "email": "test@test.com"},
     "POST", "/leads/list", {}, {"campaign": "campaign", "contacts": ["test@test.com"], "limit": 10}),
    ({"operation": "list_emails", "lead_email": "jondoe@example.com"},
     "GET", "/emails", {"lead": "jondoe@example.com", "limit": "10"}, None),
    ({"operation": "count_unread_emails"}, "GET", "/emails/unread/count", {}, None),
    ({"operation": "mark_email_thread_as_read", "thread_id": "thread"},
     "POST", "/emails/threads/thread/mark-as-read", {}, None),
    ({"operation": "get_campaign_analytics", "campaign_id": "campaign", "start_date": "2024-01-01"},
     "GET", "/campaigns/analytics", {"id": "campaign", "start_date": "2024-01-01"}, None),
    ({"operation": "get_account_warmup_analytics", "email": "user@example.com"},
     "POST", "/accounts/warmup-analytics", {}, {"emails": ["user@example.com"]}),
    ({"operation": "receive_webhook_events", "event_type": "email_sent",
      "webhook_url": "https://webhook.site/unique-url"}, "POST", "/webhooks", {}, {
          "target_hook_url": "https://webhook.site/unique-url", "event_type": "email_sent"}),
])
async def test_v2_request_contract(config, method, path, query, body, monkeypatch):
    requests = []

    def capture(request):
        requests.append(request)
        # Exercise serialization without fabricating a successful provider response.
        return httpx.Response(503)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(instantly_node.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(capture), **kwargs,
    ))
    node = InstantlyNode(
        node_id="test-node", node_type="automation-instantly", node_data={},
        config=InstantlyNodeConfig(config=config, credentials=InstantlyAPIKeyCredential(api_key="test-key")),
        sio=None, sid=None, workflow_id="test-workflow",
    )
    result = await node.execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url.copy_with(query=None)) == "https://api.instantly.ai/api/v2" + path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Bearer test-key"
    if config["operation"] == "receive_webhook_events":
        assert result["data"]["registered"] is False
    else:
        assert result["status_code"] == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("schedule", ["{broken", "[]", '"schedule"'])
async def test_create_campaign_rejects_invalid_schedule_json(schedule):
    node = InstantlyNode(
        node_id="test-node", node_type="automation-instantly", node_data={},
        config=InstantlyNodeConfig(config={
            "operation": "create_campaign", "name": "My First Campaign", "campaign_schedule": schedule,
        }, credentials=InstantlyAPIKeyCredential(api_key="test-key")),
        sio=None, sid=None, workflow_id="test-workflow",
    )
    with pytest.raises(ValueError, match="[Cc]ampaign schedule"):
        await node.execute({})

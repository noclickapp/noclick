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


@pytest.mark.asyncio
@pytest.mark.parametrize("saved, missing", [
    ({"operation": "create_email_account", "email": "user@example.com",
      "first_name": "John", "last_name": "Doe"}, list(ACCOUNT_SETTINGS)),
])
async def test_saved_account_config_loads_but_requires_unavailable_mailbox_settings(saved, missing, monkeypatch):
    """Loadability only: execution migration is blocked on owner-supplied secrets."""
    credentials = InstantlyAPIKeyCredential(api_key="test-key")
    model = InstantlyNodeConfig.model_validate({"config": saved, "credentials": credentials})
    restored = InstantlyNodeConfig.model_validate(model.model_dump())
    for name, value in saved.items():
        assert getattr(restored.config, name) == value

    def no_http(**kwargs):
        pytest.fail("Do not send invented mailbox credentials or a campaign schedule")

    monkeypatch.setattr(instantly_node.httpx, "AsyncClient", no_http)
    node = InstantlyNode(
        node_id="saved", node_type="automation-instantly", node_data={}, config=restored,
        sio=None, sid=None, workflow_id="saved-workflow",
    )
    result = await node.execute({})
    assert result["status"] == "error"
    assert result["action"] == saved["operation"]
    assert result["status_code"] == 400
    assert result["config_upgrade_required"] is True
    assert result["missing_fields"] == missing
    assert all(name in result["error"] for name in missing)
    assert "total" in result["timing_ms"]


@pytest.mark.asyncio
@pytest.mark.parametrize("start, end, expected", [
    ("2023-10-02", None, ["2023-10-02"]),
    (None, "2023-10-01", ["2023-10-01"]),
    ("2023-10-01", "2023-10-01", ["2023-10-01"]),
    ("2023-10-01", "2023-10-02", ["2023-10-01", "2023-10-02"]),
    ("2023-10-03", "2023-10-04", []),
])
async def test_saved_warmup_dates_filter_daily_rows_without_changing_provider_summary(start, end, expected, monkeypatch):
    from tests.nodes.test_instantly_node_mock import provider_response

    body = provider_response("warmup_analytics")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(instantly_node.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    model = InstantlyNodeConfig.model_validate({
        "config": {"operation": "get_account_warmup_analytics", "email": "example1@example.com",
                   "start_date": start, "end_date": end},
        "credentials": {"credential_type": "instantly_api_key", "api_key": "test-key"},
    })
    assert model.model_dump()["config"]["start_date"] == start
    assert model.model_dump()["config"]["end_date"] == end
    node = InstantlyNode(
        node_id="saved", node_type="automation-instantly", node_data={}, config=model,
        sio=None, sid=None, workflow_id="saved-workflow",
    )
    result = await node.execute({})
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"emails": ["example1@example.com"]}
    assert result["status"] == "success"
    assert result["action"] == "get_account_warmup_analytics"
    assert result["status_code"] == 200
    data = result["data"]
    assert list(data["email_date_data"]["example1@example.com"]) == expected
    for email, days in data["email_date_data"].items():
        for day, metrics in days.items():
            assert day in expected
            assert metrics == body["email_date_data"][email][day]
    assert set(data["email_date_data"]) == set(body["email_date_data"])
    assert data["aggregate_data"] == body["aggregate_data"]
    assert {"api_request", "total"} <= result["timing_ms"].keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{}, {"campaign_schedule": None}, {"campaign_schedule": ""}])
async def test_saved_name_only_campaign_executes_with_documented_default(extra, monkeypatch):
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "fixtures/instantly/create_campaign.json").read_text())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=fixture["body"])

    client_type = httpx.AsyncClient
    monkeypatch.setattr(instantly_node.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    model = InstantlyNodeConfig.model_validate({
        "config": {"operation": "create_campaign", "name": "My First Campaign", **extra},
        "credentials": {"credential_type": "instantly_api_key", "api_key": "test-key"},
    })
    restored = InstantlyNodeConfig.model_validate(model.model_dump())
    node = InstantlyNode(
        node_id="saved", node_type="automation-instantly", node_data={}, config=restored,
        sio=None, sid=None, workflow_id="saved-workflow",
    )
    result = await node.execute({})
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {
        "name": "My First Campaign", "campaign_schedule": CAMPAIGN_SCHEDULE,
    }
    assert result["status"] == "success"
    assert result["action"] == "create_campaign"
    assert result["status_code"] == 200
    assert result["data"] == fixture["body"]
    assert "config_upgrade_required" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("omit_aggregate", [False, True])
async def test_warmup_dates_preserve_success_without_optional_daily_data(omit_aggregate, monkeypatch):
    from tests.nodes.test_instantly_node_mock import provider_response

    # Both properties are optional in the current official response schema.
    # Omit them from the authored example without inventing response values.
    body = provider_response("warmup_analytics")
    body.pop("email_date_data")
    if omit_aggregate:
        body.pop("aggregate_data")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(instantly_node.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    node = InstantlyNode(
        node_id="saved", node_type="automation-instantly", node_data={},
        config=InstantlyNodeConfig.model_validate({
            "config": {"operation": "get_account_warmup_analytics", "email": "example1@example.com",
                       "start_date": "2023-10-01"},
            "credentials": {"credential_type": "instantly_api_key", "api_key": "test-key"},
        }), sio=None, sid=None, workflow_id="saved-workflow",
    )
    result = await node.execute({})
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"emails": ["example1@example.com"]}
    assert result["status"] == "success"
    assert result["action"] == "get_account_warmup_analytics"
    assert result["status_code"] == 200
    assert result["data"] == body
    assert "email_date_data" not in result["data"]
    assert {"api_request", "total"} <= result["timing_ms"].keys()

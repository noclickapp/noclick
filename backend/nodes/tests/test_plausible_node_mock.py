"""Plausible operation routing, permissions, and response tests."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nodes.plausible_node import (
    PlausibleApiKeyCredential,
    PlausibleNode,
    PlausibleNodeConfig,
    _request,
)


def node(operation, fields=None, key_type="stats"):
    config = PlausibleNodeConfig(
        config={"operation": operation, **(fields or {})},
        credentials=PlausibleApiKeyCredential(api_key="test-key", key_type=key_type),
    )
    return PlausibleNode(
        node_id="plausible-test", node_type="automation-plausible", node_data={},
        config=config, sio=Mock(), sid="test-sid", workflow_id="workflow-test", user_id="user-test",
    )


SITE = "site.example"


@pytest.mark.parametrize("operation,fields,method,path,sites_key", [
    ("query_stats", {"site_id": SITE}, "POST", "/api/v2/query", False),
    ("get_overview", {"site_id": SITE}, "POST", "/api/v2/query", False),
    ("get_realtime", {"site_id": SITE}, "POST", "/api/v2/query", False),
    ("get_breakdown", {"site_id": SITE}, "POST", "/api/v2/query", False),
    ("get_timeseries", {"site_id": SITE}, "POST", "/api/v2/query", False),
    ("list_sites", {}, "GET", "/api/v1/sites", False),
    ("list_teams", {}, "GET", "/api/v1/sites/teams", False),
    ("get_site", {"site_id": SITE}, "GET", "/api/v1/sites/site.example", False),
    ("create_site", {"domain": SITE}, "POST", "/api/v1/sites", True),
    ("update_site", {"site_id": SITE, "new_domain": "new.example"}, "PUT", "/api/v1/sites/site.example", True),
    ("delete_site", {"site_id": SITE, "confirm_domain": SITE}, "DELETE", "/api/v1/sites/site.example", True),
    ("list_goals", {"site_id": SITE}, "GET", "/api/v1/sites/goals", False),
    ("upsert_goal", {"site_id": SITE, "event_name": "Signup"}, "PUT", "/api/v1/sites/goals", True),
    ("delete_goal", {"site_id": SITE, "goal_id": "7"}, "DELETE", "/api/v1/sites/goals/7", True),
    ("list_custom_properties", {"site_id": SITE}, "GET", "/api/v1/sites/custom-props", False),
    ("upsert_custom_property", {"site_id": SITE, "property": "campaign"}, "PUT", "/api/v1/sites/custom-props", True),
    ("delete_custom_property", {"site_id": SITE, "property": "campaign"}, "DELETE", "/api/v1/sites/custom-props/campaign", True),
    ("list_guests", {"site_id": SITE}, "GET", "/api/v1/sites/guests", False),
    ("upsert_guest", {"site_id": SITE, "email": "guest@example.com"}, "PUT", "/api/v1/sites/guests", True),
    ("delete_guest", {"site_id": SITE, "email": "guest@example.com"}, "DELETE", "/api/v1/sites/guests/guest%40example.com", True),
    ("upsert_shared_link", {"site_id": SITE, "name": "Dashboard"}, "PUT", "/api/v1/sites/shared-links", True),
    ("record_event", {"site_id": SITE, "name": "Signup", "url": "https://site.example/signup", "user_agent": "Mozilla/5.0"}, "POST", "/api/event", False),
    ("record_pageview", {"site_id": SITE, "url": "https://site.example/", "user_agent": "Mozilla/5.0"}, "POST", "/api/event", False),
])
@pytest.mark.asyncio
async def test_operation_routes(operation, fields, method, path, sites_key):
    target = node(operation, fields, key_type="sites" if sites_key else "stats")
    expected = {"status": "success", "action": operation, "data": {}}
    with patch("nodes.plausible_node._request", new_callable=AsyncMock, return_value=expected) as request:
        result = await target.execute({})
    assert result == expected
    args, kwargs = request.call_args
    assert args[1:4] == (method, path, operation)
    if operation == "query_stats":
        assert kwargs["body"]["site_id"] == SITE
        assert kwargs["body"]["metrics"] == ["visitors", "pageviews"]
    if operation == "upsert_custom_property":
        assert kwargs["form"] == {"site_id": SITE, "property": "campaign"}
    if operation == "record_pageview":
        assert kwargs["body"]["name"] == "pageview"
        assert kwargs["event_user_agent"] == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_sites_key_required_for_site_writes():
    with pytest.raises(ValueError, match="Enterprise Sites API key"):
        await node("create_site", {"domain": SITE}).execute({})


@pytest.mark.asyncio
async def test_delete_site_requires_exact_confirmation():
    with pytest.raises(ValueError, match="Confirm domain"):
        await node("delete_site", {"site_id": SITE, "confirm_domain": "other.example"}, "sites").execute({})


@pytest.mark.asyncio
async def test_event_url_must_match_site():
    with pytest.raises(ValueError, match="selected site domain"):
        await node("record_event", {"site_id": SITE, "name": "Signup", "url": "https://other.example/", "user_agent": "Mozilla/5.0"}).execute({})


@pytest.mark.asyncio
async def test_invalid_query_json_is_rejected():
    with pytest.raises(ValueError, match="Filters must be valid JSON"):
        await node("query_stats", {"site_id": SITE, "filters_json": "bad"}).execute({})


@pytest.mark.asyncio
async def test_event_202_reports_provider_drop():
    response = httpx.Response(202, json={}, headers={"x-plausible-dropped": "1"}, request=httpx.Request("POST", "https://plausible.io/api/event"))
    client = AsyncMock()
    client.request.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    with patch("nodes.plausible_node.guarded_async_client", return_value=context):
        result = await _request(PlausibleApiKeyCredential(api_key="test"), "POST", "/api/event", "record_event", body={"name": "Signup"}, event_user_agent="Mozilla/5.0")
    assert result["status"] == "error"
    assert result["accepted"] is True
    assert result["dropped"] is True
    assert "Plausible dropped the event" in result["error"]
    assert "Authorization" not in client.request.call_args.kwargs["headers"]


@pytest.mark.asyncio
async def test_api_error_is_structured():
    response = httpx.Response(403, json={"error": "insufficient permissions"}, request=httpx.Request("GET", "https://plausible.io/api/v1/sites"))
    client = AsyncMock()
    client.request.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    with patch("nodes.plausible_node.guarded_async_client", return_value=context):
        result = await _request(PlausibleApiKeyCredential(api_key="test"), "GET", "/api/v1/sites", "list_sites")
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "insufficient permissions"


def test_credential_rejects_non_https_origin():
    with pytest.raises(ValueError):
        PlausibleApiKeyCredential(api_key="test", base_url="http://localhost:8080")


@pytest.mark.asyncio
async def test_site_picker_and_connection_evidence_use_loaded_credential():
    with patch("nodes.plausible_node._request", new_callable=AsyncMock, return_value={
        "status": "success", "data": {"sites": [{"domain": SITE}]},
    }):
        options = await PlausibleNode.load_field_options(
            field_name="site_id", credential_data={"api_key": "test-key"},
        )
    assert options == {"options": [{"label": SITE, "value": SITE}]}


@pytest.mark.asyncio
async def test_site_picker_propagates_auth_error_to_evidence():
    error = {"status": "error", "status_code": 401, "error": "invalid key"}
    with patch("nodes.plausible_node._request", new_callable=AsyncMock, return_value=error):
        result = await PlausibleNode.load_field_options(
            field_name="site_id", credential_data={"api_key": "bad-key"},
        )
    assert result == error

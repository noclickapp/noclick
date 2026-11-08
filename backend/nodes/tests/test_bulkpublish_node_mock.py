"""Bulkpublish wire-contract regression tests with synthetic account responses.

The real node factory runs against an HTTP mock so routing, auth, parameters,
null handling, pagination and asynchronous publish acknowledgements are checked.
"""
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import bulkpublish_node as native
from nodes.core.registry import NodeFactory

TOKEN = "bp_synthetic_test_key_42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bulkpublish-test", node_type="automation-bulkpublish",
        node_data={"config": config, "credentials": {"credential_type": "bulkpublish_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs) as session:
            yield session

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Expectations are written independently of the implementation route table.
CASES = [
    ({"operation": "list_posts", "page": 2, "status": "scheduled", "channel_id": 8, "search": "launch + news"}, "GET", "/api/posts", {"page": "2", "limit": "20", "status": "scheduled", "channelId": "8", "search": "launch + news", "order": "desc"}),
    ({"operation": "get_post", "post_id": 7}, "GET", "/api/posts/7", {}),
    ({"operation": "create_post", "channel_ids": "[8,9]", "content": "Launch", "media_ids": "[5]", "label_ids": "[3]"}, "POST", "/api/posts", {"channels": [{"channelId": 8}, {"channelId": 9}], "content": "Launch", "mediaFiles": [5], "labels": [3], "status": "draft", "timezone": "UTC"}),
    ({"operation": "update_post", "post_id": 7, "content": "Edited"}, "PUT", "/api/posts/7", {"content": "Edited"}),
    ({"operation": "delete_post", "post_id": 7}, "DELETE", "/api/posts/7", {}),
    ({"operation": "publish_post", "post_id": 7}, "POST", "/api/posts/7/publish", {}),
    ({"operation": "retry_post", "post_id": 7}, "POST", "/api/posts/7/retry", {"republish": False}),
    ({"operation": "get_post_metrics", "post_id": 7}, "GET", "/api/posts/7/metrics", {}),
    ({"operation": "list_channels", "active": False}, "GET", "/api/channels", {"active": "false"}),
    ({"operation": "get_channel", "channel_id": 8}, "GET", "/api/channels/8", {}),
    ({"operation": "get_channel_health", "channel_id": 8}, "GET", "/api/channels/8/health", {}),
    ({"operation": "list_media", "page": 3, "media_type": "document"}, "GET", "/api/media", {"page": "3", "limit": "20", "type": "document"}),
    ({"operation": "get_media", "media_id": 5}, "GET", "/api/media/5", {}),
    ({"operation": "delete_media", "media_id": 5}, "DELETE", "/api/media/5", {}),
    ({"operation": "update_media", "media_id": 5, "alt_text": None}, "PATCH", "/api/media/5", {"altText": None}),
    ({"operation": "get_analytics_summary", "from_date": "2026-11-01", "to_date": "2026-11-07", "channel_ids": "8,9"}, "GET", "/api/analytics/summary", {"from": "2026-11-01", "to": "2026-11-07", "tz": "UTC", "channelIds": "8,9"}),
    ({"operation": "get_analytics_engagement", "from_date": "2026-11-01", "to_date": "2026-11-07"}, "GET", "/api/analytics/engagement", {"from": "2026-11-01", "to": "2026-11-07", "tz": "UTC"}),
    ({"operation": "list_labels", "label_type": "media"}, "GET", "/api/labels", {"type": "media"}),
    ({"operation": "create_label", "name": "Campaign", "color": "#3B82F6"}, "POST", "/api/labels", {"name": "Campaign", "color": "#3B82F6", "type": "post"}),
    ({"operation": "update_label", "label_id": 3, "name": "Renamed"}, "PUT", "/api/labels/3", {"name": "Renamed"}),
    ({"operation": "delete_label", "label_id": 3}, "DELETE", "/api/labels/3", {}),
    ({"operation": "list_schedules"}, "GET", "/api/schedules", {}),
    ({"operation": "create_schedule", "name": "Daily", "time_of_day": "09:30", "channel_ids": "[8]", "content_template": "Morning update"}, "POST", "/api/schedules", {"name": "Daily", "frequency": "daily", "timeOfDay": "09:30", "timezone": "UTC", "channelIds": [8], "contentTemplate": "Morning update", "isActive": True, "requireApproval": False}),
    ({"operation": "get_schedule", "schedule_id": 4}, "GET", "/api/schedules/4", {}),
    ({"operation": "delete_schedule", "schedule_id": 4}, "DELETE", "/api/schedules/4", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,expected", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_bulkpublish_exact_single_request(monkeypatch, config, method, path, expected):
    body = {"channels": [{"id": 8, "accountName": "Campaign team"}]} if config["operation"] == "list_channels" else {"id": 7, "status": "publishing"}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result == {"status": "success", "http_status": 200, "data": body, **({"items": body["channels"]} if "channels" in body else {})}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "app.bulkpublish.com" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    actual = dict(request.url.params) if method == "GET" else json.loads(request.content) if request.content else {}
    assert actual == expected


@pytest.mark.asyncio
async def test_bulkpublish_metrics_and_pagination_are_preserved(monkeypatch):
    metrics = {"totals": {"likes": 0}, "platforms": [{"metricsSupported": False, "supportedMetrics": ["linkClicks"], "latest": None}]}
    transport(monkeypatch, metrics)
    assert (await node({"operation": "get_post_metrics", "post_id": 7}).execute({}))["data"] == metrics
    page = {"posts": [{"id": 7}], "page": 2, "limit": 20, "total": 45, "totalPages": 3}
    requests = transport(monkeypatch, page)
    assert (await node({"operation": "list_posts", "page": 2}).execute({}))["data"] == page
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500])
async def test_bulkpublish_provider_errors_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, {"error": "FORBIDDEN", "message": "Denied for " + TOKEN}, status)
    result = await node({"operation": "publish_post", "post_id": 7}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"]["error"] == "FORBIDDEN"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_bulkpublish_malformed_evidence_and_redirects_rejected(monkeypatch):
    transport(monkeypatch, {"unexpected": []})
    with pytest.raises(ValueError, match="missing channels"):
        await node({"operation": "list_channels"}).execute({})
    transport(monkeypatch, {}, 302)
    with pytest.raises(ValueError, match="redirect"):
        await node({"operation": "list_channels"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_post", "post_id": "../other"},
    {"operation": "get_post", "post_id": -1},
    {"operation": "list_posts", "limit": 501},
    {"operation": "create_post", "content": "Test", "channel_ids": "[]"},
    {"operation": "create_post", "content": "Test", "channel_ids": "[8]", "status": "scheduled"},
    {"operation": "create_post", "content": "Test", "channel_ids": "[8]", "scheduled_at": "2026-11-10T09:30:00"},
    {"operation": "get_analytics_summary", "from_date": "2026-11-07", "to_date": "2026-11-01"},
    {"operation": "get_analytics_summary", "from_date": "2026-11-01", "to_date": "2026-11-07", "timezone": "invalid-zone"},
    {"operation": "create_schedule", "name": "Test", "frequency": "weekly", "time_of_day": "09:30", "channel_ids": "[8]", "content_template": "Test"},
    {"operation": "create_label", "name": "   "},
    {"operation": "create_label", "name": "Test", "color": "red"},
    {"operation": "list_channels", "url": "https://example.com"},
])
def test_bulkpublish_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


def test_bulkpublish_manual_credential_and_schema():
    credential = native.BulkpublishAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "bulkpublish_api_key"
    assert len(CASES) == len(native.ROUTES) == 25
    for value in ["Bearer " + TOKEN, "https://app.bulkpublish.com", "bad\nkey"]:
        with pytest.raises(ValueError):
            native.BulkpublishAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_bulkpublish_empty_acknowledgement_and_empty_arrays(monkeypatch):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "publish_post", "post_id": 7}).execute({})
    assert result == {"status": "success", "http_status": 200, "data": None}
    requests = transport(monkeypatch, {"id": 7})
    await node({"operation": "update_post", "post_id": 7, "content": "Text", "media_ids": "[]", "label_ids": "[]"}).execute({})
    assert json.loads(requests[0].content) == {"content": "Text", "mediaFiles": [], "labels": []}

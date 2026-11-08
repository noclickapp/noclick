"""Offline factory tests against GTmetrix's published response examples."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import gtmetrix_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-gtmetrix-key"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/gtmetrix/documented.json").read_text())["examples"]
CASES = [
    ("start_test", {"url": "https://gtmetrix.com"}, "queued_test", 202),
    ("list_tests", {}, "test_collection", 200),
    ("get_test", {"test_id": "test-1"}, "completed_test", 200),
    ("get_report", {"report_slug": "report-1"}, "report", 200),
    ("delete_report", {"report_slug": "report-1"}, "deleted_report", 200),
    ("retest_report", {"report_slug": "report-1"}, "queued_test", 202),
    ("list_pages", {}, "page_collection", 200),
    ("get_page", {"page_id": "page-1"}, "page", 200),
    ("delete_page", {"page_id": "page-1"}, "deleted_page", 200),
    ("retest_page", {"page_id": "page-1"}, "queued_test", 202),
    ("update_page_monitoring", {"page_id": "page-1", "frequency": "daily"}, "page", 200),
    ("list_page_reports", {"page_id": "page-1"}, "report_collection", 200),
    ("get_latest_page_report", {"page_id": "page-1"}, "report", 200),
    ("list_page_alert_events", {"page_id": "page-1"}, "performance_alert_event_collection", 200),
    ("list_tags", {}, "tag_collection", 200),
    ("create_tag", {"name": "Production", "color": "00FF00"}, "tag", 201),
    ("get_tag", {"tag_id": "tag-1"}, "tag", 200),
    ("update_tag", {"tag_id": "tag-1", "description": "New description"}, "tag", 200),
    ("delete_tag", {"tag_id": "tag-1"}, "deleted_tag", 200),
    ("attach_tag_pages", {"tag_id": "tag-1", "page_ids": ["page-1", "page-2"]}, "tag", 200),
    ("detach_tag_pages", {"tag_id": "tag-1", "page_ids": ["page-1"]}, "tag", 200),
    ("list_locations", {}, "location_collection", 200),
    ("list_browsers", {}, "browser_collection", 200),
    ("list_simulated_devices", {}, "simulated_device_collection", 200),
    ("get_account_status", {}, "status", 200),
]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="gtmetrix-test", node_type="automation-gtmetrix",
        node_data={"config": {"operation": operation, **(config or {})},
            "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,example,status", CASES)
async def test_documented_response_single_request(monkeypatch, operation, config, example, status):
    requests = transport(monkeypatch, httpx.Response(status, json=EXAMPLES[example], headers={"content-type": native.MEDIA_TYPE}))
    result = await node(operation, config).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    method, path = native.ROUTES[operation]
    assert request.method == method and request.url.path == "/api/2.0" + path.format(**config)
    assert request.headers["authorization"] == "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()
    assert TOKEN not in str(result)
    if operation == "get_account_status":
        assert "id" not in result["data"] and EXAMPLES[example]["data"]["id"] not in str(result)
    if operation in {"retest_page", "retest_report"}:
        assert request.content == b""
    if operation == "start_test":
        sent = json.loads(request.content)
        assert sent["data"]["type"] == "test" and sent["data"]["attributes"]["url"] == config["url"]
        assert type(sent["data"]["attributes"]["video"]) is int
    if operation == "update_page_monitoring":
        assert json.loads(request.content) == EXAMPLES["performance_monitor_update"]
    if operation in {"attach_tag_pages", "detach_tag_pages"}:
        assert json.loads(request.content) == {"page_ids": config["page_ids"]}
    if operation == "create_tag":
        assert json.loads(request.content) == {"data": {"type": "tag", "attributes": config}}
    if request.content:
        assert request.headers["content-type"] == native.MEDIA_TYPE


@pytest.mark.asyncio
async def test_pagination_filters_and_connection_evidence(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json=EXAMPLES["test_collection"], headers={"content-type": native.MEDIA_TYPE}))
    result = await node("list_tests", {"page_number": 3, "page_size": 10, "source": "any", "state": "completed"}).execute({})
    assert dict(requests[0].url.params) == {"page[number]": "3", "page[size]": "10", "filter[source]": "any", "filter[state]": "completed"}
    assert result["has_more"] and result["next_page_number"] == 4
    transport(monkeypatch, httpx.Response(200, json=EXAMPLES["page_collection"], headers={"content-type": native.MEDIA_TYPE}))
    result = await node("list_pages").execute({})
    assert result["items"][0]["url"] == "https://gtmetrix.com"
    assert native.GTmetrixNode.connection_evidence.operation == "list_pages"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejections_keep_provider_text_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"errors": [{"title": "Invalid API key", "detail": TOKEN + " was rejected"}]}))
    result = await node("list_pages").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and "was rejected" in result["error"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": []}, {"data": None}])
async def test_malformed_success_rejected(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body, headers={"content-type": native.MEDIA_TYPE}))
    with pytest.raises(ValueError, match="unexpected JSON:API"):
        await node("list_pages").execute({})


@pytest.mark.parametrize("operation,config", [
    ("get_page", {"page_id": "../status"}), ("get_report", {"report_slug": "foo?x=y"}),
    ("start_test", {"url": "javascript:alert(1)"}),
    ("update_page_monitoring", {"page_id": "p", "frequency": "yearly"}),
    ("create_tag", {"name": "a", "color": "#ffffff"}),
    ("attach_tag_pages", {"tag_id": "a", "page_ids": ["a", "a"]}), ("update_tag", {"tag_id": "a"}),
])
def test_invalid_inputs(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        native.GTmetrixNode.parse_config({"config": {"operation": operation, **config}})


def test_manual_credential_and_family():
    assert native.GTmetrixAPIKeyCredential(api_key=TOKEN).credential_type == native.CREDENTIAL_TYPE
    with pytest.raises(ValidationError):
        native.GTmetrixAPIKeyCredential(api_key=TOKEN, credential_type="other_api_key")
    assert len(native.ROUTES) == 25

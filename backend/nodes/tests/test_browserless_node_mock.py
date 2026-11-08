"""Exercise Browserless through the native factory and an intercepted transport.

Request assertions cover methods, token placement, wire names and binary output.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import browserless_node as module
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory
from utils import ssrf


TOKEN = "fixture-browserless-token"
URL = "https://www.browserless.io"
# Exact Response example: https://docs.browserless.io/rest-apis/scrape
SCRAPE = json.loads((Path(__file__).parent / "fixtures/browserless/scrape.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(module, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, arguments=None, region="sfo"):
    return NodeFactory.create_node(node_id="browserless-test", node_type="automation-browserless", node_data={
        "config": {"operation": operation, **(arguments or {})},
        "credentials": {"credential_type": "browserless_token", "api_token": TOKEN, "region": region},
    })


CASES = [
    ("take_screenshot", {"url": URL}, "POST", "/screenshot", {"url": URL, "options": {"type": "png", "fullPage": True, "encoding": "binary"}}, b"png-bytes"),
    ("generate_pdf", {"url": URL}, "POST", "/pdf", {"url": URL, "options": {"printBackground": True, "landscape": False}}, b"%PDF-1.4"),
    ("get_content", {"url": URL, "wait_for_timeout": 1000}, "POST", "/chromium/content", {"url": URL, "waitForTimeout": 1000}, b"<html><h1>Browserless</h1></html>"),
    ("scrape_elements", {"url": URL, "elements": [{"selector": "h1"}]}, "POST", "/chromium/scrape", {"url": URL, "elements": [{"selector": "h1"}]}, SCRAPE),
    ("get_performance", {"url": URL}, "POST", "/chromium/performance", {"url": URL}, {"categories": {"performance": {"score": 0.98}}}),
    ("search", {"query": "browser automation"}, "POST", "/search", {"query": "browser automation", "limit": 10}, {"success": True, "data": {"web": []}, "totalResults": 0}),
    ("map_site", {"url": URL}, "POST", "/map", {"url": URL, "limit": 100, "sitemap": "include"}, [{"url": URL}]),
    ("list_crawls", {"cursor": "next-cursor"}, "GET", "/crawl", None, {"crawls": [{"id": "crawl-1"}], "nextCursor": "page-2"}),
    ("start_crawl", {"url": URL}, "POST", "/crawl", {"url": URL, "limit": 100, "maxDepth": 5}, {"success": True, "id": "crawl-1", "url": "/crawl/crawl-1"}),
    ("get_crawl", {"crawl_id": "crawl-1", "skip": 20}, "GET", "/crawl/crawl-1", None, {"status": "completed", "data": [], "next": None}),
    ("cancel_crawl", {"crawl_id": "crawl-1"}, "DELETE", "/crawl/crawl-1", None, b""),
    ("list_profiles", {"limit": 2, "offset": 2}, "GET", "/profiles", None, [{"name": "acme-prod", "cookieCount": 3}]),
    ("get_profile", {"profile_name": "acme-prod"}, "GET", "/profile/acme-prod", None, {"name": "acme-prod"}),
    ("rename_profile", {"profile_name": "acme-prod", "new_name": "acme-staging"}, "PUT", "/profile/acme-prod", {"name": "acme-staging"}, {"name": "acme-staging"}),
    ("delete_profile", {"profile_name": "acme-prod"}, "DELETE", "/profile/acme-prod", None, b""),
    ("create_session", {"ttl": 60000, "profile": "acme-prod"}, "POST", "/session", {"ttl": 60000, "stealth": False, "profile": "acme-prod"}, {"id": "session-1", "connect": "wss://production-sfo.browserless.io/session/connect/session-1"}),
]


@pytest.mark.parametrize("operation,arguments,method,path,body,payload", CASES)
async def test_native_operations(transport, operation, arguments, method, path, body, payload):
    requests, replies = transport
    replies.append((204 if payload == b"" else 200, payload))
    result = await node(operation, arguments).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "production-sfo.browserless.io"
    assert request.url.path == path
    assert request.url.params["token"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    for key in ("cursor", "skip", "offset", "limit"):
        if method == "GET" and key in arguments:
            assert request.url.params[key] == str(arguments[key])
    if operation in {"take_screenshot", "generate_pdf"}:
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == payload
        assert result["file"].content_type == ("image/png" if operation == "take_screenshot" else "application/pdf")
    elif operation == "get_content":
        assert result["html"] == payload.decode()
    elif payload != b"":
        assert result["data"] == payload


async def test_regional_account_read_and_provider_rejection(transport):
    requests, replies = transport
    replies.append((401, {"message": "Token rejected: " + TOKEN}))
    result = await node("list_profiles", region="ams").execute({})
    assert requests[0].url.host == "production-ams.browserless.io"
    assert result["status"] == "error" and result["http_status"] == 401
    assert "Token rejected" in result["error"] and TOKEN not in str(result)


async def test_profile_names_are_one_encoded_path_component(transport):
    requests, replies = transport
    replies.append((200, {"name": "acme/prod?x=1"}))
    await node("get_profile", {"profile_name": "acme/prod?x=1"}).execute({})
    assert requests[0].url.raw_path.split(b"?")[0] == b"/profile/acme%2Fprod%3Fx%3D1"
    assert dict(requests[0].url.params) == {"token": TOKEN}


def test_required_inputs_and_region_are_validated():
    for config in ({"operation": "scrape_elements", "url": URL}, {"operation": "create_session"},
                   {"operation": "get_profile", "profile_name": ".."},
                   {"operation": "cancel_crawl", "crawl_id": "."}):
        assert not module.BrowserlessNode.validate_config({"config": config})["valid"], config
    with pytest.raises(ValueError):
        module.BrowserlessTokenCredential(api_token=TOKEN, region="private-host")

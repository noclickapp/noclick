"""Factory-level v2 HTTP contract tests; no provider credentials or network.

Documented response fixtures retain their publisher URLs. Other responses in
this file are synthetic and exercise errors, acknowledgements and pagination.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import scrapegraph_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-scrapegraph-secret-42"
ID = "79694e03-f2ea-43f2-93cc-7c6fc26f999a"
MONITOR = "f0b171db-b288-4380-9cad-1bcac916348e"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/scrapegraph_ai/documented_responses.json").read_text())
MONITOR_BODY = {"cronId": MONITOR, "scheduleId": "schedule-fixture", "interval": "*/30 * * * *", "status": "active",
    "reason": None, "consecutiveFailures": 0, "config": {"url": "https://example.com", "interval": "*/30 * * * *"},
    "createdAt": "2026-04-23T11:11:37.487Z", "updatedAt": "2026-04-23T11:11:37.487Z"}
CASES = [
    ({"operation": "scrape_url", "url": "https://example.com", "formats": ["markdown", "screenshot"]}, "POST", "/api/scrape", FIXTURES["POST /api/scrape"]["body"]),
    ({"operation": "extract", "url": "https://example.com", "prompt": "What is the title of this page?"}, "POST", "/api/extract", FIXTURES["POST /api/extract"]["body"]),
    ({"operation": "search", "query": "scrapegraphai pricing", "num_results": 3}, "POST", "/api/search", FIXTURES["POST /api/search"]["body"]),
    ({"operation": "list_history", "page": 1, "limit": 5, "service": "scrape", "session_id": "import"}, "GET", "/api/history", FIXTURES["GET /api/history"]["body"]),
    ({"operation": "get_history", "history_id": ID}, "GET", f"/api/history/{ID}", {"id": ID, "service": "scrape", "status": "failed", "error": {"message": "Target unavailable"}, "result": None}),
    ({"operation": "create_monitor", "url": "https://example.com", "name": "Homepage watch", "interval": "*/30 * * * *"}, "POST", "/api/monitor", MONITOR_BODY),
    ({"operation": "list_monitors"}, "GET", "/api/monitor", [MONITOR_BODY]),
    ({"operation": "get_monitor", "monitor_id": MONITOR}, "GET", f"/api/monitor/{MONITOR}", MONITOR_BODY),
    ({"operation": "update_monitor", "monitor_id": MONITOR, "interval": "0 */6 * * *", "clear_webhook": True}, "PATCH", f"/api/monitor/{MONITOR}", MONITOR_BODY),
    ({"operation": "delete_monitor", "monitor_id": MONITOR}, "DELETE", f"/api/monitor/{MONITOR}", {"ok": True}),
    ({"operation": "get_monitor_activity", "monitor_id": MONITOR, "cursor": "2026-04-23T11:11:37.487Z", "limit": 2}, "GET", f"/api/monitor/{MONITOR}/activity", {"ticks": [], "nextCursor": "2026-04-22T11:11:37.487Z"}),
    ({"operation": "pause_monitor", "monitor_id": MONITOR}, "POST", f"/api/monitor/{MONITOR}/pause", {**MONITOR_BODY, "status": "paused"}),
    ({"operation": "resume_monitor", "monitor_id": MONITOR}, "POST", f"/api/monitor/{MONITOR}/resume", MONITOR_BODY),
    ({"operation": "start_crawl", "url": "https://scrapegraphai.com/", "max_depth": None, "max_pages": 5, "include_patterns": ["/blog/*"]}, "POST", "/api/crawl", FIXTURES["POST /api/crawl"]["body"]),
    ({"operation": "get_crawl", "crawl_id": ID}, "GET", f"/api/crawl/{ID}", {"id": ID, "status": "running", "total": 3, "finished": 0, "pages": []}),
    ({"operation": "delete_crawl", "crawl_id": ID}, "DELETE", f"/api/crawl/{ID}", {"ok": True}),
    ({"operation": "list_crawl_pages", "crawl_id": ID, "cursor": 50, "limit": 50}, "GET", f"/api/crawl/{ID}/pages", {"data": [], "pagination": {"limit": 50, "nextCursor": None}}),
    ({"operation": "stop_crawl", "crawl_id": ID}, "POST", f"/api/crawl/{ID}/stop", {"ok": True}),
    ({"operation": "resume_crawl", "crawl_id": ID}, "POST", f"/api/crawl/{ID}/resume", {"ok": True}),
    ({"operation": "get_credits"}, "GET", "/api/credits", FIXTURES["GET /api/credits"]["body"]),
    ({"operation": "get_account"}, "GET", "/api/validate", {"email": "owner@example.com"}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="scrapegraph-fixture", node_type="automation-scrapegraph-ai",
        node_data={"config": config, "credentials": credentials or {"credential_type": native.FAMILY, "api_key": TOKEN}})


def transport(monkeypatch, body, status=200, content_type="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"content-type": content_type})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_scrapegraph_ai_one_operation_one_request(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, body, status=201 if config["operation"] == "create_monitor" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "v2-api.scrapegraphai.com"
    assert request.headers["SGAI-APIKEY"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert TOKEN not in str(result)
    action = config["operation"]
    if action == "list_history":
        assert dict(request.url.params) == {"page": "1", "limit": "5", "service": "scrape", "sessionId": "import"}
    elif action == "list_crawl_pages":
        assert dict(request.url.params) == {"cursor": "50", "limit": "50"}
    elif action == "get_monitor_activity":
        assert dict(request.url.params) == {"cursor": config["cursor"], "limit": "2"}
    elif action == "update_monitor":
        assert json.loads(request.content) == {"interval": "0 */6 * * *", "webhookUrl": None}
    elif action == "start_crawl":
        payload = json.loads(request.content)
        assert payload["maxDepth"] is None and payload["maxPages"] == 5
        assert payload["includePatterns"] == ["/blog/*"] and "max_depth" not in payload
    elif action == "scrape_url":
        assert json.loads(request.content)["formats"] == [{"type": "markdown"}, {"type": "screenshot"}]
    elif action == "get_account":
        assert result["email"] == "owner@example.com"
    if method in {"GET", "DELETE"} or action in {"pause_monitor", "resume_monitor", "stop_crawl", "resume_crawl"}:
        assert not request.content


@pytest.mark.asyncio
async def test_scrapegraph_ai_schema_session_and_fetch_options(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["POST /api/extract"]["body"])
    result = await node({"operation": "extract", "html": "<h1>Example</h1>", "prompt": "Find title",
        "json_schema": '{"type":"object","properties":{"title":{"type":"string"}}}',
        "session_id": "import-2026", "fetch_mode": "js", "wait_ms": 1000, "timeout_ms": 30000}).execute({})
    assert result["status"] == "success"
    assert requests[0].headers["SGAI-Session-Id"] == "import-2026"
    body = json.loads(requests[0].content)
    assert body["schema"]["properties"]["title"]["type"] == "string"
    assert body["fetchConfig"] == {"mode": "js", "wait": 1000, "timeout": 30000}
    assert "session_id" not in body and "url" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401,{"error":{"type":"auth_invalid_key","message":"API key rejected"}}),
    (429,{"error":{"type":"rate_limit","message":"Too many requests"}}), (500,{"error":{"message":TOKEN}}),
    (200,{"error":{"message":"Request failed"}}), (200,{}), (200,[]), (302,{})])
async def test_scrapegraph_ai_errors_are_failures_without_retry(monkeypatch,status,body):
    requests = transport(monkeypatch,body,status)
    result = await node({"operation":"get_account"}).execute({})
    assert result["status"] == "error" and len(requests) == 1 and TOKEN not in str(result)
    if status == 401:
        assert result["error"] == "API key rejected"


@pytest.mark.asyncio
async def test_scrapegraph_ai_rejects_non_json_and_false_acknowledgement(monkeypatch):
    requests = transport(monkeypatch,{"email":"owner@example.com"},content_type="text/html")
    assert (await node({"operation":"get_account"}).execute({}))["status"] == "error"
    assert len(requests) == 1
    transport(monkeypatch,{"ok":False})
    assert (await node({"operation":"delete_crawl","crawl_id":ID}).execute({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation":"get_crawl","crawl_id":"../credits"},
    {"operation":"scrape_url","url":"https://user:secret@example.com"},
    {"operation":"extract","url":"https://example.com","html":"<p>x</p>","prompt":"Extract"},
    {"operation":"extract","prompt":"Extract"},
    {"operation":"extract","url":"https://example.com","prompt":"Extract","json_schema":"[]"},
    {"operation":"update_monitor","monitor_id":MONITOR},
    {"operation":"update_monitor","monitor_id":MONITOR,"clear_webhook":True,"webhook_url":"https://example.com/hook"},
    {"operation":"get_monitor_activity","monitor_id":MONITOR,"cursor":"not-a-date"},
    {"operation":"list_crawl_pages","crawl_id":ID,"cursor":-1},
    {"operation":"search","query":"x","num_results":21},
    {"operation":"start_crawl","url":"https://example.com","max_pages":1001},
])
def test_scrapegraph_ai_invalid_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        node(config)


def test_scrapegraph_ai_manual_credential_and_account_evidence():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, _ = shape_credential(native.FAMILY, {"api_key": "  " + TOKEN + "  "})
    assert not errors and shaped["api_key"] == TOKEN and native.ScrapegraphAIAPIKeyCredential.model_validate(shaped).credential_type == native.FAMILY
    assert native.ScrapegraphAINode.connection_evidence.identity_operation == "get_account"
    with pytest.raises(ValidationError):
        native.ScrapegraphAIAPIKeyCredential(api_key="https://example.com/key")
    with pytest.raises(ValidationError):
        native.ScrapegraphAIAPIKeyCredential(api_key=TOKEN, credential_type="other")

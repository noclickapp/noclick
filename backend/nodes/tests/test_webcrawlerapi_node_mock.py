"""Verify Webcrawlerapi operations through the real factory and HTTP transport.

Provider-authored fixtures exercise response parsing; additional synthetic cases
cover request serialization, credential isolation and provider failures offline.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import webcrawlerapi_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

TOKEN = "test-webcrawlerapi-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/webcrawlerapi/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "webcrawlerapi_api_key", "api_key": TOKEN}


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="webcrawlerapi-fixture", node_type="automation-webcrawlerapi",
        node_data={"config": config, "credentials": credential() if credentials is None else credentials})


def transport(monkeypatch, body=None, *, status=200, mime="application/json", reply=None):
    requests = []
    def respond(request):
        requests.append(request)
        if reply:
            return reply(request)
        if mime != "application/json":
            return httpx.Response(status, text=body, headers={"content-type": mime})
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def operation_config(operation):
    method, path, _ = native.ROUTES[operation]
    cfg = {"operation": operation}
    for field in ("job_id", "scrape_id", "agent_job_id", "feed_id"):
        if "{" + field + "}" in path:
            cfg[field] = "abc123"
    if operation in {"create_crawl", "create_scrape", "create_feed", "extract_markdown"}:
        cfg["url"] = "https://example.com/blog"
    if operation == "run_agent":
        cfg.update(prompt="Find all pricing plans", max_spend_usd=1,
            urls="https://example.com/\nhttps://example.com/pricing")
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_all_operations_one_fixed_authenticated_request(monkeypatch, operation):
    body = FIXTURES.get(operation, {}).get("body", {"email": "account@example.com"})
    requests = transport(monkeypatch, body)
    result = await node(operation_config(operation)).execute({})
    assert result == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    method, path, _ = native.ROUTES[operation]
    assert request.method == method
    assert request.url.host == "api.webcrawlerapi.com"
    assert request.url.path == path.format(job_id="abc123", scrape_id="abc123", agent_job_id="abc123", feed_id="abc123")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result) and TOKEN not in str(request.url)
    if operation == "create_scrape":
        assert dict(request.url.params) == {"async": "true"}
    if operation == "list_agent_jobs":
        assert dict(request.url.params) == {"limit": "20", "offset": "0"}
    if operation == "get_feed_json":
        assert dict(request.url.params) == {"page": "1", "page_size": "20"}
    if method in {"PUT", "DELETE"} or operation in {"resend_job_webhook", "resend_feed_webhook"}:
        assert request.content == b""


@pytest.mark.asyncio
async def test_crawl_body_preserves_false_zero_and_arrays(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["create_crawl"]["body"])
    cfg = {"operation": "create_crawl", "url": "https://stripe.com/", "items_limit": 10,
        "webhook_url": "https://yourserver.com/webhook", "output_formats": "markdown, html,links",
        "main_content_only": False, "respect_robots_txt": False, "max_depth": 0, "max_age": 0,
        "whitelist_regexp": ".*/docs/.*", "blacklist_regexp": ".*/admin/.*"}
    await node(cfg).execute({})
    expected = {k: v for k, v in cfg.items() if k != "operation"}
    expected["output_formats"] = ["markdown", "html", "links"]
    assert json.loads(requests[0].content) == expected
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_agent_seed_urls_budget_and_nested_schema(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["run_agent"]["body"])
    cfg = operation_config("run_agent")
    cfg.update(seed_urls_only=False, output_schema={"type": "object", "properties": {"plans": {"type": "array"}}})
    await node(cfg).execute({})
    body = json.loads(requests[0].content)
    assert body["urls"] == ["https://example.com/", "https://example.com/pricing"]
    assert body["max_spend_usd"] == 1 and body["seed_urls_only"] is False
    assert body["output_schema"] == cfg["output_schema"]


@pytest.mark.asyncio
async def test_usage_query_dates_and_daily_false(monkeypatch):
    requests = transport(monkeypatch, {"total": 10})
    await node({"operation": "get_usage", "from_date": "2026-01-01", "to_date": "2026-01-31", "include_daily": False}).execute({})
    assert dict(requests[0].url.params) == {"from": "2026-01-01", "to": "2026-01-31", "include_daily": "false"}


@pytest.mark.asyncio
async def test_paging_is_one_page_and_empty_feeds_are_success(monkeypatch):
    requests = transport(monkeypatch, {"items": [], "total": 42})
    result = await node({"operation": "list_agent_jobs", "limit": 2, "offset": 40}).execute({})
    assert result["data"] == {"items": [], "total": 42}
    assert dict(requests[0].url.params) == {"limit": "2", "offset": "40"} and len(requests) == 1
    transport(monkeypatch, {"feeds": []})
    assert (await node({"operation": "list_feeds"}).execute({}))["data"] == {"feeds": []}


@pytest.mark.asyncio
async def test_pending_scrape_does_not_claim_completion(monkeypatch):
    requests = transport(monkeypatch, {"status": "pending"})
    assert await node({"operation": "get_scrape", "scrape_id": "abc123"}).execute({}) == {
        "status": "success", "data": {"status": "pending"}}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (401, {"error": "Unauthorized"}), (402, {"error": "Insufficient balance"}),
    (429, {"error": "Rate limit exceeded"}), (500, {"error": "Internal server error"}),
    (200, {"success": False, "error_code": "name_not_resolved", "error_message": "unable to resolve domain name"}),
])
async def test_provider_rejection_retains_message_without_retry(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status=status)
    result = await node({"operation": "get_scrape", "scrape_id": "abc123"}).execute({})
    assert result["status"] == "error"
    assert result["error"] == body.get("error_message", body.get("error"))
    assert len(requests) == 1 and "data" not in result


@pytest.mark.asyncio
async def test_redirect_is_never_followed(monkeypatch):
    requests = transport(monkeypatch, reply=lambda request: httpx.Response(302, headers={"location": "https://elsewhere.example/"}))
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
async def test_error_redacts_the_credential(monkeypatch):
    transport(monkeypatch, {"error": "Rejected " + TOKEN}, status=401)
    result = await node({"operation": "check_connection"}).execute({})
    assert TOKEN not in str(result) and "[redacted]" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,mime", [("<html>error</html>", "text/html"), ([], "application/json"), (None, "application/json")])
async def test_malformed_json_object_is_not_success(monkeypatch, body, mime):
    transport(monkeypatch, body, mime=mime)
    with pytest.raises(ValueError, match="JSON object"):
        await node({"operation": "list_feeds"}).execute({})


@pytest.mark.parametrize("value", ["https://example.com/key", "<YOUR_API_KEY>", "Bearer abc", "bad\nkey", "badékey", ""])
def test_manual_credential_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        native.WebcrawlerapiApiKeyCredential(api_key=value)


def test_manual_credential_has_default_type_and_shapes_pasted_key():
    shaped, errors, _ = shape_credential("webcrawlerapi_api_key", {"api_key": "  " + TOKEN + "\n"})
    assert not errors and shaped["api_key"] == TOKEN
    assert native.WebcrawlerapiApiKeyCredential.model_validate(shaped).credential_type == "webcrawlerapi_api_key"


@pytest.mark.parametrize("config", [
    {"operation": "get_job", "job_id": "../other"},
    {"operation": "create_crawl", "url": "https://user:password@example.com"},
    {"operation": "create_crawl", "url": "file:///etc/passwd"},
    {"operation": "create_crawl", "url": "https://example.com", "output_formats": "garbage"},
    {"operation": "run_agent", "prompt": "extract", "max_spend_usd": 0},
    {"operation": "get_usage", "from_date": "2026-02-02", "to_date": "2026-02-01"},
    {"operation": "run_agent", "prompt": "extract", "max_spend_usd": 1, "output_schema": "[]"},
    {"operation": "get_feed_json", "feed_id": "abc123", "page_size": 1001},
])
def test_invalid_config_fails_before_any_request(config):
    assert native.WebcrawlerapiNode.validate_config({"config": config, "credentials": credential()})["valid"] is False


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_email(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"email": "owner@example.com"})
    result = await collect_evidence(node_type="automation-webcrawlerapi", user_id="webcrawlerapi-fixture", credential_data=credential())
    assert result.reachable is True and result.account_label == "owner@example.com"


@pytest.mark.asyncio
async def test_connection_rejection_is_definitive(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"error": "Unauthorized"}, status=401)
    result = await collect_evidence(node_type="automation-webcrawlerapi", user_id="webcrawlerapi-fixture", credential_data=credential())
    assert result.reachable is False and "Unauthorized" in str(result)

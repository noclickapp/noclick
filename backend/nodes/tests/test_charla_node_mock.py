"""Wire regressions based on the Charla Public API v1 contract."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.charla_node import CharlaAPIKeyCredential, CharlaFullConfig, CharlaNode

KEY = "test-charla-secret-abc123"
CONTACT = "58300e07-2cfa-4d6c-938c-b3a362edde05"
FIXTURES = Path(__file__).parent / "fixtures" / "charla"


def node(config):
    parsed = CharlaFullConfig.model_validate({"config": config, "credentials": {"api_key": KEY}})
    return CharlaNode("test", "automation-charla", {}, config=parsed)


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr("nodes.charla_node.guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", [
    ({"operation": "check_connection"}, "GET", "/contacts"),
    ({"operation": "list_contacts", "cursor": 1757765348}, "GET", "/contacts"),
    ({"operation": "get_contact", "id": CONTACT}, "GET", "/contacts/" + CONTACT),
    ({"operation": "save_contact", "id": CONTACT, "name": "Adam", "tags": "lead, hot"}, "POST", "/contacts"),
    ({"operation": "list_conversations", "cursor": 1757765348}, "GET", "/conversations"),
    ({"operation": "get_article", "id": 43525}, "GET", "/kb/articles/43525"),
    ({"operation": "list_articles", "cursor": "NjM4OTMzNjA5NDgxMjMwMDAwXzQzNTI1"}, "GET", "/kb/articles"),
    ({"operation": "save_article", "title": "How to use Charla API", "article": "<p>Full article content here.</p>", "categories": [{"id": 1}]}, "POST", "/kb/articles"),
    ({"operation": "delete_article", "id": 43525}, "DELETE", "/kb/article/43525"),
    ({"operation": "list_categories"}, "GET", "/kb/categories"),
])
async def test_charla_wire(monkeypatch, config, method, path):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == method
        assert request.url.scheme == "https" and request.url.host == "api.charla.com"
        assert request.url.path == "/v1" + path
        assert request.headers["X-Api-Key"] == KEY
        assert dict(request.url.params) == ({"cursor": str(config["cursor"])} if "cursor" in config else {})
        if method == "POST":
            sent = json.loads(request.content)
            assert "operation" not in sent and "api_key" not in sent
            if path == "/contacts":
                assert sent == {k: v for k, v in config.items() if k != "operation"}
            else:
                assert sent["id"] == 0 and sent["categories"] == [{"id": 1}]
                assert sent["title"] == config["title"] and sent["article"] == config["article"]
        if method == "DELETE":
            return httpx.Response(200)
        if config["operation"] in {"check_connection", "list_contacts", "list_conversations", "list_articles"}:
            return httpx.Response(200, json={"data": [], "paging": {"has_next": True, "next_cursor": config.get("cursor", 1757765348)}})
        if config["operation"] == "list_categories":
            return httpx.Response(200, json=[{"id": 1, "name": "General", "parent": {"id": 2}}])
        return httpx.Response(200, json=json.loads((FIXTURES / ("contact.json" if "contact" in config["operation"] else "article.json")).read_text()))
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(seen) == 1
    if "paging" in result:
        assert result["paging"]["next_cursor"] == config.get("cursor", 1757765348)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_charla_errors_redact_key(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, text="Rejected " + KEY))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_contacts"}).execute({})
    assert KEY not in str(error.value) and str(status) in str(error.value)


@pytest.mark.asyncio
async def test_charla_malformed_page(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"error": "bad"}))
    with pytest.raises(ValueError, match="page response"):
        await node({"operation": "list_contacts"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "id": "../bad"},
    {"operation": "delete_article", "id": 0},
    {"operation": "list_contacts", "cursor": -1},
    {"operation": "save_article", "title": "T", "article": "A", "categories": []},
])
def test_charla_reject_invalid_input(config):
    with pytest.raises(ValidationError):
        node(config)


def test_charla_manual_credential():
    assert CharlaAPIKeyCredential(api_key="  " + KEY + "  ").model_dump() == {
        "credential_type": "charla_api_key", "api_key": KEY}
    for key in ["https://charla.com/key", "<token>", "bad\nkey"]:
        with pytest.raises((ValueError, ValidationError)):
            CharlaAPIKeyCredential(api_key=key)

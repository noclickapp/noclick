"""Wire regressions for CustomGPT.ai; no provider account or real token is used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import customgpt_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-customgpt-token-42"
FIXTURES = Path(__file__).parent / "fixtures/customgpt"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="customgpt-test",
        node_type="automation-customgpt",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "customgpt_api_token",
                "api_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, payload=None, status=200):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            json=payload
            if payload is not None
            else {"status": "success", "data": {"id": 1, "name": "John Doe"}},
            headers={"Location": "https://example.test/steal"},
        )

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", json.loads((FIXTURES / "routes.json").read_text()))
async def test_each_operation_has_one_published_route(monkeypatch, case):
    requests = transport(monkeypatch)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert request.url.host == "app.customgpt.ai"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_multipart_fields_stream_query_and_json_chat(monkeypatch):
    requests = transport(monkeypatch)
    await node(
        {
            "operation": "send_message",
            "project_id": 1,
            "session_id": "session-1",
            "prompt": "What is our refund policy?",
            "lang": "es",
        }
    ).execute({})
    request = requests[0]
    assert request.url.params == httpx.QueryParams({"stream": "false", "lang": "es"})
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert (
        b'name="prompt"' in request.content
        and b"What is our refund policy?" in request.content
    )
    assert (
        b'name="stream"' not in request.content
        and b'name="lang"' not in request.content
    )
    await node(
        {
            "operation": "create_chat_completion",
            "project_id": 1,
            "messages": [{"role": "user", "content": "Hello"}],
        }
    ).execute({})
    assert json.loads(requests[1].content) == {
        "messages": [{"role": "user", "content": "Hello"}],
        "lang": "en",
        "stream": False,
    }


@pytest.mark.asyncio
async def test_pagination_preserved_no_foreign_url_followed(monkeypatch):
    body = {
        "status": "success",
        "data": {
            "data": [{"id": 1, "project_name": "My agent"}],
            "current_page": 2,
            "last_page": 3,
            "next_page_url": "https://example.test/steal",
        },
    }
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_agents", "page": 2}).execute({})
    assert result["next_page"] == 3 and result["data"] == body["data"]
    assert len(requests) == 1 and requests[0].url.params["page"] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
async def test_error_envelopes_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, {"status": "error", "message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_redirect_refused_and_reindex_is_only_acknowledged(monkeypatch):
    requests = transport(monkeypatch, status=302)
    with pytest.raises(ValueError, match="unexpected HTTP status"):
        await node({"operation": "get_current_user"}).execute({})
    assert len(requests) == 1
    transport(monkeypatch, {"status": "success", "data": {"updated": True}})
    result = await node(
        {"operation": "reindex_document", "project_id": 1, "page_id": 1}
    ).execute({})
    assert result["indexing_complete"] is False


def test_manual_credential_default_and_required_secret():
    assert (
        native.CustomgptAPITokenCredential(api_token=TOKEN).credential_type
        == "customgpt_api_token"
    )
    with pytest.raises(ValidationError):
        native.CustomgptAPITokenCredential()
    for value in ["Bearer " + TOKEN, "https://example.test/key"]:
        with pytest.raises(ValidationError):
            native.CustomgptAPITokenCredential(api_token=value)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_agent", "project_id": 0},
        {"operation": "list_agents", "page": 0},
        {"operation": "get_citation", "project_id": 1, "citation_id": "../user"},
        {"operation": "delete_conversation", "project_id": 1, "session_id": "../user"},
        {
            "operation": "add_source",
            "project_id": 1,
            "sitemap_path": "file:///etc/passwd",
        },
    ],
)
def test_invalid_routes_and_source_urls_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)

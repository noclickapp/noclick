"""Exact query mapping, provider JSON, credential and error handling for SearchApi."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import search_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-search-api-key-849203"
CASES = [
    ({"operation": "check_connection"}, {"q": "Google"}),
    (
        {"operation": "search_google", "q": "chatgpt", "page": 2},
        {"q": "chatgpt", "page": "2", "device": "desktop"},
    ),
    (
        {"operation": "search_recent", "q": "chatgpt", "time_period": "last_day"},
        {"q": "chatgpt", "time_period": "last_day"},
    ),
    (
        {
            "operation": "search_date_range",
            "q": "chatgpt",
            "time_period_min": "01/01/2024",
            "time_period_max": "12/31/2024",
        },
        {
            "q": "chatgpt",
            "time_period_min": "01/01/2024",
            "time_period_max": "12/31/2024",
        },
    ),
    (
        {"operation": "search_location", "q": "Per Se", "location": "New York"},
        {"q": "Per Se", "location": "New York"},
    ),
    (
        {
            "operation": "search_coordinates",
            "q": "coffee",
            "latitude": 0,
            "longitude": 0,
        },
        {"q": "coffee", "latitude": "0.0", "longitude": "0.0"},
    ),
    (
        {"operation": "search_country", "q": "chatgpt", "gl": "us", "cr": "countryUS"},
        {"q": "chatgpt", "gl": "us", "cr": "countryUS"},
    ),
    (
        {
            "operation": "search_language",
            "q": "chatgpt",
            "hl": "en",
            "lr": "lang_en|lang_de",
        },
        {"q": "chatgpt", "hl": "en", "lr": "lang_en|lang_de"},
    ),
    (
        {"operation": "search_mobile", "q": "chatgpt"},
        {"q": "chatgpt", "device": "mobile"},
    ),
    (
        {"operation": "search_verbatim", "q": "chatgpt"},
        {"q": "chatgpt", "verbatim": "true"},
    ),
    (
        {"operation": "search_knowledge_graph", "kgmid": "/m/02_286"},
        {"kgmid": "/m/02_286", "page": "1"},
    ),
]
DEFAULTS = {
    "page": "1",
    "safe": "blur",
    "link": "raw",
    "optimization_strategy": "performance",
    "nfpr": "0",
    "filter": "1",
}


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="search-api-test",
        node_type="automation-search-api",
        node_data={
            "config": config,
            "credentials": credential
            or {"credential_type": "search_api_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []
    real_client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["google_search.json", "google_answer_box.json"])
@pytest.mark.parametrize(
    "config,expected", CASES, ids=[c[0]["operation"] for c in CASES]
)
async def test_search_api_exact_contract_requests_and_documented_response(
    monkeypatch, config, expected, fixture
):
    body = json.loads(
        (Path(__file__).parent / "fixtures/search-api" / fixture).read_text()
    )["body"]
    requests = transport(monkeypatch, body)
    output = await node(config).execute({})
    assert output == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and str(request.url).startswith(
        native.BASE_URL + "?"
    )
    defaults = (
        {}
        if config["operation"] in {"check_connection", "search_knowledge_graph"}
        else DEFAULTS
    )
    assert dict(request.url.params) == {
        **defaults,
        **expected,
        "engine": "google",
        "api_key": TOKEN,
    }
    assert request.content == b""
    assert TOKEN not in str(output)


@pytest.mark.parametrize(
    "config",
    [
        {
            "operation": "search_date_range",
            "q": "x",
            "time_period_min": "02/30/2024",
            "time_period_max": "12/31/2024",
        },
        {
            "operation": "search_date_range",
            "q": "x",
            "time_period_min": "12/31/2024",
            "time_period_max": "01/01/2024",
        },
        {"operation": "search_coordinates", "q": "x", "latitude": 91, "longitude": 0},
        {"operation": "search_coordinates", "q": "x", "latitude": 0},
        {
            "operation": "search_coordinates",
            "q": "x",
            "latitude": 0,
            "longitude": 0,
            "location": "New York",
        },
        {"operation": "search_google", "q": "x", "page": 0},
        {"operation": "search_google", "q": "x", "engine": "bing"},
        {"operation": "search_google", "q": "x", "url": "https://example.com"},
        {"operation": "search_verbatim", "q": "x", "time_period": "last_day"},
        {"operation": "search_country", "q": "x", "gl": "bogus"},
        {"operation": "search_language", "q": "x", "hl": "en", "lr": "invalid"},
    ],
)
def test_search_api_rejects_invalid_or_conflicting_inputs(config):
    with pytest.raises(ValidationError):
        native.SearchApiFullConfig.model_validate({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,message",
    [
        (401, {"error": "Invalid API key."}, "Invalid API key."),
        (429, {"error": "Too many requests"}, "Too many requests"),
        (200, {"error": "Request failed: " + TOKEN}, "Request failed: [redacted]"),
        (500, {}, "HTTP 500"),
        (302, b"<html>redirect</html>", "non-JSON"),
        (200, [], "unexpected response shape"),
    ],
)
async def test_search_api_honest_redacted_failures(monkeypatch, status, body, message):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "check_connection"}).execute({})
    assert message in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_search_api_transport_errors_hide_secret_query(monkeypatch):
    transport(monkeypatch, httpx.ConnectError(native.BASE_URL + "?api_key=" + TOKEN))
    with pytest.raises(ValueError, match="could not complete") as exc:
        await node({"operation": "check_connection"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_search_api_empty_results_and_key_echo(monkeypatch):
    transport(
        monkeypatch,
        {
            "organic_results": [],
            "search_parameters": {"api_key": TOKEN},
            "nested": ["key=" + TOKEN],
        },
    )
    output = await node({"operation": "check_connection"}).execute({})
    assert output["data"]["organic_results"] == [] and TOKEN not in str(output)
    assert output["data"]["search_parameters"] == {}


def test_search_api_manual_credential_default_and_evidence():
    credential = native.SearchApiAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "search_api_api_key"
    assert native.SearchApiNode.connection_evidence.proves == "reachability"
    for value in ["https://example.com/key", "Bearer token", "<token>"]:
        with pytest.raises(ValidationError):
            native.SearchApiAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_search_api_documented_no_results_is_not_a_rejected_key(monkeypatch):
    body = {
        "error": "Google didn't return any results.",
        "dmca_messages": {"title": "Notices about Filtered Results", "messages": []},
    }
    transport(monkeypatch, body)
    assert await node({"operation": "search_google", "q": "empty"}).execute({}) == {
        "status": "success",
        "data": body,
    }

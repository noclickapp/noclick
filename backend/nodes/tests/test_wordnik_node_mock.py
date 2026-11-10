"""Wordnik native factory and wire-contract tests; all credentials are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wordnik_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-wordnik-api-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="wordnik-test", node_type="automation-wordnik",
        node_data={"config": config, "credentials": credentials or {"api_key": KEY}})


def mock_api(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Expected routes and JSON boundaries come from the pinned Wordnik v4 contract.
CASES = [
    ("get_definitions", {"word": "cat"}, "/word.json/cat/definitions", [{"word": "cat", "text": "A feline"}]),
    ("get_examples", {"word": "cat"}, "/word.json/cat/examples", {"examples": [{"text": "The cat sleeps."}]}),
    ("get_related_words", {"word": "cat"}, "/word.json/cat/relatedWords", [{"relationshipType": "synonym", "words": ["feline"]}]),
    ("get_word_of_the_day", {}, "/words.json/wordOfTheDay", {"word": "cat", "publishDate": "2026-11-10T00:00:00Z"}),
    ("search_words", {"query": "cat"}, "/words.json/search/cat", {"searchResults": [{"word": "cat"}]}),
    ("reverse_dictionary", {"query": "feline"}, "/words.json/reverseDictionary", {"results": [{"word": "cat"}]}),
    ("get_random_word", {}, "/words.json/randomWord", {"word": "cat", "id": 1}),
    ("get_random_words", {}, "/words.json/randomWords", [{"word": "cat", "id": 1}]),
    ("get_text_pronunciations", {"word": "cat"}, "/word.json/cat/pronunciations", [{"raw": "kat"}]),
    ("get_audio", {"word": "cat"}, "/word.json/cat/audio", [{"fileUrl": "https://audio.example/cat.mp3"}]),
    ("get_etymologies", {"word": "cat"}, "/word.json/cat/etymologies", ["From Latin cattus"]),
    ("get_hyphenation", {"word": "cat"}, "/word.json/cat/hyphenation", [{"seq": 0, "text": "cat"}]),
    ("get_word_frequency", {"word": "cat"}, "/word.json/cat/frequency", {"word": "cat", "frequency": [{"year": 2012, "count": 12}]}),
    ("get_phrases", {"word": "cat"}, "/word.json/cat/phrases", [{"gram1": "cat", "gram2": "food"}]),
    ("get_top_example", {"word": "cat"}, "/word.json/cat/topExample", {"text": "The cat sleeps."}),
    ("get_scrabble_score", {"word": "cat"}, "/word.json/cat/scrabbleScore", 5),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,body", CASES)
async def test_each_native_operation_makes_one_authenticated_read(monkeypatch, operation, config, path, body):
    requests = mock_api(monkeypatch, body)
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "operation": operation, "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.wordnik.com"
    assert request.url.path == "/v4" + path
    assert request.url.params["api_key"] == KEY
    assert "authorization" not in request.headers and KEY not in str(result)


@pytest.mark.asyncio
async def test_documented_random_word_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/wordnik/random_word.json").read_text())
    mock_api(monkeypatch, fixture["body"])
    assert (await node({"operation": "get_random_word"}).execute({}))["data"] == {"id": 121108, "word": "kafta"}


@pytest.mark.asyncio
async def test_dictionary_array_wire_names_and_canonical_flag(monkeypatch):
    requests = mock_api(monkeypatch, [])
    await node({"operation": "get_definitions", "word": "cats", "source_dictionaries": ["century", "wiktionary"],
        "use_canonical": "true", "include_tags": "true", "part_of_speech": "noun", "limit": 3}).execute({})
    assert dict(requests[0].url.params) == {"api_key": KEY, "limit": "3", "partOfSpeech": "noun",
        "includeRelated": "false", "sourceDictionaries": "century,wiktionary", "useCanonical": "true", "includeTags": "true"}


@pytest.mark.asyncio
async def test_query_and_path_escaping_and_one_page_only(monkeypatch):
    requests = mock_api(monkeypatch, {"searchResults": []})
    await node({"operation": "search_words", "query": "café/a?b#c", "skip": 20, "limit": 10,
        "allow_regex": "true", "case_sensitive": "false"}).execute({})
    assert requests[0].url.raw_path.split(b"?")[0] == b"/v4/words.json/search/caf%C3%A9%2Fa%3Fb%23c"
    assert requests[0].url.params["skip"] == "20"
    assert requests[0].url.params["allowRegex"] == "true"
    assert requests[0].url.params["caseSensitive"] == "false"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_reverse_query_and_frequency_filters(monkeypatch):
    requests = mock_api(monkeypatch, {"results": []})
    await node({"operation": "reverse_dictionary", "query": "a + b & c", "skip": "20", "sort_by": "count", "sort_order": "desc"}).execute({})
    assert requests[0].url.params["query"] == "a + b & c" and requests[0].url.params["skip"] == "20"
    requests = mock_api(monkeypatch, {"frequency": []})
    await node({"operation": "get_word_frequency", "word": "cat", "start_year": 1900, "end_year": 2000}).execute({})
    assert requests[0].url.params["startYear"] == "1900" and requests[0].url.params["endYear"] == "2000"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_are_not_success_and_key_is_redacted(monkeypatch, status):
    requests = mock_api(monkeypatch, {"message": "Rejected " + KEY}, status)
    result = await node({"operation": "get_word_of_the_day"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"
    assert len(requests) == 1 and KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("get_random_word", []), ("get_audio", {}), ("get_scrabble_score", True)])
async def test_wrong_json_boundary_is_refused(monkeypatch, operation, body):
    mock_api(monkeypatch, body)
    with pytest.raises(ValueError, match="unexpected response shape"):
        await node({"operation": operation, **({"word": "cat"} if operation != "get_random_word" else {})}).execute({})


def test_manual_credential_default_schema_discovery_and_evidence():
    credential = native.WordnikAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "wordnik_api_key"
    assert "automation-wordnik" in NODE_REGISTRY
    assert native.WordnikNode.connection_evidence.proves == "reachability"
    assert native.WordnikNode.connection_evidence.operation == "get_word_of_the_day"
    assert len(native.ROUTES) == 16


@pytest.mark.parametrize("key", ["", "https://example.com/key", "<token>", "contains spaces"])
def test_invalid_key_fails_before_request(key):
    with pytest.raises((ValidationError, ValueError)):
        native.WordnikAPIKeyCredential(api_key=key)

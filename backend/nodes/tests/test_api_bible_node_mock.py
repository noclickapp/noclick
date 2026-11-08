"""Offline API.Bible request, credential and response regressions.

Response fixtures are synthetic JSON shaped like provider responses. No API key
or live provider account is used; provider-contract validation runs separately.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import api_bible_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-api-bible-key"
BIBLE = "de4e12af7f28f599-01"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/api-bible/responses.json").read_text())

CASES = [
    ("list_bibles", {}, "/bibles"),
    ("get_bible", {"bible_id": BIBLE}, f"/bibles/{BIBLE}"),
    ("list_books", {"bible_id": BIBLE}, f"/bibles/{BIBLE}/books"),
    ("get_book", {"bible_id": BIBLE, "book_id": "GEN"}, f"/bibles/{BIBLE}/books/GEN"),
    ("list_chapters", {"bible_id": BIBLE, "book_id": "GEN"}, f"/bibles/{BIBLE}/books/GEN/chapters"),
    ("get_chapter", {"bible_id": BIBLE, "chapter_id": "GEN.1"}, f"/bibles/{BIBLE}/chapters/GEN.1"),
    ("get_passage", {"bible_id": BIBLE, "passage_id": "GEN.1.1-GEN.2.1"}, f"/bibles/{BIBLE}/passages/GEN.1.1-GEN.2.1"),
    ("list_book_sections", {"bible_id": BIBLE, "book_id": "GEN"}, f"/bibles/{BIBLE}/books/GEN/sections"),
    ("list_chapter_sections", {"bible_id": BIBLE, "chapter_id": "GEN.1"}, f"/bibles/{BIBLE}/chapters/GEN.1/sections"),
    ("get_section", {"bible_id": BIBLE, "section_id": "GEN.S1"}, f"/bibles/{BIBLE}/sections/GEN.S1"),
    ("list_verses", {"bible_id": BIBLE, "chapter_id": "GEN.1"}, f"/bibles/{BIBLE}/chapters/GEN.1/verses"),
    ("get_verse", {"bible_id": BIBLE, "verse_id": "GEN.1.1"}, f"/bibles/{BIBLE}/verses/GEN.1.1"),
    ("search_bible", {"bible_id": BIBLE, "query": "love"}, f"/bibles/{BIBLE}/search"),
    ("list_audio_bibles", {}, "/audio-bibles"),
    ("get_audio_bible", {"bible_id": "audio-id"}, "/audio-bibles/audio-id"),
    ("list_audio_books", {"bible_id": "audio-id"}, "/audio-bibles/audio-id/books"),
    ("get_audio_book", {"bible_id": "audio-id", "book_id": "GEN"}, "/audio-bibles/audio-id/books/GEN"),
    ("list_audio_chapters", {"bible_id": "audio-id", "book_id": "GEN"}, "/audio-bibles/audio-id/books/GEN/chapters"),
    ("get_audio_chapter", {"bible_id": "audio-id", "chapter_id": "GEN.1"}, "/audio-bibles/audio-id/chapters/GEN.1"),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="api-bible-test", node_type="automation-api-bible", node_data={
        "config": {"operation": operation, **config},
        "credentials": {"credential_type": "api_bible_api_key", "api_key": KEY},
    })


def transport(monkeypatch, body, status=200, content_type="application/json"):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Content-Type": content_type, "Location": "https://example.test/redirect"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path", CASES, ids=["api-bible:" + c[0] for c in CASES])
async def test_every_operation_uses_one_documented_get(monkeypatch, operation, config, path):
    payload = {"data": [] if operation.startswith("list_") else {"id": "fixture"}, "meta": {"fumsId": "fixture"}}
    requests = transport(monkeypatch, payload)
    result = await node(operation, **config).execute({})
    assert result == {**payload, "status": "success", "operation": operation}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "rest.api.bible"
    assert request.url.path == "/v1" + path
    assert request.headers["api-key"] == KEY and request.headers["Accept"] == "application/json"
    assert not request.content and KEY not in str(request.url) and KEY not in str(result)


@pytest.mark.asyncio
async def test_filters_bool_and_related_text_bible_use_exact_wire_names(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["bibles"])
    await node("list_audio_bibles", language="eng", abbreviation="KJV", name="King James Version", ids=BIBLE,
        related_bible_id=BIBLE, include_full_details=True).execute({})
    assert dict(requests[0].url.params) == {"language": "eng", "abbreviation": "KJV", "name": "King James Version",
        "ids": BIBLE, "bibleId": BIBLE, "include-full-details": "true"}


@pytest.mark.asyncio
async def test_content_flags_and_copyright_fums_preserved(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["passage"])
    result = await node("get_passage", bible_id=BIBLE, passage_id="JHN.3.16-JHN.3.17", content_type="json",
        include_notes=True, include_titles=False, include_chapter_numbers=True, include_verse_numbers=False,
        include_verse_spans=True, parallels=BIBLE, use_org_id=True).execute({})
    assert dict(requests[0].url.params) == {"content-type": "json", "include-notes": "true", "include-titles": "false",
        "include-chapter-numbers": "true", "include-verse-numbers": "false", "include-verse-spans": "true", "parallels": BIBLE, "use-org-id": "true"}
    assert result["data"] == FIXTURES["passage"]["data"] and result["meta"] == FIXTURES["passage"]["meta"]


@pytest.mark.asyncio
async def test_search_pagination_wildcards_and_range(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["search"])
    result = await node("search_bible", bible_id=BIBLE, query="l?ve,wo*d", limit=10, offset=10, sort="canonical",
        range="GEN.1.1-EXO.1.1", fuzziness="2").execute({})
    assert dict(requests[0].url.params) == {"query": "l?ve,wo*d", "limit": "10", "offset": "10", "sort": "canonical", "range": "GEN.1.1-EXO.1.1", "fuzziness": "2"}
    assert result["data"] == FIXTURES["search"]["data"] and len(requests) == 1


@pytest.mark.asyncio
async def test_audio_metadata_is_returned_without_downloading(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["audio"])
    result = await node("get_audio_chapter", bible_id="fixture-audio", chapter_id="GEN.1").execute({})
    assert result["data"] == FIXTURES["audio"]["data"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 301, 302, 401, 403, 404, 429, 500])
async def test_rejections_redirects_and_errors_do_not_succeed(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + KEY}, status)
    result = await node("list_bibles").execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": None}, {"data": {}}, {"error": "denied", "data": []}])
async def test_malformed_list_responses_are_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node("list_bibles").execute({})


@pytest.mark.asyncio
async def test_empty_account_list_is_a_valid_read(monkeypatch):
    transport(monkeypatch, {"data": []})
    assert (await node("list_bibles").execute({}))["data"] == []


@pytest.mark.parametrize("config", [
    {"operation": "get_verse", "verse_id": "GEN.1.1"},
    {"operation": "get_verse", "bible_id": BIBLE},
    {"operation": "get_bible", "bible_id": "../other"},
    {"operation": "get_bible", "bible_id": "GEN?api-key=other"},
    {"operation": "search_bible", "bible_id": BIBLE, "query": "love", "offset": -1},
    {"operation": "search_bible", "bible_id": BIBLE, "query": "love", "limit": 0},
    {"operation": "create_bible"},
])
def test_required_fields_and_invalid_requests_fail_before_network(config):
    with pytest.raises(ValueError):
        native.ApiBibleNode.parse_config({"config": config})


def test_registration_and_manual_credential_schema():
    assert NODE_REGISTRY["automation-api-bible"] is native.ApiBibleNode
    assert native.ApiBibleNode.connection_evidence.operation == "list_bibles"
    schema = native.ApiBibleApiKeyCredential.model_json_schema()
    assert schema["title"] == "API.Bible API Key"
    assert schema["properties"]["api_key"]["ui:widget"] == "password"
    with pytest.raises(ValidationError) as exc:
        native.ApiBibleApiKeyCredential(api_key="secret\nvalue")
    assert "secret\nvalue" not in str(exc.value)

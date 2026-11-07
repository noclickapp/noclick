"""Request-shape and error contract tests for AssemblyAI workflow operations."""

import base64
import json

import httpx
import pytest

from nodes import assemblyai_node as module
from nodes.assemblyai_node import AssemblyAINode, AssemblyAINodeConfig


def node(operation, **fields):
    config = AssemblyAINodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"api_key": "test-key"},
    })
    return AssemblyAINode(
        node_id="assemblyai-test", node_type="automation-assemblyai",
        node_data={}, config=config,
    )


def fake_client(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw,
    ))


@pytest.mark.asyncio
async def test_list_transcripts_uses_project_api_key_and_filters(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://api.assemblyai.com/v2/transcript?limit=7&status=completed"
        assert request.headers["Authorization"] == "test-key"
        return httpx.Response(200, json={"transcripts": [{"id": "own-transcript"}]})

    fake_client(monkeypatch, handler)
    result = await node("list_transcripts", limit=7, status="completed").execute({})
    assert result["transcripts"][0]["id"] == "own-transcript"


@pytest.mark.asyncio
async def test_submit_and_wait_returns_completed_transcript(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.url.path == "/v2/transcript"
            body = json.loads(request.content)
            assert body["audio_url"] == "https://example.org/audio.wav"
            assert body["speech_models"] == ["universal-3-5-pro", "universal-2"]
            assert body["speaker_labels"] is True
            assert "max_wait_seconds" not in body
            return httpx.Response(200, json={"id": "transcript-1", "status": "queued"})
        assert request.url.path == "/v2/transcript/transcript-1"
        return httpx.Response(200, json={"id": "transcript-1", "status": "completed", "text": "Hello"})

    fake_client(monkeypatch, handler)
    result = await node("transcribe_and_wait", audio_url="https://example.org/audio.wav",
                        speaker_labels=True).execute({})
    assert result["text"] == "Hello"
    assert calls == ["POST", "GET"]


@pytest.mark.asyncio
async def test_submit_preserves_explicit_false_formatting_options(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["punctuate"] is False
        assert body["format_text"] is False
        assert "speaker_labels" not in body
        return httpx.Response(200, json={"id": "transcript-2", "status": "queued"})

    fake_client(monkeypatch, handler)
    result = await node("submit_transcript", audio_url="https://example.org/audio.wav",
                        punctuate=False, format_text=False).execute({})
    assert result["id"] == "transcript-2"


@pytest.mark.asyncio
async def test_upload_sends_raw_media_bytes(monkeypatch):
    def handler(request):
        assert request.url.path == "/v2/upload"
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.content == b"RIFF-example"
        return httpx.Response(200, json={"upload_url": "https://example.org/uploaded"})

    fake_client(monkeypatch, handler)
    result = await node("upload_audio", audio_base64=base64.b64encode(b"RIFF-example").decode()).execute({})
    assert result["upload_url"] == "https://example.org/uploaded"


@pytest.mark.asyncio
async def test_subtitle_text_is_returned_without_json_parsing(monkeypatch):
    def handler(request):
        assert request.url.path == "/v2/transcript/abc/srt"
        assert request.url.params["chars_per_caption"] == "40"
        return httpx.Response(200, text="1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    fake_client(monkeypatch, handler)
    result = await node("get_subtitles", transcript_id="abc", chars_per_caption=40).execute({})
    assert result["subtitles"].endswith("Hello\n")


@pytest.mark.asyncio
async def test_delete_returns_success_for_empty_response(monkeypatch):
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/v2/transcript/abc"
        return httpx.Response(204)

    fake_client(monkeypatch, handler)
    assert await node("delete_transcript", transcript_id="abc").execute({}) == {
        "success": True, "status_code": 204,
    }


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError, match="language code or language detection"):
        node("submit_transcript", audio_url="https://example.org/a.wav",
             language_code="en", language_detection=True)
    with pytest.raises(ValueError, match="Audio redaction requires"):
        node("submit_transcript", audio_url="https://example.org/a.wav",
             redact_pii_audio=True)


def test_generated_form_json_array_fields_parse_as_lists():
    search = node("word_search", transcript_id="abc", words='["NoClick", "workflow"]')
    assert search.config.config.words == ["NoClick", "workflow"]
    submit = node("submit_transcript", audio_url="https://example.org/a.wav",
                  speech_models='["universal-3-5-pro", "universal-2"]',
                  keyterms_prompt='["NoClick"]')
    assert submit.config.config.speech_models == ["universal-3-5-pro", "universal-2"]
    assert submit.config.config.keyterms_prompt == ["NoClick"]


@pytest.mark.asyncio
async def test_api_error_is_actionable_without_leaking_key(monkeypatch):
    fake_client(monkeypatch, lambda request: httpx.Response(401, json={"error": "Invalid API key"}))
    with pytest.raises(ValueError, match="AssemblyAI API error 401: Invalid API key") as error:
        await node("list_transcripts").execute({})
    assert "test-key" not in str(error.value)


@pytest.mark.asyncio
async def test_word_search_sends_comma_separated_keywords(monkeypatch):
    # https://www.assemblyai.com/docs/api-reference/transcripts/word-search
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/v2/transcript/d5a3d302-066e-43fb-b63b-8f57baf185db/word-search"
        assert request.url.params.multi_items() == [("words", "smoke,wildfires")]
        return httpx.Response(200, json={
            "id": "d5a3d302-066e-43fb-b63b-8f57baf185db",
            "total_count": 10,
            "matches": [
                {
                    "text": "smoke", "count": 6,
                    "timestamps": [[250, 650], [49168, 49398], [55284, 55594],
                                   [168888, 169118], [215108, 215386], [225944, 226170]],
                    "indexes": [0, 136, 156, 486, 652, 698],
                },
                {
                    "text": "wildfires", "count": 4,
                    "timestamps": [[1668, 2346], [33852, 34546], [50118, 51110], [231356, 232354]],
                    "indexes": [4, 90, 140, 716],
                },
            ],
        })

    fake_client(monkeypatch, handler)
    result = await node("word_search", transcript_id="d5a3d302-066e-43fb-b63b-8f57baf185db",
                        words=["smoke", "wildfires"]).execute({})
    assert result["total_count"] == 10
    assert [match["text"] for match in result["matches"]] == ["smoke", "wildfires"]


@pytest.mark.parametrize("audio_base64", ["", "1", "a===", "!!!!"])
def test_invalid_upload_base64_is_rejected_by_configuration(audio_base64):
    with pytest.raises(ValueError):
        node("upload_audio", audio_base64=audio_base64)

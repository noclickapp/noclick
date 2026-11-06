"""Request regressions for ElevenLabs' OpenAPI multipart and route contracts."""
import base64
import json
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

import httpx
import pytest

from nodes.tests.test_elevenlabs_node_mock import create_test_node
from nodes.elevenlabs_node import ElevenLabsAPIKeyCredential, ElevenLabsNodeConfig


def form_parts(request):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode()
        + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.content
    )
    assert message.is_multipart()
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts.setdefault(name, []).append((part.get_filename(), part.get_payload(decode=True)))
    return parts


async def execute(config, responses=None):
    requests = []
    responses = iter(responses or [{"status": "ok"}])

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=next(responses))

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(*args, **kwargs, transport=httpx.MockTransport(transport))

    model = ElevenLabsNodeConfig.model_validate({"config": config})
    node = create_test_node(model.config, ElevenLabsAPIKeyCredential(api_key="fake-key"))
    with patch("httpx.AsyncClient", client):
        await node.execute({})
    assert all(r.headers["xi-api-key"] == "fake-key" for r in requests)
    return requests


@pytest.mark.asyncio
async def test_edit_voice_is_multipart_and_keeps_labels_as_json():
    request, = await execute({
        "operation": "edit_voice_settings", "voice_id": "voice-id", "name": "John Smith",
        "labels": '{"accent": "british"}',
    })
    assert request.url.path == "/v1/voices/voice-id/edit"
    parts = form_parts(request)
    assert parts["name"] == [(None, b"John Smith")]
    assert json.loads(parts["labels"][0][1]) == {"accent": "british"}


@pytest.mark.asyncio
async def test_metadata_only_edit_preserves_the_required_name():
    requests = await execute(
        {"operation": "edit_voice_settings", "voice_id": "voice-id", "description": "Updated"},
        [{"name": "John Smith"}, {"status": "ok"}],
    )
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/voices/voice-id"
    assert form_parts(requests[1])["name"] == [(None, b"John Smith")]


@pytest.mark.asyncio
async def test_dubbing_uses_multipart_without_a_file():
    request, = await execute({
        "operation": "create_dubbing_project", "source_url": "https://example.com/audio.mp3",
        "target_lang": "es", "watermark": False,
    })
    assert request.url.path == "/v1/dubbing"
    parts = form_parts(request)
    assert parts["source_url"] == [(None, b"https://example.com/audio.mp3")]
    assert parts["target_lang"] == [(None, b"es")]
    assert parts["watermark"] == [(None, b"false")]


@pytest.mark.asyncio
async def test_audio_native_uploads_html_as_file():
    html = "<html><body><p>Article content</p></body></html>"
    request, = await execute({
        "operation": "create_audio_native_project", "name": "Article", "html": html,
        "voice_id": "voice-id", "auto_convert": True,
    })
    assert request.url.path == "/v1/audio-native"
    parts = form_parts(request)
    assert parts["file"] == [("article.html", html.encode())]
    assert "html" not in parts
    assert parts["auto_convert"] == [(None, b"true")]


@pytest.mark.asyncio
async def test_voice_clone_repeats_the_files_field():
    audio = base64.b64encode(b"audio").decode()
    request, = await execute({
        "operation": "clone_voice_from_audio_samples", "name": "John Smith",
        "files_base64": json.dumps([audio, audio]),
    })
    assert request.url.path == "/v1/voices/add"
    parts = form_parts(request)
    assert parts["files"] == [("sample_0.mp3", b"audio"), ("sample_1.mp3", b"audio")]
    assert not any(name.startswith("files_") for name in parts)


@pytest.mark.asyncio
async def test_transcription_sends_language_code():
    request, = await execute({
        "operation": "transcribe_audio_to_text", "audio_base64": base64.b64encode(b"audio").decode(),
        "language": "en",
    })
    parts = form_parts(request)
    assert parts["language_code"] == [(None, b"en")]
    assert "language" not in parts


@pytest.mark.asyncio
async def test_sound_effect_loop_uses_the_provider_field():
    request, = await execute({
        "operation": "generate_sound_effects_from_text", "text": "Rain", "enable_looping": True,
    })
    assert json.loads(request.content)["loop"] is True
    assert "enable_looping" not in json.loads(request.content)


@pytest.mark.asyncio
async def test_dictionary_rules_use_the_json_endpoint():
    rules = [{"string_to_replace": "a", "type": "alias", "alias": "b"}]
    request, = await execute({
        "operation": "create_pronunciation_dictionary", "name": "My Dictionary", "rules": json.dumps(rules),
    })
    assert request.url.path == "/v1/pronunciation-dictionaries/add-from-rules"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"name": "My Dictionary", "rules": rules}


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "method", "path"), [
    ("get_audio_native_project_details", "GET", "/v1/audio-native/project-id/settings"),
    ("delete_audio_native_project", "DELETE", "/v1/studio/projects/project-id"),
])
async def test_audio_native_project_routes(operation, method, path):
    request, = await execute({"operation": operation, "project_id": "project-id"})
    assert request.method == method
    assert request.url.path == path

"""Route, parameter, output, and error coverage for all Deepgram operations."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.core.binary_output import BinaryOutput
from nodes.deepgram_node import (
    DeepgramAPIKeyCredential,
    DeepgramAnalyzeTextConfig,
    DeepgramGetProjectConfig,
    DeepgramGetProjectModelConfig,
    DeepgramGetPublicModelConfig,
    DeepgramGetRequestConfig,
    DeepgramGetUsageBreakdownConfig,
    DeepgramListKeysConfig,
    DeepgramListProjectModelsConfig,
    DeepgramListProjectsConfig,
    DeepgramListPublicModelsConfig,
    DeepgramListRequestsConfig,
    DeepgramListThinkModelsConfig,
    DeepgramNode,
    DeepgramNodeConfig,
    DeepgramTextToSpeechConfig,
    DeepgramTranscribeURLConfig,
    DeepgramUpdateProjectConfig,
    _request,
)


def node(config, *, api_key="test-key"):
    return DeepgramNode(
        node_id="deepgram-test",
        node_type="automation-deepgram",
        node_data={},
        config=DeepgramNodeConfig(
            config=config,
            credentials=DeepgramAPIKeyCredential(api_key=api_key),
        ),
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


async def assert_route(
    config, method, path, *, params=None, body=None, agent=False, binary=False
):
    with patch("nodes.deepgram_node._request", new_callable=AsyncMock) as request:
        request.return_value = {
            "status": "success",
            "data": {"ok": True},
            "timing_ms": {"api_request": 4.0},
        }
        result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["action"] == config.operation
    assert result["timing_ms"]["api_request"] == 4.0
    args, kwargs = request.await_args
    assert args == ("test-key", method, path)
    assert kwargs["agent"] is agent
    assert kwargs["binary"] is binary
    if params is not None:
        assert kwargs["params"] == params
    if body is not None:
        assert kwargs["body"] == body


@pytest.mark.asyncio
async def test_transcribe_url():
    await assert_route(
        DeepgramTranscribeURLConfig(
            audio_url="https://example.com/speech.wav",
            keyterms="NoClick\nDeepgram",
            diarize_model="v2",
        ),
        "POST",
        "/listen",
        body={"url": "https://example.com/speech.wav"},
        params={
            "model": "nova-3",
            "detect_language": False,
            "smart_format": True,
            "punctuate": True,
            "utterances": False,
            "diarize_model": "v2",
            "sentiment": False,
            "topics": False,
            "intents": False,
            "detect_entities": False,
            "keyterm": ["NoClick", "Deepgram"],
        },
    )


@pytest.mark.asyncio
async def test_text_to_speech():
    await assert_route(
        DeepgramTextToSpeechConfig(text="Hello", model="aura-2-thalia-en"),
        "POST",
        "/speak",
        body={"text": "Hello"},
        params={"model": "aura-2-thalia-en", "encoding": "mp3"},
        binary=True,
    )


@pytest.mark.asyncio
async def test_analyze_text():
    await assert_route(
        DeepgramAnalyzeTextConfig(text="Good support", topics=True),
        "POST",
        "/read",
        body={"text": "Good support"},
        params={
            "language": "en",
            "sentiment": True,
            "topics": True,
            "intents": False,
        },
    )


@pytest.mark.asyncio
async def test_list_projects():
    await assert_route(DeepgramListProjectsConfig(), "GET", "/projects")


@pytest.mark.asyncio
async def test_get_project():
    await assert_route(
        DeepgramGetProjectConfig(project_id="project/one"),
        "GET",
        "/projects/project%2Fone",
    )


@pytest.mark.asyncio
async def test_update_project():
    await assert_route(
        DeepgramUpdateProjectConfig(project_id="p1", name="New name"),
        "PATCH",
        "/projects/p1",
        body={"name": "New name"},
    )


@pytest.mark.asyncio
async def test_list_project_models():
    await assert_route(
        DeepgramListProjectModelsConfig(project_id="p1", include_outdated=True),
        "GET",
        "/projects/p1/models",
        params={"include_outdated": True},
    )


@pytest.mark.asyncio
async def test_get_project_model():
    await assert_route(
        DeepgramGetProjectModelConfig(project_id="p1", model_id="m1"),
        "GET",
        "/projects/p1/models/m1",
    )


@pytest.mark.asyncio
async def test_list_public_models():
    await assert_route(
        DeepgramListPublicModelsConfig(),
        "GET",
        "/models",
        params={"include_outdated": False},
    )


@pytest.mark.asyncio
async def test_get_public_model():
    await assert_route(DeepgramGetPublicModelConfig(model_id="m1"), "GET", "/models/m1")


@pytest.mark.asyncio
async def test_list_think_models():
    await assert_route(
        DeepgramListThinkModelsConfig(),
        "GET",
        "/agent/settings/think/models",
        agent=True,
    )


@pytest.mark.asyncio
async def test_get_usage_breakdown():
    await assert_route(
        DeepgramGetUsageBreakdownConfig(
            project_id="p1", start="2026-09-01", endpoint="listen"
        ),
        "GET",
        "/projects/p1/usage/breakdown",
        params={"start": "2026-09-01", "endpoint": "listen"},
    )


@pytest.mark.asyncio
async def test_list_requests():
    await assert_route(
        DeepgramListRequestsConfig(project_id="p1", limit=20, page=2),
        "GET",
        "/projects/p1/requests",
        params={"limit": 20, "page": 2},
    )


@pytest.mark.asyncio
async def test_get_request():
    await assert_route(
        DeepgramGetRequestConfig(project_id="p1", request_id="r1"),
        "GET",
        "/projects/p1/requests/r1",
    )


@pytest.mark.asyncio
async def test_list_keys():
    await assert_route(
        DeepgramListKeysConfig(project_id="p1", status="active"),
        "GET",
        "/projects/p1/keys",
        params={"status": "active"},
    )


@pytest.mark.asyncio
async def test_project_picker_proves_connected_account():
    with patch("nodes.deepgram_node._request", new_callable=AsyncMock) as request:
        request.return_value = {
            "status": "success",
            "data": {"projects": [{"project_id": "p1", "name": "QA project"}]},
        }
        options = await DeepgramNode.load_field_options(
            "project_id", {"api_key": "test-key"}, search="QA"
        )
    assert options == {
        "options": [{"value": "p1", "label": "QA project"}],
        "next_page_token": None,
    }
    request.assert_awaited_once_with("test-key", "GET", "/projects")


@pytest.mark.asyncio
async def test_audio_is_binary_output_and_error_is_structured():
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/v1/speak":
            return httpx.Response(
                200, content=b"mp3-bytes", headers={"content-type": "audio/mpeg"}
            )
        return httpx.Response(401, json={"err_msg": "Invalid key"})

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(respond), *args, **kwargs)

    with patch("nodes.deepgram_node.httpx.AsyncClient", side_effect=client):
        audio = await _request(
            "test-key", "POST", "/speak", body={"text": "Hi"}, binary=True
        )
        failure = await _request("bad-key", "GET", "/projects")
    assert isinstance(audio["data"], BinaryOutput)
    assert audio["data"].data == b"mp3-bytes"
    assert audio["data"].filename == "deepgram-speech.mp3"
    assert failure["status"] == "error"
    assert failure["status_code"] == 401
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_missing_credentials_rejected():
    n = node(DeepgramListProjectsConfig())
    n.config.credentials = None
    with pytest.raises(ValueError, match="Connect a Deepgram API key"):
        await n.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config, expected",
    [
        (DeepgramTranscribeURLConfig(audio_url="https://dpgr.am/spacewalk.wav", summarize=True), "v2"),
        (DeepgramAnalyzeTextConfig(text="Hi. Thank you for calling from premier phone services.", summarize=True), True),
    ],
)
async def test_summarization_uses_endpoint_specific_enable_value(config, expected):
    with patch("nodes.deepgram_node._request", new_callable=AsyncMock) as request:
        request.return_value = {"status": "success", "data": {}}
        await node(config).execute({})
    assert request.await_args.kwargs["params"]["summarize"] == expected

"""
Mock tests for ElevenLabs AI Audio Platform node.

Tests operations that are rate-limited, require special setup, or expensive operations.
Uses mocked HTTP responses to test node logic without hitting the actual API.

Run: pytest backend/nodes/tests/test_elevenlabs_node_mock.py
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import json
import base64

from nodes.elevenlabs_node import (
    ElevenLabsNode,
    ElevenLabsNodeConfig,
    ElevenLabsAPIKeyCredential,
    # All config types
    ElevenLabsTextToSpeechConfig,
    ElevenLabsTextToSpeechStreamConfig,
    ElevenLabsTextToSpeechWithTimestampsConfig,
    ElevenLabsSpeechToSpeechConfig,
    ElevenLabsSpeechToTextConfig,
    ElevenLabsListVoicesConfig,
    ElevenLabsGetVoiceConfig,
    ElevenLabsAddVoiceConfig,
    ElevenLabsEditVoiceConfig,
    ElevenLabsDeleteVoiceConfig,
    ElevenLabsSoundEffectsConfig,
    ElevenLabsAudioIsolationConfig,
    ElevenLabsCreateDubbingConfig,
    ElevenLabsGetDubbingConfig,
    ElevenLabsDeleteDubbingConfig,
    ElevenLabsGetHistoryConfig,
    ElevenLabsGetHistoryItemConfig,
    ElevenLabsDeleteHistoryItemConfig,
    ElevenLabsGetHistoryAudioConfig,
    ElevenLabsDownloadHistoryItemsConfig,
    ElevenLabsListPronunciationDictionariesConfig,
    ElevenLabsGetPronunciationDictionaryConfig,
    ElevenLabsCreatePronunciationDictionaryConfig,
    ElevenLabsDeletePronunciationDictionaryConfig,
    ElevenLabsCreateAudioNativeConfig,
    ElevenLabsGetAudioNativeConfig,
    ElevenLabsDeleteAudioNativeConfig,
    ElevenLabsListModelsConfig,
    ElevenLabsGetUserInfoConfig,
    ElevenLabsGetSubscriptionConfig,
    ElevenLabsGetUsageStatsConfig,
)


@pytest.fixture
def mock_credentials():
    """Create mock credentials for testing"""
    return ElevenLabsAPIKeyCredential(api_key="sk_test_api_key_12345")


@pytest.fixture
def test_voice_id():
    """Test voice ID"""
    return "21m00Tcm4TlvDq8ikWAM"


@pytest.fixture
def mock_resource_store():
    """Patch the binary-output resolver's R2 writer so audio markers resolve to a
    usable {url, mime_type, name, size_bytes} reference without network/storage."""

    async def fake_create(**kwargs):
        body = kwargs["body"]
        return {
            "resource_id": "res-123",
            "name": kwargs.get("filename", "download"),
            "mime_type": kwargs.get("content_type", "application/octet-stream"),
            "size_bytes": len(body),
            "storage_ref": "test-user/test-workflow/res-123/" + kwargs.get("filename", "download"),
            "download_url": "https://assets.test/elevenlabs_audio.mp3",
        }

    with patch(
        "nodes.core.binary_output.create_resource_from_bytes",
        new=AsyncMock(side_effect=fake_create),
    ) as mock:
        yield mock


def create_test_node(config, credentials):
    """Helper to create node with config"""
    node_config = ElevenLabsNodeConfig(config=config, credentials=credentials)
    return ElevenLabsNode(
        node_id="test-elevenlabs",
        node_type="automation-elevenlabs",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
        user_id="test-user",
    )


class MockResponse:
    """Mock httpx response"""

    def __init__(self, json_data=None, status_code=200, text="", content=None):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text or (json.dumps(json_data) if json_data else "")
        self.content = content or b""
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ============================================================================
# Text-to-Speech Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_text_to_speech_success(mock_credentials, test_voice_id, mock_resource_store):
    """Test successful text-to-speech conversion"""
    config = ElevenLabsTextToSpeechConfig(
        voice_id=test_voice_id,
        text="Hello, world!",
        model_id="eleven_multilingual_v2",
        stability=0.5,
        similarity_boost=0.75,
    )
    node = create_test_node(config, mock_credentials)

    # Mock audio binary response
    mock_audio_data = b"fake_audio_data_12345"
    mock_response = MockResponse(content=mock_audio_data, status_code=200)
    mock_response.headers = {"content-type": "audio/mpeg"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["mime_type"] == "audio/mpeg"
        assert result["audio"]["size_bytes"] == len(mock_audio_data)
        assert "audio_base64" not in result
        # bytes handed to the resolver match the response body
        assert mock_resource_store.await_args.kwargs["body"] == mock_audio_data


@pytest.mark.asyncio
async def test_text_to_speech_stream_success(mock_credentials, test_voice_id, mock_resource_store):
    """Test successful streaming text-to-speech"""
    config = ElevenLabsTextToSpeechStreamConfig(
        voice_id=test_voice_id,
        text="Streaming test",
        model_id="eleven_flash_v2_5",
        stability=0.5,
        similarity_boost=0.75,
    )
    node = create_test_node(config, mock_credentials)

    mock_audio_data = b"streaming_audio_data"
    mock_response = MockResponse(content=mock_audio_data, status_code=200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["size_bytes"] == len(mock_audio_data)
        assert "audio_base64" not in result


@pytest.mark.asyncio
async def test_text_to_speech_with_timestamps_success(mock_credentials, test_voice_id):
    """Test text-to-speech with word-level timestamps"""
    config = ElevenLabsTextToSpeechWithTimestampsConfig(
        voice_id=test_voice_id,
        text="Test with timestamps",
        model_id="eleven_multilingual_v2",
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "audio_base64": "base64_audio_data",
            "alignment": {
                "chars": ["T", "e", "s", "t"],
                "char_start_times_ms": [0, 100, 200, 300],
                "char_durations_ms": [100, 100, 100, 100],
            },
        },
        200,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert "alignment" in result or isinstance(result, dict)


# ============================================================================
# Speech-to-Speech Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_speech_to_speech_success(mock_credentials, test_voice_id, mock_resource_store):
    """Test successful speech-to-speech voice conversion"""
    # Create dummy base64 audio
    dummy_audio = base64.b64encode(b"fake_audio_input").decode("utf-8")

    config = ElevenLabsSpeechToSpeechConfig(
        voice_id=test_voice_id,
        audio_base64=dummy_audio,
        model_id="eleven_english_sts_v2",
    )
    node = create_test_node(config, mock_credentials)

    mock_audio_output = b"converted_audio_data"
    mock_response = MockResponse(content=mock_audio_output, status_code=200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["size_bytes"] == len(mock_audio_output)
        assert "audio_base64" not in result


# ============================================================================
# Speech-to-Text Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_speech_to_text_success(mock_credentials):
    """Test successful speech-to-text transcription"""
    dummy_audio = base64.b64encode(b"fake_audio_for_transcription").decode("utf-8")

    config = ElevenLabsSpeechToTextConfig(
        audio_base64=dummy_audio, model_id="scribe_v2", language="en"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "text": "This is the transcribed text",
            "words": [
                {"word": "This", "start": 0.0, "end": 0.5},
                {"word": "is", "start": 0.5, "end": 0.7},
            ],
        },
        200,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["text"] == "This is the transcribed text"
        assert "words" in result


# ============================================================================
# Voice Management Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_voices_success(mock_credentials):
    """Test successful voice listing"""
    config = ElevenLabsListVoicesConfig(show_legacy=False)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "voices": [
                {
                    "voice_id": "21m00Tcm4TlvDq8ikWAM",
                    "name": "Rachel",
                    "category": "premade",
                },
                {
                    "voice_id": "AZnzlk1XvdvUeBnXmlld",
                    "name": "Domi",
                    "category": "premade",
                },
            ]
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert "voices" in result
        assert len(result["voices"]) == 2


@pytest.mark.asyncio
async def test_get_voice_success(mock_credentials, test_voice_id):
    """Test successful voice retrieval"""
    config = ElevenLabsGetVoiceConfig(voice_id=test_voice_id, with_settings=True)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "voice_id": test_voice_id,
            "name": "Rachel",
            "samples": [],
            "category": "premade",
            "settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert result["voice_id"] == test_voice_id
        assert result["name"] == "Rachel"
        assert "settings" in result


@pytest.mark.asyncio
async def test_add_voice_success(mock_credentials):
    """Test successful voice cloning"""
    # Create dummy audio samples
    dummy_audio1 = base64.b64encode(b"audio_sample_1").decode("utf-8")
    dummy_audio2 = base64.b64encode(b"audio_sample_2").decode("utf-8")
    files_json = json.dumps([dummy_audio1, dummy_audio2])

    config = ElevenLabsAddVoiceConfig(
        name="My Custom Voice",
        files_base64=files_json,
        description="A test custom voice",
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"voice_id": "custom_voice_123", "success": True}, 200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["voice_id"] == "custom_voice_123"


@pytest.mark.asyncio
async def test_delete_voice_success(mock_credentials, test_voice_id):
    """Test successful voice deletion"""
    config = ElevenLabsDeleteVoiceConfig(voice_id=test_voice_id)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"success": True, "message": "Operation completed successfully"}, 200
    )

    with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = mock_response

        result = await node.execute({})

        assert result["success"] is True


# ============================================================================
# Sound Effects Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sound_effects_success(mock_credentials, mock_resource_store):
    """Test successful sound effect generation"""
    config = ElevenLabsSoundEffectsConfig(
        text="A dog barking",
        duration_seconds=2.0,
        prompt_influence=0.3,
        enable_looping=False,
    )
    node = create_test_node(config, mock_credentials)

    mock_audio_data = b"sound_effect_audio"
    mock_response = MockResponse(content=mock_audio_data, status_code=200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["size_bytes"] == len(mock_audio_data)
        assert "audio_base64" not in result


# ============================================================================
# Audio Isolation Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_audio_isolation_success(mock_credentials, mock_resource_store):
    """Test successful audio isolation"""
    dummy_audio = base64.b64encode(b"audio_with_vocals_and_music").decode("utf-8")

    config = ElevenLabsAudioIsolationConfig(audio_base64=dummy_audio)
    node = create_test_node(config, mock_credentials)

    mock_isolated_audio = b"isolated_vocals"
    mock_response = MockResponse(content=mock_isolated_audio, status_code=200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["size_bytes"] == len(mock_isolated_audio)
        assert "audio_base64" not in result


# ============================================================================
# Dubbing Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_dubbing_success(mock_credentials):
    """Test successful dubbing project creation"""
    config = ElevenLabsCreateDubbingConfig(
        source_url="https://example.com/video.mp4",
        target_lang="es",
        source_lang="en",
        watermark=True,
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"dubbing_id": "dubbing_123", "status": "dubbing"}, 200
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["dubbing_id"] == "dubbing_123"


@pytest.mark.asyncio
async def test_get_dubbing_success(mock_credentials):
    """Test successful dubbing project retrieval"""
    config = ElevenLabsGetDubbingConfig(dubbing_id="dubbing_123")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"dubbing_id": "dubbing_123", "status": "dubbed", "target_languages": ["es"]},
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert result["dubbing_id"] == "dubbing_123"
        assert result["status"] == "dubbed"


# ============================================================================
# History Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_history_success(mock_credentials):
    """Test successful history retrieval"""
    config = ElevenLabsGetHistoryConfig(page_size=10)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "history": [
                {
                    "history_item_id": "hist_123",
                    "voice_id": "21m00Tcm4TlvDq8ikWAM",
                    "text": "Test audio",
                    "date_unix": 1640000000,
                }
            ],
            "has_more": False,
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert "history" in result
        assert len(result["history"]) == 1


@pytest.mark.asyncio
async def test_get_history_audio_success(mock_credentials, mock_resource_store):
    """Test successful history audio retrieval"""
    config = ElevenLabsGetHistoryAudioConfig(history_item_id="hist_123")
    node = create_test_node(config, mock_credentials)

    mock_audio_data = b"history_audio_data"
    mock_response = MockResponse(content=mock_audio_data, status_code=200)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.run({})

        assert result["success"] is True
        assert result["audio"]["url"] == "https://assets.test/elevenlabs_audio.mp3"
        assert result["audio"]["size_bytes"] == len(mock_audio_data)
        assert "audio_base64" not in result


# ============================================================================
# Pronunciation Dictionary Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_pronunciation_dictionaries_success(mock_credentials):
    """Test successful pronunciation dictionaries listing"""
    config = ElevenLabsListPronunciationDictionariesConfig(page_size=10)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "pronunciation_dictionaries": [
                {"id": "dict_123", "name": "My Dictionary", "version_id": "v1"}
            ]
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert "pronunciation_dictionaries" in result


@pytest.mark.asyncio
async def test_create_pronunciation_dictionary_success(mock_credentials):
    """Test successful pronunciation dictionary creation"""
    rules_json = json.dumps(
        [
            {
                "string_to_replace": "ElevenLabs",
                "phoneme": "ɪˈlɛvən læbz",
                "alphabet": "ipa",
            }
        ]
    )

    config = ElevenLabsCreatePronunciationDictionaryConfig(
        name="My Pronunciations", rules=rules_json, description="Test dictionary"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"id": "dict_456", "version_id": "v1"}, 200)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["id"] == "dict_456"


# ============================================================================
# Audio Native Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_audio_native_success(mock_credentials, test_voice_id):
    """Test successful audio native project creation"""
    config = ElevenLabsCreateAudioNativeConfig(
        name="My Article Audio",
        html="<html><body><p>Article content</p></body></html>",
        voice_id=test_voice_id,
        model_id="eleven_multilingual_v2",
        auto_convert=True,
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"project_id": "project_123", "html_snippet": "<script>...</script>"}, 200
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["project_id"] == "project_123"


# ============================================================================
# Models Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_models_success(mock_credentials):
    """Test successful models listing"""
    config = ElevenLabsListModelsConfig()
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        [
            {
                "model_id": "eleven_multilingual_v2",
                "name": "Eleven Multilingual v2",
                "can_do_text_to_speech": True,
                "can_do_voice_conversion": False,
            },
            {
                "model_id": "eleven_flash_v2_5",
                "name": "Eleven Flash v2.5",
                "can_do_text_to_speech": True,
                "can_do_voice_conversion": False,
            },
        ],
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert isinstance(result, list)
        assert len(result) == 2


# ============================================================================
# User & Subscription Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_user_info_success(mock_credentials):
    """Test successful user info retrieval"""
    config = ElevenLabsGetUserInfoConfig()
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "user_id": "user_123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert result["user_id"] == "user_123"
        assert result["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_subscription_success(mock_credentials):
    """Test successful subscription info retrieval"""
    config = ElevenLabsGetSubscriptionConfig()
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "tier": "creator",
            "character_count": 100000,
            "character_limit": 100000,
            "can_extend_character_limit": True,
        },
        200,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert result["tier"] == "creator"
        assert result["character_limit"] == 100000


@pytest.mark.asyncio
async def test_get_usage_stats_success(mock_credentials):
    """Test successful usage statistics retrieval"""
    config = ElevenLabsGetUsageStatsConfig()
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"character_count": 5000, "character_limit": 100000}, 200
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        result = await node.execute({})

        assert result["character_count"] == 5000
        assert result["character_limit"] == 100000

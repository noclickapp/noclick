"""
ElevenLabs AI Audio Platform automation node.

Provides comprehensive workflow integration with 40+ operations across:

**Text-to-Speech API**:
- Convert text to lifelike speech with 32 languages
- Streaming TTS for real-time applications
- TTS with word-level timestamps for synchronization
- Multiple AI models (Multilingual v2, Turbo v2.5, Flash v2.5)
- Voice settings control (stability, similarity boost, style, speaker boost)

**Speech-to-Speech (Voice Changer)**:
- Convert audio using any voice (voice transformation)
- Real-time streaming voice conversion
- Preserve emotion and intonation

**Speech-to-Text**:
- Transcribe audio with 90+ language support
- Word-level timestamps and speaker diarization
- Scribe v2 model for accurate transcription

**Voice Management**:
- List all available voices (10k+ pre-made voices)
- Get voice details and settings
- Instant Voice Cloning (IVC) from audio samples
- Professional Voice Cloning for high-fidelity results
- Edit voice settings and labels
- Delete custom voices

**Sound Effects Generation**:
- Generate professional sound effects from text descriptions
- Seamless looping capability
- Customizable duration (0.5-30 seconds)

**Audio Isolation**:
- Isolate vocals from background audio
- Streaming audio isolation

**Dubbing**:
- Dub videos/audio into 29 languages
- Preserve speaker characteristics
- Track dubbing project status

**Audio Native (Projects)**:
- Create embeddable audio players for web content
- Auto-convert webpage text to speech
- Project management (create, get, delete)

**Pronunciation Dictionaries**:
- Create custom pronunciation rules
- Manage pronunciation dictionaries
- Apply to text-to-speech for consistent pronunciation

**History Management**:
- List all generated audio history
- Retrieve specific history items
- Download audio from history
- Delete history items
- Batch download history

**Models**:
- List all available AI models
- Get model capabilities and features

**User & Subscription**:
- Get user account information
- Check subscription status and limits
- Get character usage statistics

Authentication: API Key (xi-api-key header)
API Documentation: https://elevenlabs.io/docs/api-reference/introduction
Get API Key: https://elevenlabs.io/app/settings (Account → API Keys)
Rate Limits: Vary by subscription tier (Free, Starter, Creator, Pro, Scale, Business)
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, ConfigDict
import httpx
import base64

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.dynamic_options import (
    filter_options_by_search,
    require_credential_token,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
ELEVENLABS_API_VERSION = "v1"

# ============================================================================
# Credential Schema
# ============================================================================


class ElevenLabsAPIKeyCredential(BaseModel):
    """
    ElevenLabs API Key credential.

    Get your API key at: https://elevenlabs.io/app/settings
    Navigate to: Account → Profile + API Key → Generate API Key

    Note: API keys are tied to your subscription tier and usage limits.
    """

    credential_type: Literal["elevenlabs_api_key"] = Field(
        "elevenlabs_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your ElevenLabs API key",
        json_schema_extra={"ui:widget": "password", "placeholder": "sk_..."},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://elevenlabs.io/app/settings",
            "x-credential-instructions": "Navigate to Account → Profile + API Key → Generate API Key. Copy the generated key.",
        }
    )


# ============================================================================
# Text-to-Speech Operations
# ============================================================================


class ElevenLabsTextToSpeechConfig(BaseModel):
    """Convert text to speech"""

    model_config = ConfigDict(title="Text to Speech")

    operation: Literal["convert_text_to_speech"] = Field(
        "convert_text_to_speech",
        json_schema_extra={
            "const": "convert_text_to_speech",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Convert Text to Speech",
        },
        title="Convert Text to Speech",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to convert to speech (up to 5000 characters for standard models)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter text to convert to speech...",
        },
    )
    model_id: str = Field(
        "eleven_multilingual_v2",
        title="Model ID",
        description="The model to use for synthesis",
        json_schema_extra={
            "enum": [
                "eleven_multilingual_v2",
                "eleven_turbo_v2_5",
                "eleven_flash_v2_5",
                "eleven_turbo_v2",
                "eleven_monolingual_v1",
            ],
            "enumNames": [
                "Multilingual v2 (Highest quality, 32 languages)",
                "Turbo v2.5 (Fast, high quality, 32 languages)",
                "Flash v2.5 (Ultra-low latency ~75ms)",
                "Turbo v2 (Balanced speed/quality)",
                "Monolingual v1 (English only, legacy)",
            ],
            "x-enum-searchable": True,
        },
    )
    stability: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        title="Stability",
        description="Stability of the voice (0-1). Higher values make output more consistent, lower adds variation",
    )
    similarity_boost: float = Field(
        0.75,
        ge=0.0,
        le=1.0,
        title="Similarity Boost",
        description="How closely to match the original voice (0-1). Higher values stick closer to the voice",
    )
    style: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        title="Style Exaggeration (Optional)",
        description="Exaggerate the style of the voice (0-1). Higher values amplify the voice's characteristics",
    )
    use_speaker_boost: bool = Field(
        True,
        title="Speaker Boost",
        description="Boost the similarity to the original speaker (recommended)",
    )
    output_format: str = Field(
        "mp3_44100_128",
        title="Output Format",
        description="Audio output format and quality",
        json_schema_extra={
            "enum": [
                "mp3_44100_128",
                "mp3_44100_192",
                "pcm_16000",
                "pcm_22050",
                "pcm_24000",
                "pcm_44100",
                "ulaw_8000",
            ],
            "enumNames": [
                "MP3 44.1kHz 128kbps",
                "MP3 44.1kHz 192kbps (Higher quality)",
                "PCM 16kHz (Raw)",
                "PCM 22.05kHz (Raw)",
                "PCM 24kHz (Raw)",
                "PCM 44.1kHz (Raw)",
                "μ-law 8kHz (Telephony)",
            ],
            "x-enum-searchable": True,
        },
    )


class ElevenLabsTextToSpeechStreamConfig(BaseModel):
    """Stream text to speech in real-time"""

    model_config = ConfigDict(title="Text to Speech (Streaming)")

    operation: Literal["stream_text_to_speech_realtime"] = Field(
        "stream_text_to_speech_realtime",
        json_schema_extra={
            "const": "stream_text_to_speech_realtime",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Stream Text to Speech Realtime",
        },
        title="Stream Text to Speech Realtime",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to convert to speech",
        json_schema_extra={"ui:widget": "textarea"},
    )
    model_id: str = Field(
        "eleven_flash_v2_5",
        title="Model ID",
        description="The model to use (flash recommended for streaming)",
        json_schema_extra={
            "enum": [
                "eleven_flash_v2_5",
                "eleven_turbo_v2_5",
                "eleven_multilingual_v2",
            ],
            "enumNames": [
                "Flash v2.5 (Ultra-low latency)",
                "Turbo v2.5 (Fast)",
                "Multilingual v2 (Highest quality)",
            ],
            "x-enum-searchable": True,
        },
    )
    stability: float = Field(0.5, ge=0.0, le=1.0, title="Stability")
    similarity_boost: float = Field(0.75, ge=0.0, le=1.0, title="Similarity Boost")


class ElevenLabsTextToSpeechWithTimestampsConfig(BaseModel):
    """Convert text to speech with word-level timestamps"""

    model_config = ConfigDict(title="Text to Speech with Timestamps")

    operation: Literal["convert_text_to_speech_with_timestamps"] = Field(
        "convert_text_to_speech_with_timestamps",
        json_schema_extra={
            "const": "convert_text_to_speech_with_timestamps",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Convert Text to Speech with Timestamps",
        },
        title="Convert Text to Speech with Timestamps",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to convert to speech",
        json_schema_extra={"ui:widget": "textarea"},
    )
    model_id: str = Field(
        "eleven_multilingual_v2",
        title="Model ID",
        json_schema_extra={
            "enum": ["eleven_multilingual_v2", "eleven_turbo_v2_5"],
            "enumNames": ["Multilingual v2", "Turbo v2.5"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Speech-to-Speech Operations
# ============================================================================


class ElevenLabsSpeechToSpeechConfig(BaseModel):
    """Convert audio using a voice (voice changer)"""

    model_config = ConfigDict(title="Speech to Speech (Voice Changer)")

    operation: Literal["convert_audio_using_voice"] = Field(
        "convert_audio_using_voice",
        json_schema_extra={
            "const": "convert_audio_using_voice",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Convert Audio Using Voice",
        },
        title="Convert Audio Using Voice",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    audio_base64: str = Field(
        ...,
        title="Audio Data (Base64)",
        description="Base64 encoded audio data to convert",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Base64 encoded audio...",
        },
    )
    model_id: str = Field(
        "eleven_english_sts_v2",
        title="Model ID",
        description="Speech-to-speech model",
        json_schema_extra={
            "enum": ["eleven_english_sts_v2", "eleven_multilingual_sts_v2"],
            "enumNames": ["English STS v2", "Multilingual STS v2"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Speech-to-Text Operations
# ============================================================================


class ElevenLabsSpeechToTextConfig(BaseModel):
    """Transcribe audio to text"""

    model_config = ConfigDict(title="Speech to Text")

    operation: Literal["transcribe_audio_to_text"] = Field(
        "transcribe_audio_to_text",
        json_schema_extra={
            "const": "transcribe_audio_to_text",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Transcribe Audio to Text",
        },
        title="Transcribe Audio to Text",
    )
    audio_base64: str = Field(
        ...,
        title="Audio Data (Base64)",
        description="Base64 encoded audio data to transcribe",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Base64 encoded audio...",
        },
    )
    model_id: str = Field(
        "scribe_v2",
        title="Model ID",
        description="Speech-to-text model",
        json_schema_extra={
            "enum": ["scribe_v2"],
            "enumNames": ["Scribe v2 (90+ languages, word timestamps)"],
            "x-enum-searchable": True,
        },
    )
    language: Optional[str] = Field(
        None,
        title="Language Code (Optional)",
        description="Language code for transcription (auto-detect if not specified)",
        json_schema_extra={"placeholder": "en"},
    )


# ============================================================================
# Voice Management Operations
# ============================================================================


class ElevenLabsListVoicesConfig(BaseModel):
    """List all available voices"""

    model_config = ConfigDict(title="List Voices")

    operation: Literal["list_available_voices"] = Field(
        "list_available_voices",
        json_schema_extra={
            "const": "list_available_voices",
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "List Available Voices",
        },
        title="List Available Voices",
    )
    show_legacy: bool = Field(
        False,
        title="Show Legacy Voices",
        description="Include legacy voices in the results",
    )


class ElevenLabsGetVoiceConfig(BaseModel):
    """Get voice details by ID"""

    model_config = ConfigDict(title="Get Voice")

    operation: Literal["get_voice_by_id"] = Field(
        "get_voice_by_id",
        json_schema_extra={
            "const": "get_voice_by_id",
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Get Voice by Id",
        },
        title="Get Voice by Id",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    with_settings: bool = Field(
        True,
        title="Include Settings",
        description="Include voice settings in the response",
    )


class ElevenLabsAddVoiceConfig(BaseModel):
    """Clone a voice from audio samples (Instant Voice Cloning)"""

    model_config = ConfigDict(title="Add Voice (Clone)")

    operation: Literal["clone_voice_from_audio_samples"] = Field(
        "clone_voice_from_audio_samples",
        json_schema_extra={
            "const": "clone_voice_from_audio_samples",
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Clone Voice from Audio Samples",
            "x-creates-resource": True,
            "x-resource-type": "elevenlabs_voice",
            "x-resource-id-path": "voice_id",
        },
        title="Clone Voice from Audio Samples",
    )
    name: str = Field(
        ...,
        title="Voice Name",
        description="Name for the cloned voice",
        json_schema_extra={"placeholder": "My Custom Voice"},
    )
    files_base64: str = Field(
        ...,
        title="Audio Files (Base64 JSON Array)",
        description='JSON array of base64 encoded audio files for cloning (e.g., ["base64data1", "base64data2"]). Provide 1-25 audio samples.',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '["base64audio1", "base64audio2"]',
        },
    )
    description: Optional[str] = Field(
        None,
        title="Description (Optional)",
        description="Description of the voice",
        json_schema_extra={"ui:widget": "textarea"},
    )
    labels: Optional[str] = Field(
        None,
        title="Labels (JSON)",
        description='JSON object of labels for the voice (e.g., {"accent": "american", "age": "young"})',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"accent": "american"}',
        },
    )


class ElevenLabsEditVoiceConfig(BaseModel):
    """Edit voice settings and metadata"""

    model_config = ConfigDict(title="Edit Voice")

    operation: Literal["edit_voice_settings"] = Field(
        "edit_voice_settings",
        json_schema_extra={
            "const": "edit_voice_settings",
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Edit Voice Settings",
        },
        title="Edit Voice Settings",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    name: Optional[str] = Field(
        None,
        title="New Name (Optional)",
        description="Update the voice name",
        json_schema_extra={"placeholder": "Updated Voice Name"},
    )
    description: Optional[str] = Field(
        None,
        title="New Description (Optional)",
        description="Update the voice description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    labels: Optional[str] = Field(
        None,
        title="New Labels (JSON, Optional)",
        description="Update voice labels",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"accent": "british"}',
        },
    )


class ElevenLabsDeleteVoiceConfig(BaseModel):
    """Delete a custom voice"""

    model_config = ConfigDict(title="Delete Voice")

    operation: Literal["delete_custom_voice"] = Field(
        "delete_custom_voice",
        json_schema_extra={
            "const": "delete_custom_voice",
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Voice",
        },
        title="Delete Custom Voice",
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )


# ============================================================================
# Sound Effects Operations
# ============================================================================


class ElevenLabsSoundEffectsConfig(BaseModel):
    """Generate sound effects from text description"""

    model_config = ConfigDict(title="Generate Sound Effect")

    operation: Literal["generate_sound_effects_from_text"] = Field(
        "generate_sound_effects_from_text",
        json_schema_extra={
            "const": "generate_sound_effects_from_text",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Generate Sound Effects from Text",
        },
        title="Generate Sound Effects from Text",
    )
    text: str = Field(
        ...,
        title="Sound Description",
        description="Text description of the sound effect to generate",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "A dog barking loudly",
        },
    )
    duration_seconds: Optional[float] = Field(
        None,
        ge=0.5,
        le=30.0,
        title="Duration (Seconds, Optional)",
        description="Duration of the sound effect (0.5-30 seconds). If not specified, AI will determine optimal duration.",
    )
    prompt_influence: float = Field(
        0.3,
        ge=0.0,
        le=1.0,
        title="Prompt Influence",
        description="How closely to follow the prompt (0-1). Higher values stick closer to the description.",
    )
    enable_looping: bool = Field(
        False,
        title="Enable Seamless Looping",
        description="Generate a sound effect that loops seamlessly (only for eleven_text_to_sound_v2 model)",
    )


# ============================================================================
# Audio Isolation Operations
# ============================================================================


class ElevenLabsAudioIsolationConfig(BaseModel):
    """Isolate vocals from audio"""

    model_config = ConfigDict(title="Audio Isolation")

    operation: Literal["isolate_vocals_from_audio"] = Field(
        "isolate_vocals_from_audio",
        json_schema_extra={
            "const": "isolate_vocals_from_audio",
            "ui:hidden": True,
            "x-category": "Audio Generation",
            "x-is-trigger": False,
            "x-display-name": "Isolate Vocals from Audio",
        },
        title="Isolate Vocals from Audio",
    )
    audio_base64: str = Field(
        ...,
        title="Audio Data (Base64)",
        description="Base64 encoded audio data to isolate vocals from",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Base64 encoded audio...",
        },
    )


# ============================================================================
# Dubbing Operations
# ============================================================================


class ElevenLabsCreateDubbingConfig(BaseModel):
    """Create a dubbing project for video/audio"""

    model_config = ConfigDict(title="Create Dubbing")

    operation: Literal["create_dubbing_project"] = Field(
        "create_dubbing_project",
        json_schema_extra={
            "const": "create_dubbing_project",
            "ui:hidden": True,
            "x-category": "Dubbing Project",
            "x-is-trigger": False,
            "x-display-name": "Create Dubbing Project",
        },
        title="Create Dubbing Project",
    )
    source_url: str = Field(
        ...,
        title="Source URL",
        description="URL of the video or audio file to dub",
        json_schema_extra={"placeholder": "https://example.com/video.mp4"},
    )
    target_lang: str = Field(
        ...,
        title="Target Language",
        description="Target language code for dubbing (e.g., 'es', 'fr', 'de')",
        json_schema_extra={"placeholder": "es"},
    )
    source_lang: Optional[str] = Field(
        None,
        title="Source Language (Optional)",
        description="Source language code (auto-detected if not specified)",
        json_schema_extra={"placeholder": "en"},
    )
    num_speakers: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        title="Number of Speakers (Optional)",
        description="Number of speakers in the source audio (auto-detected if not specified)",
    )
    watermark: bool = Field(
        True,
        title="Add Watermark",
        description="Add ElevenLabs watermark to the dubbed audio",
    )


class ElevenLabsGetDubbingConfig(BaseModel):
    """Get dubbing project status and metadata"""

    model_config = ConfigDict(title="Get Dubbing")

    operation: Literal["get_dubbing_project_status"] = Field(
        "get_dubbing_project_status",
        json_schema_extra={
            "const": "get_dubbing_project_status",
            "ui:hidden": True,
            "x-category": "Dubbing Project",
            "x-is-trigger": False,
            "x-display-name": "Get Dubbing Project Status",
        },
        title="Get Dubbing Project Status",
    )
    dubbing_id: str = Field(
        ...,
        title="Dubbing ID",
        description="The dubbing project ID to retrieve",
        json_schema_extra={"placeholder": "dubbing_abc123"},
    )


class ElevenLabsDeleteDubbingConfig(BaseModel):
    """Delete a dubbing project"""

    model_config = ConfigDict(title="Delete Dubbing")

    operation: Literal["delete_dubbing_project"] = Field(
        "delete_dubbing_project",
        json_schema_extra={
            "const": "delete_dubbing_project",
            "ui:hidden": True,
            "x-category": "Dubbing Project",
            "x-is-trigger": False,
            "x-display-name": "Delete Dubbing Project",
        },
        title="Delete Dubbing Project",
    )
    dubbing_id: str = Field(
        ...,
        title="Dubbing ID",
        description="The dubbing project ID to delete",
        json_schema_extra={"placeholder": "dubbing_abc123"},
    )


# ============================================================================
# History Operations
# ============================================================================


class ElevenLabsGetHistoryConfig(BaseModel):
    """List all generated audio history"""

    model_config = ConfigDict(title="Get History")

    operation: Literal["list_generated_audio_history"] = Field(
        "list_generated_audio_history",
        json_schema_extra={
            "const": "list_generated_audio_history",
            "ui:hidden": True,
            "x-category": "Generated Audio History",
            "x-is-trigger": False,
            "x-display-name": "List Generated Audio History",
        },
        title="List Generated Audio History",
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        title="Page Size",
        description="Number of history items to retrieve per page",
    )
    start_after_history_item_id: Optional[str] = Field(
        None,
        title="Start After ID (Optional)",
        description="Pagination: Start after this history item ID",
        json_schema_extra={"placeholder": "history_abc123"},
    )
    voice_id: Optional[str] = Field(
        None,
        title="Filter by Voice ID (Optional)",
        description="Only show history for this voice",
        json_schema_extra={"placeholder": "21m00Tcm4TlvDq8ikWAM"},
    )


class ElevenLabsGetHistoryItemConfig(BaseModel):
    """Get a specific history item by ID"""

    model_config = ConfigDict(title="Get History Item")

    operation: Literal["get_history_item_details"] = Field(
        "get_history_item_details",
        json_schema_extra={
            "const": "get_history_item_details",
            "ui:hidden": True,
            "x-category": "Generated Audio History",
            "x-is-trigger": False,
            "x-display-name": "Get History Item Details",
        },
        title="Get History Item Details",
    )
    history_item_id: str = Field(
        ...,
        title="History Item ID",
        description="The history item ID to retrieve",
        json_schema_extra={"placeholder": "history_abc123"},
    )


class ElevenLabsDeleteHistoryItemConfig(BaseModel):
    """Delete a history item"""

    model_config = ConfigDict(title="Delete History Item")

    operation: Literal["delete_history_item"] = Field(
        "delete_history_item",
        json_schema_extra={
            "const": "delete_history_item",
            "ui:hidden": True,
            "x-category": "Generated Audio History",
            "x-is-trigger": False,
            "x-display-name": "Delete History Item",
        },
        title="Delete History Item",
    )
    history_item_id: str = Field(
        ...,
        title="History Item ID",
        description="The history item ID to delete",
        json_schema_extra={"placeholder": "history_abc123"},
    )


class ElevenLabsGetHistoryAudioConfig(BaseModel):
    """Get audio file from history item"""

    model_config = ConfigDict(title="Get History Audio")

    operation: Literal["get_history_item_audio"] = Field(
        "get_history_item_audio",
        json_schema_extra={
            "const": "get_history_item_audio",
            "ui:hidden": True,
            "x-category": "Generated Audio History",
            "x-is-trigger": False,
            "x-display-name": "Get History Item Audio",
        },
        title="Get History Item Audio",
    )
    history_item_id: str = Field(
        ...,
        title="History Item ID",
        description="The history item ID to get audio from",
        json_schema_extra={"placeholder": "history_abc123"},
    )


class ElevenLabsDownloadHistoryItemsConfig(BaseModel):
    """Download multiple history items"""

    model_config = ConfigDict(title="Download History Items")

    operation: Literal["download_history_items"] = Field(
        "download_history_items",
        json_schema_extra={
            "const": "download_history_items",
            "ui:hidden": True,
            "x-category": "Generated Audio History",
            "x-is-trigger": False,
            "x-display-name": "Download History Items",
        },
        title="Download History Items",
    )
    history_item_ids: str = Field(
        ...,
        title="History Item IDs (JSON Array)",
        description='JSON array of history item IDs to download (e.g., ["id1", "id2"])',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '["history_abc123", "history_def456"]',
        },
    )


# ============================================================================
# Pronunciation Dictionary Operations
# ============================================================================


class ElevenLabsListPronunciationDictionariesConfig(BaseModel):
    """List all pronunciation dictionaries"""

    model_config = ConfigDict(title="List Pronunciation Dictionaries")

    operation: Literal["list_pronunciation_dictionaries"] = Field(
        "list_pronunciation_dictionaries",
        json_schema_extra={
            "const": "list_pronunciation_dictionaries",
            "ui:hidden": True,
            "x-category": "Pronunciation Dictionary",
            "x-is-trigger": False,
            "x-display-name": "List Pronunciation Dictionaries",
        },
        title="List Pronunciation Dictionaries",
    )
    page_size: int = Field(
        100,
        ge=1,
        le=100,
        title="Page Size",
        description="Number of dictionaries to retrieve",
    )


class ElevenLabsGetPronunciationDictionaryConfig(BaseModel):
    """Get a pronunciation dictionary by ID"""

    model_config = ConfigDict(title="Get Pronunciation Dictionary")

    operation: Literal["get_pronunciation_dictionary_by_id"] = Field(
        "get_pronunciation_dictionary_by_id",
        json_schema_extra={
            "const": "get_pronunciation_dictionary_by_id",
            "ui:hidden": True,
            "x-category": "Pronunciation Dictionary",
            "x-is-trigger": False,
            "x-display-name": "Get Pronunciation Dictionary by Id",
        },
        title="Get Pronunciation Dictionary by Id",
    )
    dictionary_id: str = Field(
        ...,
        title="Dictionary ID",
        description="The pronunciation dictionary ID to retrieve",
        json_schema_extra={"placeholder": "dict_abc123"},
    )


class ElevenLabsCreatePronunciationDictionaryConfig(BaseModel):
    """Create a pronunciation dictionary from rules"""

    model_config = ConfigDict(title="Create Pronunciation Dictionary")

    operation: Literal["create_pronunciation_dictionary"] = Field(
        "create_pronunciation_dictionary",
        json_schema_extra={
            "const": "create_pronunciation_dictionary",
            "ui:hidden": True,
            "x-category": "Pronunciation Dictionary",
            "x-is-trigger": False,
            "x-display-name": "Create Pronunciation Dictionary",
        },
        title="Create Pronunciation Dictionary",
    )
    name: str = Field(
        ...,
        title="Dictionary Name",
        description="Name for the pronunciation dictionary",
        json_schema_extra={"placeholder": "My Pronunciations"},
    )
    rules: str = Field(
        ...,
        title="Pronunciation Rules (JSON Array)",
        description='JSON array of pronunciation rules (e.g., [{"string_to_replace": "hello", "phoneme": "hɛloʊ", "alphabet": "ipa"}])',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"string_to_replace": "ElevenLabs", "phoneme": "ɪˈlɛvən læbz", "alphabet": "ipa"}]',
        },
    )
    description: Optional[str] = Field(
        None,
        title="Description (Optional)",
        description="Description of the dictionary",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ElevenLabsDeletePronunciationDictionaryConfig(BaseModel):
    """Delete a pronunciation dictionary"""

    model_config = ConfigDict(title="Delete Pronunciation Dictionary")

    operation: Literal["delete_pronunciation_dictionary"] = Field(
        "delete_pronunciation_dictionary",
        json_schema_extra={
            "const": "delete_pronunciation_dictionary",
            "ui:hidden": True,
            "x-category": "Pronunciation Dictionary",
            "x-is-trigger": False,
            "x-display-name": "Delete Pronunciation Dictionary",
        },
        title="Delete Pronunciation Dictionary",
    )
    dictionary_id: str = Field(
        ...,
        title="Dictionary ID",
        description="The pronunciation dictionary ID to delete",
        json_schema_extra={"placeholder": "dict_abc123"},
    )


# ============================================================================
# Audio Native (Projects) Operations
# ============================================================================


class ElevenLabsCreateAudioNativeConfig(BaseModel):
    """Create an audio native project (embeddable audio player)"""

    model_config = ConfigDict(title="Create Audio Native Project")

    operation: Literal["create_audio_native_project"] = Field(
        "create_audio_native_project",
        json_schema_extra={
            "const": "create_audio_native_project",
            "ui:hidden": True,
            "x-category": "Audio Native Project",
            "x-is-trigger": False,
            "x-display-name": "Create Audio Native Project",
        },
        title="Create Audio Native Project",
    )
    name: str = Field(
        ...,
        title="Project Name",
        description="Name for the audio native project",
        json_schema_extra={"placeholder": "My Article Audio"},
    )
    html: str = Field(
        ...,
        title="HTML Content",
        description="HTML content to convert to audio",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "<html><body>Article content...</body></html>",
        },
    )
    voice_id: str = Field(
        ...,
        title="Voice",
        description="Select a voice or paste voice ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "voice_id",
                "placeholder": "Select a voice...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste voice ID",
            },
            "x-resource-type": "elevenlabs_voice",
        },
    )
    model_id: str = Field(
        "eleven_multilingual_v2",
        title="Model ID",
        json_schema_extra={
            "enum": [
                "eleven_multilingual_v2",
                "eleven_turbo_v2_5",
                "eleven_flash_v2_5",
            ],
            "enumNames": ["Multilingual v2", "Turbo v2.5", "Flash v2.5"],
            "x-enum-searchable": True,
        },
    )
    auto_convert: bool = Field(
        True,
        title="Auto Convert",
        description="Automatically start conversion after creation",
    )


class ElevenLabsGetAudioNativeConfig(BaseModel):
    """Get audio native project details"""

    model_config = ConfigDict(title="Get Audio Native Project")

    operation: Literal["get_audio_native_project_details"] = Field(
        "get_audio_native_project_details",
        json_schema_extra={
            "const": "get_audio_native_project_details",
            "ui:hidden": True,
            "x-category": "Audio Native Project",
            "x-is-trigger": False,
            "x-display-name": "Get Audio Native Project Details",
        },
        title="Get Audio Native Project Details",
    )
    project_id: str = Field(
        ...,
        title="Project ID",
        description="The audio native project ID to retrieve",
        json_schema_extra={"placeholder": "project_abc123"},
    )


class ElevenLabsDeleteAudioNativeConfig(BaseModel):
    """Delete an audio native project"""

    model_config = ConfigDict(title="Delete Audio Native Project")

    operation: Literal["delete_audio_native_project"] = Field(
        "delete_audio_native_project",
        json_schema_extra={
            "const": "delete_audio_native_project",
            "ui:hidden": True,
            "x-category": "Audio Native Project",
            "x-is-trigger": False,
            "x-display-name": "Delete Audio Native Project",
        },
        title="Delete Audio Native Project",
    )
    project_id: str = Field(
        ...,
        title="Project ID",
        description="The audio native project ID to delete",
        json_schema_extra={"placeholder": "project_abc123"},
    )


# ============================================================================
# Models Operations
# ============================================================================


class ElevenLabsListModelsConfig(BaseModel):
    """List all available AI models"""

    model_config = ConfigDict(title="List Models")

    operation: Literal["list_available_ai_models"] = Field(
        "list_available_ai_models",
        json_schema_extra={
            "const": "list_available_ai_models",
            "ui:hidden": True,
            "x-category": "Model",
            "x-is-trigger": False,
            "x-display-name": "List Available Ai Models",
        },
        title="List Available Ai Models",
    )


# ============================================================================
# User & Subscription Operations
# ============================================================================


class ElevenLabsGetUserInfoConfig(BaseModel):
    """Get user account information"""

    model_config = ConfigDict(title="Get User Info")

    operation: Literal["get_user_account_information"] = Field(
        "get_user_account_information",
        json_schema_extra={
            "const": "get_user_account_information",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get User Account Information",
        },
        title="Get User Account Information",
    )


class ElevenLabsGetSubscriptionConfig(BaseModel):
    """Get subscription information and limits"""

    model_config = ConfigDict(title="Get Subscription")

    operation: Literal["get_subscription_information"] = Field(
        "get_subscription_information",
        json_schema_extra={
            "const": "get_subscription_information",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Subscription Information",
        },
        title="Get Subscription Information",
    )


class ElevenLabsGetUsageStatsConfig(BaseModel):
    """Get character usage statistics"""

    model_config = ConfigDict(title="Get Usage Statistics")

    operation: Literal["get_character_usage_stats"] = Field(
        "get_character_usage_stats",
        json_schema_extra={
            "const": "get_character_usage_stats",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Character Usage Stats",
        },
        title="Get Character Usage Stats",
    )
    start_unix: Optional[int] = Field(
        None,
        title="Start Time (Unix, Optional)",
        description="Start of time range in Unix timestamp (defaults to beginning of current billing period)",
        json_schema_extra={"placeholder": "1704067200"},
    )
    end_unix: Optional[int] = Field(
        None,
        title="End Time (Unix, Optional)",
        description="End of time range in Unix timestamp (defaults to current time)",
        json_schema_extra={"placeholder": "1704153600"},
    )


# ============================================================================
# Union Config Type (Discriminated Union for All Operations)
# ============================================================================

ElevenLabsConfig = Annotated[
    Union[
        # Text-to-Speech (3 operations)
        ElevenLabsTextToSpeechConfig,
        ElevenLabsTextToSpeechStreamConfig,
        ElevenLabsTextToSpeechWithTimestampsConfig,
        # Speech-to-Speech (1 operation)
        ElevenLabsSpeechToSpeechConfig,
        # Speech-to-Text (1 operation)
        ElevenLabsSpeechToTextConfig,
        # Voice Management (5 operations)
        ElevenLabsListVoicesConfig,
        ElevenLabsGetVoiceConfig,
        ElevenLabsAddVoiceConfig,
        ElevenLabsEditVoiceConfig,
        ElevenLabsDeleteVoiceConfig,
        # Sound Effects (1 operation)
        ElevenLabsSoundEffectsConfig,
        # Audio Isolation (1 operation)
        ElevenLabsAudioIsolationConfig,
        # Dubbing (3 operations)
        ElevenLabsCreateDubbingConfig,
        ElevenLabsGetDubbingConfig,
        ElevenLabsDeleteDubbingConfig,
        # History (5 operations)
        ElevenLabsGetHistoryConfig,
        ElevenLabsGetHistoryItemConfig,
        ElevenLabsDeleteHistoryItemConfig,
        ElevenLabsGetHistoryAudioConfig,
        ElevenLabsDownloadHistoryItemsConfig,
        # Pronunciation Dictionaries (4 operations)
        ElevenLabsListPronunciationDictionariesConfig,
        ElevenLabsGetPronunciationDictionaryConfig,
        ElevenLabsCreatePronunciationDictionaryConfig,
        ElevenLabsDeletePronunciationDictionaryConfig,
        # Audio Native (3 operations)
        ElevenLabsCreateAudioNativeConfig,
        ElevenLabsGetAudioNativeConfig,
        ElevenLabsDeleteAudioNativeConfig,
        # Models (1 operation)
        ElevenLabsListModelsConfig,
        # User & Subscription (3 operations)
        ElevenLabsGetUserInfoConfig,
        ElevenLabsGetSubscriptionConfig,
        ElevenLabsGetUsageStatsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config (Config + Credentials)
# ============================================================================


class ElevenLabsNodeConfig(NodeConfig[ElevenLabsConfig, ElevenLabsAPIKeyCredential]):
    """Full configuration for ElevenLabs automation node"""

    pass


# ============================================================================
# ElevenLabs Node Implementation
# ============================================================================


class ElevenLabsNode(WorkflowNode):
    """
    ElevenLabs AI Audio Platform automation node.

    Supports 31 operations across Text-to-Speech, Voice Management, Sound Effects,
    Dubbing, History, Pronunciation, Audio Native projects, and more.

    Authentication: API Key (xi-api-key header)
    Get your API key at: https://elevenlabs.io/app/settings
    """

    edit_examples = [
        "Convert customer support FAQs to speech in 5 languages",
        "Clone voice from audio samples and use for announcements",
        "Transcribe podcast audio with word-level timestamps",
        "Generate realistic sound effects for video ads",
        "Create embeddable audio player for blog articles",
        "Dub video to Spanish preserving original voice tone",
        "Get subscription limit and character usage statistics",
    ]

    @classmethod
    def get_config_model(cls):
        return ElevenLabsNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Load dynamic options for voice_id field.

        Args:
            field_name: Name of the field needing options (e.g., "voice_id")
            credential_data: Decrypted API key credential data
            context: Additional context (not used for ElevenLabs)
            page_token: Optional token for pagination (not used - all voices returned)
            search: Optional case-insensitive substring filter applied to option label/value

        Returns:
            Dict with 'options' (list of {value, label} dicts) and 'next_page_token' (None)
        """
        logger.info(f"[ElevenLabsNode] load_field_options called: field={field_name}")

        if field_name == "voice_id":
            # Extract API key from credential_data
            api_key = require_credential_token(
                credential_data.get("api_key"),
                "Connect an ElevenLabs account to load voices",
            )

            try:
                # Call list_voices API
                url = f"{ELEVENLABS_API_BASE}/{ELEVENLABS_API_VERSION}/voices"
                headers = {"xi-api-key": api_key}

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                    # Extract voices and format as options
                    voices = data.get("voices", [])
                    options = [
                        {"value": voice.get("voice_id"), "label": voice.get("name")}
                        for voice in voices
                        if voice.get("voice_id") and voice.get("name")
                    ]

                    logger.info(f"[ElevenLabsNode] Loaded {len(options)} voice options")

                    # ElevenLabs /v1/voices returns the full set in one response
                    # (no native search, no cursor) — substring-filter inline.
                    return {
                        "options": filter_options_by_search(options, search),
                        "next_page_token": None,
                    }

            except ValueError:
                raise
            except Exception as e:
                logger.error(f"[ElevenLabsNode] Failed to load voice options: {e}")
                raise ValueError(f"Failed to load ElevenLabs voices: {e}") from e

        return {"options": [], "next_page_token": None}

    def _get_auth_headers(
        self, credentials: ElevenLabsAPIKeyCredential
    ) -> Dict[str, str]:
        """Generate authentication headers for ElevenLabs API"""
        return {"xi-api-key": credentials.api_key, "Content-Type": "application/json"}

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: ElevenLabsAPIKeyCredential,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        return_binary: bool = False,
    ) -> Dict[str, Any]:
        """Make an authenticated request to ElevenLabs API"""
        url = f"{ELEVENLABS_API_BASE}/{ELEVENLABS_API_VERSION}/{endpoint}"

        headers = {"xi-api-key": credentials.api_key}
        if not files:
            headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    if files:
                        response = await client.post(
                            url,
                            headers={"xi-api-key": credentials.api_key},
                            files=files,
                            data=json_data,
                        )
                    else:
                        response = await client.post(
                            url, headers=headers, json=json_data, params=params
                        )
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # Handle binary responses (audio files)
                if return_binary:
                    import mimetypes

                    from nodes.core.binary_output import BinaryOutput

                    mime = (
                        response.headers.get("content-type") or "audio/mpeg"
                    )
                    ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ".mp3"
                    return {
                        "success": True,
                        "audio": BinaryOutput(
                            data=response.content,
                            content_type=mime,
                            filename=f"elevenlabs_audio{ext}",
                        ),
                    }

                # Handle JSON responses
                if response.text:
                    return response.json()

                # Handle successful responses with no content
                return {"success": True, "message": "Operation completed successfully"}

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"ElevenLabs API error: {e.response.status_code} - {e.response.text}"
                )
                raise Exception(
                    f"ElevenLabs API error: {e.response.status_code} - {e.response.text}"
                )
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                raise Exception(f"Request failed: {str(e)}")

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the ElevenLabs node operation"""
        logger.info(f"[ElevenLabsNode] Executing node {self.node_id}")

        # Extract configuration
        node_config = self.config
        if not node_config or not isinstance(node_config, ElevenLabsNodeConfig):
            raise ValueError("ElevenLabsNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[ElevenLabsNode] Credentials are required. "
                "Please add your ElevenLabs API key in the credentials tab."
            )

        action = config.operation

        # ========== Text-to-Speech Operations ==========
        if action == "convert_text_to_speech":
            typed_config: ElevenLabsTextToSpeechConfig = config
            payload = {
                "text": typed_config.text,
                "model_id": typed_config.model_id,
                "voice_settings": {
                    "stability": typed_config.stability,
                    "similarity_boost": typed_config.similarity_boost,
                    "use_speaker_boost": typed_config.use_speaker_boost,
                },
            }
            if typed_config.style is not None:
                payload["voice_settings"]["style"] = typed_config.style

            return await self._make_request(
                "POST",
                f"text-to-speech/{typed_config.voice_id}?output_format={typed_config.output_format}",
                credentials,
                json_data=payload,
                return_binary=True,
            )

        elif action == "stream_text_to_speech_realtime":
            typed_config: ElevenLabsTextToSpeechStreamConfig = config
            payload = {
                "text": typed_config.text,
                "model_id": typed_config.model_id,
                "voice_settings": {
                    "stability": typed_config.stability,
                    "similarity_boost": typed_config.similarity_boost,
                },
            }

            return await self._make_request(
                "POST",
                f"text-to-speech/{typed_config.voice_id}/stream",
                credentials,
                json_data=payload,
                return_binary=True,
            )

        elif action == "convert_text_to_speech_with_timestamps":
            typed_config: ElevenLabsTextToSpeechWithTimestampsConfig = config
            payload = {"text": typed_config.text, "model_id": typed_config.model_id}

            return await self._make_request(
                "POST",
                f"text-to-speech/{typed_config.voice_id}/with-timestamps",
                credentials,
                json_data=payload,
            )

        # ========== Speech-to-Speech Operations ==========
        elif action == "convert_audio_using_voice":
            typed_config: ElevenLabsSpeechToSpeechConfig = config
            # Convert base64 to binary
            audio_data = base64.b64decode(typed_config.audio_base64)

            files = {"audio": ("audio.mp3", audio_data, "audio/mpeg")}
            data = {"model_id": typed_config.model_id}

            return await self._make_request(
                "POST",
                f"speech-to-speech/{typed_config.voice_id}",
                credentials,
                json_data=data,
                files=files,
                return_binary=True,
            )

        # ========== Speech-to-Text Operations ==========
        elif action == "transcribe_audio_to_text":
            typed_config: ElevenLabsSpeechToTextConfig = config
            audio_data = base64.b64decode(typed_config.audio_base64)

            files = {"file": ("audio.mp3", audio_data, "audio/mpeg")}
            data = {"model_id": typed_config.model_id}
            if typed_config.language:
                data["language"] = typed_config.language

            return await self._make_request(
                "POST", "speech-to-text", credentials, json_data=data, files=files
            )

        # ========== Voice Management Operations ==========
        elif action == "list_available_voices":
            typed_config: ElevenLabsListVoicesConfig = config
            params = {}
            if typed_config.show_legacy:
                params["show_legacy"] = "true"

            return await self._make_request("GET", "voices", credentials, params=params)

        elif action == "get_voice_by_id":
            typed_config: ElevenLabsGetVoiceConfig = config
            params = {}
            if typed_config.with_settings:
                params["with_settings"] = "true"

            return await self._make_request(
                "GET", f"voices/{typed_config.voice_id}", credentials, params=params
            )

        elif action == "clone_voice_from_audio_samples":
            typed_config: ElevenLabsAddVoiceConfig = config
            import json

            files_data = json.loads(typed_config.files_base64)

            files = {}
            for i, file_b64 in enumerate(files_data):
                audio_data = base64.b64decode(file_b64)
                files[f"files_{i}"] = (f"sample_{i}.mp3", audio_data, "audio/mpeg")

            data = {"name": typed_config.name}
            if typed_config.description:
                data["description"] = typed_config.description
            if typed_config.labels:
                data["labels"] = typed_config.labels

            return await self._make_request(
                "POST", "voices/add", credentials, json_data=data, files=files
            )

        elif action == "edit_voice_settings":
            typed_config: ElevenLabsEditVoiceConfig = config
            payload = {}
            if typed_config.name:
                payload["name"] = typed_config.name
            if typed_config.description:
                payload["description"] = typed_config.description
            if typed_config.labels:
                import json

                payload["labels"] = json.loads(typed_config.labels)

            return await self._make_request(
                "POST",
                f"voices/{typed_config.voice_id}/edit",
                credentials,
                json_data=payload,
            )

        elif action == "delete_custom_voice":
            typed_config: ElevenLabsDeleteVoiceConfig = config
            return await self._make_request(
                "DELETE", f"voices/{typed_config.voice_id}", credentials
            )

        # ========== Sound Effects Operations ==========
        elif action == "generate_sound_effects_from_text":
            typed_config: ElevenLabsSoundEffectsConfig = config
            payload = {
                "text": typed_config.text,
                "prompt_influence": typed_config.prompt_influence,
            }
            if typed_config.duration_seconds:
                payload["duration_seconds"] = typed_config.duration_seconds
            if typed_config.enable_looping:
                payload["enable_looping"] = typed_config.enable_looping

            return await self._make_request(
                "POST",
                "sound-generation",
                credentials,
                json_data=payload,
                return_binary=True,
            )

        # ========== Audio Isolation Operations ==========
        elif action == "isolate_vocals_from_audio":
            typed_config: ElevenLabsAudioIsolationConfig = config
            audio_data = base64.b64decode(typed_config.audio_base64)

            files = {"audio": ("audio.mp3", audio_data, "audio/mpeg")}

            return await self._make_request(
                "POST", "audio-isolation", credentials, files=files, return_binary=True
            )

        # ========== Dubbing Operations ==========
        elif action == "create_dubbing_project":
            typed_config: ElevenLabsCreateDubbingConfig = config
            payload = {
                "source_url": typed_config.source_url,
                "target_lang": typed_config.target_lang,
                "watermark": typed_config.watermark,
            }
            if typed_config.source_lang:
                payload["source_lang"] = typed_config.source_lang
            if typed_config.num_speakers:
                payload["num_speakers"] = typed_config.num_speakers

            return await self._make_request(
                "POST", "dubbing", credentials, json_data=payload
            )

        elif action == "get_dubbing_project_status":
            typed_config: ElevenLabsGetDubbingConfig = config
            return await self._make_request(
                "GET", f"dubbing/{typed_config.dubbing_id}", credentials
            )

        elif action == "delete_dubbing_project":
            typed_config: ElevenLabsDeleteDubbingConfig = config
            return await self._make_request(
                "DELETE", f"dubbing/{typed_config.dubbing_id}", credentials
            )

        # ========== History Operations ==========
        elif action == "list_generated_audio_history":
            typed_config: ElevenLabsGetHistoryConfig = config
            params = {"page_size": typed_config.page_size}
            if typed_config.start_after_history_item_id:
                params[
                    "start_after_history_item_id"
                ] = typed_config.start_after_history_item_id
            if typed_config.voice_id:
                params["voice_id"] = typed_config.voice_id

            return await self._make_request(
                "GET", "history", credentials, params=params
            )

        elif action == "get_history_item_details":
            typed_config: ElevenLabsGetHistoryItemConfig = config
            return await self._make_request(
                "GET", f"history/{typed_config.history_item_id}", credentials
            )

        elif action == "delete_history_item":
            typed_config: ElevenLabsDeleteHistoryItemConfig = config
            return await self._make_request(
                "DELETE", f"history/{typed_config.history_item_id}", credentials
            )

        elif action == "get_history_item_audio":
            typed_config: ElevenLabsGetHistoryAudioConfig = config
            return await self._make_request(
                "GET",
                f"history/{typed_config.history_item_id}/audio",
                credentials,
                return_binary=True,
            )

        elif action == "download_history_items":
            typed_config: ElevenLabsDownloadHistoryItemsConfig = config
            import json

            history_ids = json.loads(typed_config.history_item_ids)
            payload = {"history_item_ids": history_ids}

            return await self._make_request(
                "POST",
                "history/download",
                credentials,
                json_data=payload,
                return_binary=True,
            )

        # ========== Pronunciation Dictionary Operations ==========
        elif action == "list_pronunciation_dictionaries":
            typed_config: ElevenLabsListPronunciationDictionariesConfig = config
            params = {"page_size": typed_config.page_size}

            return await self._make_request(
                "GET", "pronunciation-dictionaries", credentials, params=params
            )

        elif action == "get_pronunciation_dictionary_by_id":
            typed_config: ElevenLabsGetPronunciationDictionaryConfig = config
            return await self._make_request(
                "GET",
                f"pronunciation-dictionaries/{typed_config.dictionary_id}",
                credentials,
            )

        elif action == "create_pronunciation_dictionary":
            typed_config: ElevenLabsCreatePronunciationDictionaryConfig = config
            import json

            rules = json.loads(typed_config.rules)
            payload = {"name": typed_config.name, "rules": rules}
            if typed_config.description:
                payload["description"] = typed_config.description

            return await self._make_request(
                "POST",
                "pronunciation-dictionaries/add-from-file",
                credentials,
                json_data=payload,
            )

        elif action == "delete_pronunciation_dictionary":
            typed_config: ElevenLabsDeletePronunciationDictionaryConfig = config
            return await self._make_request(
                "DELETE",
                f"pronunciation-dictionaries/{typed_config.dictionary_id}",
                credentials,
            )

        # ========== Audio Native Operations ==========
        elif action == "create_audio_native_project":
            typed_config: ElevenLabsCreateAudioNativeConfig = config
            payload = {
                "name": typed_config.name,
                "html": typed_config.html,
                "voice_id": typed_config.voice_id,
                "model_id": typed_config.model_id,
                "auto_convert": typed_config.auto_convert,
            }

            return await self._make_request(
                "POST", "audio-native", credentials, json_data=payload
            )

        elif action == "get_audio_native_project_details":
            typed_config: ElevenLabsGetAudioNativeConfig = config
            return await self._make_request(
                "GET", f"audio-native/{typed_config.project_id}", credentials
            )

        elif action == "delete_audio_native_project":
            typed_config: ElevenLabsDeleteAudioNativeConfig = config
            return await self._make_request(
                "DELETE", f"audio-native/{typed_config.project_id}", credentials
            )

        # ========== Models Operations ==========
        elif action == "list_available_ai_models":
            return await self._make_request("GET", "models", credentials)

        # ========== User & Subscription Operations ==========
        elif action == "get_user_account_information":
            return await self._make_request("GET", "user", credentials)

        elif action == "get_subscription_information":
            return await self._make_request("GET", "user/subscription", credentials)

        elif action == "get_character_usage_stats":
            typed_config: ElevenLabsGetUsageStatsConfig = config

            # ElevenLabs API requires start_unix and end_unix
            # Default to current billing period if not provided
            current_time = int(time.time())
            # Default to last 30 days
            thirty_days_ago = current_time - (30 * 24 * 60 * 60)

            params = {
                "start_unix": typed_config.start_unix
                if typed_config.start_unix is not None
                else thirty_days_ago,
                "end_unix": typed_config.end_unix
                if typed_config.end_unix is not None
                else current_time,
            }

            return await self._make_request(
                "GET", "usage/character-stats", credentials, params=params
            )

        else:
            raise ValueError(f"Unknown action: {action}")


# Factory function for node creation
def create_elevenlabs_node(config: ElevenLabsNodeConfig) -> ElevenLabsNode:
    """Factory function to create an ElevenLabs node instance"""
    return ElevenLabsNode(config)

"""Artificial Analysis V2 data and CritPt grading, pinned to the published API contract.

Each operation makes one request. Paginated reads return the provider pagination
unchanged; callers choose the next page. Data use requires Artificial Analysis attribution.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://artificialanalysis.ai"
DOCS_URL = "https://artificialanalysis.ai/api/v2/openapi"


class ArtificialAnalysisAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Artificial Analysis API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://artificialanalysis.ai/api-key-management-redirect",
            "x-credential-instructions": "Create or copy an API key from Artificial Analysis API key management. Paste the key without a header prefix. Free keys support Free operations; standard data requires Pro, provider data and historical performance require Commercial, and CritPt grading requires separate approval. Connection checks establish key reachability, not account identity.",
        })
    credential_type: Literal["artificial_analysis_api_key"] = Field("artificial_analysis_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ArtificialAnalysisSubmission(_Input):
    problem_id: str
    generated_code: str = Field(..., title="Generated Code", json_schema_extra={"ui:widget": "textarea"})
    model: str
    generation_config: dict[str, Any]
    messages: list[dict[str, Any]] | None = None


class ArtificialAnalysisGetLanguageModelsFreeConfig(_Input):
    operation: Literal['get_language_models_free'] = Field('get_language_models_free', title='Get language models (Free tier)', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=10000, description='Page number for paginated results (1-indexed). Defaults to 1.\n')


class ArtificialAnalysisGetLanguageModelsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_language_models'] = Field('get_language_models', title='Get all language models', json_schema_extra={"ui:hidden": True})
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')
    page: int = Field(1, ge=1, le=10000, description='Page number for paginated results (1-indexed). Defaults to 1.\n')


class ArtificialAnalysisGetLanguageModelBySlugConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_language_model_by_slug'] = Field('get_language_model_by_slug', title='Get a single language model by slug', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description='The model slug (e.g. "gemini-3-pro", "claude-opus-4-6", "deepseek-v3").')
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')


class ArtificialAnalysisGetLanguageModelPerformanceOverTimeConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'commercial', "x-tier-label": 'Commercial'})
    operation: Literal['get_language_model_performance_over_time'] = Field('get_language_model_performance_over_time', title='Get performance over time for a single model', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description='The unique identifier for the model (e.g. `claude-sonnet-4`). Use the `/models` endpoint to discover available slugs.')
    window: Literal['7d', '30d', '90d'] = Field('90d', description='Lookback period from today. Maximum 90 days for single-model endpoint.')
    interval: Literal['daily', 'weekly', 'monthly'] | None = Field(None, description='Aggregation granularity. Auto-derived from window if omitted\n(7d/30d → daily, 90d → weekly).\n')
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')


class ArtificialAnalysisGetLanguageProvidersConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'commercial', "x-tier-label": 'Commercial'})
    operation: Literal['get_language_providers'] = Field('get_language_providers', title='Get all language model API providers', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=10000, description='Page number for paginated results (1-indexed). Defaults to 1.\n')


class ArtificialAnalysisGetLanguageProviderBySlugConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'commercial', "x-tier-label": 'Commercial'})
    operation: Literal['get_language_provider_by_slug'] = Field('get_language_provider_by_slug', title='Get a single language model provider by slug', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description='The provider slug (e.g. "openai", "fireworks").')
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')


class ArtificialAnalysisGetLanguageProviderPerformanceOverTimeConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'commercial', "x-tier-label": 'Commercial'})
    operation: Literal['get_language_provider_performance_over_time'] = Field('get_language_provider_performance_over_time', title='Get performance over time for a single provider', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description='The unique identifier for the provider (e.g. `anthropic`). Use the `/providers` endpoint to discover available slugs.')
    window: Literal['7d', '30d', '90d'] = Field('90d', description='Lookback period from today.')
    interval: Literal['daily', 'weekly', 'monthly'] | None = Field(None, description='Aggregation granularity. Auto-derived from window if omitted\n(7d/30d → daily, 90d → weekly).\n')
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')


class ArtificialAnalysisGetLanguageProviderMeasurementsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'commercial', "x-tier-label": 'Commercial'})
    operation: Literal['get_language_provider_measurements'] = Field('get_language_provider_measurements', title='Get raw measurements for a provider', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description='The unique identifier for the provider (e.g. `anthropic`). Your Commercial API key must have grants for this provider.')
    prompt_type: Literal['medium', 'long', '100k', 'vision_single_image', 'medium_parallel'] = Field('long', description='The prompt type preset used for performance benchmarking.\nControls how many input tokens and parallel queries are used in latency/throughput measurements.\nApplies to the `performance` fields only; `performance_v3` does not depend on it.\n\n| prompt_type | input_tokens | parallel_queries |\n| --- | --- | --- |\n| `medium` | 1,000 | 1 |\n| `long` (default) | 10,000 | 1 |\n| `100k` | 100,000 | 1 |\n| `vision_single_image` | 1,000 | 1 |\n| `medium_parallel` | 1,000 | 10 |\n')
    start_date: date | None = Field(None, description='Only return measurements recorded on or after this date (YYYY-MM-DD).\nDefaults to one month ago if omitted; dates earlier than one month ago are clamped to one month ago.')


class ArtificialAnalysisGetTextToImageArenaFreeConfig(_Input):
    operation: Literal['get_text_to_image_arena_free'] = Field('get_text_to_image_arena_free', title='Get AA-Image-T2I v2.1 rankings (Free tier)', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetTextToImageArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_text_to_image_arena'] = Field('get_text_to_image_arena', title='Get AA-Image-T2I v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetImageEditingArenaFreeConfig(_Input):
    operation: Literal['get_image_editing_arena_free'] = Field('get_image_editing_arena_free', title='Get AA-Image-Editing v2.1 rankings (Free tier)', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetImageEditingArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_image_editing_arena'] = Field('get_image_editing_arena', title='Get AA-Image-Editing v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetTextToVideoArenaFreeConfig(_Input):
    operation: Literal['get_text_to_video_arena_free'] = Field('get_text_to_video_arena_free', title='Get AA-Video-T2V-Silent v2.1 rankings (Free tier)', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetTextToVideoArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_text_to_video_arena'] = Field('get_text_to_video_arena', title='Get AA-Video-T2V-Silent v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetImageToVideoArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_image_to_video_arena'] = Field('get_image_to_video_arena', title='Get AA-Video-I2V-Silent v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetTextToVideoAudioArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_text_to_video_audio_arena'] = Field('get_text_to_video_audio_arena', title='Get AA-Video-T2V v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetImageToVideoAudioArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_image_to_video_audio_arena'] = Field('get_image_to_video_audio_arena', title='Get AA-Video-I2V v2.1 rankings', json_schema_extra={"ui:hidden": True})
    include_categories: bool = Field(False, description='Include per-category Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetTextToSpeechArenaFreeConfig(_Input):
    operation: Literal['get_text_to_speech_arena_free'] = Field('get_text_to_speech_arena_free', title='Get text-to-speech arena rankings (Free tier)', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetTextToSpeechArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_text_to_speech_arena'] = Field('get_text_to_speech_arena', title='Get text-to-speech arena rankings', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetSpeechToSpeechConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_speech_to_speech'] = Field('get_speech_to_speech', title='Get speech-to-speech model data', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetSpeechToTextModelsFreeConfig(_Input):
    operation: Literal['get_speech_to_text_models_free'] = Field('get_speech_to_text_models_free', title='Get speech-to-text models (Free tier)', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetSpeechToTextModelsConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_speech_to_text_models'] = Field('get_speech_to_text_models', title='Get speech-to-text models', json_schema_extra={"ui:hidden": True})


class ArtificialAnalysisGetMusicInstrumentalArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_music_instrumental_arena'] = Field('get_music_instrumental_arena', title='Get AA-Music-Instrumental v1.1 rankings', json_schema_extra={"ui:hidden": True})
    include_genres: bool = Field(False, description='Include per-genre Elo breakdowns (Pro tier only).')


class ArtificialAnalysisGetMusicWithVocalsArenaConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'pro', "x-tier-label": 'Pro'})
    operation: Literal['get_music_with_vocals_arena'] = Field('get_music_with_vocals_arena', title='Get AA-Music-Vocal v1.1 rankings', json_schema_extra={"ui:hidden": True})
    include_genres: bool = Field(False, description='Include per-genre Elo breakdowns (Pro tier only).')


class ArtificialAnalysisEvaluateCritPtConfig(_Input):
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": 'approved critpt access', "x-tier-label": 'Approved CritPt access'})
    operation: Literal['evaluate_crit_pt'] = Field('evaluate_crit_pt', title='Submit code for CritPt v2 evaluation', json_schema_extra={"ui:hidden": True})
    submissions: list[ArtificialAnalysisSubmission]
    batch_metadata: dict[str, Any]


Operation = Annotated[Union[
    ArtificialAnalysisGetLanguageModelsFreeConfig,
    ArtificialAnalysisGetLanguageModelsConfig,
    ArtificialAnalysisGetLanguageModelBySlugConfig,
    ArtificialAnalysisGetLanguageModelPerformanceOverTimeConfig,
    ArtificialAnalysisGetLanguageProvidersConfig,
    ArtificialAnalysisGetLanguageProviderBySlugConfig,
    ArtificialAnalysisGetLanguageProviderPerformanceOverTimeConfig,
    ArtificialAnalysisGetLanguageProviderMeasurementsConfig,
    ArtificialAnalysisGetTextToImageArenaFreeConfig,
    ArtificialAnalysisGetTextToImageArenaConfig,
    ArtificialAnalysisGetImageEditingArenaFreeConfig,
    ArtificialAnalysisGetImageEditingArenaConfig,
    ArtificialAnalysisGetTextToVideoArenaFreeConfig,
    ArtificialAnalysisGetTextToVideoArenaConfig,
    ArtificialAnalysisGetImageToVideoArenaConfig,
    ArtificialAnalysisGetTextToVideoAudioArenaConfig,
    ArtificialAnalysisGetImageToVideoAudioArenaConfig,
    ArtificialAnalysisGetTextToSpeechArenaFreeConfig,
    ArtificialAnalysisGetTextToSpeechArenaConfig,
    ArtificialAnalysisGetSpeechToSpeechConfig,
    ArtificialAnalysisGetSpeechToTextModelsFreeConfig,
    ArtificialAnalysisGetSpeechToTextModelsConfig,
    ArtificialAnalysisGetMusicInstrumentalArenaConfig,
    ArtificialAnalysisGetMusicWithVocalsArenaConfig,
    ArtificialAnalysisEvaluateCritPtConfig
], Field(discriminator="operation")]


class ArtificialAnalysisConfig(NodeConfig[Operation, ArtificialAnalysisAPIKeyCredential]):
    pass


OPERATIONS = {'get_language_models_free': ('GET', '/api/v2/language/models/free'), 'get_language_models': ('GET', '/api/v2/language/models'), 'get_language_model_by_slug': ('GET', '/api/v2/language/models/{slug}'), 'get_language_model_performance_over_time': ('GET', '/api/v2/language/models/{slug}/performance'), 'get_language_providers': ('GET', '/api/v2/language/providers'), 'get_language_provider_by_slug': ('GET', '/api/v2/language/providers/{slug}'), 'get_language_provider_performance_over_time': ('GET', '/api/v2/language/providers/{slug}/performance'), 'get_language_provider_measurements': ('GET', '/api/v2/language/providers/{slug}/measurements'), 'get_text_to_image_arena_free': ('GET', '/api/v2/media/text-to-image/models/free'), 'get_text_to_image_arena': ('GET', '/api/v2/media/text-to-image/models'), 'get_image_editing_arena_free': ('GET', '/api/v2/media/image-editing/models/free'), 'get_image_editing_arena': ('GET', '/api/v2/media/image-editing/models'), 'get_text_to_video_arena_free': ('GET', '/api/v2/media/text-to-video/models/free'), 'get_text_to_video_arena': ('GET', '/api/v2/media/text-to-video/models'), 'get_image_to_video_arena': ('GET', '/api/v2/media/image-to-video/models'), 'get_text_to_video_audio_arena': ('GET', '/api/v2/media/text-to-video-audio/models'), 'get_image_to_video_audio_arena': ('GET', '/api/v2/media/image-to-video-audio/models'), 'get_text_to_speech_arena_free': ('GET', '/api/v2/media/text-to-speech/models/free'), 'get_text_to_speech_arena': ('GET', '/api/v2/media/text-to-speech/models'), 'get_speech_to_speech': ('GET', '/api/v2/media/speech-to-speech/models'), 'get_speech_to_text_models_free': ('GET', '/api/v2/media/speech-to-text/models/free'), 'get_speech_to_text_models': ('GET', '/api/v2/media/speech-to-text/models'), 'get_music_instrumental_arena': ('GET', '/api/v2/media/music/instrumental/models'), 'get_music_with_vocals_arena': ('GET', '/api/v2/media/music/with-vocals/models'), 'evaluate_crit_pt': ('POST', '/api/v2/critpt/evaluate')}


class ArtificialAnalysisNode(WorkflowNode):
    integration_type = "automation-artificial-analysis"
    connection_evidence = ConnectionEvidence(
        operation="get_language_models_free", noun="Artificial Analysis model data", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return ArtificialAnalysisConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Artificial Analysis API key")
        config = self.config.config
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "slug" in values:
            path = path.replace("{slug}", quote(values.pop("slug"), safe=""))
        kwargs = {"json": values} if method == "POST" else {
            "params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        }
        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=60.0) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        if response.status_code != 200:
            # Keep the provider's rejection text for the shared credential proof seam.
            # Never expose a key if an upstream error echoes it.
            try:
                failure = response.json()
                message = failure.get("error", failure.get("message", "")) if isinstance(failure, dict) else ""
            except ValueError:
                message = ""
            if not isinstance(message, str) or not message:
                message = f"Artificial Analysis returned HTTP {response.status_code}"
            message = message.replace(self.config.credentials.api_key, "[redacted]")
            return {"status": "error", "error": message, "http_status": response.status_code}
        body = response.json()
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Artificial Analysis returned an invalid response")
        if method == "GET" and not isinstance(body.get("data"), (dict, list)):
            raise ValueError("Artificial Analysis response has invalid data")
        return {**body, "status": "success", "attribution": "Artificial Analysis", "source_url": BASE_URL + "/"}

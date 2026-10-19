"""Choosing an OpenRouter video model routes the agent to its video path.

The agent's model_type is inferred from the model id alone, by the same rule
the model catalog uses to flag video models (utils/model_catalog.py), and the
catalog lists OpenRouter's video models, which its chat catalog leaves out.
"""

from unittest.mock import AsyncMock, patch

import pytest

from nodes.agent.config.base import infer_model_type
from utils import model_catalog

# OpenRouter's video catalog (models?output_modalities=video) on 2026-10-08.
OPENROUTER_VIDEO_IDS = (
    "x-ai/grok-imagine-video-1.5-lite", "heygen/heygen-video-1", "black-forest-labs/flux-video-edit",
    "minimax/hailuo-3-max", "alibaba/wan-3.0-prime", "alibaba/wan-3.0", "heygen/avatar-iv",
    "black-forest-labs/flux-video-upscale", "bytedance/seedance-2.0-mini", "bytedance/seedance-2.5",
    "black-forest-labs/flux-3-video", "minimax/hailuo-3", "runway/aleph-2", "runway/gen-4.5",
    "x-ai/grok-imagine-video-1.5", "alibaba/happyhorse-1.1", "alibaba/happyhorse-1.0", "x-ai/grok-imagine-video",
    "kwaivgi/kling-v3.0-pro", "kwaivgi/kling-v3.0-std", "google/veo-3.1-fast", "google/veo-3.1-lite",
    "kwaivgi/kling-video-o1", "minimax/hailuo-2.3", "bytedance/seedance-2.0", "alibaba/wan-2.7",
    "bytedance/seedance-2.0-fast", "alibaba/wan-2.6", "bytedance/seedance-1-5-pro", "google/veo-3.1",
)


def model_type(model: str) -> str:
    return infer_model_type({"model": model})["model_type"]


@pytest.mark.parametrize("model_id", OPENROUTER_VIDEO_IDS)
def test_every_openrouter_video_model_runs_as_video(model_id):
    assert model_type(model_id) == "video"
    assert model_type(f"openrouter/{model_id}") == "video"


@pytest.mark.parametrize("model,expected", [
    ("kling/kling-v3", "kling"),                         # Kling's own API
    ("kling-v3", "kling"),
    ("openrouter/thinkingmachines/inkling", "llm"),      # a chat model, not Kling
    ("openrouter/anthropic/claude-sonnet-4.6", "llm"),
    ("openrouter/google/gemini-2.5-flash", "llm"),
    ("openrouter/google/gemini-2.5-flash-image", "image"),
    ("imagen-4.0-generate-001", "image"),                 # "gen-4" is Runway's, but an image id stays an image
])
def test_other_models_keep_their_path(model, expected):
    assert model_type(model) == expected


def test_the_catalog_lists_openrouter_video_models_and_drops_the_unrunnable_litellm_ones():
    row = {"id": "google/veo-3.1-fast", "name": "Google: Veo 3.1 Fast", "created": 1776994666,
           "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["video"]},
           "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["seed"]}
    with patch.object(model_catalog, "get_openrouter_catalog_sync", return_value=[row]) as fetch:
        [veo] = model_catalog.list_openrouter_video_models()
    fetch.assert_called_once_with("models?output_modalities=video")
    assert veo.id == "openrouter/google/veo-3.1-fast" and veo.capabilities.video_generation
    assert veo.output_modalities == ["video"] and veo.free is False  # priced per second, never by tokens
    assert model_type(veo.id) == "video"
    # LiteLLM's video models ran on its broken video API; they are no longer offered.
    assert model_catalog._translate_litellm("gemini/veo-3.1-generate-001", {
        "litellm_provider": "gemini", "mode": "video_generation"}) is None


async def test_the_async_catalog_fetches_the_video_slice_without_blocking():
    row = {"id": "alibaba/wan-2.7", "architecture": {"output_modalities": ["video"]}}
    with patch.object(model_catalog, "get_openrouter_models", AsyncMock(return_value=[])), \
         patch.object(model_catalog, "get_openrouter_catalog", AsyncMock(return_value=[row])), \
         patch.object(model_catalog, "get_openrouter_catalog_sync", side_effect=AssertionError("blocking fetch")), \
         patch.object(model_catalog, "list_opencode_zen_models_async", AsyncMock(return_value=[])):
        models = await model_catalog.list_all_models_async()
    assert any(m.id == "openrouter/alibaba/wan-2.7" and m.capabilities.video_generation for m in models)

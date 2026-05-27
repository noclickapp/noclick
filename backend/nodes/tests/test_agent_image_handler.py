from types import SimpleNamespace

import pytest

from nodes.agent.handlers.image import (
    _get_openrouter_image_config,
    _parse_optional_int,
)


def test_gpt_image_config_uses_openrouter_fields():
    config = SimpleNamespace(
        openrouter_image_aspect_ratio="16:9",
        openrouter_image_size="2K",
        gemini_aspect_ratio="1:1",
        gemini_image_size="1K",
    )

    assert _get_openrouter_image_config(
        config,
        is_gemini_image=False,
        is_gpt_image=True,
    ) == {
        "aspect_ratio": "16:9",
        "image_size": "2K",
    }


def test_gpt_image_config_omits_openrouter_defaults():
    config = SimpleNamespace(
        openrouter_image_aspect_ratio="1:1",
        openrouter_image_size="1K",
    )

    assert _get_openrouter_image_config(
        config,
        is_gemini_image=False,
        is_gpt_image=True,
    ) == {}


def test_gemini_image_config_still_uses_legacy_fields():
    config = SimpleNamespace(
        gemini_aspect_ratio="9:16",
        gemini_image_size="4K",
    )

    assert _get_openrouter_image_config(
        config,
        is_gemini_image=True,
        is_gpt_image=False,
    ) == {
        "aspect_ratio": "9:16",
        "image_size": "4K",
    }


def test_openrouter_seed_rejects_non_integer_values():
    with pytest.raises(ValueError, match="OpenRouter seed must be an integer"):
        _parse_optional_int("not-an-int", "OpenRouter seed")

"""
Tests for OpenRouter models cache utility.
"""

import pytest
from utils.openrouter_models import (
    get_openrouter_models,
    refresh_openrouter_models,
    get_openrouter_model_by_id,
    _models_cache
)


@pytest.mark.asyncio
async def test_fetch_models():
    """Test fetching models from OpenRouter API."""
    # Clear cache first
    _models_cache.clear()

    models = await get_openrouter_models()

    assert isinstance(models, list)
    assert len(models) > 0
    assert 'id' in models[0]


@pytest.mark.asyncio
async def test_cache_hit():
    """Test that second fetch hits cache."""
    # Clear cache first
    _models_cache.clear()

    # First fetch (cache miss)
    models1 = await get_openrouter_models()

    # Second fetch (should hit cache)
    models2 = await get_openrouter_models()

    # Should be exact same object from cache
    assert models1 is models2
    assert len(models1) == len(models2)


@pytest.mark.asyncio
async def test_get_model_by_id():
    """Test getting a specific model by ID."""
    # Clear cache first
    _models_cache.clear()

    models = await get_openrouter_models()

    if models:
        test_id = models[0]['id']
        model = await get_openrouter_model_by_id(test_id)

        assert model is not None
        assert model['id'] == test_id
        print(f"✅ Found model: {model.get('name', 'unknown')}")


@pytest.mark.asyncio
async def test_refresh_models():
    """Test force refreshing models."""
    # Initial fetch
    models1 = await get_openrouter_models()

    # Force refresh (clears cache and fetches again)
    models2 = await refresh_openrouter_models()

    assert len(models2) > 0
    # Should be different object (not cached)
    assert models1 is not models2

"""
Tests for OpenRouter models cache utility.
"""

import pytest
from utils.openrouter_models import (
    get_openrouter_models,
    get_openrouter_models_sync,
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


def test_sync_fetch_models():
    """Test synchronous fetch."""
    # Clear cache first
    _models_cache.clear()

    # Fetch synchronously
    models = get_openrouter_models_sync()

    assert isinstance(models, list)
    assert len(models) > 0
    assert 'id' in models[0]
    print(f"✅ Fetched {len(models)} models (sync)")


def test_sync_cache_hit():
    """Test that sync fetch uses cache."""
    # Clear cache
    _models_cache.clear()

    # First fetch (cache miss)
    models1 = get_openrouter_models_sync()

    # Second fetch (should hit cache)
    models2 = get_openrouter_models_sync()

    # Should be exact same object from cache
    assert models1 is models2
    print(f"✅ Sync cache hit: {len(models2)} models")


def test_sync_cache_refresh_on_expiry():
    """Test that sync fetch refreshes when cache expires."""
    # Clear cache
    _models_cache.clear()

    # First fetch
    models1 = get_openrouter_models_sync()

    # Manually clear cache to simulate expiry
    _models_cache.clear()

    # Should fetch fresh data
    models2 = get_openrouter_models_sync()

    assert len(models2) > 0
    # Should be different object (re-fetched)
    assert models1 is not models2
    print(f"✅ Sync refresh on expiry: {len(models2)} models")

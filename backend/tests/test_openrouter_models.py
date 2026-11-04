"""
Tests for OpenRouter models cache utility. OpenRouter's /models answers through a fake at the HTTP boundary each fetch
uses (respx for httpx, ``requests.get`` for the sync path), so they run without the network.
"""

import json

import pytest
import requests
import respx

from utils import openrouter_models
from utils.openrouter_models import (
    OPENROUTER_API_URL,
    get_openrouter_models,
    get_openrouter_models_sync,
    _models_cache
)

MODELS = [{"id": "openai/gpt-5", "name": "GPT-5"}, {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5"}]


@pytest.fixture(autouse=True)
def empty_cache():
    _models_cache.clear()
    yield
    _models_cache.clear()


@pytest.fixture
def sync_api(monkeypatch):
    """``requests.get`` as the sync fetch calls it, answering OpenRouter's /models; returns the URLs it was asked."""
    asked = []

    def get(url, timeout):
        asked.append(url)
        answer = requests.Response()
        answer.status_code, answer.url = 200, url
        answer._content = json.dumps({"data": MODELS}).encode()
        return answer

    monkeypatch.setattr(openrouter_models.requests, "get", get)
    return asked


@pytest.mark.asyncio
@respx.mock
async def test_fetch_models():
    """Test fetching models from OpenRouter API."""
    route = respx.get(OPENROUTER_API_URL).respond(json={"data": MODELS})

    models = await get_openrouter_models()

    assert route.call_count == 1
    assert isinstance(models, list)
    assert models == MODELS
    assert 'id' in models[0]


@pytest.mark.asyncio
@respx.mock
async def test_cache_hit():
    """Test that second fetch hits cache."""
    route = respx.get(OPENROUTER_API_URL).respond(json={"data": MODELS})

    # First fetch (cache miss)
    models1 = await get_openrouter_models()

    # Second fetch (should hit cache)
    models2 = await get_openrouter_models()

    # Should be exact same object from cache, fetched once
    assert models1 is models2
    assert route.call_count == 1


def test_sync_fetch_models(sync_api):
    """Test synchronous fetch."""
    models = get_openrouter_models_sync()

    assert sync_api == [OPENROUTER_API_URL]
    assert isinstance(models, list)
    assert models == MODELS
    assert 'id' in models[0]


def test_sync_cache_hit(sync_api):
    """Test that sync fetch uses cache."""
    # First fetch (cache miss)
    models1 = get_openrouter_models_sync()

    # Second fetch (should hit cache)
    models2 = get_openrouter_models_sync()

    # Should be exact same object from cache, fetched once
    assert models1 is models2
    assert len(sync_api) == 1


def test_sync_cache_refresh_on_expiry(sync_api):
    """Test that sync fetch refreshes when cache expires."""
    # First fetch
    models1 = get_openrouter_models_sync()

    # Manually clear cache to simulate expiry
    _models_cache.clear()

    # Should fetch fresh data
    models2 = get_openrouter_models_sync()

    assert models2 == MODELS
    # Should be different object (re-fetched)
    assert models1 is not models2
    assert len(sync_api) == 2

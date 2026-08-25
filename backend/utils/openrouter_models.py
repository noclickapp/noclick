"""
Utility for fetching and caching OpenRouter models metadata.

Simple in-memory cache using cachetools with 10-minute TTL.
Provides both async (httpx) and sync (requests) fetch functions.
"""

import logging
from typing import Optional, List, Dict, Any
import httpx
import requests
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# In-memory cache with 10-minute TTL
# maxsize=1 because we only cache one key (the models list)
CACHE_TTL = 10 * 60  # 10 minutes in seconds
_models_cache = TTLCache(maxsize=1, ttl=CACHE_TTL)
CACHE_KEY = "models"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"


async def get_openrouter_models() -> List[Dict[str, Any]]:
    """
    Get OpenRouter models (cached with 10-minute TTL).

    Returns:
        List of model metadata dictionaries
    """
    # Check cache first
    if CACHE_KEY in _models_cache:
        logger.info(f"[OPENROUTER] Returning {len(_models_cache[CACHE_KEY])} models from cache")
        return _models_cache[CACHE_KEY]

    # Cache miss - fetch from API
    logger.info("[OPENROUTER] Cache miss, fetching from API")
    models = await _fetch_models_from_api()

    # Store in cache
    _models_cache[CACHE_KEY] = models
    logger.info(f"[OPENROUTER] Cached {len(models)} models with {CACHE_TTL}s TTL")

    return models


async def _fetch_models_from_api() -> List[Dict[str, Any]]:
    """
    Fetch models from OpenRouter API.

    Returns:
        List of model metadata dictionaries
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(OPENROUTER_API_URL)
        response.raise_for_status()

        data = response.json()
        models = data.get('data', [])

        logger.info(f"[OPENROUTER] Fetched {len(models)} models from API")
        return models


def get_openrouter_models_sync() -> List[Dict[str, Any]]:
    """
    Get OpenRouter models (cached with 10-minute TTL) - SYNC version.

    This is a synchronous version that uses requests instead of httpx.
    When cache expires, it fetches fresh data synchronously.

    Returns:
        List of model metadata dictionaries
    """
    # Check cache first
    if CACHE_KEY in _models_cache:
        logger.info(f"[OPENROUTER] Returning {len(_models_cache[CACHE_KEY])} models from cache (sync)")
        return _models_cache[CACHE_KEY]

    # Cache miss or expired - fetch synchronously
    logger.info("[OPENROUTER] Cache miss/expired, fetching from API (sync)")

    response = requests.get(OPENROUTER_API_URL, timeout=10)
    response.raise_for_status()

    data = response.json()
    models = data.get('data', [])

    logger.info(f"[OPENROUTER] Fetched {len(models)} models from API (sync)")

    # Store in cache
    _models_cache[CACHE_KEY] = models

    return models


async def refresh_openrouter_models() -> List[Dict[str, Any]]:
    """
    Force refresh models by clearing cache and fetching from API.

    Returns:
        List of model metadata dictionaries
    """
    logger.info("[OPENROUTER] Force refreshing models")

    # Clear cache
    _models_cache.clear()

    # Fetch fresh data
    return await get_openrouter_models()


async def get_openrouter_model_by_id(model_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific OpenRouter model by ID.

    Args:
        model_id: Model ID (e.g., "openai/gpt-4")

    Returns:
        Model metadata dictionary if found, None otherwise
    """
    models = await get_openrouter_models()

    for model in models:
        if model.get('id') == model_id:
            return model

    return None


async def ensure_models_cached() -> None:
    """
    Ensure OpenRouter models are cached.

    Useful to call during app startup or before creating LLMs
    to ensure cache is warm.
    """
    if CACHE_KEY not in _models_cache:
        logger.info("[OPENROUTER] Pre-populating models cache")
        await get_openrouter_models()
    else:
        logger.info("[OPENROUTER] Models cache already populated")

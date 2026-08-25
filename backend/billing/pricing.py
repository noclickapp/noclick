"""Operator-configured usage prices.

No provider catalogue or NoClick price schedule is embedded in the community
edition.  Optional prices come from the installation environment and otherwise
resolve to zero.  The exported names preserve shared node call sites.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional


def _price(name: str) -> Decimal:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return Decimal("0")
    value = Decimal(raw)
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


EMAIL_SEND_PRICE = _price("USAGE_PRICE_EMAIL_SEND")
AI_EXTRACTION_PRICE_PER_PAGE = _price("USAGE_PRICE_EXTRACTION_PAGE")
PERPLEXITY_SEARCH_REQUEST_PRICE = _price("USAGE_PRICE_SEARCH_REQUEST")


class _OperatorVideoRates(dict[str, Decimal]):
    """Mapping-compatible view used by a legacy video handler."""

    def get(self, _key: str, _default: Optional[Decimal] = None) -> Decimal:
        return _price("USAGE_PRICE_VIDEO_SECOND")


VEO_PRICE_PER_SECOND: dict[str, Decimal] = _OperatorVideoRates()


def get_veo_cost(_model_name: str, duration: int, n_videos: int) -> Decimal:
    return _price("USAGE_PRICE_VIDEO_SECOND") * duration * n_videos


def get_kling_video_cost(_model_name: str, duration: int, _mode: str) -> Decimal:
    return _price("USAGE_PRICE_VIDEO_SECOND") * duration


def get_kling_image_cost(_model_name: str) -> Decimal:
    return _price("USAGE_PRICE_IMAGE_REQUEST")


def get_x_cost(_operation_type: str, quantity: int) -> Decimal:
    return _price("USAGE_PRICE_API_RESOURCE") * quantity


def get_embedding_cost(tokens: int) -> Decimal:
    return (
        Decimal(int(tokens))
        / Decimal(1_000_000)
        * _price("USAGE_PRICE_EMBEDDING_MILLION_TOKENS")
    )

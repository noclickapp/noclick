"""What a metered unit costs.

Two kinds of number live here, and the difference is who publishes them.

A provider's list price is public: Google says what a second of Veo costs, and
an installation calling Veo on its own key pays exactly that. Those tables are
below, and they are the same in every edition — recording a provider cost of
zero would make the usage ledger a lie, and `markup.py` already says costs are
recorded at list price.

What a deployment charges FOR that work is its own business: the per-unit
prices come from the environment and default to zero, and the platform markup
lives in markup.py. Rate tables for something only a platform runs — its own
compute, priced per core-second — stay behind register_pricing().

Everything returns Decimal, and zero is a real answer: a cost of zero records
an event and charges nothing.
"""

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _price(name: str) -> Decimal:
    """A per-unit price from the environment, in dollars. Absent means free."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return Decimal("0")
    value = Decimal(raw)
    if value < 0:
        raise ValueError(f"{name} must not be negative; got {raw!r}")
    return value


EMAIL_SEND_PRICE = _price("PRICE_EMAIL_SEND")
AI_EXTRACTION_PRICE_PER_PAGE = _price("PRICE_AI_EXTRACTION_PER_PAGE")
SANDBOX_MINUTE_PRICE = _price("PRICE_SANDBOX_MINUTE")

# Credits a warm sandbox must have before a turn may start, so a legitimately
# started turn has runway before the uptime reaper can reach it.
SANDBOX_START_MIN_CREDITS = float(os.getenv("SANDBOX_START_MIN_CREDITS") or 0.0)


# ── Rate tables ──────────────────────────────────────────────────────────────

_impl: Optional[Any] = None


def register_pricing(impl: Any) -> None:
    """Install a platform's rate tables. Call before serving traffic."""
    global _impl
    _impl = impl
    logger.info(f"[pricing] Rate tables registered: {type(impl).__name__}")


def registered_pricing() -> Optional[Any]:
    return _impl


def _rate(name: str, *args, **kwargs) -> Decimal:
    if _impl is None:
        return Decimal("0")
    return getattr(_impl, name)(*args, **kwargs)


def get_modal_compute_cost(*args, **kwargs) -> Decimal:
    return _rate("get_modal_compute_cost", *args, **kwargs)


# ── Google Veo (Video Generation) ────────────────────────────────────────────
# Per-second pricing: https://ai.google.dev/gemini-api/docs/video
VEO_PRICE_PER_SECOND: Dict[str, Decimal] = {
    "veo-2.0-generate-001":          Decimal("0.35"),
    "veo-3.0-generate-001":          Decimal("0.50"),
    "veo-3.0-generate-preview":      Decimal("0.50"),
    "veo-3.0-fast-generate-preview": Decimal("0.15"),
    "veo-3.1-generate-preview":      Decimal("0.50"),
    "veo-3.1-fast-generate-preview": Decimal("0.15"),
}


def get_veo_cost(model_name: str, duration: int, n_videos: int) -> Decimal:
    """Calculate Veo video generation cost: per-second x duration x clip count."""
    price_per_sec = VEO_PRICE_PER_SECOND.get(model_name, Decimal("0.50"))
    return price_per_sec * duration * n_videos


# ── Kling AI (Video Generation) ─────────────────────────────────────────────
# Based on official Kling API pricing: https://klingai.com/global/dev/pricing
# Key: (model_name, duration_seconds, mode) → price in USD.
# For per-second models (v3+), duration is 1; caller multiplies by actual duration.
# For fixed-duration models (v2.6 and below), use exact duration (5 or 10).
KLING_VIDEO_PRICES: Dict[Tuple[str, int, str], Decimal] = {
    # V3 Omni — per-second pricing
    ("kling-v3-omni", 1, "std"): Decimal("0.084"),
    ("kling-v3-omni", 1, "pro"): Decimal("0.112"),
    # V3 — per-second pricing
    ("kling-v3", 1, "std"): Decimal("0.084"),
    ("kling-v3", 1, "pro"): Decimal("0.126"),
    # Video O1 — per-second pricing
    ("kling-video-o1", 1, "std"): Decimal("0.084"),
    ("kling-video-o1", 1, "pro"): Decimal("0.112"),
    # V2.6 — fixed-duration pricing
    ("kling-v2-6", 5, "std"): Decimal("0.21"),
    ("kling-v2-6", 5, "pro"): Decimal("0.35"),
    ("kling-v2-6", 10, "std"): Decimal("0.42"),
    ("kling-v2-6", 10, "pro"): Decimal("0.70"),
    # V2.5 Turbo — fixed-duration pricing
    ("kling-v2-5-turbo", 5, "std"): Decimal("0.21"),
    ("kling-v2-5-turbo", 5, "pro"): Decimal("0.35"),
    ("kling-v2-5-turbo", 10, "std"): Decimal("0.42"),
    ("kling-v2-5-turbo", 10, "pro"): Decimal("0.70"),
    # V2.1 Master — fixed-duration pricing
    ("kling-v2-1-master", 5, "std"): Decimal("0.28"),
    ("kling-v2-1-master", 5, "pro"): Decimal("0.49"),
    ("kling-v2-1-master", 10, "std"): Decimal("0.56"),
    ("kling-v2-1-master", 10, "pro"): Decimal("0.98"),
    # V1.6 — fixed-duration pricing
    ("kling-v1-6", 5, "std"): Decimal("0.28"),
    ("kling-v1-6", 5, "pro"): Decimal("0.49"),
    ("kling-v1-6", 10, "std"): Decimal("0.56"),
    ("kling-v1-6", 10, "pro"): Decimal("0.98"),
    # V1.5 — fixed-duration pricing
    ("kling-v1-5", 5, "std"): Decimal("0.14"),
    ("kling-v1-5", 5, "pro"): Decimal("0.49"),
    ("kling-v1-5", 10, "std"): Decimal("0.28"),
    ("kling-v1-5", 10, "pro"): Decimal("0.98"),
    # V1 — fixed-duration pricing
    ("kling-v1", 5, "std"): Decimal("0.14"),
    ("kling-v1", 5, "pro"): Decimal("0.49"),
    ("kling-v1", 10, "std"): Decimal("0.28"),
    ("kling-v1", 10, "pro"): Decimal("0.98"),
}


def get_kling_video_cost(model_name: str, duration: int, mode: str) -> Decimal:
    """Look up Kling video generation cost.

    For per-second models (v3+), returns price * duration.
    For fixed-duration models, returns the fixed price for that duration.
    """
    per_sec_key = (model_name, 1, mode)
    if per_sec_key in KLING_VIDEO_PRICES:
        return KLING_VIDEO_PRICES[per_sec_key] * duration

    fixed_key = (model_name, duration, mode)
    if fixed_key in KLING_VIDEO_PRICES:
        return KLING_VIDEO_PRICES[fixed_key]

    # Conservative default
    return Decimal("0.35")


# ── Kling AI (Image Generation) ─────────────────────────────────────────────
# Flat per-request pricing.
KLING_IMAGE_PRICES: Dict[str, Decimal] = {
    "kling-image-o1": Decimal("0.028"),
    "kling-v2-1-image": Decimal("0.014"),
    "kling-v2-image": Decimal("0.014"),
}


def get_kling_image_cost(model_name: str) -> Decimal:
    """Look up Kling image generation cost."""
    return KLING_IMAGE_PRICES.get(model_name, Decimal("0.028"))


# ── X/Twitter API (pay-per-use) ──────────────────────────────────────────────
# Per-resource pricing: https://developer.x.com/en/docs/x-api/getting-started/pricing
# Billing is per individual resource returned (not per HTTP request).
# Only successful responses are billed; zero-result reads cost nothing.
X_OPERATION_PRICES: Dict[str, Decimal] = {
    "post_read":        Decimal("0.005"),   # GET /tweets, search, timelines, liked_tweets, etc.
    "user_lookup":      Decimal("0.010"),   # GET /users, followers, following, liking_users, etc.
    "post_create":      Decimal("0.010"),   # POST /tweets
    "user_interaction": Decimal("0.015"),   # POST likes, retweets, follows
    "dm_event_read":    Decimal("0.010"),   # GET /dm_conversations events, /dm_events
    "dm_create":        Decimal("0.015"),   # POST /dm_conversations, DM messages
}


def get_x_cost(operation_type: str, quantity: int) -> Decimal:
    """Calculate X API cost based on operation type and resource count."""
    return X_OPERATION_PRICES.get(operation_type, Decimal("0")) * quantity


# ── Embeddings (NoClick-keyed, for document upload/ingest into vector DBs) ────
# text-embedding-3-small list price is $0.02 / 1M tokens. Charged at real cost
# (no markup) so uploading a document to index doesn't have NoClick eat the
# embedding bill. Providers that embed server-side on the user's own account
# (e.g. Upstash upsert-data) skip this entirely.
EMBEDDING_PRICE_PER_1M_TOKENS = Decimal("0.02")


def get_embedding_cost(tokens: int) -> Decimal:
    """Embedding cost for `tokens` of text-embedding-3-small input."""
    return (Decimal(int(tokens)) / Decimal(1_000_000)) * EMBEDDING_PRICE_PER_1M_TOKENS


# ── Perplexity Search API (platform-keyed perplexity node) ────────────────────
# Published rate: $5 / 1k requests. The /search response carries no cost object
# (unlike chat completions' in-band usage.cost), so the raw provider cost is
# this flat per-request price; the platform markup applies on top at the call
# site (perplexity_node._track_platform_usage).
PERPLEXITY_SEARCH_REQUEST_PRICE = Decimal("0.005")

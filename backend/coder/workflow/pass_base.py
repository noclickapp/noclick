# Provider-neutral helpers used by the community builder's model calls.

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import litellm

from .builder_config import BRAIN_PRIMARY_MODEL


logger = logging.getLogger(__name__)


# Live output-counter cadence shared by community model streams.
TOKEN_PROGRESS_INTERVAL_S = float(os.environ.get("NOCLICK_TOKEN_PROGRESS_INTERVAL_MS", "300")) / 1000.0


# LiteLLM exception classes that represent transient failures worth retrying.
# Matched by class name because litellm's exception hierarchy is partially
# dynamic. Shared with the agentic brain so both layers retry on the same set.
_TRANSIENT_LLM_ERROR_NAMES: frozenset = frozenset({
    'APIConnectionError',
    'Timeout',
    'APITimeoutError',
    # On Python 3.11+ `asyncio.TimeoutError` IS the builtin `TimeoutError`
    # (same class object — `asyncio.TimeoutError = TimeoutError`), so this
    # one name covers both. It's the class raised by the node drafter inter-chunk
    # `asyncio.wait_for` when a provider stalls mid-stream.
    'TimeoutError',
    'ServiceUnavailableError',
    'InternalServerError',
    'RateLimitError',
    'MidStreamFallbackError',
})


def is_transient_llm_error(exc: BaseException) -> bool:
    """True if the error is a transient provider issue that a retry can fix.

    Walks the exception cause chain so wrapped errors (e.g. an HTTP timeout
    raised inside a litellm wrapper) still match.
    """
    name = type(exc).__name__
    if name in _TRANSIENT_LLM_ERROR_NAMES:
        return True
    cause = exc.__cause__ or exc.__context__
    if cause and cause is not exc:
        return is_transient_llm_error(cause)
    return False


# ── Model-call utilities ────────────────────────────────────────────────

def build_provider_extra_body(
    model: str,
    provider_order: Optional[List[str]] = None,
    provider_sort: Optional[str] = None,
) -> dict:
    """Build OpenRouter provider preferences for litellm extra_body.

    Everything here (``provider`` routing prefs, ``usage.include``) is an
    OpenRouter-only extension. litellm merges extra_body verbatim into the
    outbound JSON, and strict providers reject unknown properties (Groq 400s
    ``property 'usage' is unsupported``) — so non-OpenRouter models get {}.
    """
    if not model.startswith('openrouter/'):
        return {}
    extra_body: Dict[str, Any] = {}
    provider_opts: Dict[str, Any] = {}
    if provider_order:
        provider_opts['order'] = provider_order        # An explicit order is a hard operator choice; do not silently route elsewhere.
        provider_opts['allow_fallbacks'] = False
    if provider_sort:
        provider_opts['sort'] = provider_sort
    if provider_opts:
        extra_body['provider'] = provider_opts
    # Ask OpenRouter to include provider-reported cost for models absent from
    # the local LiteLLM pricing database.
    extra_body['usage'] = {'include': True}
    return extra_body


@dataclass
class StreamingCostResult:
    """Cost, token, and routing breakdown from a streaming LLM call."""
    cost: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0    # Resolved model/provider metadata for operator diagnostics.
    model: Optional[str] = None
    provider: Optional[str] = None
    # OpenRouter generation id (gen-...). Used to resolve ``provider`` via
    # the generation endpoint when litellm strips the inline field.
    generation_id: Optional[str] = None


def extract_response_provider(combined: Any, chunks: list) -> Optional[str]:
    """Pull the OpenRouter upstream-provider name from a streaming response.

    OpenRouter returns ``provider`` at the top level, but litellm's response
    models drop unknown fields, so it's rarely accessible directly. Try the
    handful of places it *might* land (top-level attr, forwarded header,
    per-chunk payload) before giving up. The reliable path is
    ``fetch_openrouter_provider`` which queries OpenRouter's generation
    endpoint by id — call that when this returns None.
    """
    provider = getattr(combined, 'provider', None)
    if provider:
        return str(provider)
    hidden = getattr(combined, '_hidden_params', None)
    if isinstance(hidden, dict):
        headers = hidden.get('additional_headers') or {}
        if isinstance(headers, dict):
            for key in ('x-or-provider', 'openrouter-provider'):
                val = headers.get(key)
                if val:
                    return str(val)
    for chunk in chunks:
        prov = getattr(chunk, 'provider', None)
        if prov:
            return str(prov)
    return None


def extract_generation_id(combined: Any, chunks: list) -> Optional[str]:
    """OpenRouter generation id (gen-...) — litellm preserves it in hidden_params."""
    for obj in (combined, *chunks):
        if obj is None:
            continue
        hidden = getattr(obj, '_hidden_params', None)
        if isinstance(hidden, dict):
            gid = hidden.get('received_model_id') or hidden.get('id')
            if gid and isinstance(gid, str) and gid.startswith('gen-'):
                return gid
    return None


async def fetch_openrouter_provider(
    generation_id: Optional[str],
    *,
    timeout: float = 3.0,
) -> Optional[str]:
    """Look up the upstream provider that served an OpenRouter generation.

    Litellm strips the top-level ``provider`` field from OpenRouter responses,
    but the generation id (gen-...) survives. Resolve via the documented
    ``/api/v1/generation`` endpoint. Failures are swallowed — the log entry
    simply records ``provider=None`` and SessionViewer hides the field.
    """
    if not generation_id:
        return None
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f'https://openrouter.ai/api/v1/generation?id={generation_id}',
                headers={'Authorization': f'Bearer {api_key}'},
            )
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get('data') or {}
            provider = data.get('provider_name')
            return str(provider) if provider else None
    except Exception:
        return None


def extract_streaming_cost(chunks: list, messages: list) -> StreamingCostResult:
    """Extract cost, token usage, and routing metadata from litellm streaming chunks.

    Cost resolution order:
      1. ``usage.cost`` from OpenRouter (requires ``extra_body.usage.include``
         and ``stream_options.include_usage`` on the request). Works for any
         model OpenRouter prices, including ones litellm doesn't know about.
      2. ``litellm.completion_cost()`` — works for models in litellm's pricing
         DB. Raises for unmapped models, which is why we try OpenRouter first.

    Token counts and routing metadata (model + provider) are extracted
    independently of cost resolution so an unmapped model doesn't wipe out
    usage data alongside the missing cost.
    """
    result = StreamingCostResult()
    try:
        combined = litellm.stream_chunk_builder(chunks, messages=messages)
    except Exception:
        return result

    result.model = getattr(combined, 'model', None)
    result.provider = extract_response_provider(combined, chunks)
    result.generation_id = extract_generation_id(combined, chunks)

    if hasattr(combined, 'usage') and combined.usage:
        result.total_tokens = getattr(combined.usage, 'total_tokens', 0) or 0
        result.input_tokens = getattr(combined.usage, 'prompt_tokens', 0) or 0
        result.output_tokens = getattr(combined.usage, 'completion_tokens', 0) or 0
        openrouter_cost = getattr(combined.usage, 'cost', None)
        if openrouter_cost is not None:
            result.cost = float(openrouter_cost)
            return result

    try:
        result.cost = float(litellm.completion_cost(completion_response=combined) or 0.0)
    except Exception:
        pass
    return result


# ── Base class for node drafting ─────────────────────────────────────


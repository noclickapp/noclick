"""Model lists for the CLI harnesses whose pickers query a live catalogue.

These read public catalogues — OpenRouter's /api/v1/models, models.dev — and
nothing about how a harness is executed, so they belong with the other config
helpers rather than inside the hosted handler modules. They lived there before,
which meant selecting a model for opencode, hermes or openclaw raised
ModuleNotFoundError in any build without those handlers: three of the five
harnesses had an unusable model dropdown.

The handlers re-export from here, so there is one implementation.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


# ── opencode ────────────────────────────────────────────────────

_OPENCODE_MODELS_CACHE: Optional[List] = None
_OPENCODE_MODELS_CACHE_TIME: float = 0
_OPENCODE_MODELS_CACHE_TTL = 3600
async def _get_zen_servable_ids() -> Optional[set]:
    """Live set of model IDs OpenCode Zen will actually serve — models.dev is
    a historical SUPERSET that keeps rotated-out models the CLI rejects with
    ProviderModelNotFoundError, so the picker filters to this. Module-level
    delegate (tests stub it) to the shared cached fetch in utils/opencode_zen,
    which the model catalog's Zen source shares."""
    from utils.opencode_zen import get_zen_servable_ids

    return await get_zen_servable_ids("opencode")
async def _fetch_models_dev() -> dict:
    """The raw models.dev catalog (metadata source for the picker). Module-level
    delegate (tests stub it) to the shared cached fetch in utils/opencode_zen."""
    from utils.opencode_zen import fetch_models_dev

    return await fetch_models_dev()
def _is_chatgpt_plus_supported(model_id: str) -> bool:
    """Check whether an openai/* sub-model is reachable via ChatGPT Plus OAuth.

    Single source of truth: `backend/nodes/agent/config/_cli_models.json`
    — the curated Codex model list extracted from the `@openai/codex`
    binary by `scripts/refresh_cli_models.py` and refreshed daily by the
    `refresh-cli-models` GitHub workflow. When OpenAI ships a new
    ChatGPT-Plus-eligible model the JSON updates automatically, no code
    change.

    Same JSON powers the Codex node's model dropdown — so the OpenCode
    wrapper's OAuth gate is guaranteed to stay aligned with what the
    standalone Codex wrapper accepts.
    """
    from nodes.agent.config._cli_models_loader import codex_models
    return model_id in set(codex_models())
async def fetch_opencode_models() -> List[Dict[str, str]]:
    """Fetch and cache the OpenCode model picker list.

    Metadata (labels, context, cost) comes from models.dev/api.json; the
    opencode/* (Zen) provider is then filtered to Zen's live servable set
    (the tier's live /models endpoint) so the picker never offers a model the CLI
    would reject at runtime with ProviderModelNotFoundError.
    """
    import time as _time
    global _OPENCODE_MODELS_CACHE, _OPENCODE_MODELS_CACHE_TIME

    now = _time.time()
    if _OPENCODE_MODELS_CACHE is not None and (now - _OPENCODE_MODELS_CACHE_TIME) < _OPENCODE_MODELS_CACHE_TTL:
        return _OPENCODE_MODELS_CACHE

    try:
        data = await _fetch_models_dev()
    except Exception as e:
        logger.warning(f"[OpenCode] Failed to fetch models from models.dev: {e}")
        if _OPENCODE_MODELS_CACHE is not None:
            return _OPENCODE_MODELS_CACHE
        return []

    zen_servable = await _get_zen_servable_ids()
    if zen_servable is None:
        # Can't determine the servable set and nothing cached — never reintroduce
        # the unservable superset. Serve the last good list if we have one;
        # otherwise build with opencode/* dropped (non-Zen providers still show).
        if _OPENCODE_MODELS_CACHE is not None:
            return _OPENCODE_MODELS_CACHE
        zen_servable = set()

    priority_providers = [
        "opencode", "anthropic", "openai", "google", "xai", "groq",
        "deepseek", "mistral", "openrouter",
    ]
    free_providers = ["opencode-go", "github-models", "nvidia"]

    def _make_label(provider_name, name, is_free, ctx, oauth_badges=None):
        # Append the subscription sign-in badges shipped by this edition
        # so the picker tells users at a glance which models are
        # subscription-OAuth eligible — matters because opencode-ai's
        # CodexAuthPlugin only accepts a restricted gpt-5.X subset for
        # ChatGPT Plus (see _is_chatgpt_plus_supported); picking a
        # non-supported openai/* with only an OAuth credential would
        # 401 at runtime.
        parts = [name]
        if is_free:
            parts.append("Free")
        if ctx >= 1_000_000:
            parts.append(f"{ctx // 1_000_000}M context")
        elif ctx >= 100_000:
            parts.append(f"{ctx // 1000}K context")
        label = f"[{provider_name}] {' - '.join(parts)}"
        if oauth_badges:
            label = f"{label} · {', '.join(oauth_badges)}"
        return label

    free_options: List[Dict[str, str]] = []
    paid_options: List[Dict[str, str]] = []
    seen_providers: set = set()

    def _oauth_badges_for(provider_id: str, model_id: str) -> List[str]:
        """Which subscription-OAuth flows accept this model. Used to
        annotate the picker label so users see at a glance which
        models are reachable via their subscription.

        Mirrors opencode-ai's plugin filters:
          • CodexAuthPlugin (codex.ts): ChatGPT Plus accepts the
            gpt-5.X subset defined in _is_chatgpt_plus_supported.          • Anthropic Claude Pro/Max: badge added when the optional
            opencode-claude-auth plugin is installed.
        """
        badges: List[str] = []
        if provider_id == 'openai' and _is_chatgpt_plus_supported(model_id):
            badges.append('ChatGPT Plus')
        if provider_id == 'anthropic':
            # Re-enabled via the vendored opencode-claude-auth plugin;
            # the badge tells users a Claude Pro/Max subscription works
            # here. Anthropic doesn't officially support this but does
            # not enforce against it in practice.
            badges.append('Claude Pro/Max')
        return badges

    for provider_id in priority_providers:
        provider = data.get(provider_id)
        if not provider:
            continue
        seen_providers.add(provider_id)
        provider_name = provider.get('name', provider_id)
        for model_id, model in provider.get('models', {}).items():
            if not model.get('tool_call', False):
                continue
            # The opencode/* (Zen) provider is the one models.dev oversells —
            # only offer what Zen actually serves, else the CLI 404s at runtime.
            if provider_id == 'opencode' and model_id not in zen_servable:
                continue
            cost = model.get('cost', {})
            is_free = cost.get('input', 1) == 0 and cost.get('output', 1) == 0
            ctx = model.get('limit', {}).get('context', 0)
            name = model.get('name', model_id)
            badges = _oauth_badges_for(provider_id, model_id)
            entry = {
                "value": f"{provider_id}/{model_id}",
                "label": _make_label(provider_name, name, is_free, ctx, badges),
            }
            (free_options if is_free else paid_options).append(entry)

    for provider_id in free_providers:
        if provider_id in seen_providers:
            continue
        provider = data.get(provider_id)
        if not provider:
            continue
        provider_name = provider.get('name', provider_id)
        for model_id, model in provider.get('models', {}).items():
            if not model.get('tool_call', False):
                continue
            cost = model.get('cost', {})
            if cost.get('input', 1) != 0 or cost.get('output', 1) != 0:
                continue
            ctx = model.get('limit', {}).get('context', 0)
            name = model.get('name', model_id)
            badges = _oauth_badges_for(provider_id, model_id)
            free_options.append({
                "value": f"{provider_id}/{model_id}",
                "label": _make_label(provider_name, name, True, ctx, badges),
            })

    options = free_options + paid_options
    _OPENCODE_MODELS_CACHE = options
    _OPENCODE_MODELS_CACHE_TIME = now
    logger.info(f"[OpenCode] Cached {len(options)} models from models.dev")
    return options


# ── hermes_agent ────────────────────────────────────────────────

_HERMES_MODELS_CACHE: Optional[List] = None
_HERMES_MODELS_CACHE_TIME: float = 0
_HERMES_MODELS_CACHE_TTL = 3600
_HERMES_SUPPORTED_PROVIDERS = [
    "openrouter", "anthropic", "openai", "google",
    "groq", "deepseek", "mistral",
]
_REASONING_MODEL_BLOCKLIST = (
    "deepseek-r1", "deepseek-r2",
    "/o1", "o1-", "/o3", "o3-",
    "qwq",
)
_HERMES_FALLBACK_MODELS: List[Dict[str, str]] = [
    {"value": "openrouter/nousresearch/hermes-3-llama-3.1-70b", "label": "[OpenRouter] Hermes 3 70B"},
    {"value": "openrouter/anthropic/claude-sonnet-4-5", "label": "[OpenRouter] Claude Sonnet 4.5"},
    {"value": "openrouter/openai/gpt-4o", "label": "[OpenRouter] GPT-4o"},
    {"value": "anthropic/claude-sonnet-4-5", "label": "[Anthropic] Claude Sonnet 4.5"},
    {"value": "openai/gpt-4o", "label": "[OpenAI] GPT-4o"},
]
def _make_model_label(provider_name: str, model_name: str, ctx: int) -> str:
    parts = [model_name]
    if ctx >= 1_000_000:
        parts.append(f"{ctx // 1_000_000}M ctx")
    elif ctx >= 100_000:
        parts.append(f"{ctx // 1000}K ctx")
    return f"[{provider_name}] {' - '.join(parts)}"
def _is_reasoning_model(model_id: str) -> bool:
    model_id_lower = model_id.lower()
    return any(p in model_id_lower for p in _REASONING_MODEL_BLOCKLIST)
async def _fetch_openrouter_models(client) -> List[Dict[str, str]]:
    """
    Fetch tool-capable OpenRouter models from OpenRouter's own API.

    OpenRouter's /api/v1/models includes a `supported_parameters` list per model.
    Only models with "tools" in that list actually accept function-calling requests.
    This is the authoritative source — unlike models.dev, it reflects real availability.
    """
    resp = await client.get("https://openrouter.ai/api/v1/models")
    resp.raise_for_status()
    data = resp.json()

    options: List[Dict[str, str]] = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if not model_id:
            continue
        # Only models with confirmed tool/function-calling support
        if "tools" not in model.get("supported_parameters", []):
            continue
        if _is_reasoning_model(model_id):
            continue
        name = model.get("name", model_id)
        ctx = model.get("context_length", 0)
        options.append({
            "value": f"openrouter/{model_id}",
            "label": _make_model_label("OpenRouter", name, ctx),
        })
    return options
async def _fetch_other_provider_models(client) -> List[Dict[str, str]]:
    """Fetch tool-capable models for non-OpenRouter providers from models.dev."""
    resp = await client.get("https://models.dev/api.json")
    resp.raise_for_status()
    data = resp.json()

    other_providers = [p for p in _HERMES_SUPPORTED_PROVIDERS if p != "openrouter"]
    options: List[Dict[str, str]] = []
    for provider_id in other_providers:
        provider = data.get(provider_id)
        if not provider:
            continue
        provider_name = provider.get("name", provider_id)
        for model_id, model in provider.get("models", {}).items():
            if not model.get("tool_call", False):
                continue
            if _is_reasoning_model(model_id):
                continue
            ctx = model.get("limit", {}).get("context", 0)
            name = model.get("name", model_id)
            options.append({
                "value": f"{provider_id}/{model_id}",
                "label": _make_model_label(provider_name, name, ctx),
            })
    return options
async def fetch_hermes_agent_models() -> List[Dict[str, str]]:
    """
    Fetch and cache Hermes Agent-compatible models.

    OpenRouter models come from OpenRouter's own /api/v1/models endpoint which has
    accurate `supported_parameters` data — only models with "tools" support are included.
    This prevents showing models that have no tool-capable endpoints (e.g. preview models,
    models only available via non-tool routes). Other providers come from models.dev.
    """
    global _HERMES_MODELS_CACHE, _HERMES_MODELS_CACHE_TIME

    now = time.time()
    if _HERMES_MODELS_CACHE is not None and (now - _HERMES_MODELS_CACHE_TIME) < _HERMES_MODELS_CACHE_TTL:
        return _HERMES_MODELS_CACHE

    import httpx
    options: List[Dict[str, str]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # OpenRouter: use their own API for accurate availability + tool support
        try:
            options.extend(await _fetch_openrouter_models(client))
            logger.info(f"[HermesAgent] Fetched {sum(1 for m in options if m['value'].startswith('openrouter/'))} OpenRouter models")
        except Exception as e:
            logger.warning(f"[HermesAgent] Failed to fetch OpenRouter models: {e}")
            options.extend(m for m in _HERMES_FALLBACK_MODELS if m["value"].startswith("openrouter/"))

        # Other providers (anthropic, openai, google, groq, etc.): use models.dev
        try:
            options.extend(await _fetch_other_provider_models(client))
        except Exception as e:
            logger.warning(f"[HermesAgent] Failed to fetch other provider models: {e}")
            options.extend(m for m in _HERMES_FALLBACK_MODELS if not m["value"].startswith("openrouter/"))

    if not options:
        logger.warning("[HermesAgent] No models fetched, using fallback list")
        return _HERMES_FALLBACK_MODELS

    _HERMES_MODELS_CACHE = options
    _HERMES_MODELS_CACHE_TIME = now
    logger.info(f"[HermesAgent] Cached {len(options)} models total")
    return options


# ── openclaw ────────────────────────────────────────────────────

async def fetch_openclaw_models() -> List[Dict[str, str]]:
    """OpenClaw accepts the same tool-capable provider/model ids as Hermes."""
    return await fetch_hermes_agent_models()

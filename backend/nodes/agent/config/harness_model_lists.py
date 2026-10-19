"""Model lists for the CLI harnesses whose pickers query a live catalogue.

These read public catalogues — OpenRouter's /api/v1/models, models.dev — and
nothing about how a harness is executed, so they belong with the other config
helpers rather than inside the hosted handler modules. They lived there before,
which meant selecting a model for opencode, hermes or openclaw raised
ModuleNotFoundError in any build without those handlers: three of the five
harnesses had an unusable model dropdown.

The handlers re-export from here, so there is one implementation.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


# ── opencode ────────────────────────────────────────────────────

_OPENCODE_MODELS_CACHE: Optional[List] = None
_OPENCODE_MODELS_CACHE_TIME: float = 0
_OPENCODE_MODELS_CACHE_TTL = 3600
async def _get_zen_servable_ids(tier: str = "opencode", timeout: Optional[float] = None) -> Optional[set]:
    """Live set of model IDs a Zen tier will actually serve — models.dev is
    a historical SUPERSET that keeps rotated-out models the CLI rejects with
    ProviderModelNotFoundError, so the picker filters to this. Module-level
    delegate (tests stub it) to the shared cached fetch in utils/opencode_zen,
    which the model catalog's Zen source shares."""
    from utils.opencode_zen import get_zen_servable_ids

    return await get_zen_servable_ids(tier, timeout=timeout)
async def _fetch_models_dev(timeout: Optional[float] = None) -> dict:
    """The raw models.dev catalog (metadata source for the picker). Module-level
    delegate (tests stub it) to the shared cached fetch in utils/opencode_zen."""
    from utils.opencode_zen import fetch_models_dev

    return await fetch_models_dev(timeout=timeout)


def _fetch_models_dev_sync() -> dict:
    """Sync sibling of :func:`_fetch_models_dev` (same cache) for write-time checks."""
    from utils.opencode_zen import fetch_models_dev_sync

    return fetch_models_dev_sync()


def _models_dev_cached() -> Optional[dict]:
    """The catalog already read, never reading it (tests stub it)."""
    from utils.opencode_zen import read_models_dev_cache

    return read_models_dev_cache()

# Subscription sign-ins a platform registers (cloud registers its own): the
# picker badge for a provider's models, and whether its models list as free.
SUBSCRIPTION_BADGES: Dict[str, str] = {}
SUBSCRIPTION_FREE_PROVIDERS: List[str] = []


def register_provider_badge(provider_id: str, badge: str, *, free: bool = False) -> None:
    SUBSCRIPTION_BADGES[provider_id] = badge
    if free and provider_id not in SUBSCRIPTION_FREE_PROVIDERS:
        SUBSCRIPTION_FREE_PROVIDERS.append(provider_id)

def _cli_drop_reason(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why OpenCode's own catalog drops this models.dev entry, or None if it
    keeps it: the CLI drops deprecated and alpha models and refuses an id it
    doesn't list with ProviderModelNotFoundError, which `opencode serve`
    answers as a bare 500."""
    if not entry:
        return "it isn't in OpenCode's model list"
    if entry.get("status") == "deprecated":
        return "OpenCode retired it"
    if entry.get("status") == "alpha":
        return "OpenCode only lists it as an experimental model"
    return None


def _cli_lists(entry: Optional[Dict[str, Any]]) -> bool:
    return _cli_drop_reason(entry) is None


def _is_free(entry: Dict[str, Any]) -> bool:
    cost = entry.get("cost") or {}
    return cost.get("input", 1) == 0 and cost.get("output", 1) == 0


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
    from nodes.agent.config._cli_models_loader import codex_models, codex_retired_models
    # Retired ids are hidden from the picker but still served (codex names a
    # replacement), so a saved selection keeps working instead of being gated.
    return model_id in set(codex_models()) or model_id in codex_retired_models()
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
    free_providers = ["opencode-go", "github-models", "nvidia", *SUBSCRIPTION_FREE_PROVIDERS]

    def _make_label(provider_name, name, is_free, ctx, oauth_badges=None):
        # Append "[ChatGPT Plus]" / "[SuperGrok]" / "[Copilot]" badges
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
            gpt-5.X subset defined in _is_chatgpt_plus_supported.
          • Registered sign-ins (register_provider_badge) add their own badge.
        A Claude plan runs only in Claude Code, so anthropic/* gets none.
        """
        badges: List[str] = []
        if provider_id == 'openai' and _is_chatgpt_plus_supported(model_id):
            badges.append('ChatGPT Plus')
        if provider_id in SUBSCRIPTION_BADGES:
            badges.append(SUBSCRIPTION_BADGES[provider_id])
        return badges

    for provider_id in priority_providers:
        provider = data.get(provider_id)
        if not provider:
            continue
        seen_providers.add(provider_id)
        provider_name = provider.get('name', provider_id)
        for model_id, model in provider.get('models', {}).items():
            if not model.get('tool_call', False) or not _cli_lists(model):
                continue
            # The opencode/* (Zen) provider is the one models.dev oversells —
            # only offer what Zen actually serves, else the CLI 404s at runtime.
            if provider_id == 'opencode' and model_id not in zen_servable:
                continue
            is_free = _is_free(model)
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
            if not model.get('tool_call', False) or not _cli_lists(model):
                continue
            if not _is_free(model):
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


# The bound on each catalog read a turn's pre-flight makes; a source that just
# failed answers from its last good copy without waiting (utils/opencode_zen).
_PREFLIGHT_TIMEOUT_S = 3.0

# Providers whose model list an opencode plugin replaces at run time (Copilot's
# live /models with a Copilot sign-in, Modal's and DigitalOcean's deployments;
# packages/opencode/src/plugin/ at the pinned version): models.dev can't judge them.
_PLUGIN_LISTED_PROVIDERS = frozenset({"github-copilot", "modal", "digitalocean"})


def _unoffered_reason(
    provider: str, model_id: str, catalog: Optional[Dict[str, Any]], servable: Optional[set], judge_catalog: bool,
) -> Optional[str]:
    """Why OpenCode can't run ``provider/model_id`` now, or None when it can or
    nothing read here can tell. ``servable`` is the Zen tier's live list (None off
    Zen or unread); ``judge_catalog`` says the CLI's list is exactly models.dev's."""
    if servable is not None and model_id not in servable:
        return "OpenCode Zen no longer serves it"
    if not judge_catalog:
        return None
    listed = ((catalog or {}).get(provider) or {}).get("models")
    if not isinstance(listed, dict):
        return None
    return _cli_drop_reason(listed.get(model_id))


def _offered_instead(
    provider: str, catalog: Optional[Dict[str, Any]], servable: Optional[set], judge_catalog: bool,
    exclude: str, env: Dict[str, str],
) -> List[str]:
    """What to pick instead of an unoffered model, from the provider the agent's
    credential already reaches: NoClick's default when it is that provider's and
    offered, else up to three offered models of it (free first on Zen, else newest)."""
    from nodes.agent.config._cli_models_loader import harness_default_model
    from utils.opencode_zen import ZEN_TIER_BASE_URLS

    def offered(model_id: str) -> bool:
        return _unoffered_reason(provider, model_id, catalog, servable, judge_catalog) is None

    default_provider, _, default_id = harness_default_model("opencode").partition("/")
    if default_provider == provider and f"{provider}/{default_id}" != exclude and offered(default_id):
        return [f"{provider}/{default_id}"]
    plan_only = provider == "openai" and env.get("CODEX_ACCESS_TOKEN") and not env.get("OPENAI_API_KEY")
    candidates = [
        (model_id, entry)
        for model_id, entry in (((catalog or {}).get(provider) or {}).get("models") or {}).items()
        if f"{provider}/{model_id}" != exclude and entry.get("tool_call") and _cli_lists(entry) and offered(model_id)
        and not (plan_only and not _is_chatgpt_plus_supported(model_id))
    ]
    if provider in ZEN_TIER_BASE_URLS:
        candidates = sorted(c for c in candidates if _is_free(c[1]))
    else:
        candidates.sort(key=lambda c: c[1].get("release_date") or "", reverse=True)
    return [f"{provider}/{model_id}" for model_id, _ in candidates[:3]]


async def opencode_model_refusal(
    opencode_model: str, env: Optional[Dict[str, str]] = None, *, catalog_is_the_cli_list: bool,
) -> Optional[str]:
    """Pre-flight for an OpenCode turn: the error naming why ``provider/model``
    can't run and what to pick instead, or None to run it.

    A Zen model must be on its tier's live list (Zen rotates its free models
    out). Where ``catalog_is_the_cli_list`` (NoClick's hosted config adds no
    models), the CLI's list is models.dev without deprecated and alpha entries,
    so a model missing there is refused too, except on providers a plugin lists
    at run time. Elsewhere (the open edition, whose opencode config can define
    models) models.dev judges nothing. Unchecked, a gone model reaches `opencode
    serve` and the turn fails with a bare HTTP 500. A catalog that can't be read
    within the bound judges nothing.
    """
    from utils.opencode_zen import ZEN_TIER_BASE_URLS

    provider, _, model_id = opencode_model.partition("/")
    zen = provider in ZEN_TIER_BASE_URLS
    judge_catalog = catalog_is_the_cli_list and provider not in _PLUGIN_LISTED_PROVIDERS
    if not (zen or judge_catalog):
        return None

    async def read_catalog() -> Optional[Dict[str, Any]]:
        try:
            return await _fetch_models_dev(timeout=_PREFLIGHT_TIMEOUT_S)
        except Exception as e:
            logger.warning(f"[OpenCode] model pre-flight could not read models.dev: {e!r}")
            return None

    async def no_list() -> None:
        return None

    catalog, servable = await asyncio.gather(
        read_catalog(), _get_zen_servable_ids(provider, timeout=_PREFLIGHT_TIMEOUT_S) if zen else no_list(),
    )
    reason = _unoffered_reason(provider, model_id, catalog, servable, judge_catalog)
    if reason is None:
        return None
    instead = _offered_instead(provider, catalog, servable, judge_catalog, opencode_model, env or {})
    pick = f", such as {', '.join(repr(m) for m in instead)}" if instead else ""
    return (f"OpenCode can't run {opencode_model!r}: {reason}. Pick another OpenCode Model (opencode_model) "
            f"on this agent{pick}. Its Model (model) stays 'opencode'.")


def _zen_tier_model(model: str) -> Optional[Tuple[str, str]]:
    """``(tier, model id)`` for an OpenCode Zen model id, else None."""
    from utils.opencode_zen import ZEN_TIER_BASE_URLS

    tier, _, model_id = model.partition("/")
    tier = tier.lower()
    return (tier, model_id) if tier in ZEN_TIER_BASE_URLS and model_id else None


def _zen_free_refusal(model: str, tier: str, model_id: str, catalog: Dict[str, Any]) -> Optional[str]:
    entry = ((catalog.get(tier) or {}).get("models") or {}).get(model_id)
    if not isinstance(entry, dict) or not _is_free(entry):
        return None
    return (f"{model!r} is an OpenCode Model: OpenCode Zen serves it free only to OpenCode itself, never as an "
            f"agent's Model (model). To use it, set this agent's Model (model) to 'opencode' and its OpenCode "
            f"Model (opencode_model) to {model!r}; or pick a model that isn't free.")


# The agent config fields that can name a Zen model: the SDK path's Model and
# OpenCode's. ``read_zen_catalog`` callers read both.
AGENT_ZEN_MODEL_FIELDS = ("model", "opencode_model")

# OpenCode reaches Zen's own tier with no key (the CLI sends an anonymous one)
# and Zen serves it that tier's free models; Go is a subscription.
_KEYLESS_ZEN_TIER = "opencode"


def _runs_keyless(opencode_model: str, catalog: Optional[Dict[str, Any]]) -> bool:
    zen = _zen_tier_model(opencode_model)
    if zen is None or zen[0] != _KEYLESS_ZEN_TIER or not catalog:
        return False
    entry = ((catalog.get(zen[0]) or {}).get("models") or {}).get(zen[1])
    return isinstance(entry, dict) and _is_free(entry)


async def opencode_runs_keyless(opencode_model: str) -> bool:
    """Whether OpenCode runs ``opencode_model`` with no key: a free model of
    Zen's own tier, as models.dev prices it. A catalog that can't be read
    within the bound judges nothing, so the model keeps needing its key."""
    if _zen_tier_model(opencode_model) is None:
        return False
    try:
        catalog = await _fetch_models_dev(timeout=_PREFLIGHT_TIMEOUT_S)
    except Exception as e:
        logger.warning(f"[OpenCode] keyless check could not read models.dev: {e!r}")
        return False
    return _runs_keyless(opencode_model, catalog)


def opencode_runs_keyless_cached(opencode_model: str) -> bool:
    """:func:`opencode_runs_keyless` from the catalog already read, for
    synchronous credential checks (``read_zen_catalog`` reads it for them);
    never read, it judges nothing."""
    return _runs_keyless(opencode_model, _models_dev_cached())


async def zen_gateway_refusal(model: str) -> Optional[str]:
    """Pre-flight for an SDK turn on an OpenCode Zen model (the gateway route,
    ``providers.resolve_zen_gateway_route``): Zen serves its free models only to
    OpenCode itself and refuses them there ("OpenCode's free tier can only be
    used from within OpenCode"). The error saying how to run it, or None; a
    catalog that can't be read within the bound judges nothing."""
    zen = _zen_tier_model(model)
    if zen is None:
        return None
    try:
        catalog = await _fetch_models_dev(timeout=_PREFLIGHT_TIMEOUT_S)
    except Exception as e:
        logger.warning(f"[OpenCode] gateway pre-flight could not read models.dev: {e!r}")
        return None
    return _zen_free_refusal(model, *zen, catalog)


def zen_gateway_refusal_sync(model: str) -> Optional[str]:
    """:func:`zen_gateway_refusal` for a write that sets an agent's Model, so the
    model never reaches a turn; a catalog that can't be read judges nothing."""
    zen = _zen_tier_model(model)
    if zen is None:
        return None
    try:
        catalog = _fetch_models_dev_sync()
    except Exception as e:
        logger.warning(f"[OpenCode] Model write check could not read models.dev: {e!r}")
        return None
    return _zen_free_refusal(model, *zen, catalog)


async def read_zen_catalog(models: Iterable[Any]) -> None:
    """Read models.dev with the async reader when any of ``models`` is a Zen
    model id, so :func:`zen_gateway_refusal_sync` and
    :func:`opencode_runs_keyless_cached` judge it from the cache: the builder
    and the MCP server run those checks on the event loop."""
    if not any(isinstance(m, str) and _zen_tier_model(m.strip()) for m in models):
        return
    try:
        await _fetch_models_dev(timeout=_PREFLIGHT_TIMEOUT_S)
    except Exception as e:
        logger.warning(f"[OpenCode] Model check could not read models.dev: {e!r}")


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

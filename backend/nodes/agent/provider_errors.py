"""Classify provider billing and authentication failures surfaced by agent harnesses.

Some CLI tools relay provider failures through the normal response channel. This
module recognizes provider-owned error contracts, preserves the original detail,
and moves genuine failures onto the error channel with actionable guidance.
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from billing.exceptions import INSUFFICIENT_CREDITS_RE, InsufficientBalanceError

# A provider error surfaced through the response channel is the entire
# response; real replies that merely mention credits/quotas are longer.
RESPONSE_CHANNEL_MAX_LEN = 300

# How much of the provider's verbatim text rides along in the rewrite.
_DETAIL_MAX_LEN = 300


@dataclass(frozen=True)
class ProviderError:
    provider: str  # 'anthropic' | 'openai' | 'openrouter' | 'gemini' | 'xai' | 'unknown'
    kind: str      # 'no_credits' | 'invalid_key' | 'plan_limit' | 'account_blocked' | 'provider_outage' | 'bad_request'
    message: str   # full user-facing rewrite (includes the original detail)
    detail: str    # provider's verbatim text, trimmed

    def action(self) -> Optional[Dict[str, str]]:
        """The one thing the user should do next, for the UI to render as a
        button. None when there is nothing to click — a provider outage or a
        rate limit is waited out, and offering a button implies otherwise."""
        return _action_for(self.kind, self.provider)


@dataclass(frozen=True)
class _Rule:
    provider: str
    kind: str
    pattern: re.Pattern


def _r(provider: str, kind: str, pattern: str) -> _Rule:
    return _Rule(provider, kind, re.compile(pattern, re.IGNORECASE))


# Platform credit failures are checked before provider rules. OpenRouter also
# emits the phrase "insufficient credits", so provenance is decided by the
# platform gate's exact X < Y shape rather than by a loose substring match.
_PLATFORM_RULES: Tuple[_Rule, ...] = (
    _Rule("noclick", "no_credits", INSUFFICIENT_CREDITS_RE),
)

# Ordered: first match wins. Provider-specific slugs before generic phrasings.
_RULES: Tuple[_Rule, ...] = (
    # ── Anthropic ─────────────────────────────────────────────────────────
    _r("anthropic", "no_credits", r"credit balance is too low"),
    _r("anthropic", "invalid_key", r"invalid x-api-key"),
    _r("anthropic", "invalid_key", r"authentication_error"),
    _r("anthropic", "account_blocked", r"organization has been disabled"),
    # Claude subscription (Pro/Max via OAuth) hitting its plan cap; the CLI
    # relays e.g. "Claude AI usage limit reached|<epoch>" / "5-hour limit reached".
    _r("anthropic", "plan_limit", r"claude (ai )?usage limit reached"),
    _r("anthropic", "plan_limit", r"\b5-hour limit reached"),
    # ── OpenAI ────────────────────────────────────────────────────────────
    _r("openai", "no_credits", r"insufficient_quota"),
    _r("openai", "no_credits", r"exceeded your current quota"),
    _r("openai", "invalid_key", r"incorrect api key provided"),
    _r("openai", "invalid_key", r"invalid_api_key"),
    _r("openai", "account_blocked", r"account_deactivated"),
    # ── OpenRouter ────────────────────────────────────────────────────────
    _r("openrouter", "no_credits", r"requires more credits"),
    _r("openrouter", "no_credits", r"insufficient credits"),
    _r("openrouter", "invalid_key", r"no auth credentials found"),
    # A key whose account no longer resolves (deleted/rotated) — OpenRouter
    # answers 401 "User not found." Bound to the JSON error envelope on
    # purpose: bare "user not found" is something agents legitimately say
    # after a lookup, and on the response channel that would fail the run.
    _r("openrouter", "invalid_key", r'"message"\s*:\s*"user not found'),
    _r("openrouter", "plan_limit", r"key limit exceeded"),
    # OpenRouter error envelope for an UPSTREAM model-provider failure —
    # `"error_type":"server"` in metadata on upstream failures.
    # Chronic on free-tier variants; the raw relay read as a NoClick bug.
    _r("openrouter", "provider_outage", r'"error_type":\s*"server"'),
    # "Provider returned error" is OpenRouter's WRAPPER, not a diagnosis — it
    # wraps a genuine upstream 5xx and a 400 we caused equally. Matching it
    # blind called a malformed request a transient outage and told users to
    # retry, which is how a total tool-calling failure went unnoticed: every
    # agent that called a tool died and the message pointed at OpenRouter.
    # Narrow to 400/422 on purpose: those definitively mean the request was
    # wrong. A blanket 4xx would swallow 429 (rate limiting) and 401/403
    # (credential problems), each of which has its own honest diagnosis and
    # its own remedy. Matched FIRST — this table is first-match-wins.
    _r("openrouter", "bad_request", r'"code":\s*4(?:00|22)\b'),
    # 429 was landing on provider_outage via the same wrapper — telling someone
    # to retry immediately when the remedy is to slow down. The rate_limited
    # copy already existed; nothing was routing to it.
    _r("openrouter", "rate_limited", r'"code":\s*429\b'),
    _r("openrouter", "provider_outage", r"provider returned error"),
    # ── Google / Gemini ───────────────────────────────────────────────────
    _r("gemini", "invalid_key", r"api key not valid"),
    # ── xAI ───────────────────────────────────────────────────────────────
    _r("xai", "no_credits", r"doesn'?t have any credits"),
    # ── Generic (no provider-identifying slug in the text) ────────────────
    _r("unknown", "invalid_key", r"invalid api key"),
)

_PROVIDER_META: Dict[str, Dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic",
        "billing_url": "https://platform.claude.com/settings/billing",
        "keys_url": "https://platform.claude.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI",
        "billing_url": "https://platform.openai.com/settings/organization/billing/overview",
        "keys_url": "https://platform.openai.com/api-keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "billing_url": "https://openrouter.ai/settings/credits",
        "keys_url": "https://openrouter.ai/settings/keys",
    },
    "gemini": {
        "label": "Google AI",
        "billing_url": "https://aistudio.google.com/",
        "keys_url": "https://aistudio.google.com/apikey",
    },
    "xai": {
        "label": "xAI",
        "billing_url": "https://console.x.ai/",
        "keys_url": "https://console.x.ai/",
    },
    # OpenCode Zen/Go inference gateways (one key, opencode.ai/auth dashboard).
    "opencode": {
        "label": "OpenCode Zen",
        "billing_url": "https://opencode.ai/auth",
        "keys_url": "https://opencode.ai/auth",
    },
    "unknown": {"label": "the model provider", "billing_url": "", "keys_url": ""},
    "noclick": {
        "label": "NoClick",
        "billing_url": "",
        "keys_url": "",
    },
}

# Per-(kind) message templates. Every billing-flavored kind explicitly
# disambiguates a provider balance from the instance credit pool.
_TEMPLATES: Dict[str, str] = {
    # The instance's own key (the builder's), rejected in the settings form.
    "invalid_key_instance": "{label} rejected this key. Check it{keys_hint}.",
    "no_credits_instance": "{label} reports no credits on this key.{billing_hint}",
    "no_credits": (
        "Your {label} account has no API credits. This is the balance on your "
        "{label} account — not your NoClick credits, which are unaffected."
        "{billing_hint}{extra}"
    ),
    "invalid_key": (
        "{label} rejected the API key on this agent's credential. Re-check the "
        "key{keys_hint} and reconnect it on the agent node."
    ),
    "plan_limit": (
        "Your {label} subscription hit its usage limit. This is {label}'s plan "
        "cap — not your NoClick credits. It resets on {label}'s schedule; retry "
        "later or switch this agent to an API key."
    ),
    "account_blocked": (
        "{label} reports this account is disabled or deactivated. Resolve it in "
        "your {label} console — NoClick can't work around a provider-side block."
    ),
    "rate_limited": (
        "{label} is rate-limiting this account — too many requests in too short "
        "a window. This is {label}'s limit, not your NoClick credits, and "
        "nothing is wrong with your key. Retry in a moment, or run this less "
        "often."
    ),
    "bad_request": (
        "{label} rejected this request as malformed — a 4xx, which means the "
        "request NoClick sent was wrong, not that {label} is down. Retrying "
        "will not help. Please report this so it can be fixed.{extra}"
    ),
    "provider_outage": (
        "{label}'s upstream model provider failed while serving this request — "
        "a server-side outage on their end, not a problem with your setup, key, "
        "or credits. These are usually transient: retry, or switch models if it "
        "keeps happening.{extra}"
    ),
}

# Full-template overrides per (kind, provider). The generic templates draw the
# provider-vs-NoClick line ("not your NoClick credits") — exactly backwards for
# a platform error, which needs the opposite framing.
_TEMPLATE_OVERRIDES: Dict[Tuple[str, str], str] = {
    ("no_credits", "noclick"): (
        "You've run out of NoClick credits. This is your NoClick balance — "
        "your model provider's account is unaffected.{billing_hint}"
    ),
}

# Provider-specific extra guidance appended per (kind, provider).
_EXTRA_GUIDANCE: Dict[Tuple[str, str], str] = {
    ("no_credits", "anthropic"): " Or connect a Claude Pro/Max subscription on the agent node instead of an API key.",
    ("no_credits", "openai"): " Or connect a ChatGPT subscription on the agent node instead of an API key.",
    ("provider_outage", "openrouter"): " Free (:free) model variants fail this way far more often than paid ones.",
}


# The button, per kind. `open_credentials` is handled in-app and `open_url`
# is a plain link to a third-party provider console.
#
# Kinds the user cannot act on get NO action. A "Retry" button on a provider
# outage would just be the Run button wearing a disguise, and a button that
# does nothing useful teaches people to ignore the ones that do.
def _action_for(kind: str, provider: str) -> Optional[Dict[str, str]]:
    meta = _PROVIDER_META.get(provider, _PROVIDER_META["unknown"])
    if provider == "noclick" and kind == "no_credits":
        return None
    if kind == "invalid_key":
        return {"type": "open_credentials", "label": "Open credentials"}
    if kind in ("no_credits", "account_blocked"):
        if not meta["billing_url"]:
            return {"type": "open_credentials", "label": "Open credentials"}
        label = "Add credits" if kind == "no_credits" else f"Open {meta['label']}"
        return {"type": "open_url", "label": label, "url": meta["billing_url"]}
    if kind == "plan_limit":
        # The fix is a different credential (an API key instead of the capped
        # subscription), which lives on the node.
        return {"type": "open_credentials", "label": "Open credentials"}
    return None


def format_provider_message(provider: str, kind: str, detail: str) -> str:
    """Render the user-facing message for a classified provider error.

    Shared with connect-time key validation so the connect-form rejection and
    the runtime failure read identically."""
    meta = _PROVIDER_META.get(provider, _PROVIDER_META["unknown"])
    billing_hint = f" Add credits at {meta['billing_url']}." if meta["billing_url"] else ""
    keys_hint = f" or create a new one at {meta['keys_url']}" if meta["keys_url"] else ""
    body = (_TEMPLATE_OVERRIDES.get((kind, provider)) or _TEMPLATES[kind]).format(
        label=meta["label"],
        billing_hint=billing_hint,
        keys_hint=keys_hint,
        extra=_EXTRA_GUIDANCE.get((kind, provider), ""),
    )
    trimmed = (detail or "").strip()[:_DETAIL_MAX_LEN]
    tail_label = "Details:" if provider == "noclick" else "Provider message:"
    return f"{body}\n\n{tail_label} {trimmed}" if trimmed else body


def classify_provider_error(
    text: Optional[str], *, channel: str = "error"
) -> Optional[ProviderError]:
    """Classify *text* as a provider billing/auth error, or return None.

    ``channel='error'`` (harness error field): match anywhere.
    ``channel='response'`` (assistant reply): only texts short enough to BE a
    laundered provider error are considered — see RESPONSE_CHANNEL_MAX_LEN.
    """
    if not text or not isinstance(text, str):
        return None  # classification is best-effort — never crash on odd shapes
    if channel == "response" and len(text) > RESPONSE_CHANNEL_MAX_LEN:
        return None
    for rule in _PLATFORM_RULES + _RULES:
        if rule.pattern.search(text):
            return ProviderError(
                provider=rule.provider,
                kind=rule.kind,
                message=format_provider_message(rule.provider, rule.kind, text),
                detail=text.strip()[:_DETAIL_MAX_LEN],
            )
    return None


# ── Exception-type classification ───────────────────────────────────────────
# litellm normalizes EVERY provider it supports into one static exception
# hierarchy, and stamps `llm_provider` / `status_code` on the instance. Where we
# hold the exception object, that is a far better signal than matching its
# text: it covers every provider in PROVIDER_REQUIRED_CREDENTIALS rather than
# the handful with hand-written rules, and it cannot be broken by a provider
# rewording its message.
#
# The regex table stays for the text-only paths — CLI harnesses relay a string
# across a sandbox boundary, and laundered-into-response detection has no
# exception to inspect.
#
# Types deliberately absent: BadRequestError, ContextWindowExceededError,
# NotFoundError and friends are the caller's problem (bad model id, oversized
# prompt), not a billing/auth condition, and rewriting them into "check your
# key" would send people to the wrong place.
_KIND_BY_EXCEPTION: Dict[str, str] = {
    "AuthenticationError": "invalid_key",
    "PermissionDeniedError": "account_blocked",
    "BudgetExceededError": "no_credits",
    "RateLimitError": "rate_limited",
    "ServiceUnavailableError": "provider_outage",
    "InternalServerError": "provider_outage",
    "APIConnectionError": "provider_outage",
}

# litellm's `llm_provider` slug → our provider key. Anything unlisted falls back
# to "unknown", which still yields a correct (if generic) message.
_PROVIDER_BY_LITELLM_SLUG: Dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "azure": "openai",
    "openrouter": "openrouter",
    "gemini": "gemini",
    "vertex_ai": "gemini",
    "xai": "xai",
}


def classify_provider_exception(exc: BaseException) -> Optional[ProviderError]:
    """Classify a litellm exception by TYPE, falling back to its text.

    Text matching runs first so a provider-specific rule (which distinguishes
    "no credits" from "bad key" inside a single 401/429) beats the coarser
    type mapping. The type is the safety net that makes the fifty-odd
    providers without rules produce something actionable anyway.

    One type outranks everything: our own gate's InsufficientBalanceError IS
    platform provenance, whatever its message says — no regex needed to know
    NoClick minted it.
    """
    if isinstance(exc, InsufficientBalanceError):
        detail = str(exc)
        return ProviderError(
            provider="noclick",
            kind="no_credits",
            message=format_provider_message("noclick", "no_credits", detail),
            detail=detail.strip()[:_DETAIL_MAX_LEN],
        )

    by_text = classify_provider_error(str(exc), channel="error")
    if by_text:
        return by_text

    # The name table indexes litellm's hierarchy, but the names themselves are
    # generic — stripe/openai/anthropic SDKs all mint an `AuthenticationError`.
    # Only litellm's own carry the "this is a model provider" meaning.
    if not type(exc).__module__.startswith("litellm"):
        return None
    kind = _KIND_BY_EXCEPTION.get(type(exc).__name__)
    if not kind:
        return None
    slug = str(getattr(exc, "llm_provider", "") or "").lower()
    provider = _PROVIDER_BY_LITELLM_SLUG.get(slug, "unknown")
    detail = str(exc)
    return ProviderError(
        provider=provider,
        kind=kind,
        message=format_provider_message(provider, kind, detail),
        detail=detail.strip()[:_DETAIL_MAX_LEN],
    )


# The node types whose failures ARE model-provider failures. The templates
# speak agent language ("this agent's credential", "the agent node"), and the
# generic rules are greedy outside it: a Stripe node's "Invalid API Key
# provided" or a YouTube node's "API key not valid" would be rewritten into
# model-provider guidance pointing at the wrong console.
_MODEL_PROVIDER_NODE_TYPES = frozenset({"agent"})


def describe_failure(
    exc: BaseException, *, node_type: str
) -> Tuple[str, Optional[Dict[str, str]]]:
    """(user-facing message, action) for a node failure.

    The one entry point for surfaces that hold the exception — the workflow
    runner's per-node failure path, most importantly. `node_type` is required
    because classification is only meaningful for nodes that call model
    providers (see _MODEL_PROVIDER_NODE_TYPES); every other node's failure
    comes back verbatim with no action, as do non-provider failures.

    Call it ONCE, where the string becomes user-visible: it is not idempotent,
    and a rewrite fed back in gets wrapped in another rewrite.

    The node_type scope applies to PROVIDER classification only. The platform
    gate's InsufficientBalanceError is node-type independent — it fires in
    dozens of node handlers (image, video, serverless, …) and its rewrite
    names no provider — so it classifies everywhere.
    """
    if node_type not in _MODEL_PROVIDER_NODE_TYPES and not isinstance(
        exc, InsufficientBalanceError
    ):
        return str(exc), None
    match = classify_provider_exception(exc)
    if not match:
        return str(exc), None
    _stamp_span("agent.provider_error.kind", f"{match.provider}:{match.kind}")
    return match.message, match.action()


def action_for_error_text(
    text: Optional[str], *, node_type: Optional[str]
) -> Optional[Dict[str, str]]:
    """The actionable button for an error string, without rewriting it.

    For error strings held without their exception — the node-state emit and
    stored errors read back later (the execution-detail route). Safe to call
    on an ALREADY-rewritten message: the rewrite keeps the provider's verbatim
    text after "Provider message:", so it re-classifies to the same kind — and
    since nothing is rewritten here, there is no second wrapping to cause.

    Tiered by provenance: platform (noclick) rules apply to EVERY node type —
    the credit gate fires in dozens of node handlers — while provider rules
    need model-provider provenance (see _MODEL_PROVIDER_NODE_TYPES), so a
    non-agent error that merely shares a provider's phrasing (an Apify
    "insufficient credits", a YouTube "API key not valid") can't grow a
    provider-branded button. Unknown node_type (None) gets platform tier only.
    """
    if not text:
        return None
    for rule in _PLATFORM_RULES:
        if rule.pattern.search(text):
            return _action_for(rule.kind, rule.provider)
    if node_type not in _MODEL_PROVIDER_NODE_TYPES:
        return None
    match = classify_provider_error(text, channel="error")
    return match.action() if match else None


def classify_and_rewrite_provider_error(text: str) -> str:
    """Text-only variant of describe_failure, for callers holding a string."""
    match = classify_provider_error(text, channel="error")
    if not match:
        return text
    _stamp_span("agent.provider_error.kind", f"{match.provider}:{match.kind}")
    return match.message


def _stamp_span(key: str, value) -> None:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute(key, value)
    except Exception:
        pass

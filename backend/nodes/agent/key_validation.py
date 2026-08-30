"""Connect-time validation for harness LLM API keys.

A dead or creditless key saved silently becomes a runtime failure minutes later
inside an agent turn, where a provider balance error is easy to misread as an
instance balance problem. Validating at
credential creation puts the rejection in the form, at the moment the user can
act, in the same words the runtime classifier would use.

Policy — act only on DEFINITIVE signals (same principle as the cron-scheduler
"never delete on a non-definitive signal" invariant):

- provider says the key is bad (401/403 auth) or has no credits → reject with
  the shared ``provider_errors`` message;
- anything else — network blip, provider 5xx, rate limit, a model id that
  drifted — → ALLOW. Validation exists to catch bad keys, not to make
  credential creation depend on provider availability or on our probe model
  staying current.

Inference probes use the pinned harness defaults from ``_cli_models.json``
(refreshed daily), so the probe model can't rot independently of the product.
"""

import logging
from typing import Any, Dict, Optional

import httpx
from dataclasses import dataclass

from nodes.agent.provider_errors import format_provider_message

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class Rejection:
    """A definitive provider verdict on a key: who said it, what kind, and the
    provider's own text. Worded by the caller — an agent credential and the
    instance's builder key are refused in different sentences."""

    provider: str
    kind: str  # 'invalid_key' | 'no_credits'
    detail: str

    def message(self, context: str = "agent") -> str:
        if context == "agent":
            return format_provider_message(self.provider, self.kind, self.detail)
        return format_provider_message(self.provider, f"{self.kind}_{context}", _provider_sentence(self.detail))


def _provider_sentence(detail: str) -> str:
    """The provider's own sentence out of its error body, for a form that is
    not a debugging surface: ``{"error": {"message": "User not found."}}`` →
    ``User not found.``. Anything unparseable is shown as it came."""
    import json

    try:
        node = json.loads(detail or "")
    except ValueError:
        return detail
    while isinstance(node, dict):
        if isinstance(node.get("message"), str):
            return node["message"]
        node = node.get("error")
    return detail


def _extract_env(credential_data: Any) -> Dict[str, str]:
    """The agent credential blob is ``{"credentials": {ENV: value}}``; accept a
    flat dict too (legacy shape handled by AgentCredentials' validator)."""
    if not isinstance(credential_data, dict):
        return {}
    inner = credential_data.get("credentials")
    env = inner if isinstance(inner, dict) else credential_data
    return {k: v for k, v in env.items() if isinstance(k, str) and isinstance(v, str)}


async def _probe_anthropic(key: str) -> Optional[str]:
    from nodes.agent.config._cli_models_loader import claude_code_aliases

    model = claude_code_aliases()["haiku"]  # cheapest pinned model, refreshed daily
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
        )
    if resp.status_code == 401:
        return Rejection("anthropic", "invalid_key", resp.text)
    if resp.status_code in (400, 403) and "credit balance is too low" in resp.text.lower():
        return Rejection("anthropic", "no_credits", resp.text)
    return None


async def _probe_openai(key: str) -> Optional[str]:
    from nodes.agent.config._cli_models_loader import harness_default_model

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        auth = await client.get("https://api.openai.com/v1/models", headers=headers)
        if auth.status_code == 401:
            return Rejection("openai", "invalid_key", auth.text)
        # Quota exhaustion only surfaces on inference; probe with the pinned
        # cheap codex model. A 400/404 here means OUR probe model drifted —
        # never the user's fault, so it allows.
        infer = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json={"model": harness_default_model("codex"), "input": "hi",
                  "max_output_tokens": 16},
        )
    if infer.status_code in (403, 429) and "insufficient_quota" in infer.text.lower():
        return Rejection("openai", "no_credits", infer.text)
    return None


async def _probe_openrouter(key: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code == 401:
        return Rejection("openrouter", "invalid_key", resp.text)
    # Zero balance is allowed — OpenRouter serves free models.
    return None


async def _probe_gemini(key: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key},
        )
    if resp.status_code in (400, 401, 403) and "api key not valid" in resp.text.lower():
        return Rejection("gemini", "invalid_key", resp.text)
    return None


async def _probe_xai(key: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code in (401, 403):
        return Rejection("xai", "invalid_key", resp.text)
    return None


async def _probe_opencode(key: str) -> Optional[str]:
    """OpenCode Zen validates a PROVIDED key even on its keyless free models —
    a 1-token completion against a live free model is a definitive $0 auth
    check (the /models endpoint ignores auth entirely, so it can't probe).
    The probe model comes from the live servable set so free-tier rotation
    can't rot it; no free model live → inconclusive → allow."""
    from utils.opencode_zen import ZEN_TIER_BASE_URLS, get_zen_servable_ids

    servable = await get_zen_servable_ids("opencode") or set()
    probe_model = next((m for m in sorted(servable) if m.endswith("-free")), None)
    if probe_model is None:
        return None
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.post(
            f"{ZEN_TIER_BASE_URLS['opencode']}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": probe_model, "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
        )
    if resp.status_code == 401:
        return Rejection("opencode", "invalid_key", resp.text)
    return None


def _wahooks_list_connections(key: str) -> None:
    from wahooks import WAHooks

    with WAHooks(api_key=key) as client:
        client.list_connections()


async def _probe_apify(key: str) -> Optional["Rejection"]:
    """Apify answers /users/me with 401 to a bad token; anything else is not a verdict."""
    import httpx

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        response = await client.get(
            "https://api.apify.com/v2/users/me", headers={"Authorization": f"Bearer {key}"}
        )
    if response.status_code == 401:
        return Rejection("apify", "invalid_key", response.text)
    return None


async def _probe_wahooks(key: str) -> Optional["Rejection"]:
    """WAHooks issues the WhatsApp QR sessions; its SDK raises a WAHooksError
    with the HTTP status, and only an auth status is a verdict."""
    import asyncio

    from wahooks import WAHooksError

    try:
        await asyncio.wait_for(asyncio.to_thread(_wahooks_list_connections, key), timeout=_PROBE_TIMEOUT_S)
    except WAHooksError as e:
        if e.status_code in (401, 403):
            return Rejection("wahooks", "invalid_key", str(e))
    return None


_PROBES = {
    "APIFY_API_TOKEN": _probe_apify,
    "WAHOOKS_API_KEY": _probe_wahooks,
    "ANTHROPIC_API_KEY": _probe_anthropic,
    "OPENAI_API_KEY": _probe_openai,
    "OPENROUTER_API_KEY": _probe_openrouter,
    "GEMINI_API_KEY": _probe_gemini,
    "XAI_API_KEY": _probe_xai,
    "OPENCODE_API_KEY": _probe_opencode,
}


async def validate_provider_key(env_var: str, key: str) -> Optional[Rejection]:
    """Return the provider's Rejection if ``key`` for ``env_var`` is definitively
    bad/creditless; None to allow. Unprobed variables and inconclusive probes
    (network, provider 5xx, drifted probe model) allow — see the module
    docstring. Shared by agent credentials and the instance's own keys."""
    probe = _PROBES.get(env_var)
    key = (key or "").strip()
    if probe is None or not key:
        return None
    try:
        rejection = await probe(key)
    except Exception as e:
        logger.warning(
            "[key_validation] %s probe inconclusive (allowing key): %s", env_var, e,
        )
        return None
    if rejection:
        logger.info("[key_validation] rejected %s at connect time", env_var)
    return rejection


async def validate_agent_api_key(
    credential_type: Optional[str], credential_data: Any
) -> Optional[str]:
    """Return a rejection message if a recognized LLM API key in an agent
    credential is definitively bad/creditless; None to allow creation.

    Only agent harness credential types are probed.
    """
    if not credential_type or not credential_type.startswith("agent"):
        return None
    env = _extract_env(credential_data)
    for env_var in _PROBES:
        rejection = await validate_provider_key(env_var, env.get(env_var) or "")
        if rejection:
            return rejection.message("agent")
    return None

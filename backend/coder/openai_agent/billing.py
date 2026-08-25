"""Usage-policy hooks for the OpenAI Agents SDK-backed agent.

The pre-call hook asks the registered policy whether execution may proceed.
The post-call hook records provider-reported or locally estimated usage.
Calls made with operator or user credentials keep their provenance flag so an
installation policy can account for them appropriately.
"""
from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

from agents import RunHooks

from .litellm_model import CostCapturingLitellmModel, extract_cost_from_response

logger = logging.getLogger(__name__)


def _is_free_model(model: Optional[str]) -> bool:
    """True for OpenRouter ``:free`` routes, which the provider serves at $0."""
    return bool(model) and model.strip().lower().endswith(":free")


# --- Constants mirrored from coder/openhands/agent.py ---
# Mask to prevent users from passing a gibberish env to trick the system into
# thinking they're using their own API keys while consuming platform keys.
ENV_MASK = {
    "OPENAI_API_KEY": "N/A",
    "ANTHROPIC_API_KEY": "N/A",
    "GOOGLE_API_KEY": "N/A",
    "GEMINI_API_KEY": "N/A",
    "OPENROUTER_API_KEY": "N/A",
}

# LiteLLM reads a different env var than what we expose to users for some
# providers. When a user provides key A, we must also set alias B so LiteLLM
# finds it. Format: { user_facing_key: litellm_expected_key }
_PROVIDER_KEY_ALIASES = {
    # LiteLLM's gemini/ provider reads GOOGLE_API_KEY (falls back to
    # GEMINI_API_KEY but ENV_MASK sets GOOGLE_API_KEY="N/A", so we must
    # propagate the user's key).
    "GEMINI_API_KEY": "GOOGLE_API_KEY",
}

# Re-exported for backwards-compatible imports (agent.py imports it from here and
# `except InsufficientBalanceError`). Same class identity as the canonical one.
# The pre-flight gate (incl. the MIN_CREDITS threshold) now lives entirely in
# usage_tracker.enforce_credit_gate, called from on_llm_start below.
from billing.exceptions import InsufficientBalanceError  # noqa: F401


class BillingHooks(RunHooks):
    """Pre-call balance gate + post-call usage tracking for SDK Agent runs.

    Pass an instance to ``Runner.run_streamed(..., hooks=hooks)``. The hooks
    fire on every LLM call inside the run (including tool-call follow-ups),
    matching the per-completion granularity the OpenHands TrackingLLM had.

    Constructor mirrors TrackingLLM's surface so wiring from agent.py is a
    one-shot translation.
    """

    def __init__(
        self,
        *,
        model: str,
        model_instance: CostCapturingLitellmModel,
        user_id: Optional[str],
        sio: Optional[Any],
        sid: Optional[str],
        caller_user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        # ``user_id`` is the only hard requirement — it's the billing entity
        # whose balance is gated and whose usage is recorded. ``sio``/``sid``
        # (and ``caller_user_id``) are OPTIONAL: they only drive live UI
        # updates (the credits-exhausted banner and usage ticker). Triggered
        # runs (cron, webhook, run-from-API) have no client socket, but their
        # LLM usage MUST still be recorded — so billing is never gated on the
        # socket. Emission sites below degrade to no-ops when there's no socket.
        if not user_id:
            raise ValueError("BillingHooks requires user_id for balance checking")
        if model_instance is None:
            # Hard-required: cost capture reads off the model's per-call slot.
            # No fallback path — a missing model_instance means provider cost
            # would be silently unrecoverable, which is what we just stopped
            # doing.
            raise ValueError("BillingHooks requires the CostCapturingLitellmModel instance")

        self._model = model
        self._model_instance = model_instance
        self._user_id = user_id
        self._sio = sio
        self._sid = sid
        self._caller_user_id = caller_user_id
        self._organization_id = organization_id
        self._env = env or {}
        # Input tokens computed in ``on_llm_start`` from the messages the
        # SDK is about to send. Used in ``on_llm_end`` as a fallback when
        # the provider didn't emit a usage chunk (some OpenRouter-routed
        # models like mistral-nemo / aion-labs drop usage despite
        # ``stream_options.include_usage=True``). Reset each call.
        self._pending_input_tokens: int = 0

    # ------------------------------------------------------------------ #
    # Pre-call: balance gate + input-token snapshot
    # ------------------------------------------------------------------ #
    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:  # noqa: ARG002
        # Count input tokens locally so we can use them as a fallback in
        # ``on_llm_end`` when the provider drops the usage chunk. Cheap
        # (text-only, no network) and saves us from emitting a $0/zero-
        # token event for providers like mistral-nemo via OpenRouter.
        # tiktoken's BPE encode is pure CPU work, so long prompts must be
        # counted off the event-loop thread.
        self._pending_input_tokens = await asyncio.to_thread(
            _count_input_tokens,
            model=self._model,
            system_prompt=system_prompt,
            input_items=input_items,
        )

        # If the caller supplied their own keys, they're paying their own
        # provider — we don't check or charge.
        if self._env:
            return

        # Standardized pre-flight gate: strict owner resolution (org work with no
        # resolvable owner fails the run), balance check, exhausted-event emit,
        # and abort — all in one shared implementation. Raises
        # OwnerResolutionError or InsufficientBalanceError; both abort the run.
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            self._user_id,
            organization_id=self._organization_id,
            sio=self._sio,
            sid=self._sid,
            caller_user_id=self._caller_user_id,
            surface="agent",
            message="You're out of credits. The agent has been paused.",
        )

    # ------------------------------------------------------------------ #
    # Post-call: usage tracking
    # ------------------------------------------------------------------ #
    async def on_llm_end(self, context, agent, response) -> None:  # noqa: ARG002
        try:
            await self._record_usage(response)
        except Exception as e:
            # Never break the run because billing recording failed; the OpenHands
            # wrapper used fire-and-forget for the same reason. Log loudly so
            # we notice if it stops working.
            logger.error("[billing] usage tracking failed: %s", e, exc_info=True)

    async def _record_usage(self, response) -> None:
        # Extract token counts from the SDK's Usage if the provider
        # cooperated. ``Usage`` is always present on a ModelResponse —
        # even when zero — so the ``is None`` branch is genuinely a
        # missing/broken Usage object, not a missing-usage-chunk.
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

        used_fallback = False
        if input_tokens == 0 and output_tokens == 0:
            # Provider didn't emit a usage chunk. Common when routing
            # via OpenRouter to community-hosted models (mistral-nemo,
            # aion-labs/aion-1.0, etc.) even with
            # ``stream_options.include_usage=True``. Fall back to local
            # tokenization so the event still lands in usage_events
            # with real counts — better than silently dropping the row
            # and pretending the call didn't happen.
            output_text = _extract_response_text(response)
            if not output_text and self._pending_input_tokens == 0:
                logger.warning(
                    "[billing] no usage AND no output text/input snapshot — "
                    "skipping (model=%s)", self._model,
                )
                return
            input_tokens = self._pending_input_tokens
            output_tokens = await asyncio.to_thread(
                _count_output_tokens, self._model, output_text
            )
            used_fallback = True
            logger.warning(
                "[billing] provider dropped usage chunk for model=%s; "
                "fallback to local count: input=%d output=%d",
                self._model, input_tokens, output_tokens,
            )

        total_tokens = input_tokens + output_tokens
        if total_tokens == 0:
            logger.warning("[billing] zero tokens after fallback — skipping (model=%s)", self._model)
            return

        # Cost discovery — try in order:
        #   1. OpenRouter ``:free`` routes cost $0 by contract — never billed,
        #      whatever any cost source reports. Explicit so a mis-attributed
        #      cost can't slip onto a free model (the bug the previous fix
        #      was for).
        #   2. Provider-reported cost for THIS call, captured in-band by
        #      ``CostCapturingLitellmModel`` (ground truth — the value on
        #      openrouter.ai/activity; a reported $0 counts as known-free).
        #   3. ``litellm.completion_cost`` against the model's pricing table
        #      (strip the ``openrouter/`` prefix; pricing is keyed by the
        #      underlying provider).
        #   4. Default to $0 — event still recorded with real token counts so
        #      dashboards / future pricing backfills have the row to work from.
        cost_source: str
        if _is_free_model(self._model):
            response_cost = 0.0
            cost_source = "free_model"
        else:
            reported = self._model_instance.last_call_cost_reported
            if reported:
                response_cost = self._model_instance.last_call_cost or 0.0
                cost_source = "provider"
                logger.info(
                    "[billing] using provider-reported cost for model=%s: $%.6f",
                    self._model, response_cost,
                )
            else:
                cost_lookup_model = _strip_router_prefix(self._model)
                import litellm as _litellm
                try:
                    response_cost = _litellm.completion_cost(
                        completion_response={
                            "model": cost_lookup_model,
                            "usage": {
                                "prompt_tokens": input_tokens,
                                "completion_tokens": output_tokens,
                                "total_tokens": total_tokens,
                            },
                            "choices": [],
                        }
                    )
                    cost_source = "litellm_pricing_table" if response_cost else "zero"
                except Exception as cost_err:
                    logger.warning(
                        "[billing] cost lookup failed for model=%s (looked up as %s): %s",
                        self._model, cost_lookup_model, cost_err,
                    )
                    response_cost = 0
                    cost_source = "lookup_failed"

        from billing.markup import apply_platform_markup
        from billing.usage_tracker import usage_tracker
        from billing.schema import UsageEventData

        # Preserve whether the caller supplied the upstream credentials.
        user_resource = bool(self._env)
        total_cost = Decimal(str(response_cost)) if response_cost else Decimal("0")
        total_cost = apply_platform_markup(total_cost, user_resource, self._model)

        # The registered tracker owns attribution; call sites pass the runner
        # and optional organization context without reimplementing policy.
        event = UsageEventData(
            user_id=self._user_id,
            total_cost=total_cost,
            usage_type="ai_usage",
            usage_subtype=self._model,
            quantity=Decimal(str(total_tokens)),
            unit_type="tokens",
            user_resource=user_resource,
            organization_id=self._organization_id,
            metadata={
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "model": self._model,
                "usage_source": "fallback_token_counter" if used_fallback else "provider",
                "cost_source": cost_source,
                "response_id": getattr(response, "response_id", None),
                "request_id": getattr(response, "request_id", None),
            },
        )
        await usage_tracker.track_usage_event(
            event, sio=self._sio, sid=self._sid,
        )
        logger.info(
            "[billing] tracked: runner=%s model=%s tokens=%d cost=$%s user_resource=%s",
            self._user_id, self._model, total_tokens, total_cost, user_resource,
        )

def build_litellm_env(user_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Build the effective env for a LiteLLM call.

    Returns the env vars that must be set in the calling process (or via
    utils.thread_env.override_env) before LitellmModel calls litellm.acompletion.

    If user supplied keys: mask platform keys with ENV_MASK then overlay user keys.
    If not: only apply provider key aliases (e.g. GEMINI_API_KEY → GOOGLE_API_KEY
    if litellm expects the alias and the alias isn't already set).
    """
    if user_env:
        effective_env = {**ENV_MASK, **user_env}
        # Honor LiteLLM's per-provider env var aliases.
        for user_key, litellm_key in _PROVIDER_KEY_ALIASES.items():
            if user_key in user_env:
                effective_env[litellm_key] = user_env[user_key]
        return effective_env

    # Platform-keys path: only patch up aliases if missing.
    platform_aliases: Dict[str, str] = {}
    for user_key, litellm_key in _PROVIDER_KEY_ALIASES.items():
        if user_key in os.environ and litellm_key not in os.environ:
            platform_aliases[litellm_key] = os.environ[user_key]
    return platform_aliases


# ---------------------------------------------------------------------- #
# Token-count fallback helpers
#
# Used when the upstream provider doesn't honor stream_options.include_usage
# (some OpenRouter-routed models, certain self-hosted providers). LiteLLM's
# ``token_counter`` is approximate but matches the provider's billing math
# closely enough for our usage tracking — and it's deterministic, so the
# fallback events are reproducible.
# ---------------------------------------------------------------------- #
def _strip_router_prefix(model: str) -> str:
    """Strip the ``openrouter/`` routing prefix so LiteLLM can look up
    the underlying provider's model id."""
    if model.startswith("openrouter/"):
        return model[len("openrouter/"):]
    return model


def _count_input_tokens(
    *,
    model: str,
    system_prompt: Any,
    input_items: Any,
) -> int:
    """Count input tokens for the messages the SDK is about to send.

    Returns 0 on any failure (token_counter doesn't know the model,
    input_items has an unexpected shape, etc.) — we'd rather emit a
    fallback event with output_tokens-only than fail the whole run.
    """
    try:
        import litellm as _litellm
        msgs: list = []
        if system_prompt:
            msgs.append({"role": "system", "content": str(system_prompt)})
        for item in input_items or []:
            if isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content", "")
                # content can be a string, a list of content parts, or
                # other shapes. token_counter accepts strings; flatten.
                if not isinstance(content, str):
                    content = str(content)
                msgs.append({"role": role, "content": content})
            else:
                msgs.append({"role": "user", "content": str(item)})
        return int(_litellm.token_counter(model=_strip_router_prefix(model), messages=msgs) or 0)
    except Exception as e:
        logger.warning("[billing] _count_input_tokens failed: %s", e)
        return 0


def _count_output_tokens(model: str, text: str) -> int:
    """Count tokens for the assistant's output text."""
    if not text:
        return 0
    try:
        import litellm as _litellm
        return int(_litellm.token_counter(model=_strip_router_prefix(model), text=text) or 0)
    except Exception as e:
        logger.warning("[billing] _count_output_tokens failed: %s", e)
        # Last-resort heuristic: ~4 chars per token. Worse than
        # token_counter but always succeeds.
        return max(1, len(text) // 4)


def _extract_response_text(response: Any) -> str:
    """Pull the assistant's text out of a SDK ``ModelResponse`` so we can
    count its tokens locally when the provider didn't return usage.

    ``response.output`` is a list of output items. The assistant's
    message is typically a ``ResponseOutputMessage`` with a list of
    ``ResponseOutputText`` parts. We concatenate every text part we can
    find — text-only is the common case; if there are tool calls or
    other non-text items they contribute 0 to this count, which is
    correct (tool calls have their own arguments tokens but those were
    sent to the model, not received from it).
    """
    pieces: list = []
    for item in getattr(response, "output", None) or []:
        content = getattr(item, "content", None)
        if not content:
            continue
        for part in content:
            txt = getattr(part, "text", None)
            if isinstance(txt, str):
                pieces.append(txt)
    return "".join(pieces)

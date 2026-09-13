"""NoClick's side of the thread interchange (``nodes/agent/interchange`` is
the engine): which harness a conversation row names, the versions NoClick
pins, which pairs can move, and how a move's outcome is reported.

The engine is shipped into sandboxes and must stay free of backend imports;
everything that knows about NoClick — the provider table, the pins file,
feedback, the conversation repository — lives here, imported lazily.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nodes.agent.interchange import (  # re-exported: the wiring imports one name
    FORMATS,
    INTERCHANGE_VERSION,
    REASONS,
    InterchangeError,
    InterchangeResult,
    StoreRef,
    TargetIdentity,
    carried_context,
    move_thread,
    parse_verdict,
    read_thread,
    turns_from_projection,
    with_carried_context,
)

logger = logging.getLogger(__name__)

#: The in-process SDK agent (``coder/openai_agent``): its history is our own
#: JSONB, not a harness store, so a switch FROM it carries context.
SDK_HARNESS = "llm"

#: Fallback reasons that are a known product limit rather than a translation
#: failure: recorded and stamped, never paged. Every other reason in
#: ``REASONS`` (and ``translator_crashed``) means a harness or the engine
#: drifted, and pages.
EXPECTED_FALLBACK_REASONS = frozenset({"no_adapter", "sdk_source", "source_empty"})


def harness_of(agent_model: Optional[str]) -> Optional[str]:
    """The harness a ``conversations.agent_model`` value names: a CLI harness
    key for its wrapper id (``claude-code`` → ``claude_code``), ``llm`` for
    any real model id, None for an unborn row. Mirrors the frontend's
    ``harnessOf``."""
    if not agent_model:
        return None
    from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE

    for model_type, wrapper_id in WRAPPER_ID_BY_MODEL_TYPE.items():
        if agent_model == wrapper_id:
            return model_type
    return SDK_HARNESS


def harness_pins() -> Dict[str, str]:
    """Harness → the version NoClick pins (``_cli_models.json``)."""
    from nodes.agent.config._cli_models_loader import (
        claude_code_version, codex_version, hermes_ref, openclaw_version, opencode_version,
    )

    return {
        "claude_code": claude_code_version(), "codex": codex_version(), "opencode": opencode_version(),
        "openclaw": openclaw_version(), "hermes_agent": hermes_ref(),
    }


def pair_support(source: str, target: str) -> Optional[Tuple[str, str]]:
    """``(reason, detail)`` when a thread cannot move natively from ``source``
    to ``target``, else None. Derived from the format registry: a harness
    moves when the engine has a format for it."""
    if source == target:
        return ("same_harness", "")
    for harness in (source, target):
        if harness == SDK_HARNESS:
            return ("sdk_source", REASONS["sdk_source"])
        if harness not in FORMATS:
            return ("no_adapter", f"{harness} has no thread format")
    return None


def codex_model_provider(home: Path, *, custom_base_url: bool = False) -> str:
    """The provider id a Codex thread under ``home`` runs against: the
    ``model_provider`` its config names, else the stock ``openai`` (API key
    and ChatGPT sign-in alike). ``custom_base_url`` is the hosted config's
    rule — an OpenAI-compatible endpoint is written as provider ``custom``."""
    if custom_base_url:
        return "custom"
    try:
        import tomllib

        with open(home / "config.toml", "rb") as fh:
            provider = tomllib.load(fh).get("model_provider")
        if isinstance(provider, str) and provider.strip():
            return provider.strip()
    except (OSError, ValueError):
        pass
    return "openai"


def target_identity(model_type: str, *, home: Path, model: Optional[str], custom_base_url: bool = False) -> TargetIdentity:
    """What the target harness runs as, from NoClick's pins and config."""
    return TargetIdentity(
        cli_version=harness_pins().get(model_type),
        model_provider=codex_model_provider(home, custom_base_url=custom_base_url) if model_type == "codex" else None,
        model=model or None,
    )


# ── reporting ────────────────────────────────────────────────────────────────


def stamp_span(source_harness: str, target_harness: str, *, reason: str = "", native: bool) -> None:
    """The alertable trace: ``session.interchange.fallback = true`` with the
    pair and reason (the channel ``mcp.delivery.*`` alerts ride); a native
    move stamps ``session.interchange.native = true``."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("session.interchange.native", native)
            span.set_attribute("session.interchange.fallback", not native)
            span.set_attribute("session.interchange.source", source_harness)
            span.set_attribute("session.interchange.target", target_harness)
            if reason:
                span.set_attribute("session.interchange.reason", reason)
    except Exception:
        pass


async def record_native_move(pool: Any, *, conversation_id: str, result: Dict[str, Any]) -> None:
    """A successful move: span + the verdict on the conversation row."""
    stamp_span(result.get("source_harness", ""), result.get("target_harness", ""), native=True)
    logger.info("[SessionInterchange] native %s→%s for %s: %s",
                result.get("source_harness"), result.get("target_harness"), conversation_id, result.get("fidelity"))
    await _set_last_interchange(pool, conversation_id, {**result, "ok": True})


async def report_fallback(
    pool: Any,
    *,
    user_id: str,
    conversation_id: str,
    source_harness: str,
    target_harness: str,
    reason: str,
    detail: str = "",
    versions: Optional[Dict[str, str]] = None,
    loud: Optional[bool] = None,
) -> None:
    """Make a fallback impossible to miss: error log, span attributes, one
    deduped feedback row (Slack) per pair and reason per day, and the
    verdict on the conversation row for the chat to show. Never raises.

    ``loud`` defaults from the reason: a translation FAILURE pages (a harness
    or the engine drifted), an expected limit is recorded quietly."""
    if loud is None:
        loud = reason not in EXPECTED_FALLBACK_REASONS
    stamp_span(source_harness, target_harness, reason=reason, native=False)
    log = logger.error if loud else logger.info
    log("[SessionInterchange] FALLBACK %s→%s for %s: %s %s versions=%s",
        source_harness, target_harness, conversation_id, reason, detail[:300], versions or {})
    if loud:
        try:
            from utils.feedback import record_feedback

            await record_feedback(
                pool, user_id=user_id, feedback_type="interchange_fallback",
                message=f"Thread translation {source_harness}→{target_harness} fell back to carried context: {reason}",
                metadata={"conversation_id": conversation_id, "reason": reason, "detail": detail[:2000], "versions": versions or {}},
                dedupe_key=f"{source_harness}:{target_harness}:{reason}", dedupe_window_hours=24,
            )
        except Exception:
            logger.warning("[SessionInterchange] fallback feedback not recorded", exc_info=True)
    await _set_last_interchange(pool, conversation_id, {
        "ok": False, "source_harness": source_harness, "target_harness": target_harness,
        "reason": reason, "detail": detail[:500], "versions": versions or {},
    })


def versions_for_report() -> Dict[str, str]:
    return {**harness_pins(), "interchange": INTERCHANGE_VERSION}


async def _set_last_interchange(pool: Any, conversation_id: str, value: Dict[str, Any]) -> None:
    try:
        from repositories.conversation import ConversationRepo

        await ConversationRepo(pool).set_metadata_key(conversation_id, "last_interchange", value)
    except Exception:
        logger.warning("[SessionInterchange] verdict not recorded on the conversation", exc_info=True)


__all__ = [
    "EXPECTED_FALLBACK_REASONS", "FORMATS", "INTERCHANGE_VERSION", "REASONS", "SDK_HARNESS", "InterchangeError",
    "InterchangeResult", "StoreRef", "TargetIdentity", "carried_context", "codex_model_provider", "harness_of",
    "harness_pins", "move_thread", "pair_support", "parse_verdict", "read_thread", "record_native_move",
    "report_fallback", "stamp_span", "target_identity", "turns_from_projection", "versions_for_report",
    "with_carried_context",
]

"""Conversation threads move between harnesses as the harness's own session
files, never as a history dump in the first message.

Each CLI harness keeps a conversation in its native store (a Claude Code
JSONL under ``projects/``, a Codex rollout, OpenCode's database, Hermes's
state database), and that store is the full-fidelity record of the thread:
roles, tool calls with their results, timestamps. Loading a thread NATIVELY
keeps that structure, so the provider's prefix caching and the harness's own
compaction keep working turn over turn. This module is the one seam that
turns one harness's store into another's, on a plain filesystem session
home — the hosted runtime hands it mounted volumes, the local edition its own
directories — and it never runs inside the in-sandbox daemon, which stays
stdlib-only. It runs INSIDE the target harness's sandbox instead (as the
``python3 nc_interchange.py`` script the hosted launcher ships — see
``main``), and in-process in the local edition, so it must import nothing
from the backend at module level.

The translator is ``session-migrate`` (pinned: ``TRANSLATOR_VERSION``). Around
it this module adds what production needs: a fidelity verdict computed by
re-reading the written store and comparing the conversation skeleton (every
message, every tool call paired with its result, in order), a classification
of the library's dropped-record counters into losses we accept (metadata,
provider-bound reasoning) and losses we don't, and — when translation fails —
a bounded carried-context block for the first message that the chat display
already knows how to strip, reported LOUDLY so a drift in a harness's format
is a page, not a silent degradation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: The pinned translator. ``requirements.txt`` and every harness sandbox image
#: install exactly this (``translator_requirement``); ``tests/test_session_interchange_drift.py``
#: pins the three against each other.
TRANSLATOR_VERSION = "0.11.0"


def translator_requirement() -> str:
    return f"session-migrate=={TRANSLATOR_VERSION}"


#: NoClick harness keys → session-migrate format names. OpenClaw's JSONL has
#: no adapter; a switch involving it takes the fallback.
HARNESS_FORMATS: Dict[str, str] = {
    "claude_code": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "hermes_agent": "hermes",
}

#: Harnesses the translator has a format for but cannot ADDRESS the way
#: NoClick runs them: Hermes threads live under the fixed gateway session
#: name ``noclick``, while the translator only resolves Hermes's
#: timestamp-prefixed native ids. An expected fallback, not a drift.
UNADDRESSABLE: Dict[str, str] = {
    "hermes_agent": "hermes threads run under the fixed gateway session 'noclick', which the translator cannot address",
}

#: The in-process SDK agent (``coder/openai_agent``): its history is our own
#: JSONB, not a harness store, so a switch FROM it carries context.
SDK_HARNESS = "llm"

#: Fallback reasons that are a known product limit rather than a translation
#: failure: recorded and stamped, never paged.
EXPECTED_FALLBACK_REASONS = frozenset({"no_adapter", "unaddressable", "sdk_source", "source_empty"})

#: Dropped-record keys (session-migrate's counters, by prefix) that are the
#: expected cost of leaving a harness: its bookkeeping records, provider-bound
#: reasoning, titles, and shapes the target represents differently. Anything
#: else is a fidelity loss the verdict must surface.
ACCEPTED_DROP_PREFIXES: Tuple[str, ...] = (
    "opaque",
    "thinking",
    "context",
    "session:",
    "timestamp:",
    "tool_call:non_object_input",
    "tool_result:is_error",
    "message:ui_only_projection",
    "message:privileged_role",  # a harness's own developer/system message; the target injects its own
    "tool_call:namespace",
)

FALLBACK_CHAR_BUDGET = 4000
_CARRY_OPEN = "<<<NOCLICK_CARRIED_CONTEXT"
_CARRY_CLOSE = "NOCLICK_CARRIED_CONTEXT>>>"


class InterchangeError(Exception):
    """Translation could not produce a store the target harness will resume
    faithfully. Carries the machine-readable ``reason`` the report stamps."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Skeleton:
    """The conversation's shape, independent of any harness: what a faithful
    translation must preserve."""

    roles: List[str]
    tool_calls: int
    tool_results: int
    unpaired_tool_calls: int

    @property
    def messages(self) -> int:
        return len(self.roles)


@dataclass
class Fidelity:
    source: Skeleton
    target: Skeleton
    dropped: Dict[str, int] = field(default_factory=dict)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    rejected_drops: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (
            not self.rejected_drops
            and self.source.roles == self.target.roles
            and self.source.tool_calls == self.target.tool_calls
            and self.source.tool_results == self.target.tool_results
            and self.target.unpaired_tool_calls == 0
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "source": {"messages": self.source.messages, "tool_calls": self.source.tool_calls, "tool_results": self.source.tool_results},
            "target": {"messages": self.target.messages, "tool_calls": self.target.tool_calls, "tool_results": self.target.tool_results, "unpaired_tool_calls": self.target.unpaired_tool_calls},
            "dropped": self.dropped,
            "rejected_drops": self.rejected_drops,
            "warnings": len(self.warnings),
        }


@dataclass
class InterchangeResult:
    source_harness: str
    target_harness: str
    session_id: str
    native_path: Optional[Path]
    manifest_path: Optional[Path]
    fidelity: Fidelity
    translator_version: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "source_harness": self.source_harness, "target_harness": self.target_harness,
            "session_id": self.session_id,
            "native_path": str(self.native_path) if self.native_path else None,
            "fidelity": self.fidelity.as_dict(), "translator_version": self.translator_version,
        }


@dataclass
class StoreRef:
    """Where one harness keeps this conversation's thread, and how the harness
    finds it again: ``home`` is the directory the translator addresses (the
    Claude config dir, ``CODEX_HOME``, OpenCode's XDG data home), ``cwd`` the
    working directory the thread ran under (Claude keys sessions on it), and
    ``pointer`` the file NoClick's runner reads to resume by id (codex's thread
    file, opencode's session file; the local Claude runner's ``--continue``
    marker). A move writes the new thread's id into the target's pointer."""

    harness: str
    home: Path
    cwd: Path
    pointer: Optional[Path] = None
    session_id: Optional[str] = None
    cli: Optional[Path] = None
    environ: Optional[Dict[str, str]] = None


def skeleton_of(session: Any) -> Skeleton:
    """The conversation skeleton of a session-migrate ``Session``."""
    roles: List[str] = []
    calls = results = 0
    open_calls: set = set()
    for event in session.events:
        kind = getattr(event.kind, "value", str(event.kind))
        role = getattr(event.role, "value", str(event.role)) if event.role is not None else None
        if kind == "message" and role in ("user", "assistant"):  # system/developer text is the harness's, not the thread's
            roles.append(role)
        elif kind == "tool_call":
            calls += 1
            if event.tool_call_id:
                open_calls.add(event.tool_call_id)
        elif kind == "tool_result":
            results += 1
            open_calls.discard(event.tool_call_id)
    return Skeleton(roles=roles, tool_calls=calls, tool_results=results, unpaired_tool_calls=len(open_calls))


def classify_drops(dropped: Dict[str, int]) -> Dict[str, int]:
    """The dropped-record counters that are NOT an accepted cost of leaving
    a harness — a non-empty result fails the verdict."""
    return {
        key: count
        for key, count in dropped.items()
        if count and not any(key == p or key.startswith(p) for p in ACCEPTED_DROP_PREFIXES)
    }


def translator_lag(harness: str, pins: Dict[str, str]) -> Optional[str]:
    """Why the pinned translator cannot serve ``harness`` at the version
    NoClick pins, or None. Only OpenCode is a hard gate: the library drives
    its CLI for export and import and refuses any other version. Claude and
    Codex read by record shape, so a newer pin is a warning the fixtures in
    ``tests/test_session_interchange.py`` turn into a test."""
    if harness != "opencode" or not pins.get("opencode"):
        return None
    from session_migrate.formats import opencode

    if opencode.PINNED_OPENCODE_VERSION != pins["opencode"]:
        return (
            f"session-migrate {TRANSLATOR_VERSION} drives opencode {opencode.PINNED_OPENCODE_VERSION}; "
            f"NoClick pins {pins['opencode']}"
        )
    return None


def pair_support(source: str, target: str, *, pins: Optional[Dict[str, str]] = None) -> Optional[Tuple[str, str]]:
    """``(reason, detail)`` when a thread cannot move natively from ``source``
    to ``target``, else None. ``pins`` (harness → pinned version) enables the
    translator-lag check; the in-sandbox script runs without it, the backend
    has already judged."""
    if source == target:
        return ("same_harness", "")
    for harness in (source, target):
        if harness == SDK_HARNESS:
            return ("sdk_source", "the in-process agent keeps its history in the conversation row, not a harness store")
        if harness not in HARNESS_FORMATS:
            return ("no_adapter", f"{harness} has no translator adapter")
        if harness in UNADDRESSABLE:
            return ("unaddressable", UNADDRESSABLE[harness])
        lag = translator_lag(harness, pins or {})
        if lag:
            return ("translator_pin_mismatch", lag)
    return None


def harness_of(agent_model: Optional[str]) -> Optional[str]:
    """The harness a ``conversations.agent_model`` value names: a CLI harness
    key for its wrapper id (``claude-code`` → ``claude_code``), ``llm`` for
    any real model id, None for an unborn row. Backend-only (reads the
    provider table); mirrors the frontend's ``harnessOf``."""
    if not agent_model:
        return None
    from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE

    for model_type, wrapper_id in WRAPPER_ID_BY_MODEL_TYPE.items():
        if agent_model == wrapper_id:
            return model_type
    return SDK_HARNESS


def harness_pins() -> Dict[str, str]:
    """Harness → the version NoClick pins (``_cli_models.json``). Backend-only."""
    from nodes.agent.config._cli_models_loader import (
        claude_code_version, codex_version, hermes_ref, openclaw_version, opencode_version,
    )

    return {
        "claude_code": claude_code_version(), "codex": codex_version(), "opencode": opencode_version(),
        "openclaw": openclaw_version(), "hermes_agent": hermes_ref(),
    }


def load_native_session(
    harness: str, *, home: Path, session_ref: str,
    cli: Optional[Path] = None, environ: Optional[Dict[str, str]] = None,
) -> Any:
    """The harness's native thread as a session-migrate ``Session``.

    ``session_ref`` is a file path for file-backed stores (Claude Code, Codex)
    and the native session id for database-backed ones (OpenCode via its CLI
    export, Hermes via its state database)."""
    fmt = _format_for(harness)
    from session_migrate import conversion
    from session_migrate.model import AgentFormat

    if fmt == "opencode":
        return conversion.load_opencode_session(session_ref, source_cli=cli, environ=environ)
    if fmt == "hermes":
        return conversion.load_hermes_session(session_ref, source_home=home)
    return conversion.load_session(Path(session_ref), AgentFormat(fmt))


def locate_source(ref: StoreRef) -> str:
    """The thread ``ref`` holds for this conversation — a file path for
    file-backed stores, a native id otherwise. Prefers the runner's pointer
    (the exact thread it would resume); a Claude store is keyed on the cwd,
    newest session first, the same rule ``--continue`` applies."""
    from session_migrate.errors import SessionMigrateError

    fmt = _format_for(ref.harness)
    pointed = ref.session_id or _read_pointer(ref.pointer)
    if fmt in ("opencode", "hermes"):
        if not pointed:
            raise InterchangeError("source_empty", f"no {ref.harness} session id recorded for this conversation")
        return pointed
    if fmt == "codex":
        if pointed:
            from session_migrate.discovery import locate_session
            from session_migrate.model import AgentFormat

            try:
                return str(locate_session(AgentFormat.CODEX, pointed, ref.home))
            except SessionMigrateError as e:
                raise InterchangeError("source_empty", f"codex thread {pointed} not found under {ref.home}: {e}") from e
        candidates = list((ref.home / "sessions").glob("*/*/*/rollout-*.jsonl"))
    else:  # claude: the cwd's project first, any project as a fallback
        from session_migrate.formats.claude import project_directory_name

        projects = ref.home / "projects"
        candidates = list((projects / project_directory_name(ref.cwd)).glob("*.jsonl")) or list(projects.glob("*/*.jsonl"))
    candidates = [c for c in candidates if c.is_file()]
    if not candidates:
        raise InterchangeError("source_empty", f"no {ref.harness} thread under {ref.home}")
    return str(max(candidates, key=lambda c: c.stat().st_mtime))


def translate(
    session: Any,
    *,
    target_harness: str,
    target_home: Path,
    cwd: Path,
    target_cli: Optional[Path] = None,
    target_cli_version: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
) -> InterchangeResult:
    """Write ``session`` into ``target_harness``'s store under ``target_home``
    and return the verdict. Raises ``InterchangeError`` when the target would
    not hold the conversation faithfully — the written files are left in
    place only when the verdict passed."""
    from session_migrate import __version__ as translator_version
    from session_migrate import conversion
    from session_migrate.errors import SessionMigrateError
    from session_migrate.model import TargetFormat

    fmt = _format_for(target_harness)
    source_skeleton = skeleton_of(session)
    if source_skeleton.messages == 0:
        raise InterchangeError("empty_source", "the source thread holds no messages")
    options = conversion.ConversionOptions(target_format=TargetFormat(fmt), cwd=cwd, target_cli_version=target_cli_version)
    try:
        artifact = conversion.convert_session(session, options)
    except SessionMigrateError as e:
        raise InterchangeError("convert_failed", str(e)) from e

    rejected = classify_drops(dict(artifact.dropped))
    if rejected:
        raise InterchangeError("fidelity_drop", json.dumps(rejected, sort_keys=True))

    native_path: Optional[Path] = None
    manifest_path: Optional[Path] = None
    try:
        if fmt == "opencode":
            manifest_path = conversion.opencode_manifest_path(artifact, state_home=target_home)
            native_path = conversion.install_opencode_artifact(
                artifact, manifest_path=manifest_path, target_cli=target_cli, environ=environ,
            )
        elif fmt == "hermes":
            native_path, manifest_path = conversion.install_hermes_artifact(
                artifact, target_home=target_home, target_cli=target_cli, environ=environ,
            )
        else:
            native_path, manifest_path = conversion.target_import_paths(artifact, target_home)
            _install_file_artifact(artifact, native_path, manifest_path)
    except (SessionMigrateError, OSError) as e:
        raise InterchangeError("install_failed", str(e)) from e

    # The verdict reads the store BACK through the library's own reader for
    # that harness: what a resume would see, not what we meant to write.
    try:
        written = load_native_session(
            target_harness, home=target_home,
            session_ref=str(native_path) if fmt in ("claude", "codex") else artifact.session_id,
            cli=target_cli, environ=environ,
        )
    except (SessionMigrateError, OSError, InterchangeError) as e:
        _discard(native_path, manifest_path)
        raise InterchangeError("readback_failed", str(e)) from e
    fidelity = Fidelity(
        source=source_skeleton, target=skeleton_of(written),
        dropped=dict(artifact.dropped), warnings=list(artifact.warnings), rejected_drops=rejected,
    )
    if not fidelity.ok:
        _discard(native_path, manifest_path)
        raise InterchangeError("readback_mismatch", json.dumps(fidelity.as_dict(), sort_keys=True))
    return InterchangeResult(
        source_harness=_harness_for_format(getattr(session.source_format, "value", str(session.source_format))),
        target_harness=target_harness, session_id=artifact.session_id,
        native_path=native_path, manifest_path=manifest_path,
        fidelity=fidelity, translator_version=translator_version,
    )


def move_thread(source: StoreRef, target: StoreRef, *, target_cli_version: Optional[str] = None) -> InterchangeResult:
    """Move this conversation's thread from ``source`` into ``target``'s store
    and point ``target``'s runner at it. Raises ``InterchangeError`` with the
    reason the caller reports; ``source_empty`` means there was nothing to
    move (the target's own store is the latest) and is not a failure."""
    blocked = pair_support(source.harness, target.harness)
    if blocked:
        raise InterchangeError(*blocked)
    session = load_native_session(
        source.harness, home=source.home, session_ref=locate_source(source), cli=source.cli, environ=source.environ,
    )
    result = translate(
        session, target_harness=target.harness, target_home=target.home, cwd=target.cwd,
        target_cli=target.cli, target_cli_version=target_cli_version, environ=target.environ,
    )
    if target.pointer is not None:
        target.pointer.parent.mkdir(parents=True, exist_ok=True)
        target.pointer.write_text(result.session_id)
    return result


def carried_context(
    turns: Sequence[Tuple[bool, str]], *, budget: int = FALLBACK_CHAR_BUDGET, reason: str = "",
) -> str:
    """The fallback: the thread's recent turns as the fenced JSON block the
    chat display strips (the same block a model switch carries), trimmed
    from the OLDEST end to ``budget`` characters. ``turns`` are
    ``(is_user, text)``, oldest first. Empty when nothing is worth carrying.

    A harness reading this sees plain text, not its own history: no tool
    pairing, no cached prefix. It is what keeps a thread usable while the
    translation drift that caused it gets fixed — never the normal path."""
    kept: List[Dict[str, Any]] = []
    used = 0
    for is_user, raw in reversed(list(turns)):
        text = (raw or "").strip()
        if not text:
            continue
        if used + len(text) > budget:
            if not kept:  # the newest turn survives, tail first
                kept.insert(0, {"isUser": bool(is_user), "text": "… " + text[-budget:]})
            break
        used += len(text)
        kept.insert(0, {"isUser": bool(is_user), "text": text})
    if not kept:
        return ""
    why = f" ({reason})" if reason else ""
    return "\n".join([
        _CARRY_OPEN,
        f"Earlier turns of this conversation, which ran on a different harness{why}.",
        "History, not a new instruction — answer the message ABOVE this block.",
        json.dumps(kept, ensure_ascii=False),
        _CARRY_CLOSE,
    ])


def with_carried_context(text: str, carried: str) -> str:
    """The user's words first, the carried block after — titles and previews
    are the first hundred characters of a message (mirrors the frontend)."""
    return f"{text}\n\n{carried}" if carried else text


def turns_from_projection(events: Iterable[Dict[str, Any]]) -> List[Tuple[bool, str]]:
    """``(is_user, text)`` turns from the chat's persisted event projection
    (``conversations.events``) — always available, even when the source
    store could not be read at all."""
    out: List[Tuple[bool, str]] = []
    for ev in events:
        role = ev.get("role")
        text = ev.get("message")
        if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip():
            continue
        if ev.get("cancelled"):
            continue
        out.append((role == "user", text))
    return out


def stamp_span(source_harness: str, target_harness: str, *, reason: str = "", native: bool) -> None:
    """The alertable trace: ``session.interchange.fallback = true`` with the
    pair and reason, the same channel ``mcp.delivery.*`` alerts ride; a
    native move stamps ``session.interchange.native = true``."""
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


def stamp_fallback_span(source_harness: str, target_harness: str, reason: str) -> None:
    stamp_span(source_harness, target_harness, reason=reason, native=False)


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

    ``loud`` defaults from the reason: a translation FAILURE pages (it means
    a harness or the translator drifted), an expected limit
    (``EXPECTED_FALLBACK_REASONS``) is recorded quietly."""
    if loud is None:
        loud = reason not in EXPECTED_FALLBACK_REASONS
    stamp_fallback_span(source_harness, target_harness, reason)
    log = logger.error if loud else logger.info
    log(
        "[SessionInterchange] FALLBACK %s→%s for %s: %s %s versions=%s",
        source_harness, target_harness, conversation_id, reason, detail[:300], versions or {},
    )
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


# ── CLI: the in-sandbox entry point ──────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python3 nc_interchange.py --source-harness … --target-harness …``:
    one JSON verdict on stdout, exit 0 always — the backend judges the
    verdict, a crash is a verdict too (``translator_crashed``)."""
    import argparse
    import traceback

    ap = argparse.ArgumentParser()
    ap.add_argument("--source-harness", required=True)
    ap.add_argument("--source-home", required=True)
    ap.add_argument("--source-cwd")
    ap.add_argument("--source-pointer")
    ap.add_argument("--source-session-id")
    ap.add_argument("--target-harness", required=True)
    ap.add_argument("--target-home", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--target-pointer")
    ap.add_argument("--target-cli-version")
    a = ap.parse_args(argv)
    cwd = Path(a.cwd)
    try:
        result = move_thread(
            StoreRef(a.source_harness, Path(a.source_home), Path(a.source_cwd or a.cwd),
                     pointer=Path(a.source_pointer) if a.source_pointer else None, session_id=a.source_session_id),
            StoreRef(a.target_harness, Path(a.target_home), cwd,
                     pointer=Path(a.target_pointer) if a.target_pointer else None),
            target_cli_version=a.target_cli_version,
        )
        verdict: Dict[str, Any] = result.as_dict()
    except InterchangeError as e:
        verdict = {"ok": False, "reason": e.reason, "detail": e.detail}
    except Exception:
        verdict = {"ok": False, "reason": "translator_crashed", "detail": traceback.format_exc()[-1500:]}
    print(json.dumps(verdict))
    return 0


def parse_verdict(stdout: str) -> Dict[str, Any]:
    """The verdict ``main`` printed — the LAST JSON line of stdout (a harness
    CLI the translator drives may chatter first)."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                verdict = json.loads(line)
            except ValueError:
                continue
            if isinstance(verdict, dict) and "ok" in verdict:
                return verdict
    return {"ok": False, "reason": "translator_crashed", "detail": f"no verdict in output: {stdout[-500:]!r}"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _format_for(harness: str) -> str:
    try:
        return HARNESS_FORMATS[harness]
    except KeyError:
        raise InterchangeError("unsupported_harness", f"{harness} has no translator adapter") from None


def _harness_for_format(fmt: str) -> str:
    for harness, name in HARNESS_FORMATS.items():
        if name == fmt:
            return harness
    return fmt


def _install_file_artifact(artifact: Any, native_path: Path, manifest_path: Path) -> None:
    """Land a file-backed artifact (Claude Code, Codex) where the harness
    reads it. The translator's own installer hard-links a temp file into
    place and ``fchmod``s it — the FUSE-backed session volumes the hosted
    sandboxes mount reject both (``Operation not permitted``), so the write
    here is a plain create-if-absent (``O_EXCL``, mode 0600 where the
    filesystem honours it) with no rename, link or chmod after."""
    for path, data in ((native_path, artifact.native_bytes),
                       (manifest_path, (json.dumps(artifact.manifest(output_path=native_path), indent=2, sort_keys=True) + "\n").encode())):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                try:
                    os.fsync(stream.fileno())
                except OSError:
                    pass  # a volume that does not fsync still persists on commit
        except BaseException:
            _discard(path)
            raise


def _read_pointer(pointer: Optional[Path]) -> Optional[str]:
    if pointer is None:
        return None
    try:
        return pointer.read_text().strip() or None
    except OSError:
        return None


def _discard(*paths: Optional[Path]) -> None:
    for p in paths:
        if p is None:
            continue
        try:
            if p.is_file():
                os.remove(p)
        except OSError:
            pass


async def _set_last_interchange(pool: Any, conversation_id: str, value: Dict[str, Any]) -> None:
    try:
        from repositories.conversation import ConversationRepo

        await ConversationRepo(pool).set_metadata_key(conversation_id, "last_interchange", value)
    except Exception:
        logger.warning("[SessionInterchange] verdict not recorded on the conversation", exc_info=True)


if __name__ == "__main__":  # the in-sandbox script
    raise SystemExit(main())

"""Local-edition wiring for the thread interchange
(``nodes/agent/interchange``): the same move the hosted runtime runs inside
a sandbox, run in-process on the operator's own session stores before the
new harness's process starts.

Every local harness keeps its state under the conversation workdir (a
subscription sign-in's ``.claude``/``.codex`` home) or the operator's real
home; ``local_store`` resolves both the way ``run_local_harness_turn`` sets
the process up, so the engine reads the thread the previous harness
actually wrote and writes where the next one actually looks.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from nodes.agent.session_interchange import (
    InterchangeError,
    StoreRef,
    carried_context,
    harness_of,
    move_thread,
    pair_support,
    record_native_move,
    report_fallback,
    target_identity,
    turns_from_projection,
    versions_for_report,
)

logger = logging.getLogger(__name__)


def local_store(harness: str, workdir: Path, env: Dict[str, str], *, as_target: bool) -> Optional[StoreRef]:
    """Where ``harness`` keeps this conversation's thread on this machine.

    A target uses the home the process about to start will read (the env
    ``_apply_subscription_login`` prepared, else the operator's real home). A
    source's env is gone, so its home is inferred: a subscription sign-in
    left its home inside the workdir, otherwise the thread is in the real
    home. Returns None for harnesses without a local store adapter."""
    home_dir = Path(os.environ.get("HOME") or Path.home())
    if harness == "claude_code":
        if as_target:
            home = Path(env.get("CLAUDE_CONFIG_DIR") or home_dir / ".claude")
        else:
            home = workdir / ".claude" if (workdir / ".claude" / "projects").is_dir() else home_dir / ".claude"
        # The local runner passes --continue only once this marker exists.
        return StoreRef(harness, home, workdir, pointer=workdir / ".noclick-turns")
    if harness == "codex":
        if as_target:
            home = Path(env.get("CODEX_HOME") or home_dir / ".codex")
        else:
            home = workdir / ".codex" if (workdir / ".codex" / "sessions").is_dir() else home_dir / ".codex"
        return StoreRef(harness, home, workdir, pointer=workdir / ".noclick-codex-thread")
    return None


async def interchange_local(
    node: Any, model_type: str, workdir: Path, env: Dict[str, str], *,
    conversation_id: str, user_id: str, model: Optional[str] = None,
) -> str:
    """Move the thread into ``model_type``'s store when the conversation last
    ran elsewhere. Returns the carried-context block for the first message
    when the move did not happen natively (empty when it did, or when there
    was nothing to move). Never raises — a turn must not die on its history."""
    previous = harness_of(getattr(node, "_previous_agent_model", None))
    if previous is None or previous == model_type:
        return ""
    try:
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
    except Exception:
        logger.warning("[LocalInterchange] no database pool; verdict will not be recorded")
        pool = None
    reason = detail = ""
    blocked = pair_support(previous, model_type)
    if blocked:
        reason, detail = blocked
    else:
        source = local_store(previous, workdir, env, as_target=False)
        target = local_store(model_type, workdir, env, as_target=True)
        if source is None or target is None:
            reason, detail = "no_adapter", f"{previous if source is None else model_type} has no local store adapter"
        else:
            identity = target_identity(model_type, home=target.home, model=model)
            try:
                result = await asyncio.to_thread(move_thread, source, target, identity)
            except InterchangeError as e:
                reason, detail = e.reason, e.detail
            except Exception as e:
                reason, detail = "translator_crashed", f"{type(e).__name__}: {e}"[:1500]
            else:
                await record_native_move(pool, conversation_id=conversation_id, result=result.as_dict())
                return ""
    block = ""
    if reason != "source_empty":
        try:
            from repositories.conversation import ConversationRepo

            events = await ConversationRepo(pool).read_events(conversation_id, user_id)
        except Exception:
            logger.warning("[LocalInterchange] projection unreadable; carrying nothing", exc_info=True)
            events = []
        block = carried_context(turns_from_projection(events), reason=reason)
    await report_fallback(
        pool, user_id=user_id, conversation_id=conversation_id, source_harness=previous, target_harness=model_type,
        reason=reason, detail=detail, versions=versions_for_report(),
    )
    return block

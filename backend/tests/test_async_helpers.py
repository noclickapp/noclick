"""Tests for utils.async_helpers — specifically the tracked-set spawn()
helper. This helper exists because bare asyncio.create_task has a known
weak-ref GC gotcha (Python 3.11+ docs); these tests prove spawn() avoids it
AND that exceptions surface in logs instead of being silently swallowed.

Also includes a codebase-wide AST static guard
(``test_no_orphan_create_task_outside_allowlist``) that fails fast on any
new bare ``asyncio.create_task`` / ``asyncio.ensure_future`` site
introduced outside the explicit allowlist. New fire-and-forget background
work MUST use ``spawn()``.
"""

import ast
import asyncio
import gc
import logging
from pathlib import Path

import pytest

from utils.async_helpers import (
    _bg_tasks,
    active_task_count,
    drain_spawned_tasks,
    spawn,
)


@pytest.mark.asyncio
async def test_spawn_returns_task_and_runs_to_completion():
    completed = []

    async def work():
        await asyncio.sleep(0.01)
        completed.append("done")

    task = spawn(work(), name="basic-spawn-test")
    assert isinstance(task, asyncio.Task)
    assert task.get_name() == "basic-spawn-test"

    # Without holding our own reference, the task must still complete
    # (this is what bare asyncio.create_task does NOT guarantee post-3.11).
    del task
    gc.collect()

    # Wait for the spawned work to finish via the tracked set
    await asyncio.sleep(0.05)
    assert completed == ["done"]


@pytest.mark.asyncio
async def test_spawn_holds_strong_reference_until_completion():
    """The whole reason spawn() exists: prove the tracked set holds a
    strong reference for the task's full lifetime."""
    started = asyncio.Event()
    can_finish = asyncio.Event()

    async def work():
        started.set()
        await can_finish.wait()

    initial = active_task_count()
    spawn(work(), name="strong-ref-test")
    await started.wait()

    # Force aggressive GC; the tracked set must still hold the task.
    for _ in range(3):
        gc.collect()

    assert active_task_count() == initial + 1
    assert any(t.get_name() == "strong-ref-test" for t in _bg_tasks)

    can_finish.set()
    await asyncio.sleep(0.02)  # let the done callback run
    assert active_task_count() == initial


@pytest.mark.asyncio
async def test_spawn_removes_task_from_set_when_done():
    initial = active_task_count()

    async def quick():
        await asyncio.sleep(0)

    spawn(quick(), name="cleanup-test")
    assert active_task_count() == initial + 1
    await asyncio.sleep(0.02)  # let done callback run
    assert active_task_count() == initial


@pytest.mark.asyncio
async def test_spawn_logs_unhandled_exception(caplog):
    """If the spawned coroutine raises, the exception must surface in logs
    with the task name — otherwise debugging leaked background failures is
    impossible. The exception MUST NOT propagate out of the caller's loop."""

    async def boom():
        raise ValueError("expected failure in test")

    with caplog.at_level(logging.ERROR, logger="utils.async_helpers"):
        spawn(boom(), name="exception-test")
        await asyncio.sleep(0.02)

    matching = [r for r in caplog.records if "exception-test" in r.message]
    assert matching, "exception must surface in logs with the task name"
    assert any("expected failure in test" in r.getMessage() or
               (r.exc_info and r.exc_info[1] and "expected failure" in str(r.exc_info[1]))
               for r in matching), "exception traceback must be attached"


@pytest.mark.asyncio
async def test_spawn_silent_on_cancellation():
    """Cancellation is not an error — must not log."""
    can_finish = asyncio.Event()

    async def slow():
        await can_finish.wait()

    task = spawn(slow(), name="cancel-test")
    task.cancel()
    await asyncio.sleep(0.02)
    # Cancelled tasks are reaped from the tracked set
    assert task not in _bg_tasks


@pytest.mark.asyncio
async def test_spawn_does_not_block_caller():
    """spawn() returns immediately — the caller continues without awaiting."""
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(0.5)

    spawn(slow(), name="non-blocking")
    # Give the slow coroutine a chance to start
    await asyncio.wait_for(started.wait(), timeout=0.1)
    # We're not waiting for slow() to finish — proven by the fact that
    # this test completes in much less than 0.5s.


@pytest.mark.asyncio
async def test_active_task_count_diagnostic():
    """active_task_count is a stable diagnostic for future leak hunting —
    it reflects the in-flight count, monotonically returning to baseline."""
    initial = active_task_count()
    spawn(asyncio.sleep(0.02), name="diag-1")
    spawn(asyncio.sleep(0.02), name="diag-2")
    assert active_task_count() == initial + 2
    await asyncio.sleep(0.05)
    assert active_task_count() == initial


@pytest.mark.asyncio
async def test_drain_spawned_tasks_waits_for_one_shot_work():
    completed = []

    async def work():
        await asyncio.sleep(0)
        completed.append(True)

    spawn(work(), name="shutdown-drain-complete")
    drained, cancelled = await drain_spawned_tasks(timeout=0.5)

    assert completed == [True]
    assert drained >= 1
    assert cancelled == 0


@pytest.mark.asyncio
async def test_drain_spawned_tasks_cancels_after_timeout():
    never = asyncio.Event()
    task = spawn(never.wait(), name="shutdown-drain-cancel")

    drained, cancelled = await drain_spawned_tasks(timeout=0)

    assert drained == 0
    assert cancelled >= 1
    assert task.cancelled()
    assert task not in _bg_tasks


# ============================================================================
# Codebase-wide AST static guard
# ============================================================================
#
# Walk every .py file in backend/ (excluding tests / scripts) and find every
# bare ``asyncio.create_task(...)`` / ``asyncio.ensure_future(...)`` call
# that's a statement-level expression — i.e., the returned Task is
# discarded. Each such site is the Python 3.11+ weak-ref GC footgun.
#
# After the 2026-05-27 sweep (PRs #1161/#1164/#1165/#1166 + this one), the
# only allowed-and-documented exceptions are listed in
# ORPHAN_ALLOWLIST below. Each entry must include a *reason* — adding to
# this list requires a deliberate decision, not silent regression.
#
# Adding a new orphan ``asyncio.create_task`` outside the allowlist is the
# wrong thing — use ``spawn()`` from ``utils.async_helpers`` instead.

# Each entry: (relative path, lineno, reason).
# Reasons must explain why spawn() is the wrong abstraction here.

ORPHAN_ALLOWLIST: set = set()


def _scan_orphans():
    """AST-walk backend/ and yield (path, lineno, attr) for each orphan
    bare-call statement matching asyncio.create_task / ensure_future.
    Also catches the same calls inside lambda bodies; those are still
    orphans, just not at the statement level."""
    root = Path(__file__).resolve().parent.parent  # backend/
    excludes = {"tests", "scripts", "__pycache__"}

    def is_target(call):
        if not isinstance(call, ast.Call):
            return False
        f = call.func
        return (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "asyncio"
            and f.attr in {"create_task", "ensure_future"}
        )

    for path in sorted(root.rglob("*.py")):
        if any(part in excludes for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # Statement-level orphan: bare call as a statement (Task discarded).
            if isinstance(node, ast.Expr) and is_target(node.value):
                rel = str(path.relative_to(root.parent))
                yield (rel, node.lineno, node.value.func.attr)
            # Lambda-body orphan: lambda's expression body is itself an
            # orphan create_task/ensure_future call.
            elif isinstance(node, ast.Lambda) and is_target(node.body):
                rel = str(path.relative_to(root.parent))
                yield (rel, node.body.lineno, node.body.func.attr)


def test_no_orphan_create_task_outside_allowlist():
    """Fail fast if any new bare asyncio.create_task / ensure_future
    appears outside the explicit allowlist. New fire-and-forget background
    work MUST use ``spawn()`` from ``utils.async_helpers``."""
    found = list(_scan_orphans())
    actual = {(path, attr) for path, _lineno, attr in found}
    new = actual - ORPHAN_ALLOWLIST
    if new:
        details = "\n".join(
            f"  {p}:{ln}  asyncio.{a}"
            for p, ln, a in found
            if (p, a) not in ORPHAN_ALLOWLIST
        )
        pytest.fail(
            "Bare orphan asyncio.create_task / ensure_future sites found "
            "outside the allowlist:\n" + details + "\n\n"
            "Each new fire-and-forget background task must use "
            "spawn() from utils.async_helpers (which holds a strong "
            "reference to prevent the Python 3.11+ weak-ref GC gotcha "
            "and logs unhandled exceptions). If you have a legitimate "
            "reason for the bare-call pattern, add the (path, attr) tuple "
            "to ORPHAN_ALLOWLIST in test_async_helpers.py with a reason "
            "comment explaining why spawn() is the wrong abstraction."
        )


def test_orphan_allowlist_entries_still_exist():
    """If an allowlisted site is removed or refactored, drop it from the
    allowlist instead of leaving stale entries. Catches drift in the
    other direction (we cleaned up the bare-call but forgot to update
    the allowlist)."""
    actual = {(path, attr) for path, _lineno, attr in _scan_orphans()}
    stale = ORPHAN_ALLOWLIST - actual
    if stale:
        pytest.fail(
            "Stale ORPHAN_ALLOWLIST entries (the bare-call site no longer "
            "exists in the source):\n" + "\n".join(f"  {p}  asyncio.{a}" for p, a in stale)
            + "\n\nRemove these entries from ORPHAN_ALLOWLIST."
        )

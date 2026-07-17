"""Concurrency-safety for workflow_node_state read-modify-write.

`_update_node_state` is the optimistic-concurrency primitive poll/trigger dedup
uses to advance its watermark: it reads state, applies a pure mutator, and
writes under compare-and-swap so a racing writer on another container can't be
clobbered (the old plain upsert was last-writer-wins, which double-fired
triggers). These tests exercise the retry loop against an in-memory store that
simulates the DB's version column.
"""
import pytest

from nodes.core.base import WorkflowNode, NodeStateConflict, _UNSET_VERSION

pytestmark = pytest.mark.asyncio


class _Store:
    """Stand-in for one workflow_node_state row (state + CAS version)."""

    def __init__(self, state=None, version=0, exists=True):
        self.state = dict(state or {})
        self.version = version
        self.exists = exists
        self.writes = 0


class _StateNode(WorkflowNode):
    """Minimal node whose state I/O is an in-memory CAS store."""

    def __init__(self, store):
        self.workflow_id = "wf"
        self.node_id = "n"
        self._store = store

    async def execute(self, inputs):
        return {}

    async def _load_node_state(self):
        self._node_state_version = self._store.version if self._store.exists else None
        return dict(self._store.state)

    async def _save_node_state(self, state, *, expected_version=_UNSET_VERSION):
        s = self._store
        if expected_version is _UNSET_VERSION:
            s.state, s.exists, s.writes = dict(state), True, s.writes + 1
            s.version += 1
            return
        if expected_version is None:
            if s.exists:
                raise NodeStateConflict("racing insert")
            s.state, s.version, s.exists, s.writes = dict(state), 0, True, s.writes + 1
            self._node_state_version = 0
            return
        if expected_version != s.version:
            raise NodeStateConflict(f"stale (expected {expected_version}, have {s.version})")
        s.state, s.writes = dict(state), s.writes + 1
        s.version += 1
        self._node_state_version = s.version


async def test_update_writes_and_returns_result():
    store = _Store({"seen": ["a"]}, version=3)
    node = _StateNode(store)

    result = await node._update_node_state(
        lambda st: ({"seen": st["seen"] + ["b"]}, "emitted-b")
    )

    assert result == "emitted-b"
    assert store.state == {"seen": ["a", "b"]}
    assert store.version == 4  # CAS bumped it exactly once
    assert store.writes == 1


async def test_update_skips_write_when_mutator_returns_none():
    store = _Store({"seen": ["a"]}, version=3)
    node = _StateNode(store)

    result = await node._update_node_state(lambda st: (None, "nothing-new"))

    assert result == "nothing-new"
    assert store.writes == 0
    assert store.version == 3  # untouched


async def test_update_retries_on_conflict_and_reapplies():
    """A concurrent writer lands between this node's read and its CAS write; the
    loop must re-read the winner's state and re-apply the mutator on top of it
    rather than clobbering it."""
    store = _Store({"seen": ["a"]}, version=1)
    node = _StateNode(store)
    mutator_runs = {"n": 0}

    def mutator(st):
        mutator_runs["n"] += 1
        # On the first pass, simulate another container writing during our
        # compute window — this invalidates our stashed version so the CAS
        # below loses and the loop retries against the fresh state.
        if mutator_runs["n"] == 1:
            store.state = {"seen": ["a", "concurrent"]}
            store.version += 1
        return {"seen": st["seen"] + ["mine"]}, "ok"

    result = await node._update_node_state(mutator)

    assert result == "ok"
    assert mutator_runs["n"] == 2  # ran once, lost CAS, re-ran on fresh state
    # The concurrent writer's item survives — not clobbered.
    assert store.state == {"seen": ["a", "concurrent", "mine"]}
    assert store.writes == 1  # only the winning CAS wrote


async def test_update_raises_after_exhausting_retries():
    store = _Store({"seen": []}, version=0)
    node = _StateNode(store)

    # A racing writer lands on every compute window → the CAS never converges.
    def always_conflict(st):
        store.version += 1
        return {"seen": ["x"]}, "x"

    with pytest.raises(NodeStateConflict):
        await node._update_node_state(always_conflict, max_retries=3)


async def test_update_skips_on_state_read_error_when_skip_result_given():
    """A transient state-read failure with skip_result set returns it (tick
    skipped, state untouched) instead of raising — a scheduled dedup poll must
    not fail the run on a DB blip."""
    class _BoomNode(_StateNode):
        async def _load_node_state(self):
            raise RuntimeError("pooler timeout")

    node = _BoomNode(_Store({"seen": ["a"]}, version=2))
    result = await node._update_node_state(
        lambda st: ({"seen": st["seen"] + ["b"]}, "wrote"), skip_result="SKIP"
    )
    assert result == "SKIP"


async def test_update_skips_on_exhaustion_when_skip_result_given():
    store = _Store({"seen": ["a"]}, version=0)
    node = _StateNode(store)

    def always_conflict(st):
        store.version += 1  # racing writer every attempt → never converges
        return {"seen": ["x"]}, "x"

    result = await node._update_node_state(
        always_conflict, max_retries=3, skip_result="SKIP"
    )
    assert result == "SKIP"
    assert store.state == {"seen": ["a"]}  # untouched — no partial write


async def test_update_still_raises_on_state_error_without_skip_result():
    """Default (no skip_result): a state error propagates — non-dedup callers
    that need the write to land must see the failure."""
    class _BoomNode(_StateNode):
        async def _load_node_state(self):
            raise RuntimeError("db down")

    node = _BoomNode(_Store())
    with pytest.raises(RuntimeError):
        await node._update_node_state(lambda st: ({"x": 1}, "w"))


async def test_update_inserts_when_row_absent():
    store = _Store(state={}, version=0, exists=False)
    node = _StateNode(store)

    result = await node._update_node_state(
        lambda st: ({"seen_ids": ["first"]}, "baselined")
    )

    assert result == "baselined"
    assert store.exists is True
    assert store.state == {"seen_ids": ["first"]}

"""Scheduled poll triggers must not run downstream nodes when a poll finds no
new data — the cron POST is only a wake-up signal. These tests cover both halves
of the mechanism: the poll mixin's "emitted nothing" signal
(``_filter_unseen`` / ``polled_with_no_new_items``) and the concurrent executor
halting downstream when the node sets the ``_halt_downstream`` output sentinel.
Added with the fix that stopped poll-driven agents from running every tick.
"""
import pytest
from unittest.mock import AsyncMock

from nodes.core.poll_trigger import ScheduledPollTriggerMixin, bounded_seen_ids
from nodes.gmail_node import GmailNode
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

pytestmark = pytest.mark.asyncio


def test_bounded_seen_ids_preserves_recent_on_overflow():
    """When the seen-set overflows the cap, the OLDEST-inactive ids drop — never
    ids still in the current window — and this poll's ids move to the end."""
    # prev = 3 stale ids; current poll re-sees "b" and adds "d","e"; cap 3.
    result = bounded_seen_ids(["a", "b", "c"], ["b", "d", "e"], cap=3)
    # "a","c" (not re-seen) are the oldest-inactive → dropped; "b" (re-seen) and
    # the new ids survive, ordered with the current poll last.
    assert result == ["b", "d", "e"]
    # Every current-window id is retained (none re-fire next poll).
    assert set(["b", "d", "e"]).issubset(result)


def test_bounded_seen_ids_dedupes_and_orders():
    # Under the cap: stale-not-reseen kept in front, current ids appended, deduped.
    assert bounded_seen_ids(["a", "b"], ["b", "c"], cap=10) == ["a", "b", "c"]
    # First-run style (no prev): just the deduped current ids, capped.
    assert bounded_seen_ids([], ["x", "x", "y", "z"], cap=2) == ["y", "z"]


class _FakePoll(ScheduledPollTriggerMixin):
    """Minimal poll node exercising the dedup helper with in-memory state.

    Mirrors ``WorkflowNode._update_node_state`` semantics: read state, apply the
    mutator, write the returned new state (or skip the write when it's None).
    """

    def __init__(self):
        self.workflow_id = "wf"
        self.node_id = "n"
        self._state = {}

    async def _update_node_state(self, mutator, *, max_retries: int = 4, skip_result=None):
        new_state, result = mutator(dict(self._state))
        if new_state is not None:
            self._state = dict(new_state)
        return result


async def test_mixin_filter_unseen_signals_emptiness():
    p = _FakePoll()
    # First poll baselines: records current items as seen, emits nothing.
    assert await p._filter_unseen([{"id": "1"}], lambda x: x["id"]) == []
    assert p.trigger_produced_no_event({}) is True
    # Same item again → still nothing new.
    assert await p._filter_unseen([{"id": "1"}], lambda x: x["id"]) == []
    assert p.trigger_produced_no_event({}) is True
    # A genuinely new item → emitted → has new items.
    fresh = await p._filter_unseen([{"id": "1"}, {"id": "2"}], lambda x: x["id"])
    assert [i["id"] for i in fresh] == ["2"]
    assert p.trigger_produced_no_event({}) is False


async def test_an_epoch_change_rebaselines_instead_of_firing_every_old_id():
    """IMAP's UIDVALIDITY: a rebuilt folder renumbers its messages, so ids recorded under another epoch name
    something else and the whole window would look new."""
    p = _FakePoll()
    ids = lambda x: x
    assert await p._filter_unseen(["1", "2"], ids, epoch="v1") == []
    assert await p._filter_unseen(["1", "2", "3"], ids, epoch="v1") == ["3"]
    assert await p._filter_unseen(["1", "2", "3", "4"], ids, epoch="v2") == [], "a new epoch baselines"
    assert p._state["epoch"] == "v2"
    assert await p._filter_unseen(["1", "2", "3", "4", "5"], ids, epoch="v2") == ["5"]


async def test_a_seen_set_without_an_epoch_adopts_one():
    p = _FakePoll()
    await p._filter_unseen(["1"], lambda x: x)
    assert await p._filter_unseen(["1", "2"], lambda x: x, epoch="v1") == ["2"]
    assert p._state["epoch"] == "v1"


async def test_max_fresh_emits_the_oldest_and_holds_the_rest_for_the_next_poll():
    p = _FakePoll()
    await p._filter_unseen(["a"], lambda x: x)
    items = ["a", "b", "c", "d", "e"]
    assert await p._filter_unseen(items, lambda x: x, max_fresh=2) == ["b", "c"]
    assert await p._filter_unseen(items, lambda x: x, max_fresh=2) == ["d", "e"]
    assert await p._filter_unseen(items, lambda x: x, max_fresh=2) == []


async def test_prepare_reads_only_what_emits_and_an_item_it_leaves_out_stays_new():
    p = _FakePoll()
    asked = []

    async def prepare(chosen):
        asked.append(list(chosen))
        return {item: {"read": item} for item in chosen if item != "c"}

    assert await p._filter_unseen(["a"], lambda x: x, prepare=prepare) == []
    assert asked == [], "a baseline reads nothing"
    assert await p._filter_unseen(["a", "b", "c"], lambda x: x, prepare=prepare) == [{"read": "b"}]
    assert asked == [["b", "c"]]
    assert "c" not in p._state["seen_ids"], "what couldn't be read isn't marked seen"

    async def recovered(chosen):
        return {item: {"read": item} for item in chosen}

    assert await p._filter_unseen(["a", "b", "c"], lambda x: x, prepare=recovered) == [{"read": "c"}]


async def test_a_failed_prepare_marks_nothing_seen():
    p = _FakePoll()
    await p._filter_unseen(["a"], lambda x: x)

    async def broken(chosen):
        raise RuntimeError("the server dropped the connection")

    with pytest.raises(RuntimeError):
        await p._filter_unseen(["a", "b"], lambda x: x, prepare=broken)
    assert p._state["seen_ids"] == ["a"]


async def test_the_arm_time_baseline_never_prepares_over_an_existing_baseline():
    p = _FakePoll()
    await p._filter_unseen(["a"], lambda x: x)
    p._poll_baseline_only = True

    async def prepare(chosen):
        raise AssertionError("a headless baseline run must not read new items")

    assert await p._filter_unseen(["a", "b"], lambda x: x, prepare=prepare, max_fresh=5) == []
    assert p._state["seen_ids"] == ["a"], "and it consumes nothing"


async def test_an_unreadable_state_skips_the_tick_before_preparing():
    p = _FakePoll()

    async def unreadable(mutator, *, max_retries=4, skip_result=None):
        return skip_result

    p._update_node_state = unreadable

    async def prepare(chosen):
        raise AssertionError("nothing is read when the seen-set can't be")

    assert await p._filter_unseen(["a"], lambda x: x, prepare=prepare) == []
    assert p.trigger_produced_no_event({}) is True


async def test_mixin_defaults_false_when_never_polled():
    # A node that never polled must never wrongly halt downstream.
    assert _FakePoll().trigger_produced_no_event({}) is False


def test_gmail_reads_emptiness_from_output():
    # Gmail dedups via internalDate high-water-mark; emptiness is read off the output.
    g = GmailNode.__new__(GmailNode)  # predicate reads only `output`, not self
    empty = {"operation": "poll_for_new_emails", "email_count": 0, "emails": []}
    has_mail = {"operation": "poll_for_new_emails", "email_count": 1, "emails": [{"id": "x"}]}
    assert g.trigger_produced_no_event(empty) is True
    assert g.trigger_produced_no_event(has_mail) is False


@pytest.fixture
def handler():
    sio = AsyncMock()
    sio.emit = AsyncMock()
    return WorkflowExecutionHandler(sio=sio)


def _poll_agent_graph():
    nodes = [
        {"id": "poll", "type": "automation-google-sheets", "config": {}},
        {"id": "agent", "type": "agent", "config": {}},
    ]
    edges = [{"source": "poll", "target": "agent"}]
    return nodes, edges


async def test_empty_poll_halts_downstream(handler):
    """An empty scheduled poll (signalled via _halt_downstream) skips the agent."""
    log = []

    async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
        log.append(node["id"])
        if node["id"] == "poll":
            return {"rows": [], "new_row_count": 0, "_halt_downstream": True}
        return {"node_id": node["id"]}

    handler._execute_node = mock_execute_node
    nodes, edges = _poll_agent_graph()
    executed, error, outputs = await handler._execute_nodes_concurrent(
        nodes, edges, "sid", "user", "wf"
    )

    assert error is None
    assert "agent" not in log, f"agent must be skipped on an empty poll; ran: {log}"
    assert executed == 0  # poll is skipped (not completed), agent cascade-skipped
    assert "_halt_downstream" not in outputs.get("poll", {})  # sentinel stripped


async def test_poll_with_new_data_runs_downstream(handler):
    """A poll that found new data (no sentinel) runs the agent as normal."""
    log = []

    async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
        log.append(node["id"])
        if node["id"] == "poll":
            return {"rows": [{"row": 1}], "new_row_count": 1}
        return {"node_id": node["id"]}

    handler._execute_node = mock_execute_node
    nodes, edges = _poll_agent_graph()
    executed, error, _ = await handler._execute_nodes_concurrent(
        nodes, edges, "sid", "user", "wf"
    )

    assert error is None
    assert "agent" in log, f"agent should run when there's new data; ran: {log}"
    assert executed == 2


def test_empty_poll_halt_has_no_manual_run_exemption():
    """The empty-poll halt must apply on EVERY run source. It used to be gated
    on _triggerPayload ("manual/test runs flow through"), which delivered
    {responses: [], new_response_count: 0} into a downstream agent as a real
    turn on a manual run (2026-08-04). The halt decision may depend only on
    trigger_produced_no_event — never on how the run was started; testing
    downstream without new data is what mockedOutput is for."""
    import inspect

    src = inspect.getsource(WorkflowExecutionHandler._execute_node)
    assert "_halt_downstream" in src  # the sentinel is still set here
    code_only = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "_triggerPayload" not in code_only


async def test_mixin_reports_emitted_event():
    """trigger_emitted_event is the positive counterpart: True exactly when
    the poll ran this run and emitted fresh items (drives the executor's
    _pollFired stamp for agent event delivery on any run source)."""
    p = _FakePoll()
    await p._filter_unseen([{"id": "1"}], lambda x: x["id"])  # baseline
    assert p.trigger_emitted_event({}) is False
    fresh = await p._filter_unseen([{"id": "1"}, {"id": "2"}], lambda x: x["id"])
    assert [i["id"] for i in fresh] == ["2"]
    assert p.trigger_emitted_event({}) is True
    await p._filter_unseen([{"id": "1"}, {"id": "2"}], lambda x: x["id"])  # nothing new
    assert p.trigger_emitted_event({}) is False


def test_never_polled_never_reports_emitted():
    assert _FakePoll().trigger_emitted_event({}) is False


def test_gmail_reads_emitted_from_output():
    g = GmailNode.__new__(GmailNode)
    assert g.trigger_emitted_event(
        {"operation": "poll_for_new_emails", "emails": [{"id": "x"}]}
    ) is True
    assert g.trigger_emitted_event(
        {"operation": "poll_for_new_emails", "emails": []}
    ) is False
    assert g.trigger_emitted_event({"operation": "send_email_message"}) is False


def test_executor_stamps_poll_fired_marker():
    """The stamp must live right after execute() in _execute_node — the only
    place where "this poll ran THIS run" is known — and key on
    trigger_emitted_event, so preloaded outputs can never be stamped."""
    import inspect

    src = inspect.getsource(WorkflowExecutionHandler._execute_node)
    assert "_pollFired" in src
    assert "trigger_emitted_event" in src

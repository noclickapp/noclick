"""The AI builder's stored-output inspection: <list_outputs> + the
execution/path drill-down on <get_output>.

Before this, the brain could only read a node's LATEST output, and an empty
read told it to "run the node first" — for a WhatsApp trigger that read as
"no message has arrived" while an hour-old delivery sat in the store behind
a Test Run's no-event placeholder (2026-09-09). Browsing has to stay cheap:
one compact line per run, expansion by subtree, never a page per event.
"""

import pytest

from coder.workflow.agentic.commands import (
    LIST_OUTPUTS_MAX_LIMIT,
    LIST_OUTPUTS_SEARCH_SCAN,
    compact_preview,
    execute_node_ops,
    walk_output_path,
)
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_xml import XmlOp, parse_xml

RUN_A = "11111111-1111-1111-1111-111111111111"
RUN_B = "22222222-2222-2222-2222-222222222222"

VOICE_NOTE = {
    "event": "message",
    "payload": {
        "id": "false_12025550102@lid_3A95",
        "from": "12025550102@lid",
        "body": None,
        "hasMedia": True,
        "media": {"url": "https://assets.example/ff05/v.oga", "mimetype": "audio/ogg; codecs=opus"},
        "senderPhone": "12025550102",
    },
}
NO_EVENT = {"status": "no_event", "message": "No live event: manual run of receive_message."}


class _Platform:
    def __init__(self, latest=None, history=(), by_run=None):
        self.latest = latest
        self.history = list(history)
        self.by_run = by_run or {}
        self.calls = []

    async def get_node_output(self, node_id):
        self.calls.append(("latest", node_id))
        return self.latest

    async def get_node_output_history(self, node_id, limit):
        self.calls.append(("history", node_id, limit))
        return self.history[:limit]

    async def get_node_output_at(self, node_id, execution_id):
        self.calls.append(("at", node_id, execution_id))
        return self.by_run.get(execution_id)

    async def run_node(self, node_id, include_downstream=False):
        raise AssertionError("inspection must never run the node")


def _graph(node_type="automation-whatsapp", operation="receive_message"):
    g = GraphState()
    g.add_node("wa", node_type, "WhatsApp")
    if operation:
        g.get_node("wa").operation = operation
    return g


def _row(execution_id, output, **over):
    return {
        "execution_id": execution_id,
        "created_at": "2026-09-09T14:34:00+00:00",
        "output": output,
        "trigger_source": "webhook",
        "run_status": "delivered",
        "node_status": "completed",
        "error": None,
        **over,
    }


# ============================================================================
# Registration + parsing
# ============================================================================




def test_inspection_attrs_parse():
    ops = parse_xml('<list_outputs node="wa" limit="5" search="9197" />')
    assert ops[0].tag == "list_outputs" and ops[0].attrs == {"node": "wa", "limit": "5", "search": "9197"}
    ops = parse_xml(f'<get_output node="wa" execution="{RUN_A}" path="payload.media" full />')
    assert ops[0].attrs["execution"] == RUN_A
    assert ops[0].attrs["path"] == "payload.media"
    assert "full" in ops[0].attrs


def test_system_prompt_documents_inspection():
    from coder.workflow.agentic.prompts import build_system_prompt_parts

    stable, _ = build_system_prompt_parts()
    assert "<list_outputs" in stable
    assert 'execution="RUN_ID"' in stable
    assert 'path="' in stable


# ============================================================================
# Pure helpers
# ============================================================================


def test_compact_preview_reads_the_facts_that_matter_in_one_line():
    line = compact_preview({**VOICE_NOTE, "_data": {"raw": "x" * 1000}})
    assert "\n" not in line and "_data" not in line  # raw provider blobs never spend the budget
    assert line.startswith('event="message", payload.id="false_12025550102@lid_3…", payload.from="12025550102@lid"')
    assert 'payload.media.url="https://assets.example/…"' in line  # host, not an opaque path
    # Shallow scalars first, so the sender lands before the nested media …
    assert line.index('payload.senderPhone="12025550102"') < line.index("payload.media.url=")
    # … nulls last, so `body=null` never displaces the media type.
    assert 'payload.media.mimetype="audio/ogg; codecs=opus"' in line
    assert line.index("payload.body=null") > line.index("payload.media.mimetype=")
    assert len(line) <= 281  # budget + the trailing ellipsis


def test_compact_preview_clips_long_strings_lists_and_the_budget():
    big = {"text": "x" * 500, "items": list(range(200)), "rows": [{"id": 1}, {"id": 2}]}
    line = compact_preview(big, budget=60)
    assert len(line) <= 61 and line.endswith("…")
    assert 'text="' + "x" * 23 + '…"' in line  # 24-char string clip
    assert compact_preview(big) == (
        'text="' + "x" * 23 + '…", items=[0, 1, 2, +197], rows=[2 items], rows[0].id=1'
    )
    assert compact_preview({"a": 1, "b": [True, None], "c": None}) == "a=1, b=[true, null], c=null"
    assert compact_preview("plain") == '"plain"'


def test_walk_output_path_drills_and_names_what_exists_on_a_miss():
    sub, err = walk_output_path(VOICE_NOTE, "payload.media")
    assert err is None and sub["mimetype"].startswith("audio/")
    sub, err = walk_output_path({"items": [{"id": 7}]}, "items[0].id")
    assert (sub, err) == (7, None)
    _, err = walk_output_path(VOICE_NOTE, "payload.medai")
    assert "no key 'medai' at payload" in err and "keys: id, from, body, hasMedia, media, senderPhone" in err
    _, err = walk_output_path({"items": [1]}, "items[3]")
    assert "no index [3] at items" in err and "a list of 1 items" in err
    _, err = walk_output_path(VOICE_NOTE, "payload..x")
    assert "malformed path segment" in err


# ============================================================================
# execute_node_ops
# ============================================================================


@pytest.mark.asyncio
async def test_list_outputs_one_line_per_run_with_provenance():
    platform = _Platform(history=[
        _row(RUN_B, NO_EVENT, trigger_source="manual", run_status="completed"),
        _row(RUN_A, VOICE_NOTE),
    ])
    out = await execute_node_ops([XmlOp(tag="list_outputs", attrs={"node": "wa"}, body="")], platform, _graph())
    text = out[0]
    assert text.startswith("[list_outputs node=wa] newest 2 stored outputs, newest first.")
    assert f'<get_output node="wa" execution="ID" />' in text
    assert f"#1 2026-09-09 14:34 UTC · manual · completed execution={RUN_B}" in text
    assert f"#2 2026-09-09 14:34 UTC · webhook · completed execution={RUN_A}" in text
    assert "12025550102" in text and "audio/ogg" in text  # the preview carries the sender + kind
    assert "older ones exist" not in text
    # Default limit 10 → the platform is asked for 11 (the extra row detects "more").
    assert platform.calls == [("history", "wa", 11)]


@pytest.mark.asyncio
async def test_list_outputs_limit_is_clamped_and_more_is_signalled():
    rows = [_row(f"{i:08d}-0000-0000-0000-000000000000", {"i": i}) for i in range(40)]
    platform = _Platform(history=rows)
    out = await execute_node_ops(
        [XmlOp(tag="list_outputs", attrs={"node": "wa", "limit": "999"}, body="")], platform, _graph()
    )
    assert platform.calls == [("history", "wa", LIST_OUTPUTS_MAX_LIMIT + 1)]
    assert f"#{LIST_OUTPUTS_MAX_LIMIT} " in out[0] and f"#{LIST_OUTPUTS_MAX_LIMIT + 1} " not in out[0]
    assert "older ones exist" in out[0]
    # A garbage limit falls back to the default rather than erroring the turn.
    platform = _Platform(history=rows[:3])
    out = await execute_node_ops(
        [XmlOp(tag="list_outputs", attrs={"node": "wa", "limit": "ten"}, body="")], platform, _graph()
    )
    assert platform.calls == [("history", "wa", 11)] and "#3 " in out[0]


@pytest.mark.asyncio
async def test_list_outputs_search_filters_the_newest_window_by_content():
    rows = [_row(RUN_B, NO_EVENT), _row(RUN_A, VOICE_NOTE)]
    platform = _Platform(history=rows)
    out = await execute_node_ops(
        [XmlOp(tag="list_outputs", attrs={"node": "wa", "search": "5550102"}, body="")], platform, _graph()
    )
    assert platform.calls == [("history", "wa", LIST_OUTPUTS_SEARCH_SCAN)]
    assert "1 match among the newest 2 stored outputs" in out[0]
    assert RUN_A in out[0] and RUN_B not in out[0]
    out = await execute_node_ops(
        [XmlOp(tag="list_outputs", attrs={"node": "wa", "search": "nope"}, body="")], platform, _graph()
    )
    assert "None of the newest 2 stored outputs contains 'nope'" in out[0]


@pytest.mark.asyncio
async def test_empty_trigger_reads_as_no_delivery_not_run_it():
    platform = _Platform(latest=None, history=[])
    graph = _graph()
    for tag in ("get_output", "list_outputs"):
        out = await execute_node_ops([XmlOp(tag=tag, attrs={"node": "wa"}, body="")], platform, graph)
        assert "no delivery has been recorded for this trigger" in out[0]
        assert "run_node" not in out[0].split("A manual")[0]  # never the first instruction
    # trigger-* types count without consulting the registry; action nodes keep the old advice.
    out = await execute_node_ops(
        [XmlOp(tag="get_output", attrs={"node": "wa"}, body="")], platform, _graph("trigger-webhook", None)
    )
    assert "no delivery has been recorded" in out[0]
    out = await execute_node_ops(
        [XmlOp(tag="get_output", attrs={"node": "wa"}, body="")], platform, _graph("automation-slack", "send_message")
    )
    assert 'Run the node first with <run_node node="wa" />' in out[0]


@pytest.mark.asyncio
async def test_latest_get_output_flags_placeholders_and_points_at_history():
    platform = _Platform(latest={"output": NO_EVENT, "created_at": "2026-09-09T20:04:00+00:00", "stored_count": 3})
    out = await execute_node_ops([XmlOp(tag="get_output", attrs={"node": "wa"}, body="")], platform, _graph())
    assert out[0].startswith("[get_output node=wa] (latest, stored 2026-09-09T20:04:00+00:00) Output schema:")
    assert "manual run's no-event placeholder" in out[0]
    assert '3 outputs are stored across runs — <list_outputs node="wa" />' in out[0]
    # A single real output gets neither hint.
    platform = _Platform(latest={"output": VOICE_NOTE, "created_at": "t", "stored_count": 1})
    out = await execute_node_ops([XmlOp(tag="get_output", attrs={"node": "wa"}, body="")], platform, _graph())
    assert "placeholder" not in out[0] and "list_outputs" not in out[0]


@pytest.mark.asyncio
async def test_get_output_by_execution_and_path_expands_only_the_subtree():
    platform = _Platform(latest={"output": NO_EVENT, "stored_count": 2}, by_run={RUN_A: VOICE_NOTE})
    op = XmlOp(tag="get_output", attrs={"node": "wa", "execution": RUN_A, "path": "payload.media", "full": ""}, body="")
    out = await execute_node_ops([op], platform, _graph())
    assert platform.calls == [("at", "wa", RUN_A)]  # the latest read is skipped entirely
    assert out[0].startswith(f"[get_output node=wa execution={RUN_A} path=payload.media full]\n")
    assert '"mimetype": "audio/ogg; codecs=opus"' in out[0]
    assert "senderPhone" not in out[0]  # only the subtree
    # Schema view of a subtree, and a miss that teaches the real keys.
    op = XmlOp(tag="get_output", attrs={"node": "wa", "execution": RUN_A, "path": "payload"}, body="")
    out = await execute_node_ops([op], platform, _graph())
    assert "Output schema:" in out[0] and "senderPhone: '12025550102'" in out[0]
    op = XmlOp(tag="get_output", attrs={"node": "wa", "execution": RUN_A, "path": "payload.medai"}, body="")
    out = await execute_node_ops([op], platform, _graph())
    assert "no key 'medai' at payload" in out[0]


@pytest.mark.asyncio
async def test_get_output_by_execution_rejects_bad_ids_and_reports_missing_runs():
    platform = _Platform(by_run={RUN_A: VOICE_NOTE})
    out = await execute_node_ops(
        [XmlOp(tag="get_output", attrs={"node": "wa", "execution": "#2"}, body="")], platform, _graph()
    )
    assert "must be the full run id shown by <list_outputs" in out[0]
    assert platform.calls == []
    out = await execute_node_ops(
        [XmlOp(tag="get_output", attrs={"node": "wa", "execution": RUN_B}, body="")], platform, _graph()
    )
    assert "No stored output for that run" in out[0]


@pytest.mark.asyncio
async def test_inspection_ops_name_unknown_nodes():
    platform = _Platform()
    for tag in ("get_output", "list_outputs"):
        out = await execute_node_ops([XmlOp(tag=tag, attrs={"node": "ghost"}, body="")], platform, _graph())
        assert "does not exist in the workflow" in out[0]
        out = await execute_node_ops([XmlOp(tag=tag, attrs={}, body="")], platform, _graph())
        assert "'node' attribute is required" in out[0]
    assert platform.calls == []

"""Caps on tool output entering the model request and the persisted history.

Root cause (2026-08-24): execute_bash returned its result uncapped, so one
`cat` of a 415KB PDF put millions of JSON-escaped tokens into the model
request AND into ``conversations.metadata.sdk_history`` — after which EVERY
turn of that conversation replayed the giant item and died on the provider's
context limit (even a bare "hi"). Two independent bounds fix the class:

  1. ``clip_bash_result`` — write-time cap at the execute_bash tool, so a
     single command can never produce an unbounded tool message.
  2. ``clip_history_item`` — load-time cap in PostgresSession.get_items on
     ``function_call_output`` items, so a conversation whose stored history
     already carries an oversized tool output (pre-fix rows, or any other
     writer) is healed on replay instead of bricked forever.

Deliberately dependency-free so both agent.py and session.py import it.
"""
from typing import Any, Dict

# execute_bash is a real work tool (unlike the builder's investigative <bash>,
# capped at 4000), so it gets room for genuine file reads — but bounded: worst
# case ~10-15k tokens per call instead of millions.
BASH_STDOUT_CAP = 30_000
BASH_STDERR_CAP = 10_000
# Backstop for replayed history items — generous (a legit tool result should
# never be near this), it only exists to keep a pathological stored item from
# killing every subsequent turn.
HISTORY_TOOL_OUTPUT_CAP = 50_000


def clip_text(text: str, cap: int) -> str:
    """Head+tail clip with an omission marker — command output puts errors at
    the end, so the tail must survive the clip."""
    if len(text) <= cap:
        return text
    head = int(cap * 0.7)
    tail = cap - head
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n... <{omitted} chars omitted — output clipped; "
        f"re-run with head/tail/grep to see specific parts> ...\n{text[-tail:]}"
    )


def clip_bash_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Bound an execute_bash result's stdout/stderr before it reaches the
    model (and, via the SDK session, the persisted history)."""
    out = dict(result)
    stdout = out.get("stdout")
    if isinstance(stdout, str):
        out["stdout"] = clip_text(stdout, BASH_STDOUT_CAP)
    stderr = out.get("stderr")
    if isinstance(stderr, str):
        out["stderr"] = clip_text(stderr, BASH_STDERR_CAP)
    return out


def clip_history_item(item: Any) -> Any:
    """Bound a stored SDK history item on load. Only tool-output items are
    touched (``{"type": "function_call_output", "output": "<str>"}``) — user
    and assistant content replays verbatim."""
    if (
        isinstance(item, dict)
        and item.get("type") == "function_call_output"
        and isinstance(item.get("output"), str)
        and len(item["output"]) > HISTORY_TOOL_OUTPUT_CAP
    ):
        return {**item, "output": clip_text(item["output"], HISTORY_TOOL_OUTPUT_CAP)}
    return item

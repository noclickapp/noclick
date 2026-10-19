"""Caps on tool output entering the model request and the persisted history.

Root cause (2026-08-24): execute_bash returned its result uncapped, so one
`cat` of a 415KB PDF put millions of JSON-escaped tokens into the model
request AND into ``conversations.metadata.sdk_history`` — after which EVERY
turn of that conversation replayed the giant item and died on the provider's
context limit (even a bare "hi"). Independent bounds fix the class:

  1. ``tool_output`` — write-time cap where every SDK tool's result becomes
     the model's tool message (``clip_bash_result`` bounds execute_bash's two
     streams apart first), so no single call produces an unbounded tool message.
  2. ``clip_history_item`` — load-time cap in PostgresSession.get_items on
     ``function_call_output`` items, so a conversation whose stored history
     already carries an oversized tool output (pre-fix rows, or any other
     writer) is healed on replay instead of bricked forever.

Several results of one turn can still outgrow the model's context together
(three web searches with page text did, 2026-10); the compactor cuts them in
the model's view to ``TOOL_OUTPUT_FLOOR``, and the ones already acted on to
``TOOL_OUTPUT_STUB`` when the turn can't fold any further.

Deliberately dependency-free so both agent.py and session.py import it.
"""
import json
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
# Any tool's whole result as the model reads it: a whole execute_bash result's
# worth (~10k tokens), under the history backstop so a new result replays verbatim.
TOOL_OUTPUT_CAP = BASH_STDOUT_CAP + BASH_STDERR_CAP
# The least of a result the compactor keeps when one turn's results outgrow the model's context.
TOOL_OUTPUT_FLOOR = 2_000
# What it keeps of one the model already acted on, once folding can't make room (the turn's summaries spent, or one
# failed): its head and tail, so a long turn's next call still fits rather than failing.
TOOL_OUTPUT_STUB = 300

BASH_HINT = "output clipped; re-run with head/tail/grep to see specific parts"
TOOL_HINT = ("the tool's result was clipped; call it again for a narrower part "
             "(fewer results, one page or URL, a filter) to see the rest")
CONTEXT_HINT = "cut to fit the model's context; call the tool again for the part you need"


def clip_text(text: str, cap: int, hint: str = BASH_HINT) -> str:
    """Head+tail clip with an omission marker saying how to see the rest —
    command output puts errors at the end, so the tail must survive the clip."""
    if len(text) <= cap:
        return text
    head = int(cap * 0.7)
    tail = cap - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n... <{omitted} chars omitted: {hint}> ...\n{text[-tail:]}"


def tool_output(result: Any) -> str:
    """A tool's result as the model reads it and the session keeps it: JSON, at
    most ``TOOL_OUTPUT_CAP`` characters."""
    try:
        # Characters as themselves: a model copying "·" back into a file wrote a control character.
        text = json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(result)
    # A lone surrogate, which UTF-8 can't carry, stays escaped.
    text = text.encode("utf-8", "backslashreplace").decode("utf-8")
    return clip_text(text, TOOL_OUTPUT_CAP, TOOL_HINT)


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

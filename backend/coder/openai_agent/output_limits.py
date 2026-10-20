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
``TOOL_OUTPUT_STUB`` when the turn can't fold any further. A call's own
arguments (a commit carrying whole files) are cut the same way
(``clip_arguments``), keeping the call's JSON.

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
# The least of each long string a cut call's arguments keep: its head and tail, so a stub still says what it held.
ARGUMENT_STRING_FLOOR = 64
# A copy of a cut argument (a file it wrote) would write the marker back, so it says where the whole value is.
ARGUMENTS_HINT = "cut to fit the model's context; the call ran with the whole value, so read it back before reusing it"


def clip_text(text: str, cap: int, hint: str = BASH_HINT) -> str:
    """Head+tail clip with an omission marker saying how to see the rest —
    command output puts errors at the end, so the tail must survive the clip."""
    if len(text) <= cap:
        return text
    head = int(cap * 0.7)
    tail = cap - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n... <{omitted} chars omitted: {hint}> ...\n{text[-tail:]}"


def _clip_strings(value: Any, cap: int, hint: str) -> Any:
    """``value`` with each string longer than ``cap`` clipped, where clipping shortens it; keys untouched."""
    if isinstance(value, str):
        clipped = clip_text(value, cap, hint)
        return clipped if len(clipped) < len(value) else value
    if isinstance(value, list):
        return [_clip_strings(item, cap, hint) for item in value]
    if isinstance(value, dict):
        return {key: _clip_strings(item, cap, hint) for key, item in value.items()}
    return value


def clip_arguments(arguments: str, cap: int, hint: str = ARGUMENTS_HINT) -> str:
    """A tool call's JSON arguments in about ``cap`` characters, still the call's JSON: every key and short value as
    it was, each long string its head and tail around a marker, all clipped to the longest length that fits (to
    ``ARGUMENT_STRING_FLOOR`` when even that passes ``cap``). Arguments that aren't JSON clip as text."""
    if len(arguments) <= cap:
        return arguments
    try:
        value = json.loads(arguments)
    except ValueError:
        return clip_text(arguments, cap, hint)

    def dump(limit: int) -> str:
        return json.dumps(_clip_strings(value, limit, hint), ensure_ascii=False, separators=(",", ":"))

    low, high = ARGUMENT_STRING_FLOOR, len(arguments)
    while low < high:
        mid = (low + high + 1) // 2
        if len(dump(mid)) <= cap:
            low = mid
        else:
            high = mid - 1
    return dump(low)


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

"""Bounds on tool output (execute_bash's and every SDK tool's) + replayed history tool outputs.

Pins the 2026-08-24 poisoned-conversation fix: an uncapped `cat` of a PDF put
millions of tokens into the model request AND sdk_history, after which every
turn of that conversation failed on the provider context limit. Two layers:
clip_bash_result / tool_output (write-time, at the tool) and clip_history_item
(load-time, in PostgresSession.get_items — heals pre-fix rows)."""

import json

from coder.openai_agent.output_limits import (
    BASH_STDERR_CAP,
    BASH_STDOUT_CAP,
    HISTORY_TOOL_OUTPUT_CAP,
    TOOL_HINT,
    TOOL_OUTPUT_CAP,
    clip_bash_result,
    clip_history_item,
    clip_text,
    tool_output,
)


def test_clip_text_passthrough_under_cap():
    assert clip_text("small", 100) == "small"


def test_clip_text_keeps_head_and_tail():
    text = "H" * 900 + "MIDDLE" + "T" * 900
    clipped = clip_text(text, 100)
    assert len(clipped) < len(text)
    assert clipped.startswith("H" * 70)
    assert clipped.endswith("T" * 30)
    assert "chars omitted" in clipped


def test_clip_bash_result_bounds_both_streams_and_keeps_exit_code():
    result = {
        "stdout": "x" * (BASH_STDOUT_CAP * 3),
        "stderr": "e" * (BASH_STDERR_CAP * 3),
        "exit_code": 0,
    }
    clipped = clip_bash_result(result)
    # Clipped size = cap + marker text, never multiples of the cap.
    assert len(clipped["stdout"]) < BASH_STDOUT_CAP + 200
    assert len(clipped["stderr"]) < BASH_STDERR_CAP + 200
    assert clipped["exit_code"] == 0
    # Original untouched (callers may hold a reference).
    assert len(result["stdout"]) == BASH_STDOUT_CAP * 3


def test_clip_bash_result_passthrough_small_and_non_string():
    result = {"stdout": "ok", "stderr": None, "exit_code": 1}
    assert clip_bash_result(result) == result
    assert clip_bash_result({"error": "boom"}) == {"error": "boom"}


def test_clip_history_item_bounds_only_tool_outputs():
    giant = "P" * (HISTORY_TOOL_OUTPUT_CAP * 4)  # the cat'ed-PDF shape
    tool_item = {"type": "function_call_output", "call_id": "c1", "output": giant}
    clipped = clip_history_item(tool_item)
    assert len(clipped["output"]) < HISTORY_TOOL_OUTPUT_CAP + 200
    assert clipped["call_id"] == "c1"
    # User/assistant content replays verbatim, whatever its size.
    msg = {"role": "user", "content": giant}
    assert clip_history_item(msg) is msg
    # Small tool outputs replay verbatim (same object, no copy).
    small = {"type": "function_call_output", "call_id": "c2", "output": "ok"}
    assert clip_history_item(small) is small
    # Non-dict items pass through.
    assert clip_history_item("raw") == "raw"


def test_tool_output_bounds_any_tools_result_and_says_how_to_see_the_rest():
    """Every SDK tool's result passes here on its way to the model (a web search with page text
    returned hundreds of thousands of characters per call)."""
    result = {"results": [{"url": f"https://example.org/{i}", "text": "page " * 20_000} for i in range(10)]}
    text = tool_output(result)
    assert len(text) < TOOL_OUTPUT_CAP + 300 and TOOL_HINT in text
    assert text.startswith('{"results": [{"url": "https://example.org/0"')
    # Under the cap a result reaches the model whole, as JSON.
    small = {"ok": True, "url": "https://example.org"}
    assert tool_output(small) == json.dumps(small)
    # The history backstop never re-clips a result bounded here.
    assert len(text) < HISTORY_TOOL_OUTPUT_CAP


def test_tool_output_shows_characters_as_themselves():
    """A coordinator read a page whose "·" reached it as the escape \\u00b7 and committed the page back with a
    control character in its place: a result's text reaches the model as itself, still JSON."""
    page = {"value": '<div class="eyebrow">Your neighborhood bakery · Austin — “fresh” daily</div>'}
    text = tool_output(page)
    assert page["value"].replace('"', '\\"') in text and "\\u00b7" not in text
    assert json.loads(text) == page
    # A lone surrogate, which UTF-8 can't carry, stays escaped, so the result can still be sent and stored.
    odd = tool_output({"value": "a\ud800b"})
    assert odd.encode("utf-8") and "\\ud800" in odd

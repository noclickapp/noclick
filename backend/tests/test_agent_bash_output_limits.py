"""Bounds on execute_bash output + replayed history tool outputs.

Pins the 2026-08-24 poisoned-conversation fix: an uncapped `cat` of a PDF put
millions of tokens into the model request AND sdk_history, after which every
turn of that conversation failed on the provider context limit. Two layers:
clip_bash_result (write-time, at the tool) and clip_history_item (load-time,
in PostgresSession.get_items — heals pre-fix rows)."""

from coder.openai_agent.output_limits import (
    BASH_STDERR_CAP,
    BASH_STDOUT_CAP,
    HISTORY_TOOL_OUTPUT_CAP,
    clip_bash_result,
    clip_history_item,
    clip_text,
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

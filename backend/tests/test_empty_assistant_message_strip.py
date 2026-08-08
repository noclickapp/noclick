"""Content-free assistant turns must not reach the Chat Completions wire.

Models routinely emit an empty assistant message alongside a tool call. On the
Responses API that is harmless; on Chat Completions it lands BETWEEN the
assistant's tool_calls and the tool messages answering them, and the provider
rejects the request:

    An assistant message with 'tool_calls' must be followed by tool messages
    responding to each 'tool_call_id'

Which our error classifier then reported as "a server-side outage on their end,
retry" — so every agent that called a tool failed, and the message sent people
looking in the wrong place.
"""

from __future__ import annotations

from coder.openai_agent.litellm_model import strip_empty_assistant_messages


def test_the_empty_turn_between_a_tool_call_and_its_result_is_removed():
    """The exact history that broke the sales agent."""
    items = [
        {"role": "user", "content": "A new inbound email just arrived."},
        {
            "type": "function_call",
            "name": "slack__list_channels_in_workspace",
            "call_id": "call_yGQ",
            "arguments": "{}",
        },
        {
            "role": "assistant",
            "type": "message",
            "status": "completed",
            "content": [{"text": "", "type": "output_text"}],
        },
        {"type": "function_call_output", "call_id": "call_yGQ", "output": "{}"},
    ]
    out = strip_empty_assistant_messages(items)
    assert len(out) == 3
    # The call is now immediately followed by its output, which is the whole
    # requirement the provider enforces.
    assert out[1]["type"] == "function_call"
    assert out[2]["type"] == "function_call_output"


def test_an_assistant_turn_with_words_survives():
    items = [{"role": "assistant", "content": "Here is the briefing."}]
    assert strip_empty_assistant_messages(items) == items


def test_an_assistant_turn_carrying_tool_calls_survives():
    """This is the message the tool outputs answer — dropping it breaks the pair."""
    items = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
    ]
    assert strip_empty_assistant_messages(items) == items


def test_whitespace_only_counts_as_empty():
    items = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "   "}]
    assert strip_empty_assistant_messages(items) == [{"role": "user", "content": "hi"}]


def test_other_roles_are_never_touched():
    """An empty USER or TOOL message is not ours to judge."""
    items = [
        {"role": "user", "content": ""},
        {"role": "tool", "tool_call_id": "c1", "content": ""},
        {"role": "system", "content": ""},
    ]
    assert strip_empty_assistant_messages(items) == items


def test_unexpected_shapes_pass_through_untouched():
    """This runs on every request; it must never be able to eat real content."""
    assert strip_empty_assistant_messages("not a list") == "not a list"
    assert strip_empty_assistant_messages(None) is None
    weird = [{"no_role": True}, 42, None]
    assert strip_empty_assistant_messages(weird) == weird


def test_the_list_is_returned_unchanged_when_nothing_is_dropped():
    """Identity when clean, so the common path allocates nothing new."""
    items = [{"role": "user", "content": "hi"}]
    assert strip_empty_assistant_messages(items) is items

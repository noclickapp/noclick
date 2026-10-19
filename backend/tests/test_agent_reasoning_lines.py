"""A model's reasoning reaches whoever watches the turn as short lines (``coder.openai_agent.reasoning``): each
section's bold title the moment it closes, else a section's first sentence, from the deltas the SDK wrapper
streams; a run's text or tool call starts the next segment."""

from unittest.mock import MagicMock, patch

import pytest
from agents.stream_events import RawResponsesStreamEvent

from coder.openai_agent.reasoning import MAX_CHARS, ReasoningLines
from tests.test_agent_llm_retry import MESSAGE, FakeResult, _make_agent, _text_delta_event
from wss.sender import ChatMessageEvent


def _feed(lines: ReasoningLines, *deltas: str):
    out = []
    for delta in deltas:
        out += lines.feed(delta)
    return out


def test_a_title_is_a_line_the_moment_it_closes():
    lines = ReasoningLines()
    assert _feed(lines, "**Diagnos", "ing workflow") == []
    assert _feed(lines, " issues**\n\nI found that the list excludes the coordinator.") == ["Diagnosing workflow issues"]
    # The section's body says nothing more; the next section's title does.
    assert _feed(lines, " That could mean...\n\n**Checking the run**\n\n") == ["Checking the run"]


def test_reasoning_with_no_title_gives_its_first_sentence_once():
    lines = ReasoningLines()
    assert _feed(lines, "I need to look at the run") == []
    assert _feed(lines, " that failed. Then the workflow.") == ["I need to look at the run that failed."]
    assert _feed(lines, " Then more. And more.") == []


def test_a_long_line_is_cut_and_a_new_segment_starts_fresh():
    lines = ReasoningLines()
    [line] = _feed(lines, "**" + "word " * 60 + "**")
    assert len(line) == MAX_CHARS and line.endswith("…")
    lines.reset()
    assert _feed(lines, "**Planning app deployment**") == ["Planning app deployment"]


def _reasoning_delta(text):
    ev = MagicMock(spec=RawResponsesStreamEvent)
    ev.data = MagicMock()
    ev.data.type = "response.reasoning_summary_text.delta"
    ev.data.delta = text
    return ev


@pytest.mark.asyncio
async def test_the_wrapper_sends_each_reasoning_line_as_a_thought():
    events = []
    agent = _make_agent(events)
    stream = [_reasoning_delta("**Reading the "), _reasoning_delta("failed run**\n\nIt says"),
              _text_delta_event("It failed on Gmail."), _reasoning_delta("**Planning a fix**")]
    with patch("coder.openai_agent.agent.Runner.run_streamed", return_value=FakeResult(stream, final_output="ok")):
        await agent(MESSAGE)
    thoughts = [e.thought for e in events if isinstance(e, ChatMessageEvent) and e.thought]
    assert thoughts == ["Reading the failed run", "Planning a fix"]
    # The thinking pulse still runs on every delta; a thought never carries reply text.
    assert all(e.message is None for e in events if isinstance(e, ChatMessageEvent) and e.thought)

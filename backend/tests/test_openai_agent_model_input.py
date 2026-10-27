"""A tool sees the input the model's latest call saw (``CURRENT_MODEL_INPUT``), through the real streamed SDK and
PostgreSQL: the person's message, the calls before it and what they returned. ``render`` holds a picture's figures to
it, so it must be the turn as the model had it when it called the tool, and nothing once the run is over."""

import pytest

from tests.test_builder_requests import builder_request_db  # noqa: F401
from tests.test_openai_agent_handed_on import _run

pytestmark = pytest.mark.asyncio


class _Reading(dict):
    """Tool results, and what the model's input was when each tool ran."""

    def __init__(self, results):
        super().__init__(results)
        self.seen = {}

    def __getitem__(self, name):
        from coder.openai_agent.agent import CURRENT_MODEL_INPUT

        self.seen[name] = CURRENT_MODEL_INPUT.get()
        return super().__getitem__(name)


async def test_a_tool_sees_the_turn_the_model_had_when_it_called_it(builder_request_db, monkeypatch):
    from coder.openai_agent.agent import CURRENT_MODEL_INPUT

    results = _Reading({"quote": {"symbol": "SPX", "close": "7,676.77"}, "render": {"success": True}})
    calls, ran, _, _, _ = await _run(builder_request_db[0], monkeypatch,
                                     [("Looking it up.", "quote"), ("Drawing it.", "render"), ("Here it is.", None)],
                                     results)

    assert ran == ["quote", "render"]
    # Each tool saw the input of the call that asked for it: the quote's call had the message alone, render's the
    # quote's call and its result too.
    assert results.seen["quote"] == calls[0] and results.seen["render"] == calls[1]
    held = str(results.seen["render"])
    assert "Make me a bakery site." in held and "7,676.77" in held
    assert "7,676.77" not in str(results.seen["quote"])
    # Nothing leaks past the run into whatever runs next in this task.
    assert CURRENT_MODEL_INPUT.get() is None

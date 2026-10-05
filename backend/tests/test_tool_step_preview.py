"""A consumer that draws its chat from tool steps (the coordinator's inline
cards) shapes each call's arguments and result into a whole, bounded preview;
everyone else keeps the plain clipped text."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from coder.coordinator.tools import STEP_PREVIEW_CHARS, CoordinatorTools, step_preview
from coder.openai_agent.agent import Agent
from wss.sender.events import TOOL_STEP_TEXT_CHARS

pytestmark = pytest.mark.asyncio

LINKS = [{"job_id": f"j{i}", "url": f"https://noclick.com/pay/{i}", "label": f"the plan {i}, billed monthly",
          "price_usd": 20 * i, "billing_period": "monthly", "expires_at": "2026-10-07T00:00:00+00:00"} for i in range(1, 4)]
REFUSAL = {"success": False, "error": "Video generation needs the Plus or Pro plan. " * 4, "kind": "plan",
           "purchase_links": LINKS, "next": "Send these links, one per line with its price. " * 4}


def agent_with(preview):
    agent = Agent.__new__(Agent)
    agent._tool_step_preview = preview
    agent._emit_message = AsyncMock()
    return agent


def run_item(name, **item):
    return SimpleNamespace(name=name, item=SimpleNamespace(**item))


def step_texts(agent):
    return [c.args[0].agentic_steps[0].text for c in agent._emit_message.await_args_list]


async def test_a_previewing_consumer_gets_whole_json_in_both_frames():
    agent = agent_with(step_preview)
    args = {"prompt": "a teaser " * 300, "seconds": 8}
    await agent._emit_run_item_event(run_item(
        "tool_called", tool_name="generate_video", call_id="c1",
        to_input_item=lambda: {"arguments": json.dumps(args)}))
    await agent._emit_run_item_event(run_item("tool_output", call_id="c1", output=json.dumps(REFUSAL)))
    called, answered = step_texts(agent)
    assert called.startswith("Calling generate_video(") and called.endswith(")")
    assert json.loads(called[len("Calling generate_video("):-1])["seconds"] == 8
    shown = json.loads(answered)
    # Every link the refusal minted survives, though the whole result is far past a plain step's length.
    assert len(json.dumps(REFUSAL)) > TOOL_STEP_TEXT_CHARS
    assert [link["url"] for link in shown["purchase_links"]] == [link["url"] for link in LINKS]


async def test_everyone_else_keeps_the_plain_clipped_step():
    agent = agent_with(None)
    await agent._emit_run_item_event(run_item("tool_output", call_id="c1", output=json.dumps(REFUSAL)))
    [answered] = step_texts(agent)
    assert answered == json.dumps(REFUSAL)[:TOOL_STEP_TEXT_CHARS]


async def test_the_preview_stays_bounded_however_big_the_value():
    # Past even the tight bound it is a prefix of JSON, which the chat reads as far as it is whole.
    huge = {"nodes": [{"id": str(i), "config": {f"k{j}": "v" * 500 for j in range(40)}} for i in range(30)]}
    text = step_preview(huge)
    assert len(text) <= STEP_PREVIEW_CHARS
    assert step_preview({"url": "https://noclick.com/pay/1", "ok": True}) == '{"url": "https://noclick.com/pay/1", "ok": true}'


async def test_the_coordinator_records_the_same_preview_for_its_transcript():
    t = CoordinatorTools(pool=None, sio=None, user_id="11111111-1111-1111-1111-111111111111", organization_id=None,
                         conversation_id="coordinator:11111111-1111-1111-1111-111111111111")
    t._tools["generate_video"] = AsyncMock(return_value=REFUSAL)
    with patch("coder.coordinator.tools.record_tool_call") as audit:
        await t.execute("generate_video", {"prompt": "a teaser"})
    recorded = json.loads(audit.call_args.kwargs["result_preview"])
    assert [link["job_id"] for link in recorded["purchase_links"]] == ["j1", "j2", "j3"]

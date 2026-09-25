"""Delivery choices cannot turn a late recording into a second call recap."""
import pytest

from coder.coordinator.followup import FollowupDelivery
from coder.coordinator.tools import CoordinatorTools
from tests.mocks.mock_asyncpg import MockNativePool

URL = "https://assets.example/call.mp3"
AUDIO = {"operation": "call_recording", "status": "available", "recording": {"download_url": URL}}


def event(*, late=False, background=False):
    return {"source": "operation", "context": {"origin": "background" if background else "user"},
            "payload": AUDIO if late else {"operation": "place_call", "artifacts": {"recording": AUDIO}}}


def test_direct_call_attaches_audio_once_and_late_audio_never_repeats_summary():
    assert FollowupDelivery(event()).reply("They confirmed.\n![Recording](" + URL + ")").text == (
        "They confirmed.\n\n![Call recording](" + URL + ")")
    assert FollowupDelivery(event(late=True)).reply("I already shared the outcome.").text == f"![Call recording]({URL})"


@pytest.mark.asyncio
async def test_background_can_omit_summary_audio_or_both_with_audited_tool():
    choice = FollowupDelivery(event(background=True))
    tools = CoordinatorTools(pool=MockNativePool(), sio=object(), user_id="owner", organization_id=None,
                             conversation_id="coordinator:owner", followup=choice)
    assert choice.reply("An exception needs attention.").text == "An exception needs attention."
    assert "set_followup_delivery" in {tool["function"]["name"] for tool in tools.tool_params()}
    result = await tools.execute("set_followup_delivery", {
        "notify": False, "include_recordings": False, "reason": "Routine scheduled success."})
    assert result["success"]
    reply = choice.reply("The call succeeded.")
    assert not reply.text and not reply.delivery["notify"]
    await choice.choose(True, True, "The owner should hear the issue.")
    assert URL in choice.reply("An issue occurred.").text


@pytest.mark.asyncio
async def test_bulk_direct_call_can_override_default_and_late_artifact_inherits_choice():
    first = FollowupDelivery(event())
    await first.choose(True, False, "Owner asked for aggregate results only.")
    assert URL not in first.reply("One call finished. " + URL).text
    parent = {"payload": {"delivery": first.decision()}}
    late = FollowupDelivery(event(late=True), parent=parent)
    assert not late.reply("Already done.").text
    await first.choose(False, True, "Owner asked for silence.")
    late = FollowupDelivery(event(late=True), parent={"payload": {"delivery": first.decision()}})
    assert not late.reply("Here is the recording.").text


def test_background_artifact_is_silent_by_default_and_missing_audio_does_not_repeat_outcome():
    assert not FollowupDelivery(event(late=True, background=True)).reply("Already done.").text
    missing = event(late=True)
    missing["payload"] = {"operation": "call_recording", "status": "unavailable"}
    assert FollowupDelivery(missing).reply("Already done.").text == "The call recording couldn't be retrieved."


def test_interactive_turn_has_no_suppression_tool():
    tools = CoordinatorTools(pool=MockNativePool(), sio=object(), user_id="owner", organization_id=None,
                             conversation_id="coordinator:owner")
    assert "set_followup_delivery" not in tools._tools
    assert "set_followup_delivery" not in {tool["function"]["name"] for tool in tools.tool_params()}

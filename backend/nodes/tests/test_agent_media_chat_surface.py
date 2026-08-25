"""Regression tests for media fast-path handlers (image / kling) surfacing
their generated images in the agent node's chat interface.

These handlers return their output directly and bypass the LLM path's
emit_callback, so AgentNode._emit_media_chat_result is what bridges their
result onto the chat:message channel (live display) + conversations.events
(reload restore). Before this, image generation produced no chat output at
all — the AgentChatBlock transcript hung on the streaming dot.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.agent_node import AgentNode
from wss.sender import ChatMessageEvent


def _make_node():
    """Minimal stand-in carrying just what _emit_media_chat_result reads.
    _media_urls_from_output is a staticmethod, so the stub borrows the real
    one rather than reimplementing extraction."""
    return SimpleNamespace(
        sio=MagicMock(),
        sid="sid-1",
        node_id="n1",
        _persist_interface_chat_event=AsyncMock(),
        _media_urls_from_output=AgentNode._media_urls_from_output,
    )


@pytest.mark.asyncio
async def test_image_output_emits_finished_chat_message_with_image_content():
    node = _make_node()
    output = {
        "type": "agent",
        "status": "completed",
        "response": "Here is your image.",
        "images": [{"url": "https://r2/a.png"}],
        "image_url": "https://r2/a.png",
    }

    with patch("nodes.agent_node.send_event", new=AsyncMock()) as mock_send:
        await AgentNode._emit_media_chat_result(
            node, output, conversation_id="ck:wf:n1:k", model="gpt-image-1"
        )

    assert mock_send.call_count == 1
    event = mock_send.call_args.args[2]
    assert isinstance(event, ChatMessageEvent)
    assert event.finished is True
    assert event.conversation_id == "ck:wf:n1:k"
    assert event.message == "Here is your image."
    assert event.content is not None and len(event.content) == 1
    assert event.content[0].type == "image_url"
    assert event.content[0].get_image_url() == "https://r2/a.png"

    node._persist_interface_chat_event.assert_awaited_once()
    kwargs = node._persist_interface_chat_event.await_args.kwargs
    assert kwargs["role"] == "assistant"
    assert kwargs["message"] == "Here is your image."
    assert kwargs["image_urls"] == ["https://r2/a.png"]


@pytest.mark.asyncio
async def test_image_only_output_has_no_text_message_but_still_persists():
    """DALL-E returns no text — the chat message carries images with a None
    text body, and the turn is still persisted with its image URLs."""
    node = _make_node()
    output = {
        "status": "completed",
        "response": "",
        "images": [{"url": "https://r2/x.png"}, {"url": "https://r2/y.png"}],
    }

    with patch("nodes.agent_node.send_event", new=AsyncMock()) as mock_send:
        await AgentNode._emit_media_chat_result(
            node, output, conversation_id="ck:wf:n1:k", model="dall-e-3"
        )

    event = mock_send.call_args.args[2]
    assert event.message is None
    assert [c.get_image_url() for c in event.content] == [
        "https://r2/x.png",
        "https://r2/y.png",
    ]
    kwargs = node._persist_interface_chat_event.await_args.kwargs
    assert kwargs["message"] == ""
    assert kwargs["image_urls"] == ["https://r2/x.png", "https://r2/y.png"]


@pytest.mark.asyncio
async def test_video_output_emits_video_url_content_and_persists():
    """Video handlers return `videos` (not `images`) — these surface as
    video_url content items + persist with video_urls."""
    node = _make_node()
    output = {
        "status": "completed",
        "response": "Generated 1 video(s)",
        "videos": [{"url": "https://r2/v.mp4", "mime_type": "video/mp4"}],
        "video_url": "https://r2/v.mp4",
    }

    with patch("nodes.agent_node.send_event", new=AsyncMock()) as mock_send:
        await AgentNode._emit_media_chat_result(
            node, output, conversation_id="ck:wf:n1:k", model="veo-3"
        )

    event = mock_send.call_args.args[2]
    assert event.finished is True
    assert len(event.content) == 1
    assert event.content[0].type == "video_url"
    assert event.content[0].video_url == "https://r2/v.mp4"
    kwargs = node._persist_interface_chat_event.await_args.kwargs
    assert kwargs["video_urls"] == ["https://r2/v.mp4"]
    assert kwargs["image_urls"] is None


@pytest.mark.asyncio
async def test_output_with_no_media_is_a_noop():
    """A plain text output (no images/videos) emits nothing — the LLM/CLI
    paths own their own chat:message stream."""
    node = _make_node()
    output = {"status": "completed", "response": "just text"}

    with patch("nodes.agent_node.send_event", new=AsyncMock()) as mock_send:
        await AgentNode._emit_media_chat_result(
            node, output, conversation_id="ck:wf:n1:k", model="gpt-4o"
        )

    mock_send.assert_not_called()
    node._persist_interface_chat_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_event_carries_media_urls_and_skips_empty():
    """_persist_interface_chat_event stores image_urls/video_urls on the
    event row, and the relaxed guard admits an image-only turn (empty
    message) while still skipping a truly empty turn."""
    persist_node = SimpleNamespace(
        user_id="u1", workflow_id="wf1", node_id="n1",
        _UPSERT_INTERFACE_EVENT_SQL=AgentNode._UPSERT_INTERFACE_EVENT_SQL,
    )
    pool = MagicMock()
    pool.execute = AsyncMock()

    with patch("utils.database_pool.get_native_pool", return_value=pool):
        # image-only turn (empty message) — must persist
        await AgentNode._persist_interface_chat_event(
            persist_node, conversation_id="c", role="assistant", message="",
            model="m", image_urls=["https://r2/a.png"], video_urls=["https://r2/v.mp4"],
        )
        event = pool.execute.await_args.args[5][0]
        assert event["role"] == "assistant"
        assert event["image_urls"] == ["https://r2/a.png"]
        assert event["video_urls"] == ["https://r2/v.mp4"]

        # truly empty turn (no message, no media) — must skip the DB write
        pool.execute.reset_mock()
        await AgentNode._persist_interface_chat_event(
            persist_node, conversation_id="c", role="assistant", message="", model="m",
        )
        pool.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_assistant_turn_persists_completed_with_images():
    node = SimpleNamespace(
        _media_urls_from_output=AgentNode._media_urls_from_output,
        _persist_interface_chat_event=AsyncMock(),
    )
    output = {"status": "completed", "response": "done", "images": [{"url": "https://r2/a.png"}]}
    await AgentNode._persist_llm_assistant_turn(
        node, output, conversation_id="c", model="gpt-4o",
        raw_text="raw streamed text", agent_errored=False,
    )
    kwargs = node._persist_interface_chat_event.await_args.kwargs
    assert kwargs["message"] == "raw streamed text"  # raw, not output['response']
    assert kwargs["image_urls"] == ["https://r2/a.png"]


@pytest.mark.asyncio
async def test_llm_assistant_turn_skipped_when_agent_errored():
    """A real agent error already persisted a cancelled bubble via the
    AgentStateEvent branch — don't double-persist a normal turn."""
    node = SimpleNamespace(
        _media_urls_from_output=AgentNode._media_urls_from_output,
        _persist_interface_chat_event=AsyncMock(),
    )
    output = {"status": "failed", "response": "Error: rate limited", "error": "rate limited"}
    await AgentNode._persist_llm_assistant_turn(
        node, output, conversation_id="c", model="gpt-4o",
        raw_text="Error: rate limited", agent_errored=True,
    )
    node._persist_interface_chat_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_assistant_turn_persists_error_prose_when_not_errored():
    """Regression guard: a model that legitimately opens its reply with
    "Error:" (no real agent error) flips output['status'] to 'failed' via a
    legacy heuristic — but the turn must still be saved to history. The gate
    is the authoritative agent_errored flag, not output['status']."""
    node = SimpleNamespace(
        _media_urls_from_output=AgentNode._media_urls_from_output,
        _persist_interface_chat_event=AsyncMock(),
    )
    output = {"status": "failed", "response": "Error: budgets are tricky. Here's why..."}
    await AgentNode._persist_llm_assistant_turn(
        node, output, conversation_id="c", model="gpt-4o",
        raw_text="Error: budgets are tricky. Here's why...", agent_errored=False,
    )
    node._persist_interface_chat_event.assert_awaited_once()
    assert node._persist_interface_chat_event.await_args.kwargs["message"] == (
        "Error: budgets are tricky. Here's why..."
    )


@pytest.mark.asyncio
async def test_llm_assistant_turn_skipped_without_conversation():
    node = SimpleNamespace(
        _media_urls_from_output=AgentNode._media_urls_from_output,
        _persist_interface_chat_event=AsyncMock(),
    )
    await AgentNode._persist_llm_assistant_turn(
        node, {"status": "completed", "response": "hi"}, conversation_id=None,
        model="gpt-4o", raw_text="hi", agent_errored=False,
    )
    node._persist_interface_chat_event.assert_not_awaited()


def test_media_urls_from_output_extracts_both_lists():
    img, vid = AgentNode._media_urls_from_output(
        {
            "images": [{"url": "https://r2/a.png"}, {"no_url": 1}, "bad"],
            "videos": [{"url": "https://r2/v.mp4"}],
        }
    )
    assert img == ["https://r2/a.png"]
    assert vid == ["https://r2/v.mp4"]
    assert AgentNode._media_urls_from_output(None) == ([], [])
    assert AgentNode._media_urls_from_output({}) == ([], [])


@pytest.mark.asyncio
async def test_no_chat_emit_without_socket():
    """A canvas/headless run (no sio/sid) still persists the turn but emits no
    chat:message (no subscriber)."""
    node = _make_node()
    node.sio = None
    node.sid = None
    output = {"response": "img", "images": [{"url": "https://r2/a.png"}]}

    with patch("nodes.agent_node.send_event", new=AsyncMock()) as mock_send:
        await AgentNode._emit_media_chat_result(
            node, output, conversation_id="ck:wf:n1:k", model="gpt-image-1"
        )

    mock_send.assert_not_called()
    node._persist_interface_chat_event.assert_awaited_once()

"""``read_recent_messages``: every chat active in a window, read in one call and returned one line per message.

A daily digest of an account's group chats read each chat's raw page (ids, media blobs, nulls: ~90% of the JSON)
one tool call at a time, which outran a small daily budget; this read lists the active chats once, reads them a few
at a time off the event loop, and keeps only who said what, when.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppQRCredential,
    WhatsAppReadRecentMessagesConfig,
)

NOW = time.time()
HOUR = 3600


def _at(hours_ago: float) -> int:
    return int(NOW - hours_ago * HOUR)


def _clock(ts: int, fmt: str = "%H:%M") -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt)


def _message(chat_id, ts, text, *, sender="Maria", sender_jid="12025550100@s.whatsapp.net", from_me=False,
             kind="text", media=None):
    """A message as WAHooks pages it (newest first), every field a real page carries."""
    return {
        "id": f"{'true' if from_me else 'false'}_{chat_id}_3EB0{ts:X}C1A2B3D4E5F6",
        "chatId": chat_id,
        "timestamp": ts,
        "fromMe": from_me,
        "senderJid": None if from_me else sender_jid,
        "senderPushName": None if from_me else sender,
        "type": kind,
        "text": text,
        "quotedMessageId": None,
        "media": media,
    }


def _chat(chat_id, name, last_ts, *, group):
    return {"id": chat_id, "name": name, "isGroup": group,
            "lastMessage": {"body": "…", "timestamp": last_ts, "fromMe": False}, "unread": False}


class _FakeWAHooks:
    """wahooks' sync client over an in-memory account: chats most recently active first, each chat's messages
    paged newest first with ``nextBefore`` cursors, every call recorded with the thread it ran on."""

    def __init__(self, chats, messages, calls):
        self._chats, self._messages, self._calls = chats, messages, calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_chats(self, conn_id, *, limit=None, offset=None, unread_only=False):
        self._calls.append(("get_chats", offset, threading.current_thread()))
        return self._chats[offset or 0:(offset or 0) + limit]

    def get_messages(self, conn_id, chat_id, *, limit=50, before=None):
        self._calls.append(("get_messages", chat_id, threading.current_thread()))
        newest_first = sorted(self._messages.get(chat_id, []), key=lambda m: -m["timestamp"])
        start = int(before) if before else 0
        page = newest_first[start:start + limit]
        more = start + limit < len(newest_first)
        return {"messages": page, "nextBefore": str(start + limit) if more else None,
                "historyStartsAt": None if more else (page[-1]["timestamp"] if page else None)}


async def _read(config, chats, messages, calls=None):
    calls = [] if calls is None else calls
    node = WhatsAppNode(
        node_id="wa", node_type="automation-whatsapp", node_data={}, sio=None, sid=None, workflow_id="wf",
        config=WhatsAppNodeConfig(config=config, credentials=WhatsAppQRCredential(connection_id="conn-1")),
    )
    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), \
            patch("wahooks.WAHooks", lambda api_key: _FakeWAHooks(chats, messages, calls)):
        result = await node.execute({})
    assert result["status"] == "success", result
    assert result["action"] == "read_recent_messages"
    return result["data"]


GROUP, OLD_GROUP, DIRECT = "120000000000000001@g.us", "222@g.us", "12025550101@c.us"
ACCOUNT = [
    _chat(GROUP, "Book club", _at(1), group=True),
    _chat("status@broadcast", "Status", _at(1.5), group=False),
    _chat(DIRECT, "Ana", _at(2), group=False),
    _chat("120000000000000002@newsletter", "News", _at(3), group=False),
    _chat(OLD_GROUP, "Old group", _at(30), group=True),
    _chat("12025550107@c.us", "Ben", _at(40), group=False),
]
MESSAGES = {
    GROUP: [_message(GROUP, _at(26), "yesterday's news"),
            _message(GROUP, _at(3), "Chapter  five\nby Friday?", sender="Maria"),
            _message(GROUP, _at(2), "Yes", from_me=True),
            _message(GROUP, _at(1), "", sender=None, sender_jid="12025550104@s.whatsapp.net", kind="audio",
                     media={"url": "https://media.example/a.ogg", "mimetype": "audio/ogg", "filename": None})],
    DIRECT: [_message(DIRECT, _at(2), "Lunch?", sender="Ana", sender_jid=None),
             _message(DIRECT, _at(1.9), "the menu", sender="Ana", kind="image",
                      media={"url": "https://media.example/i.jpg", "mimetype": "image/jpeg", "filename": None})],
    OLD_GROUP: [_message(OLD_GROUP, _at(30), "old")],
    "12025550107@c.us": [_message("12025550107@c.us", _at(40), "older", sender="Ben")],
}


@pytest.mark.asyncio
async def test_it_reads_only_the_chats_active_in_the_window_of_the_kind_asked():
    calls = []
    data = await _read(WhatsAppReadRecentMessagesConfig(chats="groups"), ACCOUNT, MESSAGES, calls)
    assert [c["chat_id"] for c in data["chats"]] == [GROUP]
    assert data["chats"][0]["group"] is True and data["chats"][0]["name"] == "Book club"
    # The first chat last active before the window ends the scan: nothing older is read.
    assert [c[1] for c in calls if c[0] == "get_messages"] == [GROUP]

    direct = await _read(WhatsAppReadRecentMessagesConfig(chats="direct"), ACCOUNT, MESSAGES)
    assert [c["chat_id"] for c in direct["chats"]] == [DIRECT]  # never status updates or channels
    asked_at = time.time()  # NOW is the module's import time: a long suite runs this test much later
    everything = await _read(WhatsAppReadRecentMessagesConfig(), ACCOUNT, MESSAGES)
    assert [c["chat_id"] for c in everything["chats"]] == [GROUP, DIRECT]  # most recently active first
    assert everything["chat_count"] == 2 and everything["message_count"] == 5
    assert everything["truncated"] is False
    since = datetime.strptime(everything["since"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).timestamp()
    assert abs(since - (asked_at - 24 * HOUR)) < 120

    wider = await _read(WhatsAppReadRecentMessagesConfig(hours=48), ACCOUNT, MESSAGES)
    assert [c["chat_id"] for c in wider["chats"]] == [GROUP, DIRECT, OLD_GROUP, "12025550107@c.us"]


@pytest.mark.asyncio
async def test_each_chat_reads_oldest_first_one_line_per_message_with_media_as_a_placeholder():
    data = await _read(WhatsAppReadRecentMessagesConfig(), ACCOUNT, MESSAGES)
    group, direct = data["chats"]
    assert group["messages"] == [
        f"{_clock(_at(3))} Maria: Chapter five by Friday?",  # whitespace folded; yesterday's message left out
        f"{_clock(_at(2))} You: Yes",
        f"{_clock(_at(1))} 12025550104: [voice note]",  # no push name: the sender's number
    ]
    assert direct["messages"] == [f"{_clock(_at(2))} Ana: Lunch?", f"{_clock(_at(1.9))} Ana: [image] the menu"]
    assert "more" not in group
    # A window longer than a day dates each line.
    week = await _read(WhatsAppReadRecentMessagesConfig(hours=48, chats="groups"), ACCOUNT, MESSAGES)
    assert week["chats"][0]["messages"][0] == f"{_clock(_at(26), '%m-%d %H:%M')} Maria: yesterday's news"


@pytest.mark.asyncio
async def test_a_busy_chat_pages_back_through_the_window_and_keeps_its_newest_when_capped():
    busy = {GROUP: [_message(GROUP, _at(20) + i * 60, f"message {i}") for i in range(250)]
            + [_message(GROUP, _at(25), "before the window")]}
    chats = [_chat(GROUP, "Book club", _at(1), group=True)]
    calls = []
    data = await _read(WhatsAppReadRecentMessagesConfig(per_chat_limit=500), chats, busy, calls)
    lines = data["chats"][0]["messages"]
    assert len(lines) == 250 and lines[0].endswith("Maria: message 0") and lines[-1].endswith("message 249")
    assert len([c for c in calls if c[0] == "get_messages"]) == 3  # 100 + 100 + the page reaching the window
    assert "more" not in data["chats"][0]

    capped = await _read(WhatsAppReadRecentMessagesConfig(per_chat_limit=120), chats, busy)
    chat = capped["chats"][0]
    assert len(chat["messages"]) == 120 and chat["more"] is True
    assert chat["messages"][0].endswith("message 130") and chat["messages"][-1].endswith("message 249")


@pytest.mark.asyncio
async def test_more_active_chats_than_asked_reads_the_most_recent_and_says_so():
    chats = [_chat(f"12036300000000010{i}@g.us", f"Group {i}", _at(1 + i), group=True) for i in range(3)]
    messages = {c["id"]: [_message(c["id"], c["lastMessage"]["timestamp"], "hi")] for c in chats}
    data = await _read(WhatsAppReadRecentMessagesConfig(max_chats=2), chats, messages)
    assert [c["name"] for c in data["chats"]] == ["Group 0", "Group 1"]
    assert data["truncated"] is True


@pytest.mark.asyncio
async def test_chats_are_read_off_the_event_loop():
    calls = []
    await _read(WhatsAppReadRecentMessagesConfig(), ACCOUNT, MESSAGES, calls)
    loop_thread = threading.current_thread()
    assert calls and all(thread is not loop_thread for _, _, thread in calls)


@pytest.mark.asyncio
async def test_a_full_page_reads_in_a_small_fraction_of_its_raw_json():
    """What an agent's context pays: 100 messages as get_chat_messages returns them, and as this read does."""
    from nodes.whatsapp_node import WhatsAppGetChatMessagesConfig

    texts = ["Who's bringing the projector tomorrow?", "I can, after 6", "ok 👍", "Sharing the slides now",
             "Can someone send the address again?", "Running 10 min late, sorry!"]
    page = []
    for i in range(100):
        kind = "image" if i % 10 == 0 else "audio" if i % 15 == 0 else "text"
        media = None if kind == "text" else {
            "url": f"https://api.example.com/api/connections/cb8d8763-455a-41e0-834d-5c3125377ef5/media/3AB15B00{i:04d}"
                   f"4077F2BCC146.{'jpeg' if kind == 'image' else 'ogg'}",
            "mimetype": "image/jpeg" if kind == "image" else "audio/ogg; codecs=opus", "filename": None}
        page.append(_message(GROUP, _at(10) + i * 300, None if kind == "audio" else texts[i % len(texts)],
                             sender=["Maria Santos", "Jun Reyes", "Lia Cruz"][i % 3],
                             sender_jid=f"6391700000{i % 3:02d}@s.whatsapp.net", kind=kind, media=media))
    chats = [_chat(GROUP, "Project team", _at(1), group=True)]

    node = WhatsAppNode(
        node_id="wa", node_type="automation-whatsapp", node_data={}, sio=None, sid=None, workflow_id="wf",
        config=WhatsAppNodeConfig(config=WhatsAppGetChatMessagesConfig(chat_id=GROUP, limit=100),
                                  credentials=WhatsAppQRCredential(connection_id="conn-1")),
    )
    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), \
            patch("wahooks.WAHooks", lambda api_key: _FakeWAHooks(chats, {GROUP: page}, [])):
        raw = json.dumps((await node.execute({}))["data"])
    compact = json.dumps(await _read(WhatsAppReadRecentMessagesConfig(), chats, {GROUP: page}))

    ratio = len(compact) / len(raw)
    print(f"raw {len(raw)} chars, compact {len(compact)} chars, ratio {ratio:.2f}")
    assert ratio < 0.2


def test_it_is_an_agent_tool():
    from nodes.agent.node_op_tools import build_node_op_tools

    params, tools = build_node_op_tools("automation-whatsapp", ["read_recent_messages"], node_id="wa")
    (tool,) = [p for p in params if p["function"]["name"] == "whatsapp__read_recent_messages"]
    assert set(tool["function"]["parameters"]["properties"]) == {"hours", "chats", "max_chats", "per_chat_limit"}
    assert "digest or summary across chats" in tool["function"]["description"]
    assert tools["whatsapp__read_recent_messages"]["operation"] == "read_recent_messages"

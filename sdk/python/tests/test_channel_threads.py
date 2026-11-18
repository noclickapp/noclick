"""Channels' threads, pins, bookmarks, files and links, and deleting a channel to the trash."""

import pytest

import noclick as nc
from platform_helpers import body, listing

CHANNEL = {"object": "channel", "id": "ch_1", "name": "launch", "topic": "", "mode": "all", "status": "open",
           "user_id": None, "workspace_id": None, "unread_count": 0, "members": []}
OWNER = {"type": "account", "id": None, "name": "owner"}
WRITER = {"type": "agent", "id": "agt_w", "name": "Writer"}


def _message(message_id="m1", **extra):
    return {"object": "channel_message", "id": message_id, "channel_id": "ch_1", "author": OWNER, "text": "hi",
            "mentions": [], "created_at": "2026-11-10T10:00:00Z", "attachments": [], "reactions": [],
            "thread_id": None, "also_in_channel": False, "reply_count": 0, "last_reply_at": None,
            "reply_authors": [], "following": False, "unread_replies": 0, "pinned": None, **extra}


def test_a_reply_goes_in_its_thread_and_the_thread_reads_back(api, client):
    post = api.post("/v1/channels/ch_1/messages").respond(json=_message("r1", thread_id="m1"))
    replies = api.get("/v1/channels/ch_1/messages/m1/replies").respond(json=listing(*[_message("r1", thread_id="m1")]))
    room = nc.Channel.from_id("ch_1")
    reply = room.reply("m1", "Tuesday works.", also_in_channel=True)
    assert body(post.calls.last.request) == {"text": "Tuesday works.", "thread_id": "m1", "also_in_channel": True}
    assert reply.thread_id == "m1"
    room.post("Notes go out Monday.", thread=reply)
    assert body(post.calls.last.request) == {"text": "Notes go out Monday.", "thread_id": "r1"}
    room.post("Top level.")
    assert body(post.calls.last.request) == {"text": "Top level."}

    assert [r.id for r in room.replies("m1", newest=True, limit=10)] == ["r1"]
    assert dict(replies.calls.last.request.url.params) == {"newest": "true", "limit": "10"}
    with pytest.raises(ValueError, match="one of after"):
        room.replies("m1", after="r1", newest=True)


def test_a_message_carries_its_thread_and_pin(api, client):
    api.get("/v1/channels/ch_1/messages/m1").respond(json=_message(
        reply_count=2, last_reply_at="2026-11-10T11:00:00Z", reply_authors=[WRITER, OWNER], following=True,
        unread_replies=1, mentions=["channel"], pinned={"by": WRITER, "at": "2026-11-10T12:00:00Z"}))
    message = nc.Channel.from_id("ch_1").message("m1")
    assert (message.reply_count, message.following, message.unread_replies) == (2, True, 1)
    assert message.mentions == ["channel"]
    assert [a.name for a in message.reply_authors] == ["Writer", "owner"] and message.last_reply_at.hour == 11
    assert message.pinned.by.name == "Writer" and message.pinned.at.hour == 12


def test_read_follow_and_the_threads_you_follow(api, client):
    read = api.post("/v1/channels/ch_1/messages/m1/read").respond(json=_message(following=True))
    follow = api.post("/v1/channels/ch_1/messages/m1/follow").respond(json=_message(following=True))
    unfollow = api.delete("/v1/channels/ch_1/messages/m1/follow").respond(json=_message())
    threads = api.get("/v1/channels/threads").respond(json=listing(*[{
        "object": "channel_thread", "id": "m1", "channel_id": "ch_1", "channel_name": "launch", "workspace_id": None,
        "parent": _message(reply_count=2), "latest_reply": _message("r2", thread_id="m1", author=WRITER),
        "reply_count": 2, "unread_count": 1, "following": True, "last_reply_at": "2026-11-10T11:00:00Z"}]))
    room = nc.Channel.from_id("ch_1")
    room.mark_thread_read("m1", "r1")
    assert body(read.calls.last.request) == {"reply_id": "r1"}
    room.mark_thread_read("m1")
    assert body(read.calls.last.request) == {}
    assert room.follow("m1").following and not room.unfollow("m1").following
    assert follow.called and unfollow.called

    [thread] = nc.Channel.threads(unread=True, workspace="ws_1")
    assert isinstance(thread, nc.ChannelThread)
    assert (thread.channel_name, thread.parent.id, thread.latest_reply.author.name, thread.unread_count) == (
        "launch", "m1", "Writer", 1)
    assert dict(threads.calls.last.request.url.params) == {"unread": "true", "workspace_id": "ws_1"}


def test_pins_and_bookmarks(api, client):
    pin = api.post("/v1/channels/ch_1/messages/m1/pin").respond(json=_message(pinned={"by": OWNER, "at": None}))
    unpin = api.delete("/v1/channels/ch_1/messages/m1/pin").respond(json=_message())
    api.get("/v1/channels/ch_1/pins").respond(json=listing(*[
        {"object": "channel_pin", "message": _message(), "by": OWNER, "at": "2026-11-10T12:00:00Z"}]))
    bookmark = {"object": "channel_bookmark", "id": "bm_1", "channel_id": "ch_1", "title": "Launch plan",
                "url": "https://docs.example.com/plan", "by": OWNER, "created_at": "2026-11-10T12:00:00Z"}
    add = api.post("/v1/channels/ch_1/bookmarks").respond(201, json=bookmark)
    api.get("/v1/channels/ch_1/bookmarks").respond(json=listing(*[bookmark]))
    patch = api.patch("/v1/channels/ch_1/bookmarks/bm_1").respond(json={**bookmark, "title": "Plan"})
    remove = api.delete("/v1/channels/ch_1/bookmarks/bm_1").respond(json={"object": "channel_bookmark",
                                                                           "id": "bm_1", "deleted": True})
    room = nc.Channel.from_id("ch_1")
    assert room.pin("m1").pinned.by.name == "owner" and body(pin.calls.last.request) == {}
    assert room.unpin("m1").pinned is None and unpin.called
    [pinned] = room.pins()
    assert isinstance(pinned, nc.ChannelPin) and pinned.message.id == "m1" and pinned.by.name == "owner"

    saved = room.add_bookmark("https://docs.example.com/plan", title="Launch plan")
    assert body(add.calls.last.request) == {"url": "https://docs.example.com/plan", "title": "Launch plan"}
    assert isinstance(saved, nc.ChannelBookmark) and saved.title == "Launch plan"
    assert [b.url for b in room.bookmarks()] == ["https://docs.example.com/plan"]
    assert room.update_bookmark(saved, title="Plan").title == "Plan"
    assert body(patch.calls.last.request) == {"title": "Plan"}
    room.remove_bookmark("bm_1")
    assert remove.called


def test_files_links_and_delete(api, client):
    attachment = {"object": "channel_attachment", "id": "att_1", "name": "report.pdf", "mime_type": "application/pdf",
                  "size_bytes": 10, "kind": "file", "url": "https://assets.example/report.pdf"}
    files = api.get("/v1/channels/ch_1/files").respond(json={"object": "list", "next_cursor": "m1:1", "data": [
        {"object": "channel_file", "message_id": "m1", "thread_id": None, "author": OWNER,
         "created_at": "2026-11-10T10:00:00Z", "file": attachment}]})
    api.get("/v1/channels/ch_1/links").respond(json=listing(*[
        {"object": "channel_link", "message_id": "m2", "thread_id": "m1", "author": WRITER,
         "created_at": "2026-11-10T10:00:00Z", "url": "https://docs.example.com/plan", "title": "the plan",
         "domain": "docs.example.com"}]))
    api.delete("/v1/channels/ch_1").respond(json={
        "object": "channel", "id": "ch_1", "deleted": True, "restorable_until": "2026-12-10T10:00:00Z",
        "operation_id": "op_1", "trash": {"object": "trash_item", "id": "tr_1", "kind": "channel",
                                          "resource_id": "ch_1", "name": "launch", "user_id": None,
                                          "trashed_at": "2026-11-10T10:00:00Z",
                                          "purge_after": "2026-12-10T10:00:00Z"}})
    room = nc.Channel.from_id("ch_1")
    page = room.files(q="report", limit=1)
    assert dict(files.calls.last.request.url.params) == {"q": "report", "limit": "1"}
    [item] = page.data
    assert isinstance(item, nc.ChannelFile) and item.file.name == "report.pdf" and page.next_cursor == "m1:1"
    [link] = room.links().data
    assert isinstance(link, nc.ChannelLink) and (link.url, link.title, link.domain, link.thread_id) == (
        "https://docs.example.com/plan", "the plan", "docs.example.com", "m1")
    trashed = room.delete()
    assert isinstance(trashed, nc.TrashItem) and trashed.id == "tr_1"


def test_who_joined_or_left_reads_as_the_channels_membership_entry(api, client):
    system = {"type": "system", "id": None, "name": "NoClick"}
    api.get("/v1/channels/ch_1/messages").respond(json=listing(
        _message("j1", author=system, text="owner added Writer.", event={
            "type": "membership", "action": "added", "by": OWNER,
            "members": [{"id": "cm_1", "type": "agent", "name": "Writer", "agent_id": "agt_w", "user_id": None}]}),
        _message("j2", author=system, text="Ana left.", event={
            "type": "membership", "action": "removed", "by": None,
            "members": [{"id": "cm_2", "type": "user", "name": "Ana", "agent_id": None, "user_id": "ana"}]}),
        _message("p1", author=system, text="owner pinned a message.", event={"type": "pinned", "message_id": "m1"}),
        _message("m2"),
    ))
    said = nc.Channel.from_id("ch_1").messages()
    added, left, pinned, plain = (m.membership for m in said)
    assert (added.action, added.by, added.members[0]["agent_id"]) == ("added", nc.ChannelAuthor("account", None, "owner"),
                                                                       "agt_w")
    assert (left.action, left.by, left.members[0]["user_id"]) == ("removed", None, "ana")
    assert pinned is None and plain is None


def test_star_mute_leave_and_reopen_a_channel(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    room = nc.Channel.get("ch_1")
    star = api.post("/v1/channels/ch_1/star").respond(json={**CHANNEL, "starred": True, "muted": False})
    assert room.star().starred is True and star.called
    api.delete("/v1/channels/ch_1/star").respond(json={**CHANNEL, "starred": False, "muted": False})
    assert room.unstar().starred is False
    api.post("/v1/channels/ch_1/mute").respond(json={**CHANNEL, "starred": False, "muted": True, "unread_count": 0})
    assert (room.mute().muted, room.unread_count) == (True, 0)
    api.delete("/v1/channels/ch_1/mute").respond(json={**CHANNEL, "starred": False, "muted": False})
    assert room.unmute().muted is False
    reopen = api.post("/v1/channels/ch_1/reopen").respond(json={**CHANNEL, "name": "launch-2", "status": "open"})
    assert room.reopen(name="launch-2").name == "launch-2"
    assert body(reopen.calls.last.request) == {"name": "launch-2"}
    leave = api.post("/v1/channels/ch_1/leave").respond(json={"object": "channel_member", "id": "m1", "deleted": True})
    assert room.leave() is None and leave.called
    joined = api.post("/v1/channels/ch_1/join").respond(json={**CHANNEL, "muted": True, "unread_count": 1,
                                                               "mention_count": 1})
    assert (room.join().mention_count, room.unread_count) == (1, 1) and joined.called


def test_your_own_sections_read_save_against_their_version_and_lose_to_a_newer_save(api, client):
    layout = {"object": "channel_sections", "workspace_id": "ws_1", "version": 2, "folded": ["channels"],
              "updated_at": "2026-11-14T10:00:00Z", "sections": [
                  {"id": "8f9c5a0e-3b0e-4b7f-9a59-3c6c3a2f1d10", "name": "Launch", "folded": True,
                   "channel_ids": ["ch_1", "ch_2"]}]}
    read = api.get("/v1/channels/sections").respond(json=layout)
    got = nc.Channel.sections(workspace="ws_1")
    assert read.calls.last.request.url.params["workspace_id"] == "ws_1"
    assert (got.workspace_id, got.version, got.folded) == ("ws_1", 2, ["channels"])
    assert got.sections == [nc.ChannelSection("8f9c5a0e-3b0e-4b7f-9a59-3c6c3a2f1d10", "Launch", True, ["ch_1", "ch_2"])]

    save = api.put("/v1/channels/sections").respond(json={**layout, "version": 3, "sections": [], "folded": []})
    assert nc.Channel.save_sections([], version=got.version, workspace="ws_1").version == 3
    assert body(save.calls.last.request) == {"workspace_id": "ws_1", "version": 2, "folded": [], "sections": []}

    api.put("/v1/channels/sections").respond(409, json={"error": {"type": "conflict", "message": "Changed.",
                                                                   "version": 4}})
    with pytest.raises(nc.Conflict) as refused:
        nc.Channel.save_sections(got.sections, version=3, folded=["starred"])
    assert refused.value.version == 4

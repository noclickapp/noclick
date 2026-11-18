"""Channels' files, voice clips, reactions, history paging, topic and read point."""

import httpx
import pytest

import noclick as nc
from platform_helpers import body, listing

CHANNEL = {"object": "channel", "id": "ch_1", "name": "launch", "topic": "Friday's launch", "mode": "mentions",
           "status": "open", "user_id": None, "workspace_id": None, "unread_count": 3, "members": [
               {"id": "mem_1", "type": "agent", "agent_id": "agt_s", "name": "Scout"}]}
REPORT = {"object": "channel_attachment", "id": "att_1", "channel_id": "ch_1", "name": "report.pdf",
          "mime_type": "application/pdf", "size_bytes": 1200, "kind": "file", "voice": False,
          "url": "https://assets.example/u/account/att_1/report.pdf", "duration_ms": None, "peaks": None}
CLIP = {**REPORT, "id": "att_2", "name": "Voice clip.mp3", "mime_type": "audio/mpeg", "kind": "audio", "voice": True,
        "url": "https://assets.example/u/account/att_2/Voice%20clip.mp3", "duration_ms": 4200, "peaks": [0.2, 1.0]}


def _message(message_id="m1", **extra):
    return {"object": "channel_message", "id": message_id, "channel_id": "ch_1",
            "author": {"type": "account", "id": None, "name": "owner"}, "text": "hi", "mentions": [],
            "created_at": "2026-10-09T10:00:00Z", "attachments": [], "reactions": [], **extra}


def test_files_upload_then_post_with_the_message(api, client, tmp_path):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    upload = api.post("/v1/channels/ch_1/attachments").mock(side_effect=[
        httpx.Response(201, json=CLIP), httpx.Response(201, json=REPORT)])
    post = api.post("/v1/channels/ch_1/messages").respond(json=_message(attachments=[REPORT, CLIP]))
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4")
    room = nc.Channel.get("ch_1")
    clip = room.upload(b"OggS...", name="Voice clip.webm", mime_type="audio/webm", voice=True, peaks=[0.2, 1])
    assert isinstance(clip, nc.ChannelAttachment) and (clip.voice, clip.duration_ms, clip.peaks) == (True, 4200, [0.2, 1.0])
    sent = upload.calls.last.request
    assert dict(sent.url.params) == {"name": "Voice clip.webm", "mime_type": "audio/webm", "voice": "true",
                                     "peaks": "0.2,1"}
    assert sent.content == b"OggS..."

    message = room.post("@Scout what stands out?", files=[str(report), clip])
    first = upload.calls[1].request  # the path was uploaded first, named and typed from its name
    assert dict(first.url.params) == {"name": "report.pdf", "mime_type": "application/pdf"}
    assert first.content == b"%PDF-1.4"
    assert body(post.calls.last.request) == {"text": "@Scout what stands out?", "attachments": ["att_1", "att_2"]}
    assert [(a.name, a.kind, a.url) for a in message.attachments] == [
        ("report.pdf", "file", REPORT["url"]), ("Voice clip.mp3", "audio", CLIP["url"])]
    room.post(files=[clip])  # files alone
    assert body(post.calls.last.request) == {"text": "", "attachments": ["att_2"]}
    with pytest.raises(TypeError, match="name="):
        room.upload(b"bytes")

    # More files than a message carries is refused before any of them is uploaded, so none is left behind.
    uploads, posts = upload.call_count, post.call_count
    with pytest.raises(nc.InvalidRequest, match="at most 100 files") as refused:
        room.post("Everything", files=[str(report)] * 101)
    assert refused.value.field == "attachments"
    assert (upload.call_count, post.call_count) == (uploads, posts)


def test_reactions_as_the_account_or_a_member(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    reacted = _message(reactions=[{"emoji": "🎉", "count": 2, "by": [
        {"type": "account", "id": None, "name": "owner"}, {"type": "agent", "id": "agt_s", "name": "Scout"}]}])
    add = api.post("/v1/channels/ch_1/messages/m1/reactions").respond(json=reacted)
    remove = api.delete(url__regex=r"/v1/channels/ch_1/messages/m1/reactions/.+").respond(json=_message())
    room = nc.Channel.get("ch_1")
    message = room.react("m1", "🎉")
    assert body(add.calls.last.request) == {"emoji": "🎉"}
    [party] = message.reactions
    assert isinstance(party, nc.ChannelReaction) and (party.emoji, party.count) == ("🎉", 2)
    assert [(b.type, b.name) for b in party.by] == [("account", "owner"), ("agent", "Scout")]
    room.react(message, "🎉", as_=nc.Agent.from_id("agt_s"))
    assert body(add.calls.last.request) == {"emoji": "🎉", "as": {"agent_id": "agt_s"}}

    assert room.unreact(message, "🎉").reactions == []
    request = remove.calls.last.request
    assert request.url.raw_path == b"/v1/channels/ch_1/messages/m1/reactions/%F0%9F%8E%89"
    room.unreact("m1", "🎉", as_=nc.Agent.from_id("agt_s"))
    assert dict(remove.calls.last.request.url.params) == {"agent_id": "agt_s"}


def test_history_reads_back_from_the_newest_and_one_message(api, client):
    route = api.get("/v1/channels/ch_1/messages").respond(json=listing(_message("m4"), _message("m5")))
    one = api.get("/v1/channels/ch_1/messages/m5").respond(json=_message("m5"))
    room = nc.Channel.from_id("ch_1")
    latest = room.messages(newest=True, limit=2)
    assert dict(route.calls.last.request.url.params) == {"newest": "true", "limit": "2"}
    room.messages(before=latest[0], limit=2)
    assert dict(route.calls.last.request.url.params) == {"before": "m4", "limit": "2"}
    assert room.message(latest[-1]).id == "m5" and one.call_count == 1
    with pytest.raises(ValueError, match="one of"):
        room.messages(after="m1", newest=True)


def test_topic_update_and_read_point(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    create = api.post("/v1/channels").respond(json=CHANNEL)
    patch = api.patch("/v1/channels/ch_1").respond(json={**CHANNEL, "topic": "Post-launch", "mode": "all"})
    read = api.post("/v1/channels/ch_1/read").respond(json={**CHANNEL, "unread_count": 0})
    made = nc.Channel.create("launch", topic="Friday's launch")
    assert body(create.calls.last.request) == {"name": "launch", "members": [], "topic": "Friday's launch"}
    assert (made.topic, made.unread_count) == ("Friday's launch", 3)
    room = nc.Channel.get("ch_1")
    room.update(topic="Post-launch", mode="all")
    assert body(patch.calls.last.request) == {"topic": "Post-launch", "mode": "all"}
    assert (room.topic, room.mode) == ("Post-launch", "all")
    room.update(name="launch-day")
    assert body(patch.calls.last.request) == {"name": "launch-day"}
    with pytest.raises(ValueError, match="mode"):
        room.update(mode="loud")
    assert room.mark_read().unread_count == 0 and body(read.calls.last.request) == {}
    room.mark_read("m2")
    assert body(read.calls.last.request) == {"message_id": "m2"}


def test_a_workspace_takes_a_logo_upload(api, client, tmp_path):
    workspace = {"object": "workspace", "id": "ws_1", "name": "Acme", "logo_url": None, "user_id": None,
                 "status": "active", "members": []}
    api.get("/v1/workspaces/ws_1").respond(json=workspace)
    put = api.put("/v1/workspaces/ws_1/logo").respond(json={**workspace, "logo_url": "https://assets.example/logo.png"})
    logo = tmp_path / "acme.png"
    logo.write_bytes(b"\x89PNG")
    acme = nc.Workspace.get("ws_1")
    assert acme.set_logo(str(logo)).logo_url == "https://assets.example/logo.png"
    assert dict(put.calls.last.request.url.params) == {"mime_type": "image/png"}
    assert put.calls.last.request.content == b"\x89PNG"
    with pytest.raises(TypeError, match="mime_type"):
        acme.set_logo(b"\x89PNG")

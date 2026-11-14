"""Files people send a WhatsApp agent land in its chat's workspace (``utils.agent_inbox``).

A photo or document someone sends was a link the agent had to download, and an agent asked to send the photo back
went looking for it on the platform instead. The delivery now keeps the bytes its rehost already fetched as a file in
the durable ``/workspace`` of the conversation the chat's turn runs in, written through the volume backend (no
sandbox boots), in a folder of the chat's own, named for when it was sent and what it is, and the turn names its
path beside the link. A save that fails never drops the message.

The engine's own wiring decides here (a WhatsApp trigger wired into an agent on the canvas); a platform's agents are
covered in ``cloud/tests/platform/test_platform_agent_templates.py``."""

import logging
import posixpath
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from nodes.whatsapp_node import WhatsAppNode
from utils import agent_inbox, capabilities
from utils import volume_backend
from utils.agent_inbox import Held, Workspace, agent_inbox_volume, chat_folder, file_name, reserve

WORKFLOW = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
ASHA, BEN = "12025550101@c.us", "12025550107@c.us"
SENT = 1763141220  # 2025-11-14 17:27 UTC
GRAPH = {
    "nodes": [{"id": "wa", "type": "automation-whatsapp", "config": {"operation": "receive_message"}},
              {"id": "agent", "type": "agent", "config": {"label": "Assistant"}}],
    "edges": [{"source": "wa", "target": "agent", "sourceHandle": "right", "targetHandle": "left"}],
}


class _Pool:
    """The workflow's graph and owner, as the delivery reads them."""

    def __init__(self, graph=GRAPH):
        self.graph = graph

    async def fetchval(self, sql, *args):
        assert "SELECT workflow FROM workflows" in sql and args == (WORKFLOW,)
        return self.graph

    async def fetchrow(self, sql, *args):
        assert "FROM workflows" in sql
        return {"owner_id": OWNER, "organization_id": None}


class _Response:
    def __init__(self, body):
        self.body = body
        self.headers = {}

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        for i in range(0, len(self.body), 1 << 20):
            yield self.body[i:i + (1 << 20)]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Provider:
    """WAHooks' media endpoint: each URL's bytes, fetched once."""

    def __init__(self, files):
        self.files = files
        self.fetched = []

    def __call__(self, timeout=None, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.fetched.append(url)
        return _Response(self.files[url])


async def _resource(*, chunks, content_type, filename, **kwargs):
    """Workflow resources (R2), taking the stream as the real store does."""
    size = 0
    async for chunk in chunks:
        size += len(chunk)
    rid = uuid.uuid4().hex
    return {"resource_id": rid, "size_bytes": size, "download_url": f"https://assets.example.test/{rid}/{filename}"}


def _media_message(chat, url, mimetype, *, filename=None, body="", message_id="m1", name=None, **fields):
    return {"event": "message", "session": "u_1_s_1", "payload": {
        "id": message_id, "from": chat, "fromMe": False, "body": body, "hasMedia": True, "timestamp": SENT,
        "media": {"url": url, "mimetype": mimetype, **({"filename": filename} if filename else {})},
        "_data": {"key": {"remoteJid": chat}, **({"pushName": name} if name else {})}, **fields}}


def _url(name):
    return f"https://api.wahooks.com/api/connections/c1/media/{name}"


@pytest.fixture(autouse=True)
def engine(monkeypatch, tmp_path):
    """The engine's wiring decides (no platform's), over local volumes, with no Redis."""
    monkeypatch.setenv("WAHOOKS_API_KEY", "platform-key")
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    monkeypatch.delitem(capabilities._providers, capabilities.DELIVERY_WORKSPACES, raising=False)
    monkeypatch.setattr(volume_backend, "_backend", volume_backend.LocalVolumeBackend())
    monkeypatch.setattr(volume_backend, "_initialized", True)
    monkeypatch.setattr(agent_inbox, "_claimed_here", {})
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)


def _volume(chat):
    """The volume the chat's turns mount, as every inbox write resolves it."""
    return agent_inbox_volume(WORKFLOW, "agent", chat, GRAPH["nodes"], GRAPH["edges"]).volume_name


async def _files(chat):
    listing = await volume_backend.get_volume_backend().list_files(_volume(chat))
    return {f["path"]: f["size"] for f in listing["files"]}


ASHAS = chat_folder(ASHA, "Asha")


async def _read(chat, rel):
    chunks = await volume_backend.get_volume_backend().iter_file(_volume(chat), rel)
    return b"".join([c async for c in chunks])


async def _deliver(provider, payload, pool=None):
    with patch("utils.inbound_media.guarded_async_client", provider), \
         patch("utils.resource_store.create_resource_from_stream", _resource):
        return await WhatsAppNode.transform_trigger_payload(
            payload, {"operation": "receive_message"}, pool=pool or _Pool(), workflow_id=WORKFLOW, node_id="wa")


async def test_a_photo_lands_in_its_chats_workspace_and_the_turn_names_its_path():
    provider = _Provider({_url("p.jpg"): b"jpeg-bytes"})

    out = await _deliver(provider, _media_message(ASHA, _url("p.jpg"), "image/jpeg", body="look", name="Asha"))

    name = "2025-11-14_1727_photo.jpg"  # sent at 17:27 UTC; the engine names files in UTC
    assert ASHAS.startswith("asha-") and len(ASHAS) == len("asha-") + 6
    media = out["payload"]["media"]
    assert media["inbox"] == {"kind": "photo", "path": f"/workspace/inbox/{ASHAS}/{name}", "folder": ASHAS,
                              "name": name}
    # The bytes the rehost fetched, written once into the chat's workspace: one download.
    assert provider.fetched == [_url("p.jpg")]
    assert await _read(ASHA, f"inbox/{ASHAS}/{name}") == b"jpeg-bytes"

    event = WhatsAppNode.resolve_agent_event(out)
    assert f"photo: /workspace/inbox/{ASHAS}/{name}" in event["text"]
    assert media["url"] in event["text"] and "look" in event["text"]
    # The model still sees the picture itself.
    [entry] = event["media"]
    assert entry["url"] == media["url"] and entry["mime_type"] == "image/jpeg"


async def test_each_chats_files_land_under_its_own_folder():
    provider = _Provider({_url("a.jpg"): b"asha's photo", _url("b.pdf"): b"%PDF ben's"})

    asha = await _deliver(provider, _media_message(ASHA, _url("a.jpg"), "image/jpeg", name="Asha"))
    ben = await _deliver(provider, _media_message(BEN, _url("b.pdf"), "application/pdf", filename="Lease draft.pdf",
                                                  message_id="m2"))

    # Ben's WhatsApp gives no name: his folder is his number's.
    bens = chat_folder(BEN, "+12025550107")
    assert bens.startswith("12025550107-") and bens != ASHAS
    assert await _files(ASHA) == {f"inbox/{ASHAS}/2025-11-14_1727_photo.jpg": len(b"asha's photo")}
    assert await _files(BEN) == {f"inbox/{bens}/2025-11-14_1727_document_Lease-draft.pdf": len(b"%PDF ben's")}
    assert asha["payload"]["media"]["inbox"]["path"] == f"/workspace/inbox/{ASHAS}/2025-11-14_1727_photo.jpg"
    assert f"document: /workspace/inbox/{bens}/2025-11-14_1727_document_Lease-draft.pdf" in \
        WhatsAppNode.resolve_agent_event(ben)["text"]


async def test_a_chat_keeps_its_folder_when_its_name_changes():
    provider = _Provider({_url("1.jpg"): b"one", _url("2.jpg"): b"two"})
    await _deliver(provider, _media_message(ASHA, _url("1.jpg"), "image/jpeg", name="Asha"))
    later = await _deliver(provider, _media_message(ASHA, _url("2.jpg"), "image/jpeg", name="Asha K.",
                                                    message_id="m2"))

    assert later["payload"]["media"]["inbox"]["folder"] == ASHAS
    assert set(await _files(ASHA)) == {f"inbox/{ASHAS}/2025-11-14_1727_photo.jpg",
                                       f"inbox/{ASHAS}/2025-11-14_1727_photo_2.jpg"}


async def test_a_save_that_fails_still_delivers_the_message_with_its_link(caplog):
    class _Broken(volume_backend.LocalVolumeBackend):
        async def write_file(self, name, path, data):
            raise OSError("volume unavailable")

    provider = _Provider({_url("p.jpg"): b"jpeg-bytes"})
    with patch.object(volume_backend, "_backend", _Broken()), caplog.at_level(logging.ERROR, "utils.agent_inbox"):
        out = await _deliver(provider, _media_message(ASHA, _url("p.jpg"), "image/jpeg", body="look", name="Asha"))

    media = out["payload"]["media"]
    assert media["rehosted"] is True and media["inbox"] == {"kind": "photo", "error": agent_inbox.FAILED}
    assert any(r.levelno == logging.ERROR and "OSError" in r.getMessage() for r in caplog.records)
    event = WhatsAppNode.resolve_agent_event(out)
    assert "look" in event["text"] and media["url"] in event["text"] and "curl" in event["text"]
    assert "It wasn't saved in your workspace: saving it failed." in event["text"]
    assert len(event["media"]) == 1
    # The name it would have had is free again.
    assert agent_inbox._claimed_here == {}


async def test_a_file_too_large_to_save_still_runs_with_its_link(caplog):
    body = bytes(agent_inbox.MAX_BYTES + 1)
    provider = _Provider({_url("v.mp4"): body})
    with caplog.at_level(logging.ERROR, "utils.agent_inbox"):
        out = await _deliver(provider, _media_message(ASHA, _url("v.mp4"), "video/mp4"))

    media = out["payload"]["media"]
    assert media["rehosted"] is True and media["size"] == len(body)
    assert media["inbox"] == {"kind": "video", "error": agent_inbox.TOO_LARGE}
    assert await _files(ASHA) == {}
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert f"It wasn't saved in your workspace: {agent_inbox.TOO_LARGE}." in \
        WhatsAppNode.resolve_agent_event(out)["text"]


async def test_media_that_never_arrived_saves_nothing_and_frees_its_name():
    class _Gone(_Provider):
        def stream(self, method, url, headers=None):
            raise OSError("connection reset")

    out = await _deliver(_Gone({}), _media_message(ASHA, _url("p.jpg"), "image/jpeg"))

    assert out["payload"]["media"]["unavailable"] is True and "inbox" not in out["payload"]["media"]
    assert await _files(ASHA) == {} and agent_inbox._claimed_here == {}


async def test_a_trigger_no_agent_hears_keeps_no_file():
    alone = {"nodes": [GRAPH["nodes"][0]], "edges": []}
    out = await _deliver(_Provider({_url("p.jpg"): b"x"}), _media_message(ASHA, _url("p.jpg"), "image/jpeg"),
                         pool=_Pool(alone))

    assert out["payload"]["media"]["rehosted"] is True and "inbox" not in out["payload"]["media"]


async def test_files_sent_in_one_minute_each_get_a_name_of_their_own():
    provider = _Provider({_url("1.jpg"): b"one", _url("2.jpg"): b"two"})
    first = await _deliver(provider, _media_message(ASHA, _url("1.jpg"), "image/jpeg"))
    second = await _deliver(provider, _media_message(ASHA, _url("2.jpg"), "image/jpeg", message_id="m2"))

    assert first["payload"]["media"]["inbox"]["name"] == "2025-11-14_1727_photo.jpg"
    assert second["payload"]["media"]["inbox"]["name"] == "2025-11-14_1727_photo_2.jpg"
    folder = second["payload"]["media"]["inbox"]["folder"]
    assert await _read(ASHA, f"inbox/{folder}/2025-11-14_1727_photo_2.jpg") == b"two"


async def test_names_landing_together_are_claimed_apart():
    """Deliveries arriving at once (an album) list the same empty inbox: the claim keeps them apart."""
    at = datetime(2026, 11, 14, 17, 27, tzinfo=timezone.utc)
    spaces = [Workspace("ws-one", "/workspace")]
    one, two = [await reserve(spaces, "photo", at, chat_key=ASHA, chat_name="Asha", mimetype="image/jpeg")
                for _ in range(2)]
    assert (one.rel, two.rel) == (f"inbox/{ASHAS}/2026-11-14_1727_photo.jpg",
                                  f"inbox/{ASHAS}/2026-11-14_1727_photo_2.jpg")


def test_a_file_is_named_in_its_owners_time_by_what_it_is():
    at = datetime(2026, 11, 14, 17, 27, tzinfo=timezone.utc)
    assert file_name("photo", at, "Asia/Kolkata", mimetype="image/png") == "2026-11-14_2257_photo.png"
    assert file_name("voice", at, "UTC", mimetype="audio/ogg; codecs=opus") == "2026-11-14_1727_voice.ogg"
    assert file_name("document", at, "UTC", original="Q3 report (final).PDF") == \
        "2026-11-14_1727_document_Q3-report-final.pdf"
    assert file_name("sticker", at, "UTC", mimetype="image/webp", suffix=3) == "2026-11-14_1727_sticker_3.webp"
    # Nothing a sent name holds reaches a path: no folders, no shell metacharacters.
    unsafe = file_name("document", at, "UTC", original="../../etc/$(rm -rf)`x`.txt")
    assert posixpath.basename(unsafe) == unsafe and not set("$`/ ()") & set(unsafe)


def test_a_chats_folder_is_its_name_and_a_short_id():
    assert chat_folder("120000000000000001@g.us", "Book Club 📚") == \
        f"book-club-{agent_inbox.chat_id('120000000000000001@g.us')}"
    assert chat_folder("12025550102@lid", None) == f"12025550102-{agent_inbox.chat_id('12025550102@lid')}"
    # Two chats sharing a name still get folders of their own.
    assert chat_folder(ASHA, "Asha") != chat_folder(BEN, "Asha")
    unsafe = chat_folder(ASHA, "../$(rm -rf ~)")
    assert "/" not in unsafe and not set("$() ~") & set(unsafe)


def test_held_bytes_stop_at_their_cap():
    held = Held(cap=4)
    held.add(b"ab")
    held.add(b"cd")
    assert held.data == b"abcd" and not held.over
    held.add(b"e")
    assert held.over and held.data == b""


def test_the_kind_a_whatsapp_file_is_named_by():
    def kind(mimetype, **p):
        return WhatsAppNode._inbox_kind(p, {"mimetype": mimetype})

    assert kind("image/jpeg") == "photo"
    assert kind("image/webp", _data={"message": {"stickerMessage": {}}}) == "sticker"
    assert kind("audio/ogg; codecs=opus") == "voice"
    assert kind("audio/mpeg") == "audio"
    assert kind("video/mp4") == "video"
    assert kind("application/pdf") == "document"
    assert kind("application/zip") == "document"

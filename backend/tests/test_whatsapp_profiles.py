"""WhatsApp chat profiles (``utils.whatsapp_profiles``) over real PostgreSQL, with WAHooks and WhatsApp's picture CDN
faked as one transport: a picture is fetched once, copied into storage and served from there at a URL that lasts; it is
fetched again only after its refresh window, and stored again only when it changed. No picture, a private one, a
gateway failure and a link off WhatsApp's CDN all read as None. A group's name comes from the connection's chats. A
delivery's read never waits on WhatsApp."""

import asyncio
import hashlib
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx
import pytest

from nodes.whatsapp_node import GROUP_CHAT_TITLE, WhatsAppNode
from utils import r2_cloudflare, wahooks_connections, whatsapp_profiles
from utils.async_helpers import drain_spawned_tasks

pytestmark = pytest.mark.asyncio

PERSON = "12025550101@c.us"
HIDDEN = "12025550102@lid"
GROUP = "120000000000000001@g.us"
WRITER = "12025550107@c.us"


class FakeWhatsApp:
    """What each chat shows on WhatsApp, served the way WAHooks and the CDN serve it; every request is recorded."""

    def __init__(self) -> None:
        self.pictures: Dict[str, Optional[bytes]] = {}
        self.chats: List[Dict[str, Any]] = []
        self.groups: Dict[str, Dict[str, Any]] = {}  # each group's object, as GET .../groups/{id} answers it
        self.link_host = "pps.whatsapp.net"
        self.failing: Optional[str] = None  # "status" (WAHooks answers 503) or "network"
        self.requests: List[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "api.wahooks.com":
            if self.failing == "network":
                raise httpx.ConnectError("unreachable", request=request)
            if self.failing == "status":
                return httpx.Response(503, json={"message": "Service Unavailable"})
            parts = request.url.path.split("/")
            if parts[-2] == "groups":
                group = self.groups.get(unquote(parts[-1]))
                return httpx.Response(200, json=group) if group else httpx.Response(
                    404, json={"message": "Group not found"})
            if parts[-1] == "chats":
                offset = int(request.url.params.get("offset", 0))
                return httpx.Response(200, json=self.chats[offset:offset + int(request.url.params["limit"])])
            jid = unquote(parts[-2])
            picture = self.pictures.get(jid)
            link = (f"https://{self.link_host}/v/t61/{hashlib.sha1(picture).hexdigest()}.jpg?oe=6A1B2C3D&jid={jid}"
                    if picture else None)
            return httpx.Response(200, json={"profilePictureUrl": link})
        jid = request.url.params["jid"]
        return httpx.Response(200, content=self.pictures[jid], headers={"content-type": "image/jpeg"})

    def calls(self, kind: str) -> int:
        return sum(1 for r in self.requests if r.endswith(kind) or (kind == "cdn" and r.startswith("pps.")))


@pytest.fixture
def whatsapp(monkeypatch):
    fake = FakeWhatsApp()
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setenv("WAHOOKS_API_KEY", "wh_test")
    monkeypatch.setattr(wahooks_connections, "wahooks_http", lambda key, **kw: httpx.AsyncClient(
        base_url="https://api.wahooks.com/api", transport=transport, headers={"Authorization": f"Bearer {key}"}))
    monkeypatch.setattr(whatsapp_profiles, "_cdn_client", lambda: httpx.AsyncClient(transport=transport))
    return fake


@pytest.fixture
def storage(monkeypatch):
    """The bucket: what is kept under each key, and the URL a key is served at."""
    kept: Dict[str, bytes] = {}

    async def upload(*, bucket, key, body, content_type):
        assert bucket == "workflow-resources" and content_type == "image/jpeg"
        kept[key] = body

    async def delete(bucket, keys):
        for key in keys:
            kept.pop(key, None)
        return len(keys)

    monkeypatch.setattr(r2_cloudflare, "upload_bytes_to_r2_async", upload)
    monkeypatch.setattr(r2_cloudflare, "delete_files_from_r2_async_native", delete)
    monkeypatch.setattr(r2_cloudflare, "get_public_download_url", lambda key: f"https://files.noclick.test/{key}")
    return kept


@pytest.fixture
def line():
    return f"conn-{uuid.uuid4().hex[:12]}"


def _kept_at(url: str) -> str:
    return url.removeprefix("https://files.noclick.test/")


async def _expire(pool, connection_id: str, jid: str) -> None:
    await pool.execute("UPDATE whatsapp_chat_profiles SET refresh_after = now() - interval '1 second' "
                       "WHERE connection_id = $1 AND jid = $2", connection_id, jid)


async def _window_s(pool, connection_id: str, jid: str) -> float:
    return await pool.fetchval("SELECT extract(epoch FROM refresh_after - now()) FROM whatsapp_chat_profiles "
                               "WHERE connection_id = $1 AND jid = $2", connection_id, jid)


async def test_a_chat_never_read_is_fetched_in_the_background_then_served_from_the_copy(
        postgres_pool, whatsapp, storage, line):
    whatsapp.pictures[PERSON] = b"\xff\xd8 Asha's photo"

    first = await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON])
    assert first[PERSON].avatar_url is None  # nothing waited on
    await drain_spawned_tasks(timeout=5)

    kept = (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON]))[PERSON]
    assert kept.avatar_url is not None and kept.name is None
    assert storage[_kept_at(kept.avatar_url)] == b"\xff\xd8 Asha's photo"
    # The copy's key is NoClick's own and unguessable, never WhatsApp's link.
    assert "pps.whatsapp.net" not in kept.avatar_url
    assert uuid.UUID(_kept_at(kept.avatar_url).split("/")[1].split(".")[0]).version == 4
    assert (whatsapp.calls("/picture"), whatsapp.calls("cdn")) == (1, 1)

    # Within its window: read from what is kept, the same URL, with no call out.
    again = await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5)
    assert again[PERSON].avatar_url == kept.avatar_url
    assert len(whatsapp.requests) == 2
    assert 23 * 3600 < await _window_s(postgres_pool, line, PERSON) <= 24 * 3600


async def test_a_read_that_may_wait_gets_what_wasnt_kept_and_a_groups_name(postgres_pool, whatsapp, storage, line):
    whatsapp.pictures.update({PERSON: b"person", GROUP: b"group"})
    whatsapp.chats = [{"id": PERSON, "name": "Asha"}, {"id": GROUP, "name": "Bakery orders"}]

    found = await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON, GROUP, PERSON], wait_s=5)
    assert list(found) == [PERSON, GROUP]
    assert found[GROUP].name == "Bakery orders" and storage[_kept_at(found[GROUP].avatar_url)] == b"group"
    # Only a group is named from here: a person's name is whatever their messages say.
    assert found[PERSON].name is None and storage[_kept_at(found[PERSON].avatar_url)] == b"person"
    assert found[GROUP].as_dict() == {"jid": GROUP, "name": "Bakery orders", "avatar_url": found[GROUP].avatar_url}


async def test_after_its_window_a_picture_is_fetched_again_and_stored_only_when_it_changed(
        postgres_pool, whatsapp, storage, line):
    whatsapp.pictures[PERSON] = b"old photo"
    kept = (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url

    await _expire(postgres_pool, line, PERSON)
    same = (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url
    assert same == kept and list(storage) == [_kept_at(kept)]
    assert whatsapp.calls("/picture") == 2 and await _window_s(postgres_pool, line, PERSON) > 23 * 3600

    # They changed it: the new one is kept, the old one deleted.
    whatsapp.pictures[PERSON] = b"new photo"
    await _expire(postgres_pool, line, PERSON)
    changed = (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url
    assert changed != kept and storage == {_kept_at(changed): b"new photo"}

    # They took it down: it reads None, and its copy goes too.
    whatsapp.pictures[PERSON] = None
    await _expire(postgres_pool, line, PERSON)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url is None
    assert storage == {}


async def test_no_picture_or_a_private_one_reads_none_and_is_asked_again_sooner(postgres_pool, whatsapp, storage,
                                                                                 line):
    found = await whatsapp_profiles.chat_profiles(postgres_pool, line, [HIDDEN], wait_s=5)
    assert found[HIDDEN].avatar_url is None and storage == {}
    assert whatsapp.calls("/picture") == 1 and whatsapp.calls("cdn") == 0
    # WAHooks answers null for its own failures as well, so the window is shorter than a picture's.
    assert 5 * 3600 < await _window_s(postgres_pool, line, HIDDEN) <= 6 * 3600
    await whatsapp_profiles.chat_profiles(postgres_pool, line, [HIDDEN], wait_s=5)
    assert whatsapp.calls("/picture") == 1


@pytest.mark.parametrize("failing", ["status", "network"])
async def test_a_gateway_failure_reads_none_keeps_what_was_kept_and_is_retried_soon(
        postgres_pool, whatsapp, storage, line, failing, caplog):
    whatsapp.pictures[PERSON] = b"photo"
    kept = (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url
    whatsapp.failing = failing

    new = await whatsapp_profiles.chat_profiles(postgres_pool, line, [WRITER], wait_s=5)
    assert new[WRITER].avatar_url is None
    await _expire(postgres_pool, line, PERSON)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url == kept
    assert "not refreshed" in caplog.text
    assert 0 < await _window_s(postgres_pool, line, PERSON) <= 15 * 60
    assert 0 < await _window_s(postgres_pool, line, WRITER) <= 15 * 60

    # Back: the next read past the retry window fetches it.
    whatsapp.failing = None
    whatsapp.pictures[WRITER] = b"writer"
    await _expire(postgres_pool, line, WRITER)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [WRITER], wait_s=5))[WRITER].avatar_url


async def test_a_storage_failure_reads_none_and_never_breaks_the_read(postgres_pool, whatsapp, storage, line,
                                                                      monkeypatch):
    async def down(**_kw):
        raise httpx.ConnectError("storage down")

    monkeypatch.setattr(r2_cloudflare, "upload_bytes_to_r2_async", down)
    whatsapp.pictures[PERSON] = b"photo"
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url is None


async def test_a_picture_link_off_whatsapps_cdn_is_never_fetched(postgres_pool, whatsapp, storage, line):
    whatsapp.pictures[PERSON] = b"photo"
    whatsapp.link_host = "files.example.org"
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url is None
    assert whatsapp.requests == [f"api.wahooks.com/api/connections/{line}/contacts/{PERSON}/picture"]


async def test_a_group_not_in_the_chats_keeps_the_name_it_had(postgres_pool, whatsapp, storage, line):
    whatsapp.chats = [{"id": f"1200000000000000{n:02d}@g.us", "name": f"Group {n}"} for n in range(2, 102)]
    whatsapp.chats.append({"id": GROUP, "name": "Bakery orders"})
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [GROUP], wait_s=5))[GROUP].name == \
        "Bakery orders"
    assert whatsapp.calls("/chats") == 2  # paged past the first hundred

    whatsapp.chats = []  # WAHooks lists none when its gateway fails
    await _expire(postgres_pool, line, GROUP)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [GROUP], wait_s=5))[GROUP].name == \
        "Bakery orders"


async def test_reads_at_once_share_one_fetch(postgres_pool, whatsapp, storage, line):
    whatsapp.pictures[PERSON] = b"photo"
    both = await asyncio.gather(*(whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5)
                                  for _ in range(3)))
    assert len({found[PERSON].avatar_url for found in both}) == 1
    assert whatsapp.calls("/picture") == 1 and len(storage) == 1


async def test_nothing_is_fetched_without_a_connection_or_a_wahooks_key(postgres_pool, whatsapp, storage, line,
                                                                       monkeypatch):
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, "", [PERSON], wait_s=5))[PERSON].avatar_url is None
    monkeypatch.delenv("WAHOOKS_API_KEY")
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], wait_s=5))[PERSON].avatar_url is None
    assert whatsapp.requests == []


async def test_a_torn_down_connection_forgets_its_chats(postgres_pool, whatsapp, storage, line):
    whatsapp.pictures.update({PERSON: b"person", GROUP: b"group"})
    whatsapp.chats = [{"id": GROUP, "name": "Bakery orders"}]
    other = f"{line}-other"
    await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON, GROUP], wait_s=5)
    kept_other = (await whatsapp_profiles.chat_profiles(postgres_pool, other, [PERSON], wait_s=5))[PERSON].avatar_url

    assert await whatsapp_profiles.forget_connection(postgres_pool, line) == 2
    assert storage == {_kept_at(kept_other): b"person"}
    assert await postgres_pool.fetchval(
        "SELECT count(*) FROM whatsapp_chat_profiles WHERE connection_id = $1", line) == 0


def _wahooks_message(chat: str, *, participant: str = "", push_name: str = "Ravi",
                     profiles: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = {"remoteJid": chat, **({"participant": participant} if participant else {})}
    return {"event": "message", "payload": {"id": "false_x_ABC", "from": chat, "body": "Morning all!",
                                            "_data": {"key": key, "pushName": push_name}},
            **({"profiles": profiles} if profiles else {})}


async def test_the_agent_event_carries_the_chats_profiles_for_the_page_never_the_model():
    """A group's turn names the chat for the group (its kept name, else as a group) and carries its picture and its
    writer's; the model's text holds neither URL."""
    group_url, writer_url = "https://files.noclick.test/g.jpg", "https://files.noclick.test/w.jpg"
    event = _wahooks_message(GROUP, participant=WRITER, profiles={
        "chat": {"jid": GROUP, "name": "Bakery orders", "avatar_url": group_url},
        "sender": {"jid": WRITER, "name": None, "avatar_url": writer_url}})
    resolved = WhatsAppNode.resolve_agent_event(event)
    assert resolved["chat"] == {"key": GROUP, "name": "Bakery orders", "avatar": group_url, "kind": "group"}
    assert resolved["sender"] == {"id": WRITER, "name": "Ravi", "avatar": writer_url}
    assert resolved["conversation_title"] == "Bakery orders" and resolved["title"] == "Ravi"
    assert "files.noclick.test" not in resolved["text"]

    # Not kept yet: named as a group, no pictures.
    unnamed = WhatsAppNode.resolve_agent_event(_wahooks_message(GROUP, participant=WRITER))
    assert unnamed["conversation_title"] == GROUP_CHAT_TITLE
    assert unnamed["chat"] == {"key": GROUP, "name": None, "avatar": None, "kind": "group"}

    direct = WhatsAppNode.resolve_agent_event(_wahooks_message(PERSON, push_name="Asha", profiles={
        "chat": {"jid": PERSON, "name": None, "avatar_url": writer_url},
        "sender": {"jid": PERSON, "name": None, "avatar_url": writer_url}}))
    assert direct["chat"] == {"key": PERSON, "name": "Asha", "avatar": writer_url, "kind": "direct"}
    assert direct["sender"]["avatar"] == writer_url and "conversation_title" not in direct


async def test_only_a_group_without_a_name_holds_a_read_that_waits_for_names(postgres_pool, whatsapp, storage, line):
    """A group's name is in none of its messages, so a delivery waits for it the first time (``name_wait_s``); a
    person's picture, or a group already named, is never waited for."""
    whatsapp.pictures[PERSON] = b"photo"
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [PERSON], name_wait_s=5))[PERSON] \
        .avatar_url is None
    whatsapp.chats = [{"id": GROUP, "name": "Bakery orders"}]
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [GROUP], name_wait_s=5))[GROUP].name == \
        "Bakery orders"

    # Named, and due a refresh: read as kept while the refresh runs in the background.
    whatsapp.chats = [{"id": GROUP, "name": "Bakery orders (new)"}]
    await _expire(postgres_pool, line, GROUP)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [GROUP], name_wait_s=5))[GROUP].name == \
        "Bakery orders"
    await drain_spawned_tasks(timeout=5)
    assert (await whatsapp_profiles.chat_profiles(postgres_pool, line, [GROUP]))[GROUP].name == "Bakery orders (new)"


def _group(*members: Dict[str, Any], name: str = "Bakery orders") -> Dict[str, Any]:
    """A group as WAHooks' GET .../groups/{id} answers it, the account itself among its members."""
    me = {"id": "12025550108@c.us", "phone": "12025550108", "lid": None, "name": "12025550108", "role": "admin",
          "isMe": True}
    return {"id": GROUP, "name": name, "description": None, "owner": None, "createdAt": None,
            "participantCount": len(members) + 1, "participants": [me, *members], "announcementOnly": False,
            "locked": False, "isCommunity": False}


@pytest.fixture
def delivered(monkeypatch, line):
    """A delivery's credential: the line's own connection."""
    from utils import inbound_media

    async def credential(pool, config, workflow_id, credential_type):
        assert credential_type == "whatsapp_qr"
        return {"connection_id": line}, None

    monkeypatch.setattr(inbound_media, "resolve_delivery_credential", credential)


async def test_a_groups_message_reaches_its_agent_named_with_its_members(postgres_pool, whatsapp, storage, line,
                                                                         delivered):
    """A group's messages carry neither its name nor who's in it: the delivery reads both, so the turn names the group
    and its members (admins first, a number WhatsApp hides said so, the account itself left out), says whether the
    sender and the account are admins, and never a bare group id."""
    whatsapp.chats = [{"id": GROUP, "name": "Bakery orders"}]
    whatsapp.groups[GROUP] = _group(
        {"id": PERSON, "phone": "12025550101", "lid": None, "name": None, "role": "member", "isMe": False},
        {"id": HIDDEN, "phone": None, "lid": HIDDEN, "name": "Meera", "role": "member", "isMe": False},
        {"id": WRITER, "phone": "12025550107", "lid": "12025550103@lid", "name": "Ravi", "role": "superadmin",
         "isMe": False})
    # The sender is named by their @lid: the same person as Ravi's @c.us entry.
    payload = _wahooks_message(GROUP, participant="12025550103@lid")
    assert await WhatsAppNode._stamp_profiles(payload, {}, pool=postgres_pool, workflow_id=str(uuid.uuid4()))
    assert payload["profiles"]["chat"]["name"] == "Bakery orders"

    text = WhatsAppNode.resolve_agent_event(payload)["text"]
    assert text.startswith(f'WhatsApp message in the group "Bakery orders" ({GROUP}), sent by 12025550103@lid '
                           "(Ravi):\n")
    assert f"to={GROUP}" in text
    assert ("Everyone in the group reads what you send to it. It has 3 members besides you: Ravi (+1 202-555-0107, "
            "admin), +1 202-555-0101, Meera (hidden number). The sender is one of its admins. You're one of its "
            "admins.") in text
    assert "12025550108" not in text and "isn't available" not in text
    # A direct chat says nothing of groups, and reads no group.
    direct = _wahooks_message(PERSON, push_name="Asha")
    assert await WhatsAppNode._stamp_profiles(direct, {}, pool=postgres_pool, workflow_id=str(uuid.uuid4()))
    assert "group" not in direct and whatsapp.calls(f"/groups/{GROUP}") == 1
    text = WhatsAppNode.resolve_agent_event(direct)["text"]
    assert text.startswith(f"WhatsApp message from {PERSON} (Asha):\n") and "group" not in text


async def test_a_group_whose_members_cant_be_read_still_reaches_its_agent(postgres_pool, whatsapp, storage, line,
                                                                          delivered, monkeypatch, caplog):
    """Members WAHooks can't give (an error, or no answer within the delivery's budget) never hold the turn: it says
    they're unknown, the failure is logged, and the group is still named by what its delivery found."""
    whatsapp.chats = [{"id": GROUP, "name": "Bakery orders"}]
    payload = _wahooks_message(GROUP, participant=WRITER)  # WAHooks answers 404 for it
    assert await WhatsAppNode._stamp_profiles(payload, {}, pool=postgres_pool, workflow_id=str(uuid.uuid4()))
    assert "group" not in payload and "Members of group" in caplog.text
    text = WhatsAppNode.resolve_agent_event(payload)["text"]
    assert text.startswith(f'WhatsApp message in the group "Bakery orders" ({GROUP})')
    assert "Its members are unknown: the member list couldn't be read just now." in text

    # A slow gateway: the delivery goes on at its budget, with what it has.
    monkeypatch.setattr(WhatsAppNode, "PROFILE_READ_TIMEOUT_S", 1)
    whatsapp.groups[GROUP] = _group()
    handle = whatsapp.handle

    async def slow(request):
        if "/groups/" in request.url.path:
            await asyncio.sleep(5)
        return handle(request)

    slow_transport = httpx.MockTransport(slow)
    monkeypatch.setattr(wahooks_connections, "wahooks_http", lambda key, **kw: httpx.AsyncClient(
        base_url="https://api.wahooks.com/api", transport=slow_transport))
    payload = _wahooks_message(GROUP, participant=WRITER)
    started = asyncio.get_running_loop().time()
    assert await WhatsAppNode._stamp_profiles(payload, {}, pool=postgres_pool, workflow_id=str(uuid.uuid4()))
    assert asyncio.get_running_loop().time() - started < 1.5
    assert "group" not in payload and payload["profiles"]["chat"]["name"] == "Bakery orders"
    assert "members are unknown" in WhatsAppNode.resolve_agent_event(payload)["text"]

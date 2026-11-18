"""Watch: a token from POST /v1/watch/tokens, then a socket that says which objects changed. The token goes in the
first frame (never the URL), a reconnect resumes after the last change, and only what retrying can't fix ends it."""

import json
import sys

import httpx
import pytest

import noclick as nc
from noclick import _watch
from platform_helpers import body


def token(n):
    return {"object": "watch_token", "url": f"wss://api.test/v1/watch/socket/r_{n}", "token": f"tok_{n}",
            "expires_at": "2026-11-18T10:01:00Z", "connection_ends_at": "2026-11-18T10:15:00Z",
            "objects": ["deployment", "channel"], "user_id": None}


class FakeSocket:
    """One connection: what it was sent, the frames the room sends, then how the room closed it."""

    def __init__(self, url, frames, close_code):
        self.url, self.frames, self.close_code, self.close_reason = url, frames, close_code, "closed"
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        for frame in self.frames:
            yield frame if isinstance(frame, str) else json.dumps(frame)


class FakeConnect:
    def __init__(self, *connections):
        self.planned = list(connections)
        self.opened = []

    def __call__(self, url, **_):
        frames, code = self.planned.pop(0)
        socket = FakeSocket(url, frames, code)
        self.opened.append(socket)

        class Context:
            async def __aenter__(self):
                return socket

            async def __aexit__(self, *exc):
                return False

        return Context()


@pytest.fixture
def no_waits(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(_watch.asyncio, "sleep", instant)


def test_watch_token_asks_for_the_objects_the_origin_and_the_user(api, client):
    route = api.post("/v1/watch/tokens").respond(201, json=token(1))
    t = nc.watch_token(objects=["deployment"], origin="https://app.example", user="user_42")
    assert body(route.calls.last.request) == {"objects": ["deployment"], "origin": "https://app.example"}
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (t.url, t.token, t.objects) == ("wss://api.test/v1/watch/socket/r_1", "tok_1", ["deployment", "channel"])
    assert "tok_1" not in repr(t)


def test_watch_authenticates_first_yields_what_it_knows_and_resumes_after_a_renew(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").mock(side_effect=[httpx.Response(201, json=token(1)),
                                                    httpx.Response(201, json=token(2))])
    change = {"type": "change", "id": "c_1", "at": "2026-11-18T10:00:00Z", "object": "deployment", "object_id": "d1",
              "status": "ready", "parent": {"object": "project", "id": "p1"}}
    connect = FakeConnect(
        ([{"type": "ready", "resumed": False}, change, {"type": "something_new"}, "pong",
          {"type": "typing", "channel_id": "ch1", "user_id": "account", "typing": True}], _watch.CLOSE_RENEW),
        ([{"type": "ready", "resumed": True}, {"type": "reset"}], 1000),
    )
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    statuses, seen = [], []
    for message in nc.watch(objects=["deployment"], on_status=statuses.append):
        seen.append(message)
        if message.type == "reset":
            break
    assert [m.type for m in seen] == ["ready", "change", "typing", "ready", "reset"]
    assert (seen[1].object, seen[1].object_id, seen[1].status, seen[1].parent) == (
        "deployment", "d1", "ready", {"object": "project", "id": "p1"})
    assert seen[3].resumed is True
    first, second = connect.opened
    assert first.url == "wss://api.test/v1/watch/socket/r_1"
    assert first.sent == [{"type": "auth", "token": "tok_1", "after": None}]
    assert second.sent == [{"type": "auth", "token": "tok_2", "after": "c_1"}]
    assert statuses == ["connecting", "live", "reconnecting", "live", "stopped"]


def test_a_refused_socket_gets_one_fresh_token_and_a_second_refusal_ends_watch(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    connect = FakeConnect(([{"type": "ready", "resumed": False}], _watch.CLOSE_REFUSED), ([], _watch.CLOSE_REFUSED))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    with pytest.raises(nc.WatchRefused):
        for _ in nc.watch():
            pass
    assert len(connect.opened) == 2


def test_a_token_call_refused_for_good_ends_watch_and_a_token_source_replaces_the_client(api, client, monkeypatch,
                                                                                        no_waits):
    api.post("/v1/watch/tokens").respond(409, json={"error": {"type": "not_available", "message": "Not here."}})
    monkeypatch.setattr(_watch, "_connector", lambda: FakeConnect())
    with pytest.raises(nc.NotAvailable):
        for _ in nc.watch():
            pass

    connect = FakeConnect(([{"type": "ready", "resumed": False}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)

    async def mine():
        return "wss://relay.test/v1/watch/socket/r_9", "tok_mine"

    for message in nc.watch(token=mine):
        assert message.type == "ready"
        break
    assert connect.opened[0].url == "wss://relay.test/v1/watch/socket/r_9"


def test_without_the_live_extra_watch_names_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "websockets.asyncio.client", None)
    with pytest.raises(ImportError, match=r'noclick\[live\]'):
        for _ in nc.watch():
            pass

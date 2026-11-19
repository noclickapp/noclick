"""Watch: a token from POST /v1/watch/tokens, then a socket that says which objects changed. The token is offered as
the socket's subprotocol (never the URL), a reconnect resumes after the last change (the URL's ``after``), and only
what retrying can't fix ends it."""

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

    def __call__(self, url, **options):
        frames, code = self.planned.pop(0)
        socket = FakeSocket(url, frames, code)
        socket.subprotocols = list(options.get("subprotocols") or [])
        self.opened.append(socket)

        class Context:
            async def __aenter__(self):
                return socket

            async def __aexit__(self, *exc):
                return False

        return Context()


@pytest.fixture
def no_waits(monkeypatch):
    """Waits take no time; the list is how long each would have been."""
    waited = []

    async def instant(seconds):
        waited.append(seconds)

    monkeypatch.setattr(_watch.asyncio, "sleep", instant)
    return waited


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
    assert first.subprotocols == ["noclick.watch", "tok_1"] and first.sent == [], "the token rides the protocol"
    assert second.url == "wss://api.test/v1/watch/socket/r_2?after=c_1"
    assert second.subprotocols == ["noclick.watch", "tok_2"]
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


@pytest.mark.parametrize("frame", ["[]", "null", "42", '"text"', "[1, 2]"])
def test_a_frame_of_json_that_isnt_an_object_is_ignored(api, client, monkeypatch, no_waits, frame):
    """The stream can grow: what this version doesn't know (an unknown type, or JSON that isn't an object) is
    skipped, never raised out of the watcher."""
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    connect = FakeConnect(([{"type": "ready", "resumed": False}, frame, {"type": "reset"}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    seen = []
    for message in nc.watch():
        seen.append(message.type)
        if message.type == "reset":
            break
    assert seen == ["ready", "reset"]


def test_frames_that_arent_json_or_carry_wrong_types_are_skipped(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    hostile = ["{", "", "not json", {"type": "change", "at": 12, "id": 5, "object": None, "parent": "x"},
               {"type": "change", "at": "never", "object": "deployment"}, {"type": "typing"}, {"type": ["change"]},
               {"type": "ready", "resumed": "yes"}]
    connect = FakeConnect(([{"type": "ready", "resumed": False}, *hostile, {"type": "reset"}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    seen = []
    for message in nc.watch():
        seen.append(message)
        if message.type == "reset":
            break
    assert seen[0].type == "ready" and seen[-1].type == "reset"
    assert all(m.type in ("ready", "change", "typing", "reset") for m in seen)


@pytest.mark.parametrize("url", ["ws://relay.example/v1/watch/socket/r_1", "http://relay.example/x", "wss://",
                                 "not a url"])
def test_a_token_is_never_sent_to_an_address_that_isnt_wss(api, client, monkeypatch, no_waits, url):
    api.post("/v1/watch/tokens").respond(201, json={**token(1), "url": url})
    connect = FakeConnect(([{"type": "ready", "resumed": False}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    with pytest.raises(nc.Error, match="wss://"):
        for _ in nc.watch():
            break
    assert connect.opened == [], f"the token went to {connect.opened[0].url}"


def test_on_this_machine_a_plain_ws_socket_will_do(api, client, monkeypatch, no_waits):
    for url in ("ws://localhost:8787/v1/watch/socket/r_1", "ws://127.0.0.1:8787/x", "ws://[::1]:8787/x"):
        api.post("/v1/watch/tokens").respond(201, json={**token(1), "url": url})
        connect = FakeConnect(([{"type": "ready", "resumed": False}], 1000))
        monkeypatch.setattr(_watch, "_connector", lambda: connect)
        for _ in nc.watch():
            break
        assert connect.opened[0].url == url


def test_watchers_turned_away_together_come_back_spread_out(api, client, monkeypatch, no_waits):
    """A room over its limits closes with 4429: each watcher waits about half a minute, spread, so they don't all
    return (and spend a token use the room counts) at the same instant."""
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    waits = []
    for _ in range(5):
        no_waits.clear()
        connect = FakeConnect(([], _watch.CLOSE_TOO_MANY), ([{"type": "ready", "resumed": False}], 1000))
        monkeypatch.setattr(_watch, "_connector", lambda: connect)
        for _message in nc.watch():
            break
        waits.append(no_waits[0])
    assert len(set(waits)) > 1, f"five watchers all waited exactly {waits[0]} s"
    assert all(_watch._TOO_MANY_S * 0.5 <= w <= _watch._TOO_MANY_S * 1.5 for w in waits)


def test_a_dropped_socket_waits_a_spread_backoff(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    monkeypatch.setattr(_watch.random, "random", lambda: 0.0)
    connect = FakeConnect(([{"type": "ready", "resumed": False}], 1006), ([{"type": "ready", "resumed": False}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    seen = 0
    for message in nc.watch():
        seen += 1
        if seen == 2:
            break
    assert no_waits == [_watch._BACKOFF_S[0] * 0.5]


def test_the_token_never_appears_in_a_repr_an_error_or_the_url(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    minted = nc.watch_token()
    assert "tok_1" not in repr(minted) and "tok_1" not in str(minted) and "tok_1" not in minted.url
    connect = FakeConnect(([], _watch.CLOSE_REFUSED), ([], _watch.CLOSE_REFUSED))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    with pytest.raises(nc.WatchRefused) as refused:
        for _ in nc.watch():
            pass
    assert "tok_1" not in str(refused.value) and "tok_1" not in repr(refused.value)
    assert all("tok_1" not in socket.url for socket in connect.opened)


def test_a_server_error_on_the_token_call_backs_off_and_a_refusal_ends_it(api, client, monkeypatch, no_waits):
    # The client retries a 503 itself; each time it gives up, watch waits longer before asking again.
    api.post("/v1/watch/tokens").mock(side_effect=[httpx.Response(503, json={"error": {"type": "upstream_error",
                                                                                     "message": "x"}})] * 40
                                      + [httpx.Response(401, json={"error": {"type": "unauthenticated",
                                                                             "message": "revoked"}})])
    monkeypatch.setattr(_watch, "_connector", lambda: FakeConnect())
    with pytest.raises(nc.Error):
        for _ in nc.watch():
            pass
    own = [w for w in no_waits if w in _watch._BACKOFF_S]
    assert own[:3] == [0.5, 1.0, 2.0], f"each failed token call waits longer than the last: {no_waits}"


@pytest.mark.parametrize("url", [
    "wss://api.noclick.com/v1/watch/socket/r_1", "WSS://api.noclick.com/x", "ws://localhost:8787/x",
    "ws://LOCALHOST/x", "ws://127.0.0.1/x", "ws://[::1]:9/x", "ws://user:pw@localhost/x",
    # A backslash is userinfo to urllib (host: localhost); websockets refuses the URI outright, so nothing leaves.
    "ws://evil.com\\@localhost/x",
])
def test_a_token_goes_to_wss_or_this_machine(url):
    assert _watch._socket_url(url) == url


@pytest.mark.parametrize("url", [
    "ws://api.noclick.com/x", "ws://localhost.evil.com/x", "ws://localhost@evil.com/x", "ws://evil.com#@localhost",
    "ws://127.0.0.1.nip.io/x", "wss:///x", "wss://", "https://api.noclick.com/x",
    "ws://0x7f000001/x", "ws://[::ffff:127.0.0.1]/x", "", "localhost",
])
def test_and_nowhere_else(url):
    with pytest.raises(nc.Error) as refused:
        _watch._socket_url(url)
    assert "tok_" not in str(refused.value)


@pytest.mark.parametrize("frame", ["5", "[1,2]", '"x"', "null", "true", '{"type": 5}', '{"type": "change", "parent": 3}'])
def test_odd_frames_are_skipped_or_read_safely(frame):
    message = _watch._message(json.loads(frame))
    assert message is None or (message.type == "change" and message.parent is None)


async def test_a_token_for_a_plain_socket_is_never_sent(monkeypatch):
    opened = []

    def connect(url, **_):
        opened.append(url)
        raise AssertionError("connected")

    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    with pytest.raises(nc.Error) as refused:
        async for _ in nc.watch.aio(token=lambda: ("ws://relay.evil.com/x", "tok_secret")):
            pass
    assert opened == [] and "tok_secret" not in str(refused.value) and "tok_secret" not in repr(refused.value)


def test_a_tokens_repr_holds_no_token():
    minted = _watch.WatchToken(url="wss://a/b", token="tok_secret", expires_at=None, connection_ends_at=None,
                               objects=[], user_id=None, origin=None, raw={"token": "tok_secret"})
    assert "tok_secret" not in repr(minted)


def test_a_refused_socket_waits_out_a_revokes_margin_before_its_next_token(api, client, monkeypatch, no_waits):
    """A token minted within a revoke's margin (a user suspended and reactivated at once) is refused once: the
    next, asked for after the margin, opens."""
    api.post("/v1/watch/tokens").respond(201, json=token(1))
    connect = FakeConnect(([], _watch.CLOSE_REFUSED), ([{"type": "ready", "resumed": False}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    for message in nc.watch():
        assert message.type == "ready"
        break
    assert len(no_waits) == 1 and 8.0 <= no_waits[0] <= 12.0, no_waits


def test_a_resume_rides_the_url_and_the_token_the_protocol(api, client, monkeypatch, no_waits):
    api.post("/v1/watch/tokens").respond(201, json={**token(1), "url": "wss://api.test/v1/watch/socket/r_1?x=1"})
    change = {"type": "change", "id": "c_AbCdEfGh_7", "at": "2026-11-18T10:00:00Z", "object": "domain",
              "object_id": "d1"}
    connect = FakeConnect(([{"type": "ready", "resumed": False}, change], 4000),
                          ([{"type": "ready", "resumed": True}], 1000))
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    seen = 0
    for _message in nc.watch():
        seen += 1
        if seen == 3:
            break
    assert connect.opened[0].url == "wss://api.test/v1/watch/socket/r_1?x=1"
    assert connect.opened[1].url == "wss://api.test/v1/watch/socket/r_1?x=1&after=c_AbCdEfGh_7"
    assert all("tok_1" not in socket.url for socket in connect.opened)


def test_review3_FINDING_a_connection_that_drops_right_after_ready_never_backs_off(api, client, monkeypatch,
                                                                                  no_waits):
    """``ready`` resets the backoff, so a socket that opens and drops at once (a room failing every connection, a
    middlebox cutting sockets after the handshake) is retried every 0.25 to 0.75 s forever, minting a token each
    time: the backoff never climbs, however many times in a row it happens."""
    flaps = 8
    api.post("/v1/watch/tokens").mock(side_effect=[httpx.Response(201, json=token(n)) for n in range(flaps + 1)])
    connect = FakeConnect(*[([{"type": "ready", "resumed": False}], 1006) for _ in range(flaps + 1)])
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    readies = 0
    for message in nc.watch():
        readies += message.type == "ready"
        if readies > flaps:
            break
    assert len(no_waits) == flaps
    assert max(no_waits) >= 5.0, f"{flaps} drops in a row, each retried within {max(no_waits):.2f} s: {no_waits}"


def test_a_connection_that_stayed_up_starts_the_backoff_again(api, client, monkeypatch, no_waits):
    """Four drops right after ``ready`` climb the backoff; a connection that then stays up 30 s and drops is tried
    again at the first step."""
    api.post("/v1/watch/tokens").mock(side_effect=[httpx.Response(201, json=token(n)) for n in range(7)])
    connect = FakeConnect(*[([{"type": "ready", "resumed": False}], 1006) for _ in range(6)])
    monkeypatch.setattr(_watch, "_connector", lambda: connect)
    # Two clock reads a connection: at its ready, at its end. Up 1 s each, but the fifth: 42 s.
    reads = iter([0, 1, 2, 3, 4, 5, 6, 7, 8, 50, 51, 52])
    monkeypatch.setattr(_watch, "time", type("Clock", (), {"monotonic": staticmethod(lambda: next(reads))}))
    readies = 0
    for message in nc.watch():
        readies += message.type == "ready"
        if readies > 5:
            break
    assert len(no_waits) == 5
    assert no_waits[3] >= 2.5, f"the fourth drop in a row waits a later step: {no_waits}"
    assert no_waits[4] <= 0.75, f"after a connection that stayed up, the first step again: {no_waits}"

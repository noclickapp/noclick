"""SoundCloud wire tests: published routes, payloads, OAuth identity and rotation."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager
import json
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import soundcloud_node as sc
from nodes.core.run_op import run_node_operation
from nodes.oauth.soundcloud_oauth import OAUTH_PROVIDER
from utils import ssrf

AUTH = {
    "credential_type": "soundcloud_oauth",
    "access_token": "synthetic-soundcloud-access",
}
CASES = [
    ("get_current_user", {}, "GET", "/me", {}, None, {"id": 1, "username": "Artist"}),
    (
        "list_my_tracks",
        {"limit": 2},
        "GET",
        "/me/tracks",
        {"limit": "2", "linked_partitioning": "true"},
        None,
        {"collection": [{"id": 308946187, "title": "Track"}], "next_href": None},
    ),
    (
        "list_my_playlists",
        {},
        "GET",
        "/me/playlists",
        {"limit": "50"},
        None,
        [{"id": 10, "title": "Playlist"}],
    ),
    (
        "list_my_liked_tracks",
        {},
        "GET",
        "/me/likes/tracks",
        {"limit": "50", "linked_partitioning": "true"},
        None,
        {"collection": [], "next_href": None},
    ),
    (
        "list_my_followers",
        {},
        "GET",
        "/me/followers",
        {"limit": "50"},
        None,
        [{"id": 743372812, "username": "Listener"}],
    ),
    (
        "list_my_followings",
        {"offset": 50},
        "GET",
        "/me/followings",
        {"limit": "50", "offset": "50"},
        None,
        [],
    ),
    (
        "list_following_tracks",
        {},
        "GET",
        "/me/followings/tracks",
        {"limit": "50", "offset": "0"},
        None,
        [],
    ),
    (
        "follow_user",
        {"user_id": 743372812},
        "PUT",
        "/me/followings/743372812",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "unfollow_user",
        {"user_id": 743372812},
        "DELETE",
        "/me/followings/743372812",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "create_playlist",
        {"title": "My Playlist", "sharing": "private", "track_ids": [1, 2]},
        "POST",
        "/playlists",
        {},
        {
            "playlist": {
                "title": "My Playlist",
                "sharing": "private",
                "tracks": [{"id": "1"}, {"id": "2"}],
            }
        },
        {"id": 10, "title": "My Playlist"},
    ),
    (
        "update_playlist",
        {"playlist_id": 10, "title": "New", "track_ids": []},
        "PUT",
        "/playlists/10",
        {},
        {"playlist": {"title": "New", "tracks": []}},
        {"id": 10, "title": "New"},
    ),
    (
        "update_track",
        {"track_id": 308946187, "title": "New", "downloadable": False},
        "PUT",
        "/tracks/308946187",
        {},
        {"track": {"title": "New", "downloadable": False}},
        {"id": 308946187, "title": "New"},
    ),
    (
        "delete_track",
        {"track_id": 308946187},
        "DELETE",
        "/tracks/308946187",
        {},
        None,
        None,
    ),
    (
        "like_track",
        {"track_id": 1015448728},
        "POST",
        "/likes/tracks/1015448728",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "unlike_track",
        {"track_id": 1015448728},
        "DELETE",
        "/likes/tracks/1015448728",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "like_playlist",
        {"playlist_id": 10},
        "POST",
        "/likes/playlists/10",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "unlike_playlist",
        {"playlist_id": 10},
        "DELETE",
        "/likes/playlists/10",
        {},
        None,
        {"status": "200 - OK"},
    ),
    (
        "repost_track",
        {"track_id": 1015448728},
        "POST",
        "/reposts/tracks/1015448728",
        {},
        None,
        None,
    ),
    (
        "unrepost_track",
        {"track_id": 1015448728},
        "DELETE",
        "/reposts/tracks/1015448728",
        {},
        None,
        None,
    ),
    (
        "repost_playlist",
        {"playlist_id": 10},
        "POST",
        "/reposts/playlists/10",
        {},
        None,
        None,
    ),
    (
        "unrepost_playlist",
        {"playlist_id": 10},
        "DELETE",
        "/reposts/playlists/10",
        {},
        None,
        None,
    ),
]


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        return replies.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        sc,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-soundcloud",
        operation=operation,
        arguments=config or {},
        credential_data=deepcopy(auth),
        user_id="test-user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,response", CASES)
async def test_soundcloud_wire(
    wire, operation, config, method, path, query, body, response
):
    requests, replies = wire
    replies.append(
        httpx.Response(
            201 if operation.startswith(("create_", "repost_")) else 200,
            **({"json": response} if response is not None else {})
        )
    )
    result = await run(operation, config)
    assert result["data"] == response
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert req.url.host == "api.soundcloud.com" and req.url.scheme == "https"
    assert req.url.path == path
    assert dict(req.url.params) == query
    assert req.headers["Authorization"] == "OAuth " + AUTH["access_token"]
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../1", "1/x", "https://evil.test", 0, -1])
async def test_soundcloud_invalid_id_never_sends(wire, bad):
    with pytest.raises(ValueError):
        await run("like_track", {"track_id": bad})
    assert not wire[0]


@pytest.mark.asyncio
async def test_soundcloud_error_redaction_and_no_write_retry(wire):
    requests, replies = wire
    replies.append(httpx.Response(429, json={"error": AUTH["access_token"]}))
    with pytest.raises(ValueError) as exc:
        await run("like_track", {"track_id": 1})
    assert AUTH["access_token"] not in str(exc.value)
    assert "429" in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"errors": ["rejected"]}),
        httpx.Response(200, text="<html>bad</html>"),
        httpx.Response(200, json={"wrong": []}),
    ],
)
async def test_soundcloud_bad_responses_not_success(wire, response):
    wire[1].append(response)
    with pytest.raises(ValueError):
        await run("list_my_tracks")


def test_soundcloud_credential_default_and_foreign_family():
    assert (
        sc.SoundcloudOAuthCredential(access_token="test-token").credential_type
        == "soundcloud_oauth"
    )
    for token in ["https://example.com", "Bearer bad", "bad\ntoken"]:
        with pytest.raises(ValueError):
            sc.SoundcloudOAuthCredential(access_token=token)
    assert not sc.SoundcloudNode.validate_config(
        {
            "config": {"operation": "get_current_user"},
            "credentials": {"credential_type": "other", "access_token": "test"},
        }
    )["valid"]


@pytest.mark.asyncio
async def test_soundcloud_oauth_exchange_identity_and_refresh(monkeypatch):
    requests = []

    async def send(req):
        requests.append(req)
        if req.url.path == "/me":
            assert req.headers["Authorization"] == "OAuth access-one"
            return httpx.Response(200, json={"id": 1, "username": "Artist"})
        return httpx.Response(
            200,
            json={
                "access_token": "access-one",
                "refresh_token": "refresh-two",
                "expires_in": 3600,
                "scope": "",
            },
        )

    @asynccontextmanager
    async def client(self, url):
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as c:
            yield c

    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", client)
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "test-client")
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("SOUNDCLOUD_REDIRECT_URI", raising=False)
    tokens, name = await OAUTH_PROVIDER.exchange(
        "code", "https://example.com/callback", "v" * 43
    )
    assert name == "Artist" and tokens.refresh_token == "refresh-two"
    req = requests[0]
    assert str(req.url) == "https://secure.soundcloud.com/oauth/token"
    body = parse_qs(req.content.decode())
    assert body["code_verifier"] == ["v" * 43]
    assert body["client_secret"] == ["test-secret"]
    assert body["grant_type"] == ["authorization_code"]
    await OAUTH_PROVIDER.refresh("refresh-one")
    assert parse_qs(requests[-1].content.decode())["refresh_token"] == ["refresh-one"]


@pytest.mark.asyncio
async def test_soundcloud_missing_rotated_refresh_rejected(monkeypatch):
    @asynccontextmanager
    async def client(self, url):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, json={"access_token": "test-token", "expires_in": 3600}
                )
            )
        ) as c:
            yield c

    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", client)
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "test-client")
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_SECRET", "test-secret")
    with pytest.raises(ValueError, match="refresh_token"):
        await OAUTH_PROVIDER.refresh("refresh-one")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,example",
    [
        ("list_my_tracks", "Tracks"),
        ("list_my_liked_tracks", "Tracks"),
        ("list_my_followers", "Users"),
        ("list_my_followings", "Users"),
    ],
)
async def test_soundcloud_invalid_published_singleton_collection(
    wire, operation, example
):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/soundcloud/documented_responses.json"
        ).read_text()
    )
    body = fixture["responses"][example]
    wire[1].append(httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="no collection"):
        await run(operation)

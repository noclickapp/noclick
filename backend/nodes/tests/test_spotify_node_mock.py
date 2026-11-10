"""Spotify request semantics and poll behavior using documented and synthetic fixtures."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import spotify_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.spotify_oauth import OAUTH_PROVIDER


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


TOKEN = "spotify-test-token-42"
PLAYLIST = "3cEYpjA9oz9GiPac4AsH4n"
TRACK_URI = "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"


def node(config, **credential):
    return NodeFactory.create_node(node_id="spotify-test", node_type="automation-spotify", node_data={
        "config": config, "credentials": {"access_token": TOKEN, **credential}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    factory = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return factory(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


# Exact public routes and methods, including the current /items and /me/library APIs.
CASES = [
    ({"operation": "get_profile"}, "GET", "/me", {}, None),
    ({"operation": "search", "q": "abacab", "type": "album,track"}, "GET", "/search", {"q": "abacab", "type": "album,track", "limit": "5", "offset": "0"}, None),
    ({"operation": "get_track", "track_id": "11dFghVXANMlKmJXsNCbNl"}, "GET", "/tracks/11dFghVXANMlKmJXsNCbNl", {}, None),
    ({"operation": "get_artist", "artist_id": "0TnOYISbd1XYRBk9myaseg"}, "GET", "/artists/0TnOYISbd1XYRBk9myaseg", {}, None),
    ({"operation": "list_playlists"}, "GET", "/me/playlists", {"limit": "20", "offset": "0"}, None),
    ({"operation": "get_playlist", "playlist_id": PLAYLIST}, "GET", "/playlists/" + PLAYLIST, {}, None),
    ({"operation": "list_playlist_items", "playlist_id": PLAYLIST}, "GET", "/playlists/" + PLAYLIST + "/items", {"limit": "20", "offset": "0"}, None),
    ({"operation": "create_playlist", "name": "New Playlist", "public": False}, "POST", "/me/playlists", {}, {"name": "New Playlist", "public": False}),
    ({"operation": "update_playlist", "playlist_id": PLAYLIST, "description": "Updated playlist description"}, "PUT", "/playlists/" + PLAYLIST, {}, {"description": "Updated playlist description"}),
    ({"operation": "add_playlist_items", "playlist_id": PLAYLIST, "uris": TRACK_URI, "position": 0}, "POST", "/playlists/" + PLAYLIST + "/items", {}, {"uris": [TRACK_URI], "position": 0}),
    ({"operation": "replace_playlist_items", "playlist_id": PLAYLIST, "uris": TRACK_URI}, "PUT", "/playlists/" + PLAYLIST + "/items", {}, {"uris": [TRACK_URI]}),
    ({"operation": "remove_playlist_items", "playlist_id": PLAYLIST, "uris": TRACK_URI, "snapshot_id": "snapshot"}, "DELETE", "/playlists/" + PLAYLIST + "/items", {}, {"items": [{"uri": TRACK_URI}], "snapshot_id": "snapshot"}),
    ({"operation": "list_saved_tracks"}, "GET", "/me/tracks", {"limit": "20", "offset": "0"}, None),
    *[({"operation": action, "uris": TRACK_URI}, method, path, {"uris": TRACK_URI}, None)
      for action, method, path in [("save_library_items", "PUT", "/me/library"), ("remove_library_items", "DELETE", "/me/library"), ("check_library_items", "GET", "/me/library/contains")]],
    ({"operation": "get_recently_played", "after": 1484811043508}, "GET", "/me/player/recently-played", {"limit": "20", "after": "1484811043508"}, None),
    ({"operation": "get_playback"}, "GET", "/me/player", {}, None),
    ({"operation": "list_devices"}, "GET", "/me/player/devices", {}, None),
    ({"operation": "start_playback", "uris": TRACK_URI, "position_ms": 0}, "PUT", "/me/player/play", {}, {"uris": [TRACK_URI], "position_ms": 0}),
    ({"operation": "pause_playback", "device_id": "device123"}, "PUT", "/me/player/pause", {"device_id": "device123"}, None),
    ({"operation": "skip_next"}, "POST", "/me/player/next", {}, None),
    ({"operation": "add_to_queue", "uri": TRACK_URI}, "POST", "/me/player/queue", {"uri": TRACK_URI}, None),
    ({"operation": "get_queue"}, "GET", "/me/player/queue", {}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[x[0]["operation"] for x in CASES])
async def test_exact_request(monkeypatch, config, method, path, query, body):
    requests = transport(monkeypatch, {"snapshot_id": "provider-snapshot"})
    output = await node(config).execute({})
    assert output["data"] == {"snapshot_id": "provider-snapshot"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.spotify.com"
    assert request.url.path == "/v1" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_playback", "pause_playback", "skip_next"])
async def test_empty_response(monkeypatch, operation):
    transport(monkeypatch, status=204)
    assert (await node({"operation": operation}).execute({}))["data"] is None


@pytest.mark.asyncio
async def test_error_redaction_no_write_retry(monkeypatch):
    requests = transport(monkeypatch, {"error": {"status": 403, "message": "Premium required " + TOKEN}}, 403)
    with pytest.raises(ValueError, match="Spotify API 403: Premium required") as exc:
        await node({"operation": "pause_playback"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_track", "track_id": "../../me"},
    {"operation": "add_to_queue", "uri": "https://example.com/track"},
    {"operation": "save_library_items", "uris": ",".join([TRACK_URI] * 41)},
    {"operation": "save_library_items", "uris": "spotify:artist:abc"},
    {"operation": "start_playback", "uris": TRACK_URI, "context_uri": "spotify:album:abc"},
    {"operation": "get_recently_played", "before": 10, "after": 1},
    {"operation": "create_playlist", "name": "New Playlist", "public": True, "collaborative": True},
    {"operation": "search", "q": "abacab", "type": "invalid"},
    {"operation": "search", "q": "abacab", "type": "track", "limit": 11},
    {"operation": "update_playlist", "playlist_id": PLAYLIST},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_connect_shape_and_oauth_contract():
    credential = native.SpotifyOAuthCredential(access_token=TOKEN)
    assert credential.credential_type == "spotify_oauth"
    assert OAUTH_PROVIDER.identity_url == "https://api.spotify.com/v1/me"
    assert OAUTH_PROVIDER.name_field == "account_id"
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.rotates_refresh_tokens is False
    assert set(native.SPOTIFY_SCOPES) == set(native.OPERATIONS) | {"on_track_played"}


@pytest.mark.asyncio
async def test_refresh_uses_choke_points(monkeypatch):
    freshen = AsyncMock(return_value={"access_token": "new-token"})
    monkeypatch.setattr(native, "freshen_oauth_credential", freshen)
    await native.SpotifyNode.freshen_credential({"access_token": TOKEN, "refresh_token": "refresh-test"}, credential_id="credential")
    assert freshen.call_args.kwargs["provider"] == "spotify"
    ensure = AsyncMock(return_value="new-token")
    monkeypatch.setattr(native, "ensure_fresh_oauth_token", ensure)
    n = node({"operation": "get_profile"}, refresh_token="refresh-test")
    assert await n._access_token() == "new-token"
    assert ensure.call_args.kwargs["caller_path"] == "execute"


@pytest.mark.asyncio
async def test_playlist_picker_paging(monkeypatch):
    requests = transport(monkeypatch, {"items": [{"id": PLAYLIST, "name": "Road trip"}], "next": "https://untrusted.invalid/page"})
    result = await native.SpotifyNode.load_field_options("playlist_id", {"access_token": TOKEN}, page_token="50", search="road")
    assert result == {"options": [{"value": PLAYLIST, "label": "Road trip"}], "next_page_token": "51"}
    assert dict(requests[0].url.params) == {"limit": "50", "offset": "50"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_documented_poll_payload_agent_event_and_dedup(monkeypatch):
    documented = json.loads((Path(__file__).parent / "fixtures/spotify/recently_played.json").read_text())
    transport(monkeypatch, documented)
    n = node({"operation": "on_track_played"})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(n, "_update_node_state", update)
    assert (await n.execute({}))["play_count"] == 0  # baseline
    assert (await n.execute({}))["play_count"] == 0  # duplicate
    state["seen_ids"] = []  # simulate a prior poll with no items
    output = await n.execute({})
    assert output["plays"] == documented["items"]
    assert output["play_count"] == 1
    event = n.resolve_agent_event(output)
    assert "You played" in event["text"]
    assert documented["items"][0]["track"]["id"] in event["text"]
    assert n.should_propagate_output(output, {"operation": "on_track_played"})
    assert (await n.execute({}))["play_count"] == 0
    assert n.resolve_agent_event({"plays": []}) is None


@pytest.mark.asyncio
async def test_oauth_identity_uses_documented_immutable_account_id(monkeypatch):
    from nodes.core.oauth_provider import OAuthProviderSpec
    profile = json.loads((Path(__file__).parent / "fixtures/spotify/profile.json").read_text())
    requests = []
    factory = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=profile)
    monkeypatch.setattr(OAuthProviderSpec, "_client", lambda self, template: factory(transport=httpx.MockTransport(respond)))
    assert await OAUTH_PROVIDER.account_name(TOKEN) == profile["account_id"]
    assert requests[0].url == "https://api.spotify.com/v1/me"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN

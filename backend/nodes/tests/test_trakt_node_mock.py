"""Independent Trakt wire tests; synthetic responses follow the published v2 schemas."""
from copy import deepcopy
from unittest.mock import AsyncMock
import json
import httpx
import pytest
from nodes import trakt_node as tr
from nodes.core.run_op import run_node_operation
from nodes.core.registry import NodeFactory
from nodes.oauth.trakt_oauth import OAUTH_PROVIDER
from utils import ssrf

AUTH = {
    "credential_type": "trakt_oauth",
    "access_token": "trakt-test-access",
    "client_id": "trakt-test-app",
}
PAGE = {"page": "1", "limit": "100"}
CASES = [
    ("get_settings", {}, "GET", "/users/settings", {}, None),
    ("get_last_activities", {}, "GET", "/sync/last_activities", {}, None),
    (
        "search",
        {"query": "tron"},
        "GET",
        "/search/movie",
        {**PAGE, "query": "tron"},
        None,
    ),
    (
        "get_movie",
        {"id": "tron-legacy-2010"},
        "GET",
        "/movies/tron-legacy-2010",
        {},
        None,
    ),
    ("get_show", {"id": "game-of-thrones"}, "GET", "/shows/game-of-thrones", {}, None),
    ("list_trending_movies", {}, "GET", "/movies/trending", PAGE, None),
    (
        "list_movie_history",
        {"start_at": "2024-01-01T00:00:00Z"},
        "GET",
        "/users/me/history/movies",
        {**PAGE, "start_at": "2024-01-01T00:00:00Z"},
        None,
    ),
    ("list_episode_history", {}, "GET", "/users/me/history/episodes", PAGE, None),
    ("list_watchlist", {}, "GET", "/sync/watchlist/movies/added/desc", PAGE, None),
    (
        "add_to_watchlist",
        {"item_id": 1},
        "POST",
        "/sync/watchlist",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "remove_from_watchlist",
        {"item_id": 1},
        "POST",
        "/sync/watchlist/remove",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "add_to_history",
        {"item_id": 1, "watched_at": "2024-01-01T00:00:00Z"},
        "POST",
        "/sync/history",
        {},
        {"movies": [{"ids": {"trakt": 1}, "watched_at": "2024-01-01T00:00:00Z"}]},
    ),
    (
        "remove_from_history",
        {"item_id": 1},
        "POST",
        "/sync/history/remove",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "rate_item",
        {"item_id": 1, "rating": 9},
        "POST",
        "/sync/ratings",
        {},
        {"movies": [{"ids": {"trakt": 1}, "rating": 9}]},
    ),
    (
        "remove_rating",
        {"item_id": 1},
        "POST",
        "/sync/ratings/remove",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "add_to_collection",
        {"item_id": 1},
        "POST",
        "/sync/collection",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "remove_from_collection",
        {"item_id": 1},
        "POST",
        "/sync/collection/remove",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    ("list_collection", {}, "GET", "/sync/collection/movies", PAGE, None),
    ("list_lists", {}, "GET", "/users/me/lists", PAGE, None),
    (
        "create_list",
        {"name": "Weekend"},
        "POST",
        "/users/me/lists",
        {},
        {"name": "Weekend", "privacy": "private"},
    ),
    (
        "add_list_item",
        {"item_id": 1, "list_id": "weekend"},
        "POST",
        "/users/me/lists/weekend/items",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
    ),
    (
        "remove_list_item",
        {"item_id": 1, "list_id": "weekend"},
        "POST",
        "/users/me/lists/weekend/items/remove",
        {},
        {"movies": [{"ids": {"trakt": 1}}]},
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
        tr,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-trakt",
        operation=operation,
        arguments=config or {},
        credential_data=deepcopy(auth),
        user_id="test-user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body", CASES)
async def test_trakt_wire(wire, operation, config, method, path, query, body):
    reply = (
        []
        if operation.startswith("list_") or operation == "search"
        else {"not_found": {"movies": []}}
    )
    wire[1].append(httpx.Response(200, json=reply))
    assert (await run(operation, config))["data"] == reply
    assert len(wire[0]) == 1
    req = wire[0][0]
    assert (
        req.method == method and req.url.host == "api.trakt.tv" and req.url.path == path
    )
    assert dict(req.url.params) == query
    assert (
        req.headers["trakt-api-key"] == AUTH["client_id"]
        and req.headers["trakt-api-version"] == "2"
    )
    assert req.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert req.headers["Content-Type"] == "application/json"
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
async def test_trakt_pagination_and_error_redaction(wire):
    wire[1].append(
        httpx.Response(200, json=[], headers={"X-Pagination-Page-Count": "3"})
    )
    assert (await run("list_movie_history"))["next_page"] == 2
    wire[1].append(httpx.Response(429, json={"error": AUTH["access_token"]}))
    with pytest.raises(ValueError) as exc:
        await run("add_to_watchlist", {"item_id": 1})
    assert "429" in str(exc.value) and AUTH["access_token"] not in str(exc.value)
    assert len(wire[0]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config",
    [
        ("rate_item", {"item_id": 1, "rating": 11}),
        ("add_to_history", {"item_id": -1}),
        ("list_movie_history", {"start_at": "yesterday"}),
    ],
)
async def test_trakt_invalid_input_no_network(wire, operation, config):
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not wire[0]


@pytest.mark.parametrize(
    "bad", ["https://example.com/token", "Bearer xyz", "bad\ntoken"]
)
def test_trakt_manual_credential(bad):
    assert (
        tr.TraktOAuthCredential(access_token="test-value").credential_type
        == "trakt_oauth"
    )
    with pytest.raises(ValueError):
        tr.TraktOAuthCredential(access_token=bad)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,path",
    [
        ("on_movie_watched", "/users/me/history/movies"),
        ("on_episode_watched", "/users/me/history/episodes"),
        ("on_watchlist_item_added", "/sync/watchlist/movies/added/desc"),
    ],
)
async def test_trakt_poll_baseline_new_and_duplicate(wire, operation, path):
    node = NodeFactory.create_node(
        node_id="trakt-poll",
        node_type="automation-trakt",
        node_data={"config": {"operation": operation}, "credentials": deepcopy(AUTH)},
        user_id="test-user",
    )
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(deepcopy(state))
        if new is not None:
            state = new
        return result

    node._update_node_state = update
    row = (
        {
            "id": 11,
            "type": "movie",
            "watched_at": "2024-01-01T00:00:00Z",
            "action": "watch",
        }
        if operation != "on_watchlist_item_added"
        else {"id": 11, "rank": 1, "listed_at": "2024-01-01T00:00:00Z", "type": "movie"}
    )
    for batch in [[row], [row, {**row, "id": 12}], [row, {**row, "id": 12}]]:
        wire[1].append(httpx.Response(200, json=batch))
    assert (await node.execute({}))["event_count"] == 0
    output = await node.execute({})
    assert [x["id"] for x in output["events"]] == [12]
    assert node.trigger_emitted_event(output)
    event = tr.TraktNode.resolve_agent_event(output)
    assert "Trakt" in event["text"] and "12" in event["text"]
    assert (await node.execute({}))["event_count"] == 0
    assert all(req.url.path == path for req in wire[0])


@pytest.mark.asyncio
async def test_trakt_identity_headers_pkce_refresh(monkeypatch):
    monkeypatch.setenv("TRAKT_CLIENT_ID", "test-app")
    monkeypatch.setenv(
        "TRAKT_REDIRECT_URI", "https://noclick.com/api/auth/oauth/trakt/callback"
    )
    requests = []

    async def send(req):
        requests.append(req)
        return httpx.Response(200, json={"user": {"username": "movie-fan"}})

    monkeypatch.setattr(
        type(OAUTH_PROVIDER),
        "_client",
        lambda *a: httpx.AsyncClient(transport=httpx.MockTransport(send)),
    )
    assert await OAUTH_PROVIDER.account_name("test-access") == "movie-fan"
    assert (
        requests[0].headers["trakt-api-key"] == "test-app"
        and requests[0].headers["trakt-api-version"] == "2"
    )
    req = OAUTH_PROVIDER.token_request(
        {
            "grant_type": "authorization_code",
            "code": "test-code",
            "code_verifier": "v" * 43,
        }
    )
    assert req["url"] == "https://auth.trakt.tv/oauth/token"
    assert (
        "client_secret" not in req["json"] and req["json"]["code_verifier"] == "v" * 43
    )
    req = OAUTH_PROVIDER.token_request(
        {"grant_type": "refresh_token", "refresh_token": "test-refresh"}
    )
    assert (
        req["json"]["redirect_uri"]
        == "https://noclick.com/api/auth/oauth/trakt/callback"
    )
    assert OAUTH_PROVIDER.rotates_refresh_tokens and OAUTH_PROVIDER.pkce

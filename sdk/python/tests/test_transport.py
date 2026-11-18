import json
import pickle

import httpx
import pytest

import noclick as nc
from noclick.exceptions import error_from_payload
from platform_helpers import USER_ID, body, listing, user_row


def test_auth_and_user_agent_headers(api, client):
    route = api.get("/v1/users").respond(json=listing())
    nc.User.list()
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer nk_live_test"
    assert request.headers["User-Agent"].startswith("noclick-python/")
    assert "Idempotency-Key" not in request.headers  # reads carry none


def test_missing_api_key_is_unauthenticated(api, monkeypatch):
    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    monkeypatch.delenv("NOCLICK_DEPLOYMENT_TOKEN", raising=False)
    with pytest.raises(nc.Unauthenticated) as info:
        nc.User.list(client=nc.Client(base_url="https://api.test"))
    # A deployed app is told it needs no key at all.
    assert info.value.next_step.startswith("Set NOCLICK_API_KEY or pass noclick.Client(api_key=...).")
    assert info.value.next_step.endswith("A deployed app needs neither: the client signs in with the credential "
                                         "NoClick puts in its environment, NOCLICK_DEPLOYMENT_TOKEN.")
    with pytest.raises(nc.Unauthenticated, match="runs inside a deployed app") as info:
        nc.Project.current()
    assert info.value.next_step.startswith("Outside a deployment")


def test_inside_a_deployed_app_the_whole_client_acts_as_the_app(api, monkeypatch):
    """NoClick puts the deployment's credential in its environment: the module-level calls (AI, Connection,
    Channel, ...) and Project.current() sign in with it, through one client."""
    from noclick import _client as client_module

    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    monkeypatch.setenv("NOCLICK_DEPLOYMENT_TOKEN", "nk_dep_123")
    monkeypatch.setattr(client_module, "_default", None)
    done = {"id": "gen_1", "choices": [{"index": 0, "delta": {"content": "Hi."}, "finish_reason": "stop"}]}
    chat = api.post("/v1/ai/chat/completions").respond(
        headers={"content-type": "text/event-stream"}, content=f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
    app = nc.configure(base_url="https://api.test")
    assert nc.AI.chat("Say hi").text == "Hi."
    assert chat.calls.last.request.headers["Authorization"] == "Bearer nk_dep_123"
    assert nc.Project.current()._client is app
    # A key set beside it is what the module-level calls use; the app itself still acts as the app.
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_env")
    keyed = nc.configure(base_url="https://api.test")
    current = nc.Project.current()._client
    assert keyed.api_key == "nk_live_env" and current is not keyed and current.in_app


def test_env_configuration(monkeypatch):
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_env")
    monkeypatch.setenv("NOCLICK_API_URL", "https://example.test/")
    c = nc.Client()
    assert c.api_key == "nk_live_env" and c.base_url == "https://example.test"
    monkeypatch.delenv("NOCLICK_API_URL")
    assert nc.Client().base_url == "https://api.noclick.com"


def test_write_retries_reuse_one_idempotency_key(api, client):
    route = api.post("/v1/users").mock(side_effect=[
        httpx.Response(503, json={"error": {"type": "server_error", "message": "busy"}}),
        httpx.Response(502, text="bad gateway"),
        httpx.Response(200, json=user_row()),
    ])
    user = nc.User.create("user_42")
    assert user.id == USER_ID
    keys = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert route.call_count == 3 and len(keys) == 1
    assert keys.pop().startswith("nc_")
    # a second write gets a fresh key
    api.post("/v1/users").respond(json=user_row())
    nc.User.create("user_43")
    assert route.calls.last.request.headers["Idempotency-Key"] not in keys


def test_explicit_idempotency_key_is_sent(api, client):
    route = api.post("/v1/users").respond(json=user_row())
    nc.User.create("user_42", idempotency_key="signup-42")
    assert route.calls.last.request.headers["Idempotency-Key"] == "signup-42"


def test_retry_after_is_respected(api, client):
    api.get("/v1/users").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"type": "rate_limited", "message": "slow"}}),
        httpx.Response(200, json=listing()),
    ])
    assert nc.User.list() == []
    assert client.sleeps == [7.0]


def test_rate_limit_exhausted_raises_rate_limited(api, client):
    api.get("/v1/users").respond(
        429, headers={"Retry-After": "2"}, json={"error": {"type": "rate_limited", "message": "slow down"}}
    )
    with pytest.raises(nc.RateLimited) as info:
        nc.User.list()
    assert info.value.retry_after == 2.0
    assert len(client.sleeps) == client.max_retries


def test_connection_errors_retry_then_succeed(api, client):
    route = api.post("/v1/users").mock(side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json=user_row())])
    nc.User.create("user_42")
    assert route.call_count == 2
    assert len({c.request.headers["Idempotency-Key"] for c in route.calls}) == 1
    assert len(client.sleeps) == 1 and 0 < client.sleeps[0] <= client.backoff


def test_connection_errors_exhausted(api, client):
    api.get("/v1/users").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(nc.APIConnectionError):
        nc.User.list()


def test_a_posts_500_is_not_retried_but_a_reads_is(api, client):
    # The server replays a POST's stored 500 for its Idempotency-Key, so a retry can't help.
    unknown = {"error": {"type": "internal_error", "message": "some of its work may have happened"}}
    write = api.post("/v1/users").respond(500, json=unknown)
    with pytest.raises(nc.Error) as info:
        nc.User.create("user_42")
    assert info.value.status == 500 and write.call_count == 1 and client.sleeps == []
    read = api.get("/v1/users").mock(side_effect=[
        httpx.Response(500, json=unknown), httpx.Response(200, json={"object": "list", "data": [], "next_cursor": None}),
    ])
    assert nc.User.list() == []
    assert read.call_count == 2


def test_cloudflares_52x_are_retried_a_write_with_its_one_key(api, client):
    # Cloudflare's own answers when it couldn't get the API's (an unknown error, the origin down or timing out).
    route = api.post("/v1/users").mock(side_effect=[
        httpx.Response(520), httpx.Response(524, text="error code: 524"), httpx.Response(200, json=user_row()),
    ])
    nc.User.create("user_42")
    assert route.call_count == 3 and len({c.request.headers["Idempotency-Key"] for c in route.calls}) == 1


def test_an_error_the_api_never_answered_names_its_request_at_the_edge(api, client):
    api.get("/v1/users").respond(520, headers={"cf-ray": "8f0a11bb22cc33dd-IAD"})
    with pytest.raises(nc.ServerError) as info:
        nc.User.list()
    err = info.value
    assert (err.status, err.request_id, err.cf_ray) == (520, "8f0a11bb22cc33dd-IAD", "8f0a11bb22cc33dd-IAD")
    assert err.message == "HTTP 520 from GET /v1/users (request 8f0a11bb22cc33dd-IAD)"
    assert len(client.sleeps) == client.max_retries
    # The API's own id stays the request's, and the edge's is beside it.
    api.post("/v1/users").respond(400, headers={"x-request-id": "req_1", "cf-ray": "8f0a11bb22cc33ee-IAD"},
                                  json={"error": {"type": "invalid_request", "message": "bad"}})
    with pytest.raises(nc.InvalidRequest) as info:
        nc.User.create("user_42")
    assert (info.value.request_id, info.value.cf_ray, info.value.message) == ("req_1", "8f0a11bb22cc33ee-IAD", "bad")


def test_a_replayed_answer_is_not_retried_and_an_error_says_how_often_the_call_was_sent(api, client):
    # The server kept the first answer because the write may have happened there: sending it again gets it again.
    unknown = {"error": {"type": "upstream_error", "message": "The database is unavailable right now (NoClick tried "
                         "3 times), and NoClick can't tell whether the call took effect.", "upstream_attempts": 3}}
    route = api.post("/v1/users").mock(side_effect=[
        httpx.Response(503, json=unknown), httpx.Response(503, json=unknown, headers={"Idempotent-Replayed": "true"}),
    ])
    with pytest.raises(nc.UpstreamError) as info:
        nc.User.create("user_42")
    err = info.value
    assert route.call_count == 2 and (err.attempts, err.upstream_attempts, err.applied) == (2, 3, None)
    api.get("/v1/users").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(nc.APIConnectionError) as unreached:
        nc.User.list()
    assert unreached.value.attempts == client.max_retries + 1


def test_an_upstream_error_says_whether_the_call_took_effect():
    nothing = error_from_payload({"error": {"type": "upstream_error", "message": "m", "applied": False}})
    assert nothing.applied is False and nothing.upstream_attempts is None and nothing.attempts is None
    assert error_from_payload({"error": {"type": "upstream_error", "message": "m"}}).applied is None
    nothing.attempts = 2
    restored = pickle.loads(pickle.dumps(nothing))
    assert (restored.applied, restored.attempts) == (False, 2)


def test_client_errors_are_not_retried(api, client):
    route = api.post("/v1/users").respond(400, json={"error": {"type": "invalid_request", "message": "bad"}})
    with pytest.raises(nc.InvalidRequest):
        nc.User.create("user_42")
    assert route.call_count == 1


def test_explicit_client_is_used(api):
    other = nc.Client(api_key="nk_live_other", base_url="https://api.test")
    route = api.get("/v1/users").respond(json=listing())
    nc.User.list(client=other)
    assert route.calls.last.request.headers["Authorization"] == "Bearer nk_live_other"


def test_pagination_follows_next_cursor(api, client):
    route = api.get("/v1/users").mock(side_effect=[
        httpx.Response(200, json=listing(user_row("a"), next_cursor="c2")),
        httpx.Response(200, json=listing(user_row("b"))),
    ])
    users = nc.User.list()
    assert [u.id for u in users] == ["a", "b"]
    assert route.calls[1].request.url.params["cursor"] == "c2"


def test_json_body_is_sent(api, client):
    route = api.post("/v1/users").respond(json=user_row())
    nc.User.create("user_42", email="ana@example.com")
    assert body(route.calls.last.request) == {"id": "user_42", "email": "ana@example.com"}

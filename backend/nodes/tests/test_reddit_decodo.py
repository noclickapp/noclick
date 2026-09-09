"""Native response contract and real node orchestration over an HTTP transport."""

import asyncio
import copy
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from nodes.core import decodo_client
from nodes.core.decodo_client import DecodoError, DecodoJsonClient
from nodes.core.reddit_scraper import attach_comments, build_reddit_input, normalize_reddit_result
from nodes.reddit_node import RedditGetSubredditPostsConfig, RedditNode, RedditNodeConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures/reddit_native.json").read_text())


def normalize(value=None, **kw):
    return normalize_reddit_result(
        copy.deepcopy(FIXTURE["feed"] if value is None else value), subreddit="Example",
        sort=kw.get("sort", "new"), period=None, limit=kw.get("limit", 25),
        comments_limit=kw.get("comments", 0),
    )


def envelope(data, status=200):
    return {"results": [{"status_code": status, "content": json.dumps(data), "task_id": "test-task"}]}


@pytest.mark.parametrize("sort", ["", "hot", "new", "top", "rising", "controversial"])
@pytest.mark.parametrize("period", ["hour", "day", "week", "month", "year", "all"])
def test_sort_and_time_request_native_json(sort, period):
    config = RedditGetSubredditPostsConfig(subreddit="r/Example/", sort=sort, time=period)
    url, sub, actual_sort, actual_period, limit, comments = build_reddit_input(config)
    parsed = urlsplit(url)
    assert parsed.netloc == "www.reddit.com"
    assert parsed.path == f'/r/Example/{sort or "hot"}.json'
    params = parse_qs(parsed.query)
    assert params == {"raw_json": ["1"], "sr_detail": ["1"], "limit": ["25"],
                      **({"t": [period]} if sort in {"top", "controversial"} else {})}
    assert sub == "Example" and actual_sort == (sort or "hot")
    assert actual_period == (period if sort in {"top", "controversial"} else None)
    assert limit == 25 and comments == 0


@pytest.mark.parametrize("old_mode", ["fast", "rich", None])
@pytest.mark.parametrize("old_proxy", ["auto", "always", "never", None])
def test_saved_legacy_options_do_not_change_the_native_reader(old_mode, old_proxy):
    cfg = RedditGetSubredditPostsConfig(subreddit="Example", content_mode=old_mode, use_proxy=old_proxy)
    assert build_reddit_input(cfg)[0].endswith("?raw_json=1&limit=25&sr_detail=1")
    assert "content_mode" not in cfg.model_json_schema()["properties"]
    assert "use_proxy" not in cfg.model_json_schema()["properties"]


@pytest.mark.parametrize("name", ["https://reddit.com/r/python", "python/../other", "python?sort=top", "python+news", ""])
def test_invalid_subreddit_fails_before_retrieval(name):
    with pytest.raises(ValueError):
        build_reddit_input(RedditGetSubredditPostsConfig(subreddit=name))


def test_post_and_comment_caps_are_independent():
    request = build_reddit_input(RedditGetSubredditPostsConfig(
        subreddit="Example", limit=200, fetch_comments="true", max_comments=20,
    ))
    assert request[-2:] == (100, 20)
    assert parse_qs(urlsplit(request[0]).query)["limit"] == ["100"]


def test_native_text_html_timestamps_counts_and_embedded_metadata():
    p = normalize()["posts"][0]
    raw = FIXTURE["feed"]["data"]["children"][0]["data"]
    assert p["body"] == raw["selftext"] and p["content_html"] == raw["selftext_html"]
    assert "literal &amp;" in p["body"]
    assert p["published_at"] == p["updated_at"] == "2023-11-14T22:13:20+00:00"
    assert (p["score"], p["num_comments"], p["tag"]) == (4, 9, "Discussion")
    assert p["community_description"] == raw["sr_detail"]["description"]
    assert p["community_members_num"] == 1234 and p["related_posts"] is None
    assert "comments" not in p


def test_full_long_text_and_nested_comment_sample_preserve_total():
    data = copy.deepcopy(FIXTURE["feed"])
    long_text = "Markdown **text**, literal &amp;, emoji 😀.\n\n" * 1000
    data["data"]["children"][0]["data"].update(selftext=long_text, selftext_html="<p>" + long_text + "</p>")
    p = normalize(data)["posts"][0]
    assert p["body"] == long_text and len(p["body"]) > 35000
    thread = copy.deepcopy(FIXTURE["thread"])
    reply = thread[1]["data"]["children"][0]["data"]["replies"]["data"]["children"][0]["data"]
    reply["body"] = "Long comment\n" * 300
    attach_comments(p, thread, 10)
    assert p["comments"][0]["replies"][0]["body"] == reply["body"]
    assert p["comment_count"] == 2 and p["num_comments"] == 9
    assert p["comments_are_sampled"] is True and p["comments"][0]["reply_count"] is None
    assert p["comment_coverage"]["deferred_comment_ids"] == 2


def test_comment_limit_counts_nested_replies_and_distinguishes_empty_samples():
    p = normalize()["posts"][0]
    attach_comments(p, FIXTURE["thread"], 1)
    assert p["comment_count"] == 1 and p["comments"][0]["replies"] == []
    empty = copy.deepcopy(FIXTURE["thread"])
    empty[1]["data"]["children"] = []
    attach_comments(p, empty, 5)
    assert p["comment_count"] == 0 and p["num_comments"] == 9


def test_gallery_order_video_metadata_and_empty_media_body():
    posts = normalize()["posts"]
    assert posts[1]["photos"] == ["https://example.org/2.jpg", "https://example.org/1.jpg?x=1&y=2"]
    assert posts[1]["body"] == ""
    assert posts[2]["videos"] == ["https://example.org/video.mp4"]
    video = posts[2]["media_assets"][0]["metadata"]["reddit_video"]
    assert video["has_audio"] and video["duration"] == 156 and video["hls_url"].endswith("m3u8")


@pytest.mark.parametrize("field", ["score", "num_comments", "selftext", "selftext_html", "created_utc", "sr_detail"])
def test_missing_required_data_is_never_zero_or_empty_success(field):
    data = copy.deepcopy(FIXTURE["feed"])
    data["data"]["children"][0]["data"].pop(field)
    with pytest.raises(ValueError):
        normalize(data)


def test_overfetch_wrong_subreddit_and_non_listing_fail():
    with pytest.raises(ValueError, match="limit"):
        normalize(limit=2)
    data = copy.deepcopy(FIXTURE["feed"])
    data["data"]["children"][0]["data"]["subreddit"] = "Wrong"
    with pytest.raises(ValueError, match="community"):
        normalize(data)
    with pytest.raises(ValueError, match="listing"):
        normalize({"error": "blocked"})


def test_wrong_comment_thread_or_parent_is_rejected():
    p = normalize()["posts"][0]
    thread = copy.deepcopy(FIXTURE["thread"])
    thread[0]["data"]["children"][0]["data"]["id"] = "different"
    with pytest.raises(ValueError, match="wrong post"):
        attach_comments(p, thread, 10)
    thread = copy.deepcopy(FIXTURE["thread"])
    thread[1]["data"]["children"][0]["data"]["parent_id"] = "t3_other"
    with pytest.raises(ValueError, match="wrong post or parent"):
        attach_comments(p, thread, 10)


def test_empty_listing_and_cursor_are_explicit():
    assert normalize()["coverage"]["next_cursor"] == "t3_abc789"
    data = copy.deepcopy(FIXTURE["feed"])
    data["data"]["children"] = []
    data["data"]["after"] = None
    output = normalize(data)
    assert output["count"] == 0 and output["coverage"]["requested_count_met"] is False


@pytest.fixture
def setup_http(monkeypatch):
    real_client = httpx.AsyncClient
    def install(handler):
        monkeypatch.setattr(decodo_client.httpx, "AsyncClient", lambda **kw: real_client(
            transport=httpx.MockTransport(handler), **kw,
        ))
    return install


@pytest.fixture
def metering(monkeypatch):
    from billing.usage_tracker import usage_tracker
    monkeypatch.setenv("DECODO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("DECODO_REQUEST_COST_USD", "0.001")
    gate, track = AsyncMock(), AsyncMock()
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr(usage_tracker, "track_usage_event", track)
    return gate, track


def node(comments=False):
    n = RedditNode(node_id="reddit-test", node_type="automation-reddit", node_data={},
        config=RedditNodeConfig(config=RedditGetSubredditPostsConfig(
            subreddit="Example", sort="new", limit=3, fetch_comments="true" if comments else "false")),
        sio=None, sid=None, user_id="00000000-0000-0000-0000-000000000001")
    n.emit = AsyncMock()
    return n


async def test_node_needs_one_request_preserves_output_and_meters_requests(setup_http, metering):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url == decodo_client.DECODO_ENDPOINT
        assert request.headers["Authorization"] == "Basic test-token"
        body = json.loads(request.content)
        assert body == {"target": "universal", "proxy_pool": "premium", "geo": "United States",
                       "url": "https://www.reddit.com/r/Example/new.json?raw_json=1&limit=3&sr_detail=1"}
        return httpx.Response(200, json=envelope(FIXTURE["feed"]))
    setup_http(respond)
    n = node()
    output = await n.execute({})
    assert output["count"] == 3 and output["source"] == "decodo"
    assert output["comments_fetched"] is False and output["time_period"] is None
    assert len(calls) == 1 and n.emit.await_count == 1
    gate, track = metering
    gate.assert_awaited_once()
    event = track.await_args.args[0]
    from billing.markup import PLATFORM_MIN_MARKUP
    assert event.total_cost == Decimal("0.001") * PLATFORM_MIN_MARKUP
    assert event.quantity == 1 and event.metadata["raw_cost_usd"] == 0.001
    assert event.metadata["billable_requests"] == 1 and event.metadata["provider"] == "decodo"


async def test_credit_gate_prevents_all_provider_calls(setup_http, metering):
    setup_http(lambda request: pytest.fail("Provider called without credit"))
    metering[0].side_effect = ValueError("insufficient credits")
    with pytest.raises(ValueError, match="credits"):
        await node().execute({})
    metering[1].assert_not_awaited()


async def test_validation_failure_bills_known_provider_cost_without_emitting(setup_http, metering):
    setup_http(lambda request: httpx.Response(200, json=envelope({"not": "a listing"})))
    n = node()
    with pytest.raises(ValueError, match="listing"):
        await n.execute({})
    n.emit.assert_not_awaited()
    assert metering[1].await_args.args[0].metadata["succeeded"] is False
    assert metering[1].await_args.args[0].metadata["raw_cost_usd"] == 0.001


@pytest.mark.parametrize("status", [401, 402, 403, 429])
async def test_account_errors_never_retry_or_bill(setup_http, status):
    setup_http(lambda request: httpx.Response(status, json={"error": "unavailable"}))
    async with DecodoJsonClient("key") as client:
        with pytest.raises(DecodoError):
            await client.fetch_json("https://www.reddit.com/r/Example/new.json")
        assert client.attempts == 1 and client.billable_requests == 0


async def test_http_200_provider_failure_is_not_success_or_billable(setup_http, monkeypatch):
    setup_http(lambda request: httpx.Response(200, json={"status": "failed", "status_code": 613}))
    monkeypatch.setattr(decodo_client.asyncio, "sleep", AsyncMock())
    async with DecodoJsonClient("key") as client:
        with pytest.raises(DecodoError, match="613"):
            await client.fetch_json("https://www.reddit.com/r/Example/new.json")
        assert client.attempts == 2 and client.billable_requests == 0


async def test_malformed_response_retry_is_bounded_and_both_calls_are_metered(setup_http, monkeypatch):
    responses = [httpx.Response(200, content=b'{"results":['), httpx.Response(200, json=envelope(FIXTURE["feed"]))]
    setup_http(lambda request: responses.pop(0))
    monkeypatch.setattr(decodo_client.asyncio, "sleep", AsyncMock())
    async with DecodoJsonClient("key") as client:
        assert await client.fetch_json("https://www.reddit.com/r/Example/new.json") == FIXTURE["feed"]
        assert client.attempts == 2 and client.billable_requests == 2


async def test_null_data_is_not_a_successful_empty_feed(setup_http):
    setup_http(lambda request: httpx.Response(200, json={"results": [{"status_code": 200, "content": None}]}))
    async with DecodoJsonClient("key") as client:
        with pytest.raises(DecodoError, match="no JSON"):
            await client.fetch_json("https://www.reddit.com/r/Example/new.json")
        assert client.attempts == 1 and client.billable_requests == 1


async def test_comment_reads_are_bounded_and_cancelled_before_failure_returns(setup_http, metering):
    active = maximum = finished = 0
    async def respond(request):
        nonlocal active, maximum, finished
        url = json.loads(request.content)["url"]
        if "/comments/" not in url:
            return httpx.Response(200, json=envelope(FIXTURE["feed"]))
        active += 1
        maximum = max(maximum, active)
        try:
            if "/abc123.json" in url:
                await asyncio.sleep(0.01)
                return httpx.Response(403, json={"error": "unavailable"})
            await asyncio.sleep(60)
        finally:
            active -= 1
            finished += 1
    setup_http(respond)
    n = node(comments=True)
    with pytest.raises(DecodoError):
        await n.execute({})
    assert maximum == finished == 3 and active == 0
    assert metering[1].await_args.args[0].metadata["billable_requests"] == 1
    n.emit.assert_not_awaited()


async def test_comments_fetch_once_per_post_and_preserve_feed_fields(setup_http, metering):
    def respond(request):
        url = json.loads(request.content)["url"]
        if "/comments/" not in url:
            return httpx.Response(200, json=envelope(FIXTURE["feed"]))
        pid = urlsplit(url).path.rsplit("/", 1)[-1].removesuffix(".json")
        thread = json.loads(json.dumps(FIXTURE["thread"]).replace("abc123", pid))
        return httpx.Response(200, json=envelope(thread))
    setup_http(respond)
    output = await node(comments=True).execute({})
    assert output["count"] == 3 and output["comments_fetched"] is True
    assert all(p["comment_count"] == 2 and p["num_comments"] == 9 for p in output["posts"])
    assert output["posts"][1]["photos"][0] == "https://example.org/2.jpg"
    event = metering[1].await_args.args[0]
    assert event.quantity == 4 and event.metadata["raw_cost_usd"] == 0.004


async def test_operation_deadline_still_settles_completed_requests(setup_http, metering):
    setup_http(lambda request: httpx.Response(200, json=envelope(FIXTURE["feed"])))
    async def operation(client):
        await client.fetch_json("https://www.reddit.com/r/Example/new.json")
        await asyncio.sleep(60)
    n = node()
    with pytest.raises(TimeoutError):
        await n._run_decodo(operation, action_name="get_subreddit_posts", platform="reddit", timeout=0.01)
    assert metering[1].await_args.args[0].quantity == 1
    n.emit.assert_not_awaited()

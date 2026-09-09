"""Public Reddit contract, replaying the selected actor's real dataset shapes."""

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.reddit_scraper import build_reddit_input, normalize_reddit_result
from nodes.reddit_node import RedditGetSubredditPostsConfig, RedditNode, RedditNodeConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures/reddit_apify.json").read_text())


def normalize(items=None, subreddit="AI_Agents", comments=10, sort="new"):
    community = copy.deepcopy(FIXTURE["community"])
    community[0]["name"] = subreddit
    return normalize_reddit_result(
        copy.deepcopy(FIXTURE["new"] if items is None else items),
        community,
        subreddit=subreddit,
        sort=sort,
        period=None,
        limit=25,
        comments_limit=comments,
    )


@pytest.mark.parametrize("sort", ["", "hot", "new", "top", "rising", "controversial"])
@pytest.mark.parametrize("period", ["hour", "day", "week", "month", "year", "all"])
def test_exact_listing_sort_and_time(sort, period):
    config = RedditGetSubredditPostsConfig(subreddit="r/AI_Agents/", sort=sort, time=period)
    payload, subreddit, actual_sort, actual_period, limit, comments = build_reddit_input(config)
    expected = f'https://www.reddit.com/r/AI_Agents/{sort or "hot"}/'
    if sort in {"top", "controversial"}:
        expected += "?t=" + period
    assert payload["startUrls"] == [{"url": expected}]
    assert actual_sort == (sort or "hot")
    assert actual_period == (period if sort in {"top", "controversial"} else None)
    assert payload["maxPostsCount"] == limit == 25
    assert payload["maxCommentsPerPost"] == comments == 0


@pytest.mark.parametrize("legacy_mode", ["fast", "rich", None])
@pytest.mark.parametrize("legacy_proxy", ["auto", "always", "never", None])
def test_old_saved_configuration_uses_complete_apify_records(legacy_mode, legacy_proxy):
    config = RedditGetSubredditPostsConfig(
        subreddit="python", content_mode=legacy_mode, use_proxy=legacy_proxy
    )
    payload = build_reddit_input(config)[0]
    assert payload["maxPostsCount"] == 25
    assert payload["proxy"]["useApifyProxy"] is True
    assert "content_mode" not in config.model_json_schema()["properties"]
    assert "use_proxy" not in config.model_json_schema()["properties"]


@pytest.mark.parametrize(
    "name", ["https://reddit.com/r/python", "python/../other", "python?sort=top", "python+news", ""]
)
def test_rejects_non_subreddit_urls_before_provider_call(name):
    with pytest.raises(ValueError):
        build_reddit_input(RedditGetSubredditPostsConfig(subreddit=name))


def test_post_limit_and_comment_cap_are_independent():
    config = RedditGetSubredditPostsConfig(
        subreddit="python", limit=200, fetch_comments="true", max_comments=20
    )
    payload = build_reddit_input(config)[0]
    assert payload["maxPostsCount"] == 100
    assert payload["maxCommentsPerPost"] == 20
    assert payload["maxCommentsCount"] == 0
    assert payload["crawlCommentsPerPost"] is True


def test_real_full_text_timestamps_engagement_and_community():
    output = normalize()
    assert output["count"] == 3
    assert [p["post_id"] for p in output["posts"]] == ["1wbfipf", "1wbf55k", "1wbf25d"]
    post = next(p for p in output["posts"] if p["post_id"] == "1wbf55k")
    raw = next(p for p in FIXTURE["new"] if p.get("id") == "t3_1wbf55k")
    assert post["body"] == raw["body"]
    assert post["content_html"] == raw["bodyHtml"]
    assert post["published_at"] == "2026-09-09T07:56:38.000Z"
    assert post["updated_at"] == (raw.get("editedAt") or raw["createdAt"])
    assert post["num_comments"] == raw["commentsCount"] == 3
    assert post["score"] == raw["score"] == 1
    assert post["url"] == raw["postUrl"]
    assert post["community_members_num"] == FIXTURE["community"][0]["membersCount"]
    assert post["community_description"] == FIXTURE["community"][0]["publicDescription"]
    assert post["related_posts"] is None


def test_long_post_and_nested_replies_preserve_real_content():
    output = normalize(FIXTURE["thread"], subreddit="n8n", comments=20)
    post = output["posts"][0]
    assert len(post["body"]) == 35832
    assert post["body"] == FIXTURE["thread"][0]["body"]
    assert post["num_comments"] == 5
    assert post["comment_count"] == 4  # Scraped sample, not Reddit's total.
    root = next(c for c in post["comments"] if c["comment_id"] == "p8oyb3b")
    reply = root["replies"][0]
    assert reply["comment_id"] == "p8ozkwn"
    assert len(reply["body"]) == 2340
    assert reply["replies"][0]["comment_id"] == "p8pcz8k"
    assert root["reply_count"] is None  # No invented total from a sample.
    assert post["comments_are_sampled"] is True


def test_commentless_request_preserves_total_count():
    post = normalize(FIXTURE["thread"][:1], subreddit="n8n", comments=0)["posts"][0]
    assert post["num_comments"] == 5
    assert "comments" not in post
    assert "comment_count" not in post


@pytest.mark.parametrize(
    "fixture,subreddit,count", [("image", "nocode", 1), ("gallery", "ClaudeAI", 2)]
)
def test_real_media_links_survive(fixture, subreddit, count):
    post = normalize(FIXTURE[fixture], subreddit=subreddit, comments=0)["posts"][0]
    assert len(post["photos"]) == count
    assert all(url.startswith("https://") for url in post["photos"])


@pytest.mark.parametrize("field", ["score", "commentsCount", "body", "bodyHtml", "createdAt"])
def test_missing_data_is_not_zero_or_empty_success(field):
    items = copy.deepcopy(FIXTURE["new"])
    items[0].pop(field)
    with pytest.raises(ValueError, match="incomplete record"):
        normalize(items)


def test_empty_body_is_valid_for_image_post():
    assert normalize(FIXTURE["image"], subreddit="nocode", comments=0)["posts"][0]["body"] == ""


def test_truncated_body_is_rejected():
    items = copy.deepcopy(FIXTURE["new"])
    items[0]["body"] = items[0]["body"][:20]
    with pytest.raises(ValueError, match="truncated"):
        normalize(items)


def test_wrong_community_is_rejected():
    with pytest.raises(ValueError, match="subreddit"):
        normalize(subreddit="other")


def test_missing_community_is_rejected():
    with pytest.raises(ValueError, match="community metadata"):
        normalize_reddit_result(
            [], [], subreddit="python", sort="new", period=None, limit=5, comments_limit=0
        )


def test_zero_comments_and_hidden_comments_are_distinguishable():
    items = copy.deepcopy(FIXTURE["new"][:1])
    items[0]["commentsCount"] = 0
    post = normalize(items)["posts"][0]
    assert post["num_comments"] == 0 and post["comment_count"] == 0
    items[0]["commentsCount"] = 5
    post = normalize(items)["posts"][0]
    assert post["num_comments"] == 5 and post["comment_count"] == 0
    assert post["comments_are_sampled"] is True


async def test_real_node_through_http_runner_without_reddit_credential(monkeypatch):
    node = RedditNode(
        node_id="reddit",
        node_type="automation-reddit",
        node_data={},
        config=RedditNodeConfig(
            config=RedditGetSubredditPostsConfig(
                subreddit="AI_Agents", sort="new", fetch_comments="true"
            )
        ),
        sio=None,
        sid=None,
        user_id="test-user",
    )
    node.emit = AsyncMock()
    node._check_credits_or_raise = AsyncMock()
    node._track_apify_usage = AsyncMock()
    monkeypatch.setenv("APIFY_API_TOKEN", "test-apify-key")
    monkeypatch.setattr("nodes.core.apify_runner.asyncio.sleep", AsyncMock())
    requests = []
    starts = []
    run_data = {}
    datasets = {}

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-apify-key"
        assert "token" not in request.url.params
        path = request.url.path
        if path.endswith("/runs"):
            payload = json.loads(request.content)
            starts.append(payload)
            rid = "community" if payload["maxPostsCount"] == 0 else "posts"
            datasets[rid] = FIXTURE["community"] if rid == "community" else FIXTURE["new"]
            run_data[rid] = {
                "id": rid,
                "status": "SUCCEEDED",
                "defaultDatasetId": rid,
                "defaultKeyValueStoreId": rid,
                "usageTotalUsd": 0.04,
                "chargedEventCounts": {"result": len(datasets[rid])},
            }
            assert request.url.params["build"] == "0.0.392"
            assert float(request.url.params["maxTotalChargeUsd"]) > 0
            assert request.url.params["timeout"] == "540"
            return httpx.Response(201, json={"data": run_data[rid]})
        if "/actor-runs/" in path:
            return httpx.Response(200, json={"data": run_data[path.split("/")[-1]]})
        if "/datasets/" in path:
            return httpx.Response(200, json=datasets[path.split("/")[-2]])
        if "/records/RUN-SUMMARY" in path:
            rid = path.split("/")[-3]
            return httpx.Response(
                200,
                json={"itemsTotal": len(datasets[rid]), "requests": {"finished": 1, "failed": 0}},
            )
        raise AssertionError(path)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.core.apify_runner.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    )
    output = await node.execute({})
    assert output["count"] == 3 and output["source"] == "apify"
    assert node._track_apify_usage.await_count == 2
    assert node.emit.await_count == 1
    assert node.emit.await_args.args[0] == output
    assert starts[0]["startUrls"][0]["url"] == "https://www.reddit.com/r/AI_Agents/new/"
    assert starts[1]["maxPostsCount"] == 0
    assert all("apify.com" == req.url.host.split(".", 1)[-1] for req in requests)

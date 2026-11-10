"""Wire-level tests against examples in Taplio's pinned, published v1 contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.taplio_node import TaplioAPIKeyCredential, TaplioNode
from nodes.core.poll_trigger import poll_scope

FIXTURE = json.loads((Path(__file__).parent / "fixtures/taplio/published_examples.json").read_text())
EXAMPLES = FIXTURE["schemas"]
KEY = "test-taplio-secret"
DRAFT = EXAMPLES["Draft"]["id"]
POST = EXAMPLES["Post"]["id"]


def node(config, *, credential=None):
    data = {"config": config, "credentials": credential or {"credential_type": "taplio_api_key", "api_key": KEY}}
    return TaplioNode("taplio", "automation-taplio", data, config=TaplioNode.parse_config(data))


@pytest.fixture
def wire(monkeypatch):
    client = httpx.AsyncClient
    calls = []

    def install(body, status=200):
        def handle(request):
            calls.append(request)
            return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
        monkeypatch.setattr("nodes.taplio_node.httpx.AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handle), **kw))
        return calls
    return install


@pytest.mark.parametrize("operation,extra,method,path,body,response,status", [
    ("list_posts", {"status": "sent", "from_date": "2026-06-01", "cursor": "next"}, "GET", "/v1/posts", None, "SearchPostsResponse", 200),
    ("get_post", {"post_id": POST}, "GET", f"/v1/posts/{POST}", None, "Post", 200),
    ("get_post", {"post_id": "urn:li:activity:7506286955412893698"}, "GET", "/v1/posts/urn%3Ali%3Aactivity%3A7506286955412893698", None, "Post", 200),
    ("list_post_drafts", {}, "GET", "/v1/posts/drafts", None, "SearchDraftsResponse", 200),
    ("create_post_draft", EXAMPLES["CreatePostDraftBody"], "POST", "/v1/posts/drafts", EXAMPLES["CreatePostDraftBody"], "Draft", 201),
    ("get_post_draft", {"draft_id": DRAFT}, "GET", f"/v1/posts/drafts/{DRAFT}", None, "Draft", 200),
    ("update_post_draft", {"draft_id": DRAFT, **EXAMPLES["UpdatePostDraftBody"]}, "PATCH", f"/v1/posts/drafts/{DRAFT}", EXAMPLES["UpdatePostDraftBody"], "Draft", 200),
    ("delete_post_draft", {"draft_id": DRAFT}, "DELETE", f"/v1/posts/drafts/{DRAFT}", None, None, 204),
    ("publish_post_draft", {"draft_id": DRAFT}, "POST", f"/v1/posts/drafts/{DRAFT}/commit", None, "Post", 200),
    ("schedule_post_draft", {"draft_id": DRAFT, "scheduled_for": "2027-01-03T12:00:00Z"}, "POST", f"/v1/posts/drafts/{DRAFT}/schedule", {"scheduled_for": "2027-01-03T12:00:00Z"}, "Post", 200),
    ("unschedule_post_draft", {"draft_id": DRAFT}, "POST", f"/v1/posts/drafts/{DRAFT}/unschedule", None, "Draft", 200),
    ("attach_media_url", {"draft_id": DRAFT, **EXAMPLES["UploadMediaFromUrlBody"]}, "POST", f"/v1/posts/drafts/{DRAFT}/upload-url", EXAMPLES["UploadMediaFromUrlBody"], "Draft", 200),
    ("list_media", {"query": "photo", "limit": 10}, "GET", "/v1/posts/media", None, None, 200),
    ("list_comments", {"post_urn": EXAMPLES["Comment"]["post_urn"]}, "GET", "/v1/comments", None, "ListCommentsResponse", 200),
    ("create_comment_draft", EXAMPLES["CreateCommentDraftBody"], "POST", "/v1/comments/drafts", EXAMPLES["CreateCommentDraftBody"], "EditableCommentDraft", 201),
    ("get_comment_draft", {"draft_id": DRAFT}, "GET", f"/v1/comments/drafts/{DRAFT}", None, "CommentDraft", 200),
    ("update_comment_draft", {"draft_id": DRAFT, **EXAMPLES["UpdateCommentDraftBody"]}, "PATCH", f"/v1/comments/drafts/{DRAFT}", EXAMPLES["UpdateCommentDraftBody"], "EditableCommentDraft", 200),
    ("delete_comment_draft", {"draft_id": DRAFT}, "DELETE", f"/v1/comments/drafts/{DRAFT}", None, None, 204),
    ("commit_comment_draft", {"draft_id": DRAFT}, "POST", f"/v1/comments/drafts/{DRAFT}/commit", None, "QueuedCommentDraft", 200),
    ("cancel_comment_draft", {"draft_id": DRAFT}, "POST", f"/v1/comments/drafts/{DRAFT}/cancel", None, "CommentDraft", 200),
    ("get_analytics_overview", {"from_date": "2026-06-01", "metrics": "followers,impressions"}, "GET", "/v1/analytics/overview", None, None, 200),
    ("get_post_analytics", {"to_date": "2026-06-30"}, "GET", "/v1/analytics/posts", None, None, 200),
    ("list_engagement_feed", {"source": "curated_feed", "feed": "LinkedIn Growth"}, "GET", "/v1/engagement/feed", None, "ListEngagementFeedResponse", 200),
    ("like_post", {"post_urn": EXAMPLES["Comment"]["post_urn"]}, "POST", "/v1/likes", {"post_urn": EXAMPLES["Comment"]["post_urn"]}, "Like", 201),
])
async def test_wire_contract(wire, operation, extra, method, path, body, response, status):
    payload = EXAMPLES[response] if response else {"data": [], "meta": {"has_more": False}}
    calls = wire(payload, status)
    result = await node({"operation": operation, **extra}).execute({})
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method
    assert req.url.scheme == "https" and req.url.host == "api.taplio.com"
    assert req.url.raw_path.decode().split("?")[0] == path
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(req.content) == body if body else not req.content
    assert result == ({"deleted": True} if status == 204 else payload)
    for field, value in extra.items():
        if method == "GET" and field not in {"post_id", "draft_id"}:
            assert req.url.params[{"from_date": "from", "to_date": "to"}.get(field, field)] == str(value)
    if operation == "get_analytics_overview":
        assert req.url.params["granularity"] == "day"


async def test_media_only_and_replacement_preserve_empty_content(wire):
    calls = wire(EXAMPLES["Draft"])
    await node({"operation": "create_post_draft", "media_ids": ["media-1"]}).execute({})
    assert json.loads(calls[-1].content) == {"media_ids": ["media-1"]}
    await node({"operation": "update_post_draft", "draft_id": DRAFT, "media_ids": []}).execute({})
    assert json.loads(calls[-1].content) == {"media_ids": []}


@pytest.mark.parametrize("status", [400, 401, 403, 409, 429, 503])
async def test_provider_errors_are_visible_and_not_retried(wire, status):
    payload = EXAMPLES["ErrorEnvelope"]
    calls = wire(payload, status)
    with pytest.raises(ValueError, match=payload["error"]["message"]):
        await node({"operation": "create_post_draft", "content": "test"}).execute({})
    assert len(calls) == 1


async def test_never_follow_redirects(wire):
    calls = wire({}, 302)
    with pytest.raises(ValueError, match="HTTP 302"):
        await node({"operation": "list_posts"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "create_post_draft"},
    {"operation": "create_post_draft", "content": "x" * 3001},
    {"operation": "create_post_draft", "media_ids": [""]},
    {"operation": "update_post_draft", "draft_id": DRAFT},
    {"operation": "create_comment_draft", "post_urn": "urn:li:activity:1", "content": "x" * 1251},
    {"operation": "get_post_draft", "draft_id": "../../settings"},
    {"operation": "get_post", "post_id": "https://attacker.test"},
    {"operation": "list_engagement_feed", "feed": "LinkedIn Growth"},
    {"operation": "list_media", "limit": 101},
    {"operation": "attach_media_url", "draft_id": DRAFT, "url": "http://example.com/file"},
])
def test_invalid_configs(config):
    assert not TaplioNode.validate_config({"config": config})["valid"]


def test_manual_credential_shape():
    cred = TaplioAPIKeyCredential(api_key="  real-api-key  ")
    assert cred.api_key == "real-api-key"
    assert cred.credential_type == "taplio_api_key"
    for key in ["https://example.com/key", "<token>", "Bearer secret"]:
        with pytest.raises((ValueError, ValidationError)):
            TaplioAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("operation,example", [("on_new_post", "SearchPostsResponse"), ("on_new_comment", "ListCommentsResponse")])
async def test_poll_baseline_dedup_and_agent_event(wire, operation, example):
    calls = wire(EXAMPLES[example])
    n = node({"operation": operation})
    state = {}

    async def update(mutator, **kw):
        nonlocal state
        change, result = mutator(dict(state))
        if change is not None:
            state = change
        return result

    n._update_node_state = update
    first = await n.execute({})
    assert first["data"] == []
    assert n.trigger_produced_no_event(first)
    # A prior empty baseline represents arming before the documented activity arrived.
    state["seen_ids"] = []
    fired = await n.execute({})
    assert fired["data"] == EXAMPLES[example]["data"]
    assert n.trigger_emitted_event(fired)
    event = TaplioNode.resolve_agent_event(fired)
    assert "LinkedIn" in event["text"] and EXAMPLES[example]["data"][0]["content"][:100] in event["text"]
    assert EXAMPLES[example]["data"][0].get("id", EXAMPLES[example]["data"][0].get("post_urn")) in event["text"]
    assert (await n.execute({}))["new_count"] == 0
    assert all(call.url.params["limit"] == "100" for call in calls)
    if operation == "on_new_post":
        assert calls[0].url.params["status"] == "sent"


async def test_older_comment_optional_urn_enrichment_does_not_repeat(wire):
    comment = dict(EXAMPLES["Comment"])
    comment.pop("comment_urn")
    payload = {"data": [comment], "meta": EXAMPLES["ListCommentsResponse"]["meta"]}
    wire(payload)
    n = node({"operation": "on_new_comment", "post_urn": comment["post_urn"]})
    state = {"seen_ids": []}

    async def update(mutator, **kw):
        nonlocal state
        change, result = mutator(dict(state))
        if change is not None:
            state = change
        return result

    n._update_node_state = update
    out = await n.execute({})
    assert out["new_count"] == 1
    assert comment["post_urn"] in TaplioNode.resolve_agent_event(out)["text"]
    payload["data"] = [EXAMPLES["Comment"]]
    assert (await n.execute({}))["new_count"] == 0


def test_poll_scope_ignores_canvas_metadata_and_tracks_declared_filters():
    base = {"operation": "on_new_post"}
    assert poll_scope(TaplioNode, base) == poll_scope(TaplioNode, {**base, "label": "Renamed", "goal": "draft"})
    assert poll_scope(TaplioNode, base) != poll_scope(TaplioNode, {**base, "from_date": "2026-06-01"})

"""Mock HTTP with response bodies from DropInBlog's published v2 examples."""
import json
from copy import deepcopy
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import dropinblog_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "dropinblog"
AUTH = {
    "credential_type": "dropinblog_api_key",
    "blog_id": "34236460",
    "public_api_key": "dib-public-test-key-42",
    "private_api_key": "dib-private-test-key-42",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def example(operation):
    return json.loads(
        (
            FIXTURES / (native.OPERATIONS[operation]["contract_operation"] + ".json")
        ).read_text()
    )


def node(operation, **arguments):
    return NodeFactory.create_node(
        node_id="dropinblog-test",
        node_type="automation-dropinblog",
        node_data={
            "config": {"operation": operation, **arguments},
            "credentials": AUTH,
        },
    )


def transport(monkeypatch, replies):
    requests = []
    client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        native.httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw),
    )
    return requests


CASES = [
    (
        "create_post",
        {"title": "My First Post", "content": "<p>My first post</p>"},
        "POST",
        "/posts",
    ),
    (
        "list_posts",
        {"page": 2, "limit": 10, "modified_at_start": "2024-03-16"},
        "GET",
        "/posts",
    ),
    ("get_post", {"id": 42349491}, "GET", "/posts/42349491"),
    (
        "update_post",
        {"id": 42349491, "title": "My First Post"},
        "PATCH",
        "/posts/42349491",
    ),
    ("search_posts", {"search": "blogging"}, "GET", "/posts/search"),
    (
        "get_post_by_slug",
        {"slug": "welcome-to-dropinblog"},
        "GET",
        "/posts/slug/welcome-to-dropinblog",
    ),
    (
        "update_post_by_slug",
        {"post_slug": "welcome-to-dropinblog", "slug": "new-slug"},
        "PATCH",
        "/posts/slug/welcome-to-dropinblog",
    ),
    ("list_categories", {"exclude_private": 1}, "GET", "/categories"),
    ("get_category", {"id": 899048726}, "GET", "/categories/899048726"),
    (
        "get_category_by_slug",
        {"slug": "announcements"},
        "GET",
        "/categories/slug/announcements",
    ),
    ("list_authors", {"exclude_without_published_post": 1}, "GET", "/authors"),
    ("get_author", {"id": 73672}, "GET", "/authors/73672"),
    ("get_author_by_slug", {"slug": "alexander"}, "GET", "/authors/slug/alexander"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,suffix", CASES)
async def test_every_operation_native_factory(
    monkeypatch, operation, arguments, method, suffix
):
    reply = example(operation)
    replies = [(200, reply)]
    requests = transport(monkeypatch, replies)
    assert await node(operation, **arguments).execute({}) == reply
    assert not replies and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.dropinblog.com"
    assert request.url.path == "/v2/blog/34236460" + suffix
    assert (
        request.headers["Authorization"]
        == "Bearer " + AUTH["public_api_key" if method == "GET" else "private_api_key"]
    )
    spec = native.OPERATIONS[operation]
    assert dict(request.url.params) == {
        k: str(v) for k, v in arguments.items() if k in spec["query"]
    }
    if method != "GET":
        assert json.loads(request.content) == {
            k: v for k, v in arguments.items() if k in spec["body"]
        }


@pytest.mark.asyncio
async def test_write_preserves_false_empty_lists_faqs_and_omits_unsupplied_fields(
    monkeypatch,
):
    requests = transport(monkeypatch, [(200, example("create_post"))])
    arguments = {
        "title": "My First Post",
        "content": "<h2>Hello</h2>",
        "noindex": False,
        "category_ids": [],
        "faqs": [{"question": "Why?", "answer": "Because."}],
        "enable_toc": True,
    }
    await node("create_post", **arguments).execute({})
    assert json.loads(requests[0].content) == arguments


@pytest.mark.asyncio
async def test_missing_private_key_never_sends_write(monkeypatch):
    requests = transport(monkeypatch, [])
    instance = node("create_post", title="My First Post", content="<p>Hello</p>")
    instance.config.credentials.private_api_key = None
    with pytest.raises(ValueError, match="private API key"):
        await instance.execute({})
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload,error",
    [
        (200, {"success": False, "message": "Invalid API Key"}, ValueError),
        (401, {"message": "Unauthorized"}, httpx.HTTPStatusError),
        (429, {"message": "Slow down"}, httpx.HTTPStatusError),
        (302, {}, httpx.HTTPStatusError),
        (200, {"success": True}, ValueError),
    ],
)
async def test_errors_are_not_connection_success(monkeypatch, status, payload, error):
    requests = transport(monkeypatch, [(status, payload)])
    with pytest.raises(error):
        await node("list_categories").execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_slug_is_encoded_without_route_injection(monkeypatch):
    requests = transport(monkeypatch, [(200, example("get_post_by_slug"))])
    await node("get_post_by_slug", slug="a/b?x=1").execute({})
    assert requests[0].url.raw_path.endswith(b"/slug/a%2Fb%3Fx%3D1")


def state_store(instance, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_post", "on_updated_post"])
async def test_poll_documented_baseline_dedup_new_and_updated(monkeypatch, operation):
    original = example("list_posts")
    changed = deepcopy(original)
    changed["data"]["posts"][0]["updatedAtIso8601"] = "2024-03-17T16:45:06-05:00"
    added = deepcopy(changed["data"]["posts"][0])
    added["id"] = 42349492
    changed["data"]["posts"].append(added)
    replies = [(200, deepcopy(original)), (200, deepcopy(original)), (200, changed)]
    transport(monkeypatch, replies)
    instance = node(operation)
    state_store(instance, {})
    assert (await instance.execute({}))["posts"] == []
    assert (await instance.execute({}))["posts"] == []
    result = await instance.execute({})
    assert result["new_post_count"] == (1 if operation == "on_new_post" else 2)
    assert native.DropInBlogNode.should_propagate_output(
        result, {"operation": operation}
    )
    event = native.DropInBlogNode.resolve_agent_event(result)
    assert all(
        s in event["text"]
        for s in ["DropInBlog", "Jason", "42349492", "dropindemo.com"]
    )
    assert not replies


@pytest.mark.asyncio
async def test_poll_collects_pages_before_seen_write_and_keeps_filters(monkeypatch):
    first = example("list_posts")
    first["data"]["pagination"]["last_page"] = 2
    second = deepcopy(first)
    second["data"]["posts"] = []
    requests = transport(monkeypatch, [(200, first), (200, second)])
    instance = node("on_updated_post", modified_at_start="2024-03-16")
    state_store(instance, {"seen_ids": []})
    assert (await instance.execute({}))["new_post_count"] == 4
    assert [dict(r.url.params) for r in requests] == [
        {"modified_at_start": "2024-03-16", "page": str(p), "limit": "100"}
        for p in [1, 2]
    ]


@pytest.mark.asyncio
async def test_incomplete_poll_does_not_consume_events(monkeypatch):
    first = example("list_posts")
    first["data"]["pagination"]["last_page"] = 21
    transport(monkeypatch, [(200, deepcopy(first)) for _ in range(20)])
    instance = node("on_new_post")
    state = {"seen_ids": []}
    state_store(instance, state)
    with pytest.raises(ValueError, match="2,000 posts"):
        await instance.execute({})
    assert state == {"seen_ids": []}


def test_manual_credential_defaults_and_validation():
    parsed = native.DropInBlogAPIKeyCredential.model_validate(
        {k: v for k, v in AUTH.items() if k != "credential_type"}
    )
    assert parsed.credential_type == "dropinblog_api_key"
    for changes in [
        {"blog_id": "https://example.com"},
        {"public_api_key": "Bearer abc"},
        {"public_api_key": "https://example.com"},
    ]:
        with pytest.raises(ValidationError):
            native.DropInBlogAPIKeyCredential.model_validate({**AUTH, **changes})


@pytest.mark.asyncio
async def test_clear_fields_send_documented_empty_strings(monkeypatch):
    requests = transport(monkeypatch, [(200, example("update_post"))])
    await node(
        "update_post", id=42349491, clear_excerpt=True, clear_canonical_url=True
    ).execute({})
    assert json.loads(requests[0].content) == {"excerpt": "", "canonical_url": ""}


@pytest.mark.asyncio
async def test_auth_rejection_keeps_provider_words(monkeypatch):
    transport(monkeypatch, [(401, {"message": "This API key has been revoked"})])
    with pytest.raises(httpx.HTTPStatusError, match="This API key has been revoked"):
        await node("list_categories").execute({})

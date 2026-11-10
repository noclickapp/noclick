"""Exercise Flat through the native operation runner and HTTP boundary."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import flat_node as flat
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "flat_token", "access_token": "fixture-flat-personal-token"}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.flat.io"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        code, body, headers = replies.pop(0)
        return httpx.Response(code, json=body, headers=headers) if code != 204 else httpx.Response(204)
    monkeypatch.setattr(flat.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(op, arguments=None):
    return await run_node_operation(node_type="automation-flat", operation=op, arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")

@pytest.mark.asyncio
async def test_flat_write_body_and_comment_path(transport):
    req, replies = transport
    replies.append((200, {"id": "comment1", "comment": "Great work!"}, {}))
    out = await run("updateScoreComment", {"score": "score1", "comment_id": "comment1", "text": "Great work!"})
    assert req[0].method == "PUT"
    assert req[0].url.path == "/v2/scores/score1/comments/comment1"
    assert json.loads(req[0].content) == {"comment": "Great work!"}
    assert out["data"]["comment"] == "Great work!"

@pytest.mark.asyncio
async def test_flat_cursor_does_not_follow_url(transport):
    req, replies = transport
    replies.append((200, [{"id": "c1", "title": "Jazz scores"}], {"Link": '<https://untrusted.invalid/collections?next=opaque>; rel="next"'}))
    out = await run("listCollections")
    assert out["next_cursor"] == "opaque"
    assert len(req) == 1
    assert req[0].url.params["sort"] == "modificationDate"

@pytest.mark.asyncio
async def test_flat_delete_no_content(transport):
    req, replies = transport
    replies.append((204, None, {}))
    assert (await run("deleteScore", {"score": "score1"}))["data"] == {"success": True}
    assert req[0].method == "DELETE"

@pytest.mark.asyncio
async def test_flat_provider_rejection_redacts_token(transport):
    _, replies = transport
    replies.append((401, {"message": "Invalid " + AUTH["access_token"]}, {}))
    with pytest.raises(ValueError, match="401") as error:
        await run("getAuthenticatedUser")
    assert AUTH["access_token"] not in str(error.value)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,params,path", [("on_updated_score", {"collection":"allScores"}, "/collections/allScores/scores"), ("on_updated_collection", {"parent":"user"}, "/collections")])
async def test_flat_poll_all_pages_and_update_identity(transport, monkeypatch, operation, params, path):
    # Fields read by the poll are declared in the provider's Collection / ScoreDetails schemas.
    req, replies = transport
    item = {"id": "resource1", "title": "Jazz scores", "creationDate": "2020-01-01T00:00:00Z", "modificationDate": "2020-01-02T00:00:00Z", "htmlUrl": "https://flat.io/score/resource1"}
    observed = []
    async def filter_unseen(self, items, id_fn):
        observed.extend(id_fn(x) for x in items)
        return items
    monkeypatch.setattr(flat.FlatNode, "_filter_unseen", filter_unseen)
    replies.extend([(200, [item], {"Link": '<https://api.flat.io/v2'+path+'?next=page2>; rel="next"'}), (200, [{**item, "id":"resource2"}], {})])
    out = await run(operation, params)
    assert out["count"] == 2
    assert observed == ["resource1:2020-01-02T00:00:00Z", "resource2:2020-01-02T00:00:00Z"]
    assert req[1].url.params["next"] == "page2"
    assert "Jazz scores" in flat.FlatNode.resolve_agent_event(out)["text"]
    assert not flat.FlatNode.should_propagate_output({"items": []}, {"operation": operation})

@pytest.mark.asyncio
async def test_flat_poll_baselines_deduplicates_and_emits_changed_revision(transport, monkeypatch):
    _, replies = transport
    state = {}
    async def update(self, mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(flat.FlatNode, "_update_node_state", update)
    item = {"id": "s1", "title": "My score", "creationDate": "2020-01-01T00:00:00Z", "modificationDate": "2020-01-02T00:00:00Z"}
    replies.extend([(200,[item],{}),(200,[item],{}),(200,[{**item,"modificationDate":"2020-01-03T00:00:00Z"}],{})])
    assert (await run("on_updated_score"))["count"] == 0
    assert (await run("on_updated_score"))["count"] == 0
    out = await run("on_updated_score")
    assert out["count"] == 1
    assert out["items"][0]["modificationDate"] == "2020-01-03T00:00:00Z"

@pytest.mark.asyncio
async def test_flat_provider_published_score_example(transport):
    _, replies = transport
    example = json.loads((Path(__file__).parent / "fixtures/flat/score_summary.json").read_text())["body"]
    replies.append((200, example, {}))
    out = await run("getScore", {"score": example["id"]})
    assert out["data"] == example

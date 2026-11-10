"""Exercise Tovuti's wire contract and real poll state transitions without an account.

Fixtures combine the provider's schema property examples with explicitly synthetic
IDs and timestamps; live service calls are replaced at the HTTP transport boundary.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import tovuti_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tovuti-test", node_type="automation-tovuti",
        node_data={"config": config, "credentials": {"credential_type": "tovuti_api_token", "api_token": "test-tovuti-token"}})


def transport(monkeypatch, responder):
    requests = []
    def reply(request):
        requests.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_create_user_and_clear_membership_keep_false_and_empty(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(201, json={"id": 1714926, "name": "John Doe"}))
    n = node({"operation": "create_user", "name": "John Doe", "username": "johndoe",
        "email": "johndoe@gmail.com", "password": "password100", "userGroupIds": [], "requireReset": False})
    result = await n.execute({})
    assert result["id"] == 1714926
    req = requests[0]
    assert req.method == "POST" and str(req.url) == native.BASE_URL + "/user"
    assert req.headers["Authorization"] == "Bearer test-tovuti-token"
    assert json.loads(req.content) == {"name": "John Doe", "username": "johndoe", "email": "johndoe@gmail.com", "password": "password100", "userGroupIds": [], "requireReset": False}
    await node({"operation": "update_user", "resource_id": 1714926, "userGroupIds": [], "status": "disabled"}).execute({})
    assert requests[-1].method == "PATCH" and requests[-1].url.path.endswith("/user/1714926")
    assert json.loads(requests[-1].content) == {"userGroupIds": [], "status": "disabled"}


@pytest.mark.asyncio
async def test_read_filters_dates_and_progress_body(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"data": [], "next_page_url": None}))
    await node({"operation": "list_users", "email": "johndoe@gmail.com", "registeredAfter": "2023-01-12", "page": 2, "pageSize": 50}).execute({})
    assert dict(requests[0].url.params) == {"email": "johndoe@gmail.com", "registeredAfter": "2023-01-12", "page": "2", "pageSize": "50", "sortBy": "timestampModified", "sortDir": "desc"}
    await node({"operation": "create_course_progress", "user_id": 1714926, "course_id": 1, "language": "en-GB", "progress": 0, "date_due": "2023-01-12"}).execute({})
    assert json.loads(requests[-1].content) == {"user_id": 1714926, "course_id": 1, "language": "en-GB", "progress": 0, "date_due": "2023-01-12"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_errors_never_count_as_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": "Not authorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_courses"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.TRIGGERS))
async def test_poll_baselines_deduplicates_and_emits_updates(monkeypatch, operation):
    fixtures = json.loads((Path(__file__).parent / "fixtures/tovuti/poll_records.json").read_text())
    record = dict(fixtures[operation])
    transport(monkeypatch, lambda r: httpx.Response(200, json={"data": [dict(record)], "next_page_url": None}))
    n = node({"operation": operation})
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(dict(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result
    n._update_node_state = update
    assert (await n.execute({}))["event_count"] == 0
    assert (await n.execute({}))["event_count"] == 0
    record["timestamp_modified"] = "2023-01-13T15:30:00Z"
    output = await n.execute({})
    assert output["event_count"] == 1
    assert str(record["id"]) in n.resolve_agent_event(output)["text"]
    assert n.trigger_emitted_event(output)
    assert (await n.execute({}))["event_count"] == 0
    record["id"] += 1
    assert (await n.execute({}))["event_count"] == 1


@pytest.mark.asyncio
async def test_poll_paginates_fixed_host_and_filters_before_state_write(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={
        "data": [{"id": i, "timestamp_modified": "2023-01-12T15:30:00Z"} for i in (range(1, 251) if r.url.params['page'] == '1' else [251])],
        "next_page_url": "https://untrusted.example/?page=2" if r.url.params['page'] == '1' else None}))
    n = node({"operation": "on_updated_course_progress", "userId": 1714926, "courseId": 1})
    async def update(mutator, **kwargs):
        return mutator({"seen_ids": []})[1]
    n._update_node_state = update
    assert (await n.execute({}))["event_count"] == 251
    assert [r.url.params['page'] for r in requests] == ['1', '2']
    assert all(r.url.host == 'api.tovuti.io' and r.url.params['userId'] == '1714926' and r.url.params['courseId'] == '1' for r in requests)
    assert poll_scope(native.TovutiNode, {"operation": "on_updated_course_progress", "userId": 1}) != poll_scope(native.TovutiNode, {"operation": "on_updated_course_progress", "userId": 2})


def test_manual_credential_defaults_and_required_write_fields():
    c = native.TovutiTokenCredential(api_token=" test-tovuti-token ")
    assert c.credential_type == "tovuti_api_token" and c.api_token == "test-tovuti-token"
    for value in ["", "Bearer abc", "abc\nxyz"]:
        with pytest.raises(ValidationError):
            native.TovutiTokenCredential(api_token=value)
    for config in [{"operation": "create_user", "name": "John Doe"}, {"operation": "create_course_progress", "user_id": 1}, {"operation": "get_course", "resource_id": 0}, {"operation": "list_courses", "pageSize": 17}, {"operation": "create_assignment", "title": "Learn", "assignment_type": "courses"}]:
        assert not native.TovutiNode.validate_saved_config(config)["valid"]

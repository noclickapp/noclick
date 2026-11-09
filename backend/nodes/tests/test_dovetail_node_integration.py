"""Dovetail node contract tests against the documented request shapes.

These tests pin operation routing, credential handling, and generated editor metadata.
"""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from nodes import dovetail_node as module
from nodes.dovetail_node import DovetailAPICredential, DovetailNode, DovetailNodeFullConfig


def node(operation: str, **kwargs):
    config = DovetailNodeFullConfig.model_validate({
        "config": {"operation": operation, **kwargs},
        "credentials": {"credential_type": "dovetail_api_key", "api_key": "api.example"},
    })
    return DovetailNode(
        node_id="dovetail-test", node_type="automation-dovetail", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,expected", [
    ("list_projects", {"limit": 25, "cursor": "opaque", "title": "feedback"}, ("GET", "/v1/projects", {"page[limit]": 25, "page[start_cursor]": "opaque", "filter[title][contains]": "feedback"}, None)),
    ("list_data", {"title": "feedback", "project_id": "project-id"}, ("GET", "/v1/data", {"page[limit]": 100, "filter[project_id]": "project-id", "filter[title][contains]": "feedback"}, None)),
    ("create_project", {"title": "Research"}, ("POST", "/v1/projects", None, {"title": "Research"})),
    ("create_data", {"project_id": "project-id", "title": "Interview", "content": "Hello"}, ("POST", "/v1/data", None, {"project_id": "project-id", "title": "Interview", "content": "Hello"})),
    ("export_data", {"data_id": "data-id", "format": "markdown"}, ("GET", "/v1/data/data-id/export/markdown", None, None)),
    ("create_doc", {"title": "Findings", "content": "# Summary"}, ("POST", "/v1/docs", None, {"title": "Findings", "content": "# Summary", "content_type": "markdown"})),
    ("create_contact", {"name": "Ada", "email": "ada@example.com"}, ("POST", "/v1/contacts", None, {"name": "Ada", "email": "ada@example.com"})),
    ("create_tag", {"title": "Usability", "project_id": "project-id"}, ("POST", "/v1/tags", None, {"title": "Usability", "project_id": "project-id"})),
    ("list_tag_boards", {"project_id": "project-id"}, ("GET", "/v1/tags/boards", {"page[limit]": 100, "filter[project_id]": "project-id"}, None)),
    ("create_highlight", {"note_id": "data-id", "start_time": 1, "end_time": 3}, ("POST", "/v1/highlights", None, {"note_id": "data-id", "start_time": 1.0, "end_time": 3.0})),
    ("search_workspace", {"query": "interview"}, ("POST", "/v2/search", None, {"options": {"query": "interview"}, "limit": 20, "offset": 0})),
])
async def test_operation_routes(monkeypatch, operation, arguments, expected):
    request = AsyncMock(return_value={"data": {"id": "result"}})
    monkeypatch.setattr(module, "_request", request)
    assert await node(operation, **arguments).execute({}) == {"data": {"id": "result"}}
    method, path, params, body = expected
    request.assert_awaited_once_with("api.example", method, path, **({"params": params} if params is not None else {"body": body} if body is not None else {}))


@pytest.mark.asyncio
async def test_project_picker_and_identity(monkeypatch):
    request = AsyncMock(side_effect=[
        {"data": [{"id": "p1", "title": "Customer research"}], "page": {"next_cursor": "next"}},
        {"data": {"subdomain": "my-workspace"}},
    ])
    monkeypatch.setattr(module, "_request", request)
    picker = await DovetailNode.load_field_options("project_id", {"api_key": "api.example"}, search="feedback")
    request.assert_awaited_once_with("api.example", "GET", "/v1/projects", params={"page[limit]": 100, "filter[title][contains]": "feedback"})
    assert picker == {"options": [{"value": "p1", "label": "Customer research"}], "next_page_token": "next"}
    assert (await node("test_authentication").execute({}))["data"]["subdomain"] == "my-workspace"


@pytest.mark.asyncio
async def test_search_options_and_highlight_filters(monkeypatch):
    request = AsyncMock(return_value={"data": {}})
    monkeypatch.setattr(module, "_request", request)
    await node("search_workspace", query="feedback", types=["projects"]).execute({})
    request.assert_awaited_once_with(
        "api.example", "POST", "/v2/search",
        body={"options": {"query": "feedback", "types": ["projects"]}, "limit": 20, "offset": 0},
    )
    request.reset_mock()
    with pytest.raises(ValueError, match="project or tag"):
        await node("list_highlights", project_id="p1", tag_id="t1").execute({})
    with pytest.raises(ValueError, match="after start"):
        await node("create_highlight", note_id="data", start_time=5, end_time=4).execute({})
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_request_auth_and_error_redaction(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(401, json={"error": "secret response"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError, match="Dovetail API returned HTTP 401") as exc:
        await module._request("api.secret", "GET", "/v1/projects")
    assert seen[0].headers["Authorization"] == "Bearer api.secret"
    assert "api.secret" not in str(exc.value)
    assert "secret response" not in str(exc.value)


def test_config_schema_and_credential():
    assert DovetailAPICredential.model_fields["api_key"].json_schema_extra["ui:widget"] == "password"
    schema = DovetailNode.get_config_schema()
    operations = schema["properties"]["config"]["discriminator"]["mapping"]
    assert len(operations) == 34
    assert {"list_projects", "create_data", "export_doc", "create_contact", "search_workspace"} <= set(operations)


def poll_record(operation, identifier="record", *, revision="2026-11-10T01:00:00Z"):
    """Synthetic unit-test records; these are not provider-authored witnesses."""
    if operation == "on_new_or_updated_highlight":
        return {"id": identifier, "type": "highlight", "note_id": "data-id", "tags": [{"id": "tag", "title": "Usability"}],
                "text": "Customer feedback", "start_time": 10.5, "end_time": 25.3,
                "created_at": "2026-11-09T01:00:00Z", "updated_at": revision}
    record = {"id": identifier, "title": "Customer feedback", "type": "data" if operation == "on_new_data" else "doc",
              "created_at": "2026-11-09T01:00:00Z", "folder": None}
    if operation == "on_new_data":
        record.update(project={"id": "project-id", "title": "Research"}, deleted=False)
    return record


def page(rows, *, more=False, cursor=None):
    return {"data": rows, "page": {"total_count": len(rows), "has_more": more, "next_cursor": cursor}}


def poll_state(trigger, state):
    async def update(mutator, *, max_retries=4, skip_result=None):
        changed, result = mutator(dict(state))
        if changed is not None:
            state.clear()
            state.update(changed)
        return result
    trigger._update_node_state = update


POLL_ROUTES = [
    ("on_new_data", "/v1/data"),
    ("on_new_doc", "/v1/docs"),
    ("on_new_or_updated_highlight", "/v1/highlights"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", POLL_ROUTES)
async def test_poll_baselines_paginates_deduplicates_and_reaches_agent(monkeypatch, operation, path):
    trigger = node(operation, project_id="project-id")
    state = {}
    poll_state(trigger, state)
    old, new = poll_record(operation, "old"), poll_record(operation, "new")
    request = AsyncMock(return_value=page([old]))
    monkeypatch.setattr(module, "_request", request)
    baseline = await trigger.execute({})
    assert baseline["items"] == []
    assert trigger.trigger_produced_no_event(baseline)
    assert DovetailNode.resolve_agent_event(baseline) is None
    request.side_effect = [page([old], more=True, cursor="next"), page([new])]
    request.reset_mock()
    result = await trigger.execute({})
    assert result == {"operation": operation, "items": [new], "item_count": 1}
    assert trigger.trigger_emitted_event(result)
    assert not trigger.trigger_produced_no_event(result)
    assert request.await_args_list[0].args == ("api.example", "GET", path)
    assert request.await_args_list[0].kwargs == {"params": {"page[limit]": 100, "filter[project_id]": "project-id"}}
    assert request.await_args_list[1].kwargs["params"]["page[start_cursor]"] == "next"
    event = DovetailNode.resolve_agent_event({"status": "success", "data": result})
    assert "Customer feedback" in event["text"] and "id new" in event["text"]
    assert event["conversation_key"] is None
    request.side_effect = None
    request.return_value = page([old, new])
    assert (await trigger.execute({}))["item_count"] == 0
    # Repointing the same workflow node starts a fresh baseline for the new scope.
    repointed = node(operation, project_id="other-project")
    poll_state(repointed, state)
    request.return_value = page([poll_record(operation, "elsewhere")])
    assert (await repointed.execute({}))["items"] == []


@pytest.mark.asyncio
async def test_highlight_changes_emit_once_per_revision(monkeypatch):
    trigger = node("on_new_or_updated_highlight")
    poll_state(trigger, {})
    old = poll_record("on_new_or_updated_highlight")
    request = AsyncMock(return_value=page([old]))
    monkeypatch.setattr(module, "_request", request)
    assert (await trigger.execute({}))["items"] == []
    revised = poll_record("on_new_or_updated_highlight", revision="2026-11-10T02:00:00Z")
    request.return_value = page([revised])
    result = await trigger.execute({})
    assert result["items"] == [revised]
    event = DovetailNode.resolve_agent_event(result)
    assert "data-id" in event["text"] and "Usability" in event["text"]
    assert "get_highlight highlight_id" in event["text"]
    assert (await trigger.execute({}))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["api", "cursor", "missing_cursor", "bad_row", "bad_page", "missing_revision", "page_cap"])
async def test_poll_fails_without_consuming_state(monkeypatch, failure):
    trigger = node("on_new_or_updated_highlight")
    state = {"seen_ids": []}
    poll_state(trigger, state)
    record = poll_record("on_new_or_updated_highlight")
    good = page([record], more=True, cursor="next")
    if failure == "api":
        responses = [good, ValueError("Dovetail API returned HTTP 429")]
    elif failure == "cursor":
        responses = [good, good]
    elif failure == "missing_cursor":
        responses = [page([record], more=True)]
    elif failure == "bad_row":
        responses = [page([{"id": ""}])]
    elif failure == "bad_page":
        responses = [{"data": [record]}]
    elif failure == "missing_revision":
        responses = [page([{"id": "h1"}])]
    else:
        responses = [page([record], more=True, cursor=str(i)) for i in range(20)]
    monkeypatch.setattr(module, "_request", AsyncMock(side_effect=responses))
    with pytest.raises(ValueError):
        await trigger.execute({})
    assert state == {"seen_ids": []}


@pytest.mark.asyncio
async def test_deleted_data_does_not_fire(monkeypatch):
    trigger = node("on_new_data")
    poll_state(trigger, {"seen_ids": []})
    record = poll_record("on_new_data")
    record["deleted"] = True
    monkeypatch.setattr(module, "_request", AsyncMock(return_value=page([record])))
    assert (await trigger.execute({}))["items"] == []
    assert trigger.trigger_produced_no_event({})

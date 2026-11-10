"""BC Data Catalogue request contracts and provider-payload poll behavior."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import gov_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "gov"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="gov-test", node_type="automation-gov", node_data={
        "config": config, **({"credentials": {"credential_type": "gov_api_key", "api_key": "test-gov-key-123"}} if credentials else {})})


def response(monkeypatch, body, status=200):
    requests = []
    client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.OPERATIONS)
async def test_gov_every_operation_exact_route_query_and_auth(monkeypatch, operation):
    _, fields, _ = native.OPERATIONS[operation]
    values = {field: 5 if field in {"limit", "offset"} else False if field.startswith("include_") else "format:csv" if field == "query" else "grizzly-bear-population-units" for field in fields}
    requests = response(monkeypatch, {"success": True, "result": []})
    assert await node({"operation": operation, **values}).execute({}) == {"data": []}
    req, = requests
    assert req.method == "GET"
    assert str(req.url).split("?")[0] == native.BASE_URL + "/action/" + ({"get_site_status": "status_show", "list_my_organizations": "organization_list_for_user"}.get(operation, operation))
    assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()}
    assert req.headers["ckan_api_key"] == "test-gov-key-123"
    assert req.content == b""


@pytest.mark.asyncio
async def test_gov_provider_dataset_response_preserved(monkeypatch):
    body = json.loads((FIXTURES / "package_show.json").read_text())
    response(monkeypatch, body)
    actual = await node({"operation": "package_show", "id": body["result"]["id"]}).execute({})
    assert actual == {"data": body["result"]}
    assert actual["data"]["metadata_modified"] == "2019-12-17T11:23:38.231826"


@pytest.mark.asyncio
async def test_gov_error_envelope_and_http_rejection(monkeypatch):
    response(monkeypatch, {"success": False, "error": {"message": "Access denied"}})
    with pytest.raises(ValueError, match="Access denied"):
        await node({"operation": "get_site_status"}).execute({})
    monkeypatch.undo()
    response(monkeypatch, {"error": "Unauthorized"}, status=401)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "get_site_status"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"success": True}, {"success": "true", "result": []}, []])
async def test_gov_rejects_malformed_envelopes(monkeypatch, body):
    response(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_site_status"}).execute({})


@pytest.mark.asyncio
async def test_gov_requires_credential(monkeypatch):
    requests = response(monkeypatch, {"success": True, "result": []})
    with pytest.raises(ValueError, match="Connect"):
        await node({"operation": "package_list"}, credentials=False).execute({})
    assert requests == []


def test_gov_required_inputs_and_manual_credential_shape():
    for operation, (_, _, required) in native.OPERATIONS.items():
        if required:
            with pytest.raises(ConfigValidationError):
                native.GovNode.parse_config({"config": {"operation": operation}})
    assert native.GovAPIKeyCredential(api_key="abc123").credential_type == "gov_api_key"
    for value in ("bad\r\nheader", "https://example.com/key", "<token>"):
        with pytest.raises(ValidationError):
            native.GovAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_gov_poll_baseline_dedup_updates_and_agent_event(monkeypatch):
    body = json.loads((FIXTURES / "package_search.json").read_text())
    requests = response(monkeypatch, body)
    poll = node({"operation": "on_new_or_updated_dataset", "q": "*:*"})
    state = {}

    async def update(mutator, **kwargs):
        replacement, result = mutator(dict(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result

    poll._update_node_state = update
    baseline = await poll.execute({})
    assert baseline["new_or_updated_count"] == 0
    assert not native.GovNode.should_propagate_output(baseline, {"operation": "on_new_or_updated_dataset"})
    state["seen_ids"] = []
    fresh = await poll.execute({})
    assert fresh["datasets"] == body["result"]["results"]
    assert fresh["new_or_updated_count"] == 2
    event = native.GovNode.resolve_agent_event(fresh)
    assert "Metadata for Health Program" in event["text"] and "dataset 11" in event["text"]
    assert (await poll.execute({}))["new_or_updated_count"] == 0
    body["result"]["results"][0]["title"] = "Updated title"
    assert (await poll.execute({}))["new_or_updated_count"] == 1
    assert all(dict(r.url.params) == {"q": "*:*", "sort": "metadata_modified desc"} for r in requests)


@pytest.mark.asyncio
async def test_gov_poll_rejects_missing_ids(monkeypatch):
    response(monkeypatch, {"success": True, "result": {"results": [{"title": "Invalid"}]}})
    with pytest.raises(ValueError, match="no id"):
        await node({"operation": "on_new_or_updated_dataset"}).execute({})


@pytest.mark.asyncio
async def test_gov_saved_canvas_metadata_is_not_sent_to_provider(monkeypatch):
    requests = response(monkeypatch, {"success": True, "result": {"id": "grizzly-bear-population-units"}})
    await node({"operation": "package_show", "id": "grizzly-bear-population-units",
        "credentialIds": {"gov_api_key": "00000000-0000-4000-8000-000000000001"},
        "goal": "Read dataset metadata", "operationReason": "Dataset lookup"}).execute({})
    assert dict(requests[0].url.params) == {"id": "grizzly-bear-population-units"}

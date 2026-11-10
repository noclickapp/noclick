"""Registry route/body behavior and poll lifecycle against the published schemas."""
import json
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

import httpx
import pytest
import yaml
from nodes import apigee_node as mod
from nodes.core.credential_connect import shape_credential, typed_fields

CREDENTIAL = {"credential_type": "apigee_access_token", "access_token": "test-registry-token", "project": "sample-project", "location": "global"}


def node(config):
    parsed = mod.ApigeeNode.parse_config({"config": config, "credentials": CREDENTIAL})
    result = mod.ApigeeNode("registry", "automation-apigee", {"config": config}, config=parsed)
    result.emit = AsyncMock()
    return result


@pytest.mark.asyncio
async def test_create_version_wire_and_pagination(monkeypatch):
    requests = []
    def reply(request):
        requests.append(request)
        version = {"name": "projects/sample-project/locations/global/apis/petstore/versions/v100", "displayName": "Version 1"}
        return httpx.Response(200, json={"apiVersions": [version], "nextPageToken": "opaque"} if request.method == "GET" else version)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
            yield c
    monkeypatch.setattr(mod, "guarded_async_client", client)
    result = await node({"operation": "create_version", "api_id": "petstore", "api_version_id": "v100", "display_name": "Version 1", "state": "PRODUCTION"}).execute({})
    assert result["name"].endswith("/versions/v100")
    req = requests[0]
    assert str(req.url).split('?')[0] == "https://apigeeregistry.googleapis.com/v1/projects/sample-project/locations/global/apis/petstore/versions"
    assert req.method == "POST" and req.url.params["apiVersionId"] == "v100"
    assert json.loads(req.content) == {"displayName": "Version 1", "state": "PRODUCTION"}
    assert req.headers["authorization"] == "Bearer test-registry-token"
    page = await node({"operation": "list_versions", "api_id": "petstore", "page_size": 25, "page_token": "previous"}).execute({})
    assert page["nextPageToken"] == "opaque" and len(page["apiVersions"]) == 1
    assert dict(requests[1].url.params) == {"pageSize": "25", "pageToken": "previous"}


@pytest.mark.asyncio
async def test_patch_mask_and_resource_name(monkeypatch):
    request = AsyncMock(return_value={"displayName": "Renamed"})
    monkeypatch.setattr(mod.ApigeeNode, "_request", request)
    await node({"operation": "update_api", "api_id": "petstore", "display_name": "Renamed", "annotations": {"owner": "platform"}}).execute({})
    assert request.call_args.kwargs["params"] == {"allowMissing": "false", "updateMask": "displayName,annotations"}
    assert request.call_args.kwargs["body"] == {"displayName": "Renamed", "annotations": {"owner": "platform"}, "name": "projects/sample-project/locations/global/apis/petstore"}


@pytest.mark.asyncio
async def test_poll_baseline_new_update_and_scope(monkeypatch):
    payload = json.loads((Path(__file__).parent / 'fixtures/apigee/apis.json').read_text())["body"]
    request = AsyncMock(side_effect=[payload, payload, {"apis": [{**payload["apis"][0], "updateTime": "2026-11-02T12:00:00Z"}]}])
    monkeypatch.setattr(mod.ApigeeNode, "_request", request)
    n = node({"operation": "on_api_updated", "filter": 'displayName == "Petstore"'})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(state)
        if new_state is not None:
            state.clear(); state.update(new_state)
        return result
    n._update_node_state = update
    assert await n.execute({}) == {"apis": [], "new_api_count": 0}
    assert (await n.execute({}))["new_api_count"] == 0
    result = await n.execute({})
    assert result["new_api_count"] == 1 and result["apis"][0]["updateTime"] == "2026-11-02T12:00:00Z"
    event = n.resolve_agent_event(result)
    assert "Petstore" in event["text"] and "get_api api_id=petstore" in event["text"]
    assert request.call_args.kwargs["params"]["filter"] == 'displayName == "Petstore"'
    assert n.schedule_poll_scope({"operation": "on_api_updated", "filter": "createTime > timestamp('2026-01-01T00:00:00Z')"}) != state["scope"]
    assert not n.should_propagate_output({"new_api_count": 0}, {"operation": "on_api_updated"})


@pytest.mark.asyncio
async def test_poll_follows_pages_and_refuses_repeated_cursor(monkeypatch):
    request = AsyncMock(return_value={"apis": [], "nextPageToken": "same"})
    monkeypatch.setattr(mod.ApigeeNode, "_request", request)
    with pytest.raises(ValueError, match="repeated page token"):
        await node({"operation": "on_api_updated"}).execute({})
    assert request.call_count == 2


def test_manual_connect_and_path_validation():
    shaped, errors, resolved = shape_credential("apigee_access_token", {k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert not errors and resolved[1] is mod.ApigeeTokenCredential
    # The connect seam preserves omitted fields via exclude_unset; the model
    # still accepts the hand-entered blob and supplies its own type default.
    assert resolved[1].model_validate(shaped).credential_type == "apigee_access_token"
    assert shaped["access_token"] == CREDENTIAL["access_token"]
    assert {f['name'] for f in typed_fields('apigee_access_token')} == {"access_token", "project", "location"}
    with pytest.raises(ValueError):
        node({"operation": "get_api", "api_id": "../other"})
    with pytest.raises(ValueError):
        node({"operation": "get_api", "api_id": ".."})
    with pytest.raises(ValueError):
        mod.ApigeeTokenCredential(**{**CREDENTIAL, "access_token": "Bearer token"})


def test_pinned_provider_contract():
    fixture = Path(__file__).parent / "fixtures/apigee/conformance"
    manifest = json.loads((fixture / "manifest.json").read_text())["apigee"]
    raw = (fixture / manifest["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
    contract = yaml.safe_load(raw)
    assert len(mod.OPERATIONS) == 20
    for spec in mod.OPERATIONS.values():
        operation = contract["paths"][spec["path"]][spec["method"].lower()]
        assert operation["operationId"] == spec["operation_id"]


@pytest.mark.asyncio
async def test_provider_rejection_is_redacted_without_retry(monkeypatch):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "Rejected test-registry-token"}})
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
            yield c
    monkeypatch.setattr(mod, "guarded_async_client", client)
    with pytest.raises(ValueError, match=r"401: Rejected \[redacted\]"):
        await node({"operation": "delete_api", "api_id": "petstore"}).execute({})
    assert len(calls) == 1

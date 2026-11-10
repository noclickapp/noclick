"""Request-contract and stateful poll regressions. No provider account is used."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import appcenter_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-appcenter-token-42"
APP = {"owner_name": "owner", "app_name": "app"}
GROUP = {**APP, "distribution_group_name": "beta testers"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/appcenter/crash_groups.json").read_text())["body"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="appcenter-fixture", node_type="automation-appcenter",
        node_data={"config": config, "credentials": credential or {"credential_type": "appcenter_api_token", "api_token": TOKEN}})


def transport(monkeypatch, handler):
    requests = []
    def reply(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_user"}, "GET", "/v0.1/user", {}, None),
    ({"operation": "list_apps", "order_by": "name"}, "GET", "/v0.1/apps", {"$orderBy": "name"}, None),
    ({"operation": "get_app", **APP}, "GET", "/v0.1/apps/owner/app", {}, None),
    ({"operation": "create_app", "display_name": "Demo", "os": "Android", "platform": "Java"}, "POST", "/v0.1/apps", {}, {"display_name": "Demo", "os": "Android", "platform": "Java"}),
    ({"operation": "update_app", **APP, "description": "Updated"}, "PATCH", "/v0.1/apps/owner/app", {}, {"description": "Updated"}),
    ({"operation": "list_organizations"}, "GET", "/v0.1/orgs", {}, None),
    ({"operation": "get_organization", "org_name": "team"}, "GET", "/v0.1/orgs/team", {}, None),
    ({"operation": "list_releases", **APP, "published_only": False, "release_id": 4}, "GET", "/v0.1/apps/owner/app/releases", {"published_only": "false", "top": "100", "releaseId": "4"}, None),
    ({"operation": "get_release", **APP, "release_id": "latest"}, "GET", "/v0.1/apps/owner/app/releases/latest", {}, None),
    ({"operation": "update_release", **APP, "release_id": 4, "enabled": False}, "PUT", "/v0.1/apps/owner/app/releases/4", {}, {"enabled": False}),
    ({"operation": "distribute_release", **APP, "release_id": 4, "destinations": [{"id": "dest-1"}], "notify_testers": False}, "PATCH", "/v0.1/apps/owner/app/releases/4", {}, {"destinations": [{"id": "dest-1"}], "notify_testers": False}),
    ({"operation": "list_distribution_groups", **APP}, "GET", "/v0.1/apps/owner/app/distribution_groups", {}, None),
    ({"operation": "get_distribution_group", **GROUP}, "GET", "/v0.1/apps/owner/app/distribution_groups/beta testers", {}, None),
    ({"operation": "create_distribution_group", **APP, "name": "beta"}, "POST", "/v0.1/apps/owner/app/distribution_groups", {}, {"name": "beta"}),
    ({"operation": "update_distribution_group", **GROUP, "is_public": False}, "PATCH", "/v0.1/apps/owner/app/distribution_groups/beta testers", {}, {"is_public": False}),
    ({"operation": "list_group_members", **GROUP, "exclude_pending_invitations": False}, "GET", "/v0.1/apps/owner/app/distribution_groups/beta testers/members", {"exclude_pending_invitations": "false"}, None),
    ({"operation": "add_group_members", **GROUP, "user_emails": ["tester@example.com"]}, "POST", "/v0.1/apps/owner/app/distribution_groups/beta testers/members", {}, {"user_emails": ["tester@example.com"]}),
    ({"operation": "list_crash_groups", **APP, "last_occurrence_from": "2025-01-01T00:00:00Z", "continuation_token": "next+cursor"}, "GET", "/v0.1/apps/owner/app/crash_groups", {"$orderby": "last_occurrence desc", "last_occurrence_from": "2025-01-01T00:00:00Z", "continuation_token": "next+cursor"}, None),
    ({"operation": "get_crash_group", **APP, "crash_group_id": "group-1"}, "GET", "/v0.1/apps/owner/app/crash_groups/group-1", {}, None),
    ({"operation": "update_crash_group", **APP, "crash_group_id": "group-1", "status": "closed", "annotation": "Fixed"}, "PATCH", "/v0.1/apps/owner/app/crash_groups/group-1", {}, {"status": "closed", "annotation": "Fixed"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_exact_contract_requests(monkeypatch, config, method, path, query, body):
    response = FIXTURE if config["operation"] == "list_crash_groups" else {"id": "account-1", "display_name": "Account"}
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=response))
    result = await node(config).execute({})
    assert result == {"data": response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.scheme == "https" and request.url.host == "api.appcenter.ms"
    assert dict(request.url.params) == query
    assert request.headers["X-API-Token"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert "Authorization" not in request.headers
    if body is not None:
        assert request.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(401, json={"error": {"message": "token rejected"}}), httpx.Response(302, headers={"location": "https://other.example"}), httpx.Response(200, json={"error": {"message": "failed"}}), httpx.Response(200, text="<html>error</html>"), httpx.Response(200), httpx.Response(200, json="wrong shape")])
async def test_provider_failures_do_not_look_successful(monkeypatch, response):
    requests = transport(monkeypatch, lambda _: response)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        await node({"operation": "get_user"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_rejection_preserves_provider_reason_and_redacts_token(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(403, json={"error": {"message": "Denied " + TOKEN}}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_user"}).execute({})
    assert "403" in str(exc.value) and "Denied" in str(exc.value) and TOKEN not in str(exc.value)


@pytest.mark.parametrize("value", ["..", "a/b", "https://example.com", "a?b", "a\nb"])
def test_path_injection_is_rejected(value):
    with pytest.raises(ValueError):
        node({"operation": "get_app", **APP, "app_name": value})


def test_manual_credential_default_and_secret_shaping():
    assert native.AppCenterTokenCredential(api_token="  " + TOKEN + "  ").credential_type == "appcenter_api_token"
    for token in ["https://example.com/key", "my token", "bad\nheader"]:
        with pytest.raises((ValidationError, ValueError)):
            native.AppCenterTokenCredential(api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [
    {"operation": "update_app", **APP}, {"operation": "update_release", **APP, "release_id": 4},
    {"operation": "update_distribution_group", **GROUP},
    {"operation": "update_crash_group", **APP, "crash_group_id": "group-1"},
])
async def test_empty_updates_do_not_send_requests(monkeypatch, config):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="at least one"):
        await node(config).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_poll_baseline_new_update_dedup_and_agent_context(monkeypatch):
    payload = copy.deepcopy(FIXTURE)
    transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    config = {"operation": "on_new_or_updated_crash_group", **APP}
    instance = node(config)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(state)
        if new is not None:
            state = new
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))["new_or_updated_count"] == 0
    assert (await instance.execute({}))["new_or_updated_count"] == 0
    payload["crash_groups"][0]["last_occurrence"] = "2025-01-03T00:00:00Z"
    payload["crash_groups"][0]["count"] = 3
    result = await instance.execute({})
    assert result["new_or_updated_count"] == 1
    event = instance.resolve_agent_event(result)
    assert all(text in event["text"] for text in ("owner/app", "group-1", "NullPointerException", "2025-01-03", "3"))
    assert instance.trigger_emitted_event(result)
    assert (await instance.execute({}))["new_or_updated_count"] == 0
    assert instance.trigger_produced_no_event({})
    payload["crash_groups"].append({**payload["crash_groups"][0], "crash_group_id": "group-2"})
    assert (await instance.execute({}))["crash_groups"][0]["crash_group_id"] == "group-2"
    assert poll_scope(native.AppCenterNode, config) == poll_scope(native.AppCenterNode, {**config, "label": "cosmetic"})
    assert poll_scope(native.AppCenterNode, config) != poll_scope(native.AppCenterNode, {**config, "app_name": "other"})


@pytest.mark.asyncio
async def test_poll_paginates_before_recording_seen_and_preserves_filters(monkeypatch):
    def reply(request):
        if request.url.params.get("continuation_token") == "next":
            return httpx.Response(200, json={**FIXTURE, "crash_groups": [{**FIXTURE["crash_groups"][0], "crash_group_id": "group-2"}]})
        return httpx.Response(200, json={**FIXTURE, "continuation_token": "next", "limited_result_set": True})
    requests = transport(monkeypatch, reply)
    instance = node({"operation": "on_new_or_updated_crash_group", **APP, "app_version": "1.0", "group_status": "open"})
    async def update(mutator, **kwargs):
        return mutator({"seen_ids": []})[1]
    instance._update_node_state = update
    result = await instance.execute({})
    assert result["new_or_updated_count"] == 2 and len(requests) == 2
    assert all(r.url.params["app_version"] == "1.0" and r.url.params["group_status"] == "open" and r.url.params["$orderby"] == "last_occurrence desc" for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"limited_result_set": True, "crash_groups": []},
    {"limited_result_set": False, "crash_groups": [{}]},
    {**FIXTURE, "continuation_token": "repeated"},
])
async def test_incomplete_or_invalid_poll_never_records_seen(monkeypatch, payload):
    transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    instance = node({"operation": "on_new_or_updated_crash_group", **APP})
    async def no_write(*args, **kwargs):
        pytest.fail("must not record an incomplete response")
    instance._update_node_state = no_write
    with pytest.raises(ValueError):
        await instance.execute({})

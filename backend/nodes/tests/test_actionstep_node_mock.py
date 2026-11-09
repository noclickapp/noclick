"""Offline Actionstep wire/response and OAuth regressions; no live account.

fixtures/actionstep/matter.json is copied from https://docs.actionstep.com/api-responses/.
Other responses below are synthetic and are never used as conformance witnesses.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import actionstep_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.actionstep_oauth import API_ENDPOINT, OAUTH_PROVIDER

TOKEN = "actionstep-synthetic-test-token"
CREDENTIAL = {"credential_type": "actionstep_oauth", "access_token": TOKEN,
    "refresh_token": "actionstep-synthetic-refresh-token", "api_endpoint": "https://ap-southeast-2.actionstep.com/api/",
    "expires_at": "2099-01-01T00:00:00+00:00"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="actionstep-test", node_type="automation-actionstep",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def intercept(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config(operation):
    result = {"operation": operation}
    method, resource, single = native.OPERATIONS[operation]
    if single:
        result["id"] = 3
    if method in {"POST", "PUT"}:
        if resource == "participants":
            result["first_name"] = "James"
            if method == "POST":
                result["display_name"] = "Bond, James"
        elif resource == "tasks":
            result.update(name="Research", due_timestamp="2026-11-09T12:00:00+00:00", matter_id=3, assignee_id=14)
        else:
            result["text"] = "Follow up with client"
            if method == "POST":
                result["matter_id"] = 3
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.OPERATIONS))
async def test_actionstep_each_operation_uses_one_documented_route(monkeypatch, operation):
    method, resource, single = native.OPERATIONS[operation]
    def reply(request):
        if method == "DELETE":
            return httpx.Response(204)
        data = {"id": 3, "name": "Test"}
        body = {resource: data if single or method == "POST" else [data]}
        if operation.startswith("list_"):
            body["meta"] = {"paging": {resource: {"page": 1, "pageSize": 50,
                "nextPage": "https://ap-southeast-2.actionstep.com/api/rest/" + resource + "?page=2"}}}
        return httpx.Response(200, json=body)
    requests = intercept(monkeypatch, reply)
    result = await node(config(operation)).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "ap-southeast-2.actionstep.com"
    assert request.url.path == "/api/rest/" + resource + ("/3" if single else "")
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["content-type"] == "application/vnd.api+json"
    if method in {"POST", "PUT"}:
        body = json.loads(request.content)
        assert set(body) == {resource}
        if method == "PUT":
            assert body[resource]["id"] == 3
        if resource == "tasks":
            assert body[resource]["links"] == {"action": 3, "assignee": 14}
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"page": "1", "pageSize": "50"}
        assert result["next_page"] == 2 and result["has_more"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_actionstep_documented_matter_response(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/actionstep/matter.json").read_text())
    intercept(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({"operation": "get_matter", "id": 3}).execute({})
    assert result["status"] == "success"
    assert result["data"]["name"] == "Matter No 3"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": [{"message": "No access"}]}, {"actions": {"id": 9}}, {"actions": {"id": None}}])
async def test_actionstep_missing_error_or_wrong_id_never_succeeds(monkeypatch, body):
    intercept(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({"operation": "get_matter", "id": 3}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_actionstep_rejection_does_not_expose_upstream_tokens(monkeypatch, status):
    intercept(monkeypatch, lambda _: httpx.Response(status, json={"error": TOKEN}))
    result = await node({"operation": "get_matter", "id": 3}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_actionstep_list_filters_and_nonadvancing_pagination(monkeypatch):
    requests = intercept(monkeypatch, lambda _: httpx.Response(200, json={"tasks": [],
        "meta": {"paging": {"tasks": {"page": 2, "nextPage": "https://ap-southeast-2.actionstep.com/api/rest/tasks?page=2"}}}}))
    result = await node({"operation": "list_tasks", "page": 2, "matter_id": 34}).execute({})
    assert dict(requests[0].url.params) == {"page": "2", "pageSize": "50", "action_eq": "34"}
    assert result["status"] == "error"


@pytest.mark.parametrize("value", [2, "https://evil.example/api/rest/tasks?page=3",
    "https://ap-southeast-2.actionstep.com/api/rest/participants?page=3",
    "https://ap-southeast-2.actionstep.com/api/rest/tasks?page=3&page=4",
    "https://ap-southeast-2.actionstep.com/api/rest/tasks?page=1000001"])
def test_actionstep_continuation_refuses_wrong_origin_resource_or_page(value):
    with pytest.raises(ValueError):
        native.ActionstepNode._next_page(value, origin="https://ap-southeast-2.actionstep.com", resource="tasks", current=2)


def test_actionstep_contract_continuation_url_and_documented_terminal_null():
    kwargs = {"origin": "https://ap-southeast-2.actionstep.com", "resource": "tasks", "current": 2}
    assert native.ActionstepNode._next_page("https://ap-southeast-2.actionstep.com/api/rest/tasks?page=3", **kwargs) == 3
    assert native.ActionstepNode._next_page(None, **kwargs) is None


@pytest.mark.parametrize("endpoint", ["https://evil.example/api/", "https://ap-southeast-2.actionstep.com.evil.example/api/",
    "http://ap-southeast-2.actionstep.com/api/", "https://ap-southeast-2.actionstep.com/other/",
    "https://ap-southeast-2.actionstep.com/api/?key=1", "https://user@ap-southeast-2.actionstep.com/api/"])
def test_actionstep_regional_origin_is_closed(endpoint):
    with pytest.raises(ValueError):
        API_ENDPOINT.validate(endpoint)


def test_actionstep_refresh_requires_rotation_and_adopts_region(monkeypatch):
    for key in ["ACTIONSTEP_CLIENT_ID", "ACTIONSTEP_CLIENT_SECRET", "ACTIONSTEP_REDIRECT_URI"]:
        monkeypatch.setenv(key, "test-" + key)
    request = OAUTH_PROVIDER.token_request({"grant_type": "refresh_token", "refresh_token": "old"})
    assert request["data"]["redirect_uri"] == "test-ACTIONSTEP_REDIRECT_URI"
    payload = {"access_token": "new", "refresh_token": "rotated", "expires_in": 28800,
               "api_endpoint": "https://eu-west-1.actionstep.com/api/", "orgkey": "legalES"}
    tokens, _ = OAUTH_PROVIDER.parse_tokens(httpx.Response(200, json=payload), context={"api_endpoint": CREDENTIAL["api_endpoint"]})
    assert tokens.api_endpoint == "https://eu-west-1.actionstep.com" and tokens.orgkey == "legalES"
    del payload["refresh_token"]
    with pytest.raises(ValueError):
        OAUTH_PROVIDER.parse_tokens(httpx.Response(200, json=payload), context={"api_endpoint": CREDENTIAL["api_endpoint"]})


@pytest.mark.asyncio
async def test_actionstep_expiry_refresh_routes_to_new_region(monkeypatch):
    import nodes.core.oauth_refresh as refresh
    async def fresh(**kwargs):
        assert set(kwargs["additional_token_fields"]) == {"orgkey", "api_endpoint"}
        kwargs["credential"]["api_endpoint"] = "https://eu-west-1.actionstep.com"
        return "new-access-token"
    monkeypatch.setattr(refresh, "ensure_fresh_oauth_token", fresh)
    requests = intercept(monkeypatch, lambda _: httpx.Response(200, json={"actions": {"id": 3}}))
    assert (await node({"operation": "get_matter", "id": 3}).execute({}))["status"] == "success"
    assert requests[0].url.host == "eu-west-1.actionstep.com"
    assert requests[0].headers["authorization"] == "Bearer new-access-token"


def test_actionstep_manual_credentials_have_type_default_and_validate():
    cred = native.ActionstepOAuthCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert cred.credential_type == "actionstep_oauth"
    assert cred.api_endpoint == "https://ap-southeast-2.actionstep.com"
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS["create_task"](name="Test", matter_id=3, assignee_id=14, due_timestamp="tomorrow")


@pytest.mark.asyncio
async def test_actionstep_identity_matches_official_demo(monkeypatch):
    import utils.ssrf
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"linked": {"participants": [{"id": 14, "firstName": "James", "lastName": "Bond"}]}})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(utils.ssrf, "guarded_async_client", client)
    assert await OAUTH_PROVIDER.account_name(TOKEN, context={"api_endpoint": "https://ap-southeast-2.actionstep.com"}) == "James"
    assert requests[0].url.path == "/api/rest/users/current"
    assert dict(requests[0].url.params) == {"include": "participant", "fields[participants]": "id,firstName,lastName"}
    assert requests[0].headers["accept"] == "application/vnd.api+json"

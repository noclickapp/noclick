"""BugSnag request contracts; external HTTP is mocked, not live QA."""

import json
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.bugsnag_node import (
    API_BASE, ROUTES, BugsnagNode, BugsnagNodeConfig, _path, _request,
)
from nodes.agent.node_op_tools import node_supports_op_tools, list_node_operations


def _node(action: str, **values):
    return BugsnagNode(
        node_id="b", node_type="automation-bugsnag", node_data={},
        config=BugsnagNodeConfig(
            config={"operation": action, **values},
            credentials={"auth_token": "private-test-token"},
        ),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


def _required(action):
    samples = {
        "organization_id": "org1", "project_id": "proj1", "error_id": "err1",
        "event_id": "ev1", "comment_id": "comment1", "release_id": "release1",
        "collaborator_id": "collab1", "name": "NoClick QA", "project_type": "rails",
        "body_json": '{"name":"NoClick QA"}', "error_operation": "fix",
        "message": "QA note", "display_id": "user.id", "field_path": "user.id",
        "confirm_delete": True,
        "auto_upgrade": False, "filter_options_json": '{"name":"plan tier"}',
    }
    return {name: samples[name] for name in ROUTES[action].required}


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(ROUTES))
async def test_all_actions_dispatch_to_documented_path(action):
    route = ROUTES[action]
    captured = {}

    async def fake(token, method, path, *, params=None, body=None):
        captured.update(token=token, method=method, path=path, params=params, body=body)
        return [{"id": "example"}], None

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        result = await _node(action, **_required(action)).execute({})
    assert captured["token"] == "private-test-token"
    assert captured["method"] == route.method
    assert captured["path"].startswith("/")
    assert "{" not in captured["path"]
    assert result["action"] == action
    assert result["count"] == 1


def test_versioned_schema_exposes_all_actions_and_connection_evidence():
    schema = BugsnagNode.get_config_schema()
    assert len(ROUTES) == 36
    assert schema["properties"]["config"]["oneOf"]
    assert BugsnagNode.connection_evidence.field == "organization_id"
    assert "auth_token" in schema["$defs"]["BugsnagAuthTokenCredential"]["properties"]
    credential = schema["$defs"]["BugsnagAuthTokenCredential"]
    assert credential["title"] == "Bugsnag Personal Auth Token"
    assert credential["properties"]["credential_type"]["const"] == "bugsnag_auth_token"
    assert BugsnagNode.integration_type == "automation-bugsnag"
    assert "x-oauth-provider" not in credential
    assert node_supports_op_tools("automation-bugsnag")
    assert len(list_node_operations("automation-bugsnag")) == 36


def test_path_encodes_an_id_as_one_segment():
    path = _path(ROUTES["get_error"], {"project_id": "one/two", "error_id": "e?x"})
    assert path == "/projects/one%2Ftwo/errors/e%3Fx"


@pytest.mark.asyncio
async def test_error_update_sends_operation_and_optional_severity():
    captured = {}

    async def fake(token, method, path, *, params=None, body=None):
        captured.update(method=method, path=path, body=body)
        return {"status": "fixed"}, None

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        result = await _node("update_error", project_id="p", error_id="e", error_operation="fix", severity="warning").execute({})
    assert captured == {"method": "PATCH", "path": "/projects/p/errors/e", "body": {"operation": "fix", "severity": "warning"}}
    assert result["data"]["status"] == "fixed"


@pytest.mark.asyncio
async def test_project_create_uses_bugsnag_type_field():
    captured = {}

    async def fake(token, method, path, *, params=None, body=None):
        captured["body"] = body
        return {}, None

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        await _node("create_project", organization_id="o", name="QA", project_type="rails").execute({})
    assert captured["body"] == {"name": "QA", "type": "rails"}


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_upgrade", [False, True])
async def test_organization_update_sends_explicit_auto_upgrade(auto_upgrade):
    def respond(request):
        assert request.method == "PATCH"
        assert request.url.path == "/organizations/515fb9337c1074f6fd000001"
        assert json.loads(request.content) == {"name": "Acme Co.", "auto_upgrade": auto_upgrade}
        return httpx.Response(200, json={"name": "Acme Co.", "auto_upgrade": auto_upgrade})

    with httpx.MockTransport(respond) as transport:
        client = httpx.AsyncClient(transport=transport, base_url=API_BASE)
        with patch("nodes.bugsnag_node.httpx.AsyncClient", return_value=client):
            await _node("update_organization", organization_id="515fb9337c1074f6fd000001",
                        name="Acme Co.", auto_upgrade=auto_upgrade).execute({})


def test_required_provider_fields_are_validated_before_execution():
    with pytest.raises(ValidationError, match="auto_upgrade"):
        _node("update_organization", organization_id="o", name="Acme Co.")
    with pytest.raises(ValidationError, match="filter_options_json"):
        _node("create_event_field", project_id="p", display_id="user.id", field_path="user.id")


@pytest.mark.asyncio
async def test_custom_event_field_sends_required_filter_options():
    def respond(request):
        assert request.method == "POST"
        assert request.url.path == "/projects/515fb9337c1074f6fd000001/event_fields"
        assert json.loads(request.content) == {
            "display_id": "user.id", "path": "metaData.plan.tier",
            "filter_options": {"name": "plan tier"},
        }
        return httpx.Response(201, json={"display_id": "user.id"})

    with httpx.MockTransport(respond) as transport:
        client = httpx.AsyncClient(transport=transport, base_url=API_BASE)
        with patch("nodes.bugsnag_node.httpx.AsyncClient", return_value=client):
            await _node("create_event_field", project_id="515fb9337c1074f6fd000001",
                        display_id="user.id", field_path="metaData.plan.tier",
                        filter_options_json='{"name":"plan tier"}').execute({})


@pytest.mark.asyncio
async def test_invalid_json_and_deletion_confirmation_fail_before_http():
    with patch("nodes.bugsnag_node._request") as request:
        with pytest.raises(ValueError, match="valid JSON"):
            await _node("update_project", project_id="p", body_json="{").execute({})
        with pytest.raises(ValueError, match="Confirm permanent deletion"):
            await _node("delete_project", project_id="p", confirm_delete=False).execute({})
    request.assert_not_called()


@pytest.mark.asyncio
async def test_org_options_prove_credential_against_account_data():
    async def fake(token, method, path, *, params=None, body=None):
        assert path == "/user/organizations"
        return [{"id": "123", "name": "NoClick QA"}], None

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        options = await BugsnagNode.load_field_options(
            "organization_id", {"auth_token": "key"}, page_token=None, search="noclick",
        )
    assert options == {"options": [{"value": "123", "label": "NoClick QA"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_http_auth_version_and_next_page_without_echoing_token():
    with httpx.MockTransport(lambda req: httpx.Response(
        200, json=[{"id": "o"}], headers={"Link": '<https://api.bugsnag.com/user/organizations?page=2>; rel="next"'},
    )) as transport:
        with patch("nodes.bugsnag_node.httpx.AsyncClient", wraps=httpx.AsyncClient) as client_class:
            client_class.return_value = httpx.AsyncClient(transport=transport, base_url=API_BASE)
            data, next_link = await _request("secret", "GET", "/user/organizations")
    assert data == [{"id": "o"}]
    assert next_link == "https://api.bugsnag.com/user/organizations?page=2"


@pytest.mark.asyncio
async def test_http_error_never_returns_provider_body_or_token():
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def request(self, method, path, **kwargs):
            assert kwargs["headers"]["Authorization"] == "token secret"
            assert kwargs["headers"]["X-Version"] == "2"
            return httpx.Response(401, json={"error": "secret was echoed"}, request=httpx.Request(method, API_BASE + path))

    with patch("nodes.bugsnag_node.httpx.AsyncClient", return_value=FakeClient()):
        with pytest.raises(ValueError) as exc:
            await _request("secret", "GET", "/user/organizations")
    assert "HTTP 401" in str(exc.value)
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_project_notifier_key_is_redacted_from_workflow_output():
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def request(self, method, path, **kwargs):
            return httpx.Response(200, json=[{"id": "p", "api_key": "notifier-secret"}],
                                  request=httpx.Request(method, API_BASE + path))

    with patch("nodes.bugsnag_node.httpx.AsyncClient", return_value=FakeClient()):
        data, _ = await _request("token", "GET", "/organizations/o/projects")
    assert data == [{"id": "p", "api_key": "[REDACTED]"}]


@pytest.mark.asyncio
async def test_all_pages_follows_only_bugsnag_link_and_joins_rows():
    paths = []

    async def fake(token, method, path, *, params=None, body=None):
        paths.append(path)
        if len(paths) == 1:
            return [{"id": "first"}], "https://api.bugsnag.com/user/organizations?offset=1"
        return [{"id": "second"}], None

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        result = await _node("list_organizations", all_pages=True).execute({})
    assert paths == ["/user/organizations", "/user/organizations?offset=1"]
    assert result["count"] == 2
    assert [row["id"] for row in result["data"]] == ["first", "second"]


@pytest.mark.asyncio
async def test_all_pages_rejects_external_next_link():
    async def fake(token, method, path, *, params=None, body=None):
        return [{"id": "first"}], "https://another.example.com/steal"

    with patch("nodes.bugsnag_node._request", side_effect=fake):
        with pytest.raises(ValueError, match="outside its API host"):
            await _node("list_organizations", all_pages=True).execute({})

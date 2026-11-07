"""Native Coolify factory/connect/dispatcher/socket/current-credential seams.

Synthetic metadata only. Explicit MockTransport; execution requires root lane.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from nodes import coolify_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-coolify"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
TOKEN = {"credential_type": native.TYPE, "api_url": "https://coolify.fixture.com", "expected_team_id": 7, "api_token": "12|syntheticPrivateToken0123456789"}
TEAM = {"id": 7, "name": "Synthetic team", "members": ["omit-person"], "custom_server_limit": 100}
PROJECT = {"id": 8, "uuid": "projectFixture", "name": "Synthetic project", "description": "Fixture only", "team_id": 7, "environment_variables": ["omit-variable"]}
ENV = {"id": 9, "uuid": "envFixture", "name": "Synthetic environment", "project_id": 8, "description": None, "applications": [{"docker_compose_raw": "omit-secret"}], "redis": [{"password": "omit-password"}]}
APP = {"id": 10, "uuid": "appFixture", "name": "Synthetic app", "environment_id": 9, "status": "running:healthy", "docker_compose_raw": "omit-compose", "fqdn": "https://private.example.test", "manual_webhook_secret_github": "omit-secret"}
SERVICE = {"id": 11, "uuid": "serviceFixture", "name": "Synthetic service", "environment_id": 9, "docker_compose_raw": "omit-compose", "applications": [{"password": "omit-secret"}]}
DEPLOYMENT = {"id": 12, "deployment_uuid": "deployFixture", "application_id": "10", "status": "finished", "logs": "omit-private-logs", "config_snapshot": "omit-private-config", "server_name": "omit-server", "deployment_url": "https://private.example.test"}


def node(operation, raw=TOKEN, **args):
    return NodeFactory.create_node(node_id="coolify-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


def parents(): return [TEAM, [PROJECT], PROJECT, [ENV], ENV]


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        calls.append(request)
        data = responses.pop(0)
        if callable(data): data = data()
        return data if isinstance(data, httpx.Response) else httpx.Response(200, json=data)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as value: yield value
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("value", [True, "20", 20.5, "20x", 0, 101, 9007199254740993])
def test_actual_factory_refuses_malformed_limit_before_io(transport, value):
    with pytest.raises(ValueError): node("list_projects", limit=value)
    assert transport[0] == []


@pytest.mark.parametrize("field,value", [("skip", "2"), ("skip", -1), ("skip", True), ("take", 0), ("take", 1.5), ("take", "1x")])
def test_actual_factory_strict_provider_paging_before_io(transport, field, value):
    with pytest.raises(ValueError): node("list_deployments", project_uuid="projectFixture", environment_uuid="envFixture", application_uuid="appFixture", **{field: value})
    assert transport[0] == []


@pytest.mark.parametrize("origin", ["http://coolify.fixture.com", "https://localhost", "https://127.0.0.1", "https://[::1]", "https://coolify.fixture.com/", "https://Coolify.fixture.com", "https://coolify.fixture.com.", "https://coolify.fixture.com:443", "https://coolify.fixture.com:0", "https://user:pass@coolify.fixture.com", "https://coolify.fixture.com/api", "https://coolify.fixture.com?q=1", "https://coolify.internal"])
def test_canonical_public_origin_refused_before_io(transport, origin):
    with pytest.raises(ValueError): node("check_connection", raw={**TOKEN, "api_url": origin})
    assert transport[0] == []


def test_intentional_https_port_retained_in_native_credentials():
    assert native.credential({**TOKEN, "api_url": "https://coolify.fixture.com:8443"}).api_url.endswith(":8443")


def test_actual_factory_foreign_discriminator_precedes_misleading_attachment(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"credentials": {**TOKEN, "credential_type": "rossum_token"}, "credentialIds": {native.TYPE: CID}, "config": {"operation": "check_connection"}}, sio=None, sid=None)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_preparsed_foreign_blob_refuses_before_transport(transport):
    instance = node("check_connection")
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_visible_form_connect_tags_literal_and_proves_bound_team(transport):
    transport[1].append(TEAM)
    visible = {"api_url": TOKEN["api_url"], "expected_team_id": "7", "api_token": TOKEN["api_token"]}
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data=visible, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE and verdict.credential_data["expected_team_id"] == 7
    assert verdict.evidence.account_label == "Synthetic team"
    assert "omit" not in repr(verdict.evidence)
    assert transport[0][0].url.path == "/api/v1/teams/current"
    assert transport[0][0].headers["authorization"] == "Bearer " + TOKEN["api_token"]
    assert all("health" not in str(request.url) for request in transport[0])


@pytest.mark.asyncio
async def test_actual_dispatch_parent_bound_deployment_projection(transport):
    transport[1].extend(parents() + [APP, DEPLOYMENT])
    result = await run_node_operation(node_type=NT, operation="get_deployment", arguments={"project_uuid": "projectFixture", "environment_uuid": "envFixture", "application_uuid": "appFixture", "deployment_uuid": "deployFixture"}, user_id=USER, credential_data=TOKEN)
    assert result["data"] == {"id": 12, "deployment_uuid": "deployFixture", "application_id": 10, "status": "finished", "created_at": None, "updated_at": None}
    assert "omit" not in repr(result) and "private.example" not in repr(result)
    assert [request.url.path for request in transport[0]] == ["/api/v1/teams/current", "/api/v1/projects", "/api/v1/projects/projectFixture", "/api/v1/projects/projectFixture/environments", "/api/v1/projects/projectFixture/envFixture", "/api/v1/applications/appFixture", "/api/v1/deployments/deployFixture"]


@pytest.mark.asyncio
async def test_parent_mismatch_refuses_before_deployment_request(transport):
    transport[1].extend(parents() + [{**APP, "environment_id": 999}])
    with pytest.raises(native.OutcomeUnverified): await node("get_deployment", project_uuid="projectFixture", environment_uuid="envFixture", application_uuid="appFixture", deployment_uuid="deployFixture").execute({})
    assert len(transport[0]) == 6 and all("deployments" not in request.url.path for request in transport[0])


@pytest.mark.asyncio
async def test_provider_history_uses_real_count_deployments_envelope_and_integer_query(transport):
    transport[1].extend(parents() + [APP, {"count": 3, "deployments": [DEPLOYMENT]}])
    result = await node("list_deployments", project_uuid="projectFixture", environment_uuid="envFixture", application_uuid="appFixture", skip=1, take=1).execute({})
    assert dict(transport[0][-1].url.params) == {"skip": "1", "take": "1"}
    assert result["data"]["next_skip"] == 2 and result["data"]["paging"] == "provider_skip_take"
    assert "omit" not in repr(result)


@pytest.mark.asyncio
async def test_local_inventory_slice_is_not_fabricated_provider_paging(transport):
    transport[1].extend([TEAM, [PROJECT, {**PROJECT, "id": 20, "uuid": "otherProject"}]])
    result = await node("list_projects", limit=1, offset=0).execute({})
    assert result["data"]["next_offset"] == 1 and result["data"]["paging"] == "local_inventory_slice"
    assert not transport[0][-1].url.query


@pytest.mark.asyncio
async def test_project_update_201_sends_only_supplied_fields_then_independent_get(transport):
    changed = {**PROJECT, "description": None}
    transport[1].extend([TEAM, [PROJECT], PROJECT, httpx.Response(201, json={"uuid": "projectFixture"}), [changed], changed])
    result = await node("update_project", project_uuid="projectFixture", description=None).execute({})
    assert json.loads(transport[0][3].content) == {"description": None}
    assert transport[0][3].method == "PATCH" and transport[0][4].method == "GET"
    assert result["data"]["status_code"] == 201 and result["data"]["readback_verified"] is True


@pytest.mark.asyncio
async def test_environment_rename_retains_uuid_and_get_route_differs_from_patch(transport):
    changed = {**ENV, "name": "Renamed fixture"}
    transport[1].extend(parents() + [{"uuid": "envFixture"}, [changed], changed])
    result = await node("update_environment", project_uuid="projectFixture", environment_uuid="envFixture", name="Renamed fixture").execute({})
    assert transport[0][5].url.path == "/api/v1/projects/projectFixture/environments/envFixture"
    assert json.loads(transport[0][5].content) == {"name": "Renamed fixture"}
    assert transport[0][-1].url.path == "/api/v1/projects/projectFixture/envFixture"
    assert result["data"]["environment"]["uuid"] == "envFixture" and result["data"]["readback_verified"] is True


@pytest.mark.asyncio
async def test_create_project_acknowledgment_requires_matching_independent_readback(transport):
    transport[1].extend([TEAM, httpx.Response(201, json={"uuid": "projectFixture"}), [PROJECT], PROJECT])
    with pytest.raises(native.OutcomeUnverified): await node("create_project", name="Different name").execute({})
    assert sum(request.method == "POST" for request in transport[0]) == 1


@pytest.mark.parametrize("operation", ["delete_project", "delete_empty_project", "delete_environment", "start", "stop", "cancel_deployment", "get_envs", "get_logs"])
def test_cascading_deletes_and_execution_secret_routes_absent(transport, operation):
    with pytest.raises(ValueError): node(operation)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(401, False), (403, None), (429, None), (500, None)])
async def test_connection_rejection_unknown_and_error_redaction(transport, status, valid):
    transport[1].append(httpx.Response(status, json={"message": TOKEN["api_token"]}, headers={"Retry-After": "60"}))
    verdict = await native.CoolifyNode.validate_credential_access(TOKEN)
    assert verdict["valid"] is valid and TOKEN["api_token"] not in repr(verdict)


@pytest.fixture
def stored(monkeypatch):
    state = {"credential": deepcopy(TOKEN), "accessible": True}
    async def load(identifier, principal, pool, **kwargs):
        assert identifier == CID and principal == USER
        return deepcopy(state["credential"]) if state["accessible"] else None
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", load)
    return state


@pytest.mark.asyncio
async def test_saved_missing_caller_and_foreign_credential_never_open_transport(stored, transport):
    with pytest.raises(ValueError): await native.Authority.create(TOKEN, pool=object(), credential_id=CID, organization_id=None)
    stored["credential"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await native.Authority.create(TOKEN, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["access", "kind", "token", "team", "origin"])
async def test_saved_credential_change_during_response_blocks_output(stored, transport, change):
    auth = await native.Authority.create(TOKEN, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    def changed():
        if change == "access": stored["accessible"] = False
        else:
            key, value = {"kind": ("credential_type", "foreign"), "token": ("api_token", "12|replacementPrivateToken012345"), "team": ("expected_team_id", 99), "origin": ("api_url", "https://other.fixture.com")}[change]
            stored["credential"][key] = value
        return TEAM
    transport[1].append(changed)
    with pytest.raises(ValueError): await native.operate(auth, native.CheckConnection())
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_actual_socket_denies_inaccessible_saved_picker_before_provider(monkeypatch, transport):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value=None))
    @asynccontextmanager
    async def acquire(): yield conn
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    loader = AsyncMock(wraps=native.CoolifyNode.load_field_options)
    monkeypatch.setattr(native.CoolifyNode, "load_field_options", loader)
    sent = AsyncMock(); monkeypatch.setattr(workflow_handler, "send_event", sent)
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=SimpleNamespace(acquire=acquire))
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="fixture-request", node_type=NT, credential_id=CID, field_name="project_uuid", context={}))
    conn.fetchrow.assert_awaited_once(); loader.assert_not_awaited()
    assert transport[0] == [] and sent.await_count == 1


@pytest.mark.asyncio
async def test_real_scoped_environment_picker_and_missing_parent_no_io(transport):
    with pytest.raises(ValueError): await native.CoolifyNode.load_field_options("environment_uuid", TOKEN, context={})
    assert transport[0] == []
    transport[1].extend([TEAM, [PROJECT], PROJECT, [ENV]])
    result = await native.CoolifyNode.load_field_options("environment_uuid", TOKEN, context={"project_uuid": "projectFixture"})
    assert result == {"options": [{"value": "envFixture", "label": "Synthetic environment"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_actual_saved_factory_execute_missing_caller_denies_before_io(transport):
    instance = NodeFactory.create_node(node_id="saved", node_type=NT, node_data={"credential_id": CID, "config": {"operation": "check_connection"}, "credentials": deepcopy(TOKEN)}, sio=None, sid=None, user_id=None)
    with pytest.raises(ValueError, match="unavailable"): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_wrong_token_team_stops_before_project_inventory(transport):
    transport[1].append({**TEAM, "id": 999})
    with pytest.raises(native.OutcomeUnverified): await node("list_projects").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, {}, [None], [{**PROJECT, "id": True}], [PROJECT, PROJECT]])
async def test_malformed_inventory_shape_is_unverified_not_empty_success(transport, raw):
    transport[1].extend([TEAM, httpx.Response(200, json=raw)])
    with pytest.raises(native.OutcomeUnverified): await node("list_projects").execute({})
    assert len(transport[0]) == 2

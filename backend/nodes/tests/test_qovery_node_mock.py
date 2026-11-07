"""Native Qovery schema/connect/wire/readback fixtures.

Real native factory and schema helpers consume synthetic primary envelopes.
No fixture establishes real Qovery roles, DB access, entitlement or deployment.
"""
import ast
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import qovery_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence

ORG = "66666666-6666-4666-8666-666666666666"
PROJECT = "77777777-7777-4777-8777-777777777777"
ENV = "88888888-8888-4888-8888-888888888888"
CLUSTER = "99999999-9999-4999-8999-999999999999"
SERVICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DEPLOYMENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
KEY = {"credential_type": "qovery_api_token", "api_token": "synthetic-private-machine-token", "organization_id": ORG}
BASE = {"created_at": "2026-10-06T10:00:00Z"}
ORGANIZATION = {**BASE, "id": ORG, "name": "Fixture org", "owner": "private-user", "admin_emails": ["private@example.test"], "plan": "ENTERPRISE"}
PROJECT_ROW = {**BASE, "id": PROJECT, "name": "Fixture project", "organization": {"id": ORG}, "associated_environments_count": 0, "description": "Fixture description"}
ENV_ROW = {**BASE, "id": ENV, "name": "Fixture environment", "organization": {"id": ORG}, "project": {"id": PROJECT}, "cluster_id": CLUSTER, "mode": "DEVELOPMENT", "cloud_provider": {"provider": "AWS", "cluster": "private-cloud-reference"}}
CLUSTER_ROW = {**BASE, "id": CLUSTER, "name": "Fixture cluster", "organization": {"id": ORG}, "region": "eu-west-1", "cloud_provider": "AWS", "ssh_keys": ["private-ssh-key"], "estimated_cloud_provider_cost": 999}
SERVICE_ROW = {**BASE, "id": SERVICE, "name": "Fixture app", "environment": {"id": ENV}, "service_type": "APPLICATION", "source": {"credentials": "private-source"}, "arguments": ["private-argument"]}
ENV_STATUS = {"id": ENV, "state": "READY", "last_deployment_state": "DEPLOYED", "triggered_by": "private-user", "metrics": [{"secret": "private-metric"}]}
SERVICE_STATUS = {"id": SERVICE, "state": "DEPLOYED", "service_deployment_status": "UP_TO_DATE", "is_part_last_deployment": True, "deployment_requests_count": 0, "deployment_request_id": None, "status_details": "private-status-detail", "steps": [{"log": "private-log"}]}


@pytest.fixture
def ensure_native_db_pool():
    yield


class Wire:
    def __init__(self):
        self.calls, self.responses = [], []
        self.organization = deepcopy(ORGANIZATION)

    @asynccontextmanager
    async def client(self, **options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        wire = self
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                wire.calls.append((method, url, kwargs))
                assert url.startswith(p.ROOT + '/') and kwargs['headers']['Authorization'] == 'Token ' + KEY['api_token']
                assert 'api_token' not in str(kwargs['params']) and 'api_token' not in str(kwargs['json'])
                if method == 'GET' and url == p.ROOT + '/organization/' + ORG:
                    response = httpx.Response(200, json=wire.organization)
                else:
                    assert wire.responses, 'Unexpected synthetic Qovery request'
                    result = wire.responses.pop(0)
                    response = result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)
                response.request = httpx.Request(method, url)
                yield response
        yield Client()


@pytest.fixture
def wire(monkeypatch):
    mock = Wire()
    monkeypatch.setattr(p, 'guarded_async_client', mock.client)
    return mock


def node(config, credential=KEY):
    return NodeFactory.create_node('fixture', 'automation-qovery', {'config': config, 'credentials': deepcopy(credential)})


def test_actual_native_schema_and_production_constraint_helper():
    schema = p.QoveryNode.get_config_schema()
    source = Path(__file__).resolve().parents[2] / 'scripts/generate_socket_types.py'
    helpers = [n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_assert_no_incoherent_constraints']
    namespace = {}
    assert len(helpers) == 1
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source), 'exec'), namespace)
    namespace['_assert_no_incoherent_constraints']('qovery', schema)
    actual = {schema['$defs'][entry['$ref'].split('/')[-1]]['properties']['operation']['const'] for entry in schema['properties']['config']['oneOf']}
    assert actual == p.OPERATIONS and len(actual) == 17
    assert schema['$defs']['GetEnvironment']['properties']['environment_id']['x-dynamic-options']['depends_on'] == 'project_id'
    assert schema['$defs']['ServiceStatus']['properties']['service_id']['x-dynamic-options']['depends_on'] == 'environment_id'
    assert schema['$defs']['QoveryAPITokenCredential']['properties']['api_token']['ui:widget'] == 'password'
    assert not actual & {'deploy', 'create_cluster', 'delete_project', 'delete_environment', 'get_secrets', 'raw_request', 'create_token'}


@pytest.mark.parametrize('bad', [True, 1, {}, '../project', 'not-a-uuid', PROJECT + '?token=private'])
def test_actual_native_config_rejects_invalid_resource_ids(bad):
    with pytest.raises(ValidationError): p.GetProject(project_id=bad)


def test_native_credential_and_optional_controls_are_honest():
    assert KEY['api_token'] not in repr(p.guard(KEY))
    assert p.QoveryAPITokenCredential(organization_id=ORG, api_token='bearerOpaqueToken').api_token == 'bearerOpaqueToken'
    with pytest.raises(ValueError) as error: p.guard({**KEY, 'api_token': ['synthetic-private-machine-token']})
    assert KEY['api_token'] not in str(error.value)
    for token in ['Bearer private', 'Token private', 'private\nheader']:
        with pytest.raises(ValidationError): p.QoveryAPITokenCredential(organization_id=ORG, api_token=token)
    parsed = p.UpdateProject(project_id=PROJECT, name='Name', description=None, clear_description=None, expected_snapshot='0' * 64)
    assert parsed.description is None and parsed.clear_description is False
    assert p.EnvironmentDeployments(project_id=PROJECT, environment_id=ENV, start_id=None).start_id is None
    assert p.environment_record({**ENV_ROW, 'mode': 'PREVIEW'}, ORG, PROJECT)['mode'] == 'PREVIEW'


@pytest.mark.asyncio
async def test_actual_visible_only_connect_proves_org_access_not_user_or_role(wire, monkeypatch):
    evidence = await connection_evidence.collect_evidence(
        node_type='automation-qovery', credential_data=KEY, user_id='fixture-user',
    )
    assert evidence.reachable is True and p.QoveryNode.connection_evidence.proves == 'reachability'
    assert len(wire.calls) == 1 and wire.calls[0][1] == p.ROOT + '/organization/' + ORG
    result = await node({'operation': 'get_organization'}).execute({})
    assert result['human_identity_verified'] is False and result['token_scope_verified'] is False
    assert 'private' not in json.dumps(result) and 'plan' not in result


@pytest.mark.asyncio
async def test_wrong_org_or_project_never_reaches_child_route(wire):
    wire.organization['id'] = PROJECT
    with pytest.raises(ValueError, match='different metadata'): await node({'operation': 'list_projects'}).execute({})
    assert len(wire.calls) == 1
    wire.organization = deepcopy(ORGANIZATION)
    wire.responses = [{**PROJECT_ROW, 'organization': {'id': ENV}}]
    with pytest.raises(ValueError, match='different organization'):
        await node({'operation': 'get_environment', 'project_id': PROJECT, 'environment_id': ENV}).execute({})
    assert wire.calls[-1][1].endswith('/project/' + PROJECT)


@pytest.mark.asyncio
async def test_service_kind_and_parent_are_checked_before_status_endpoint(wire):
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': [{**SERVICE_ROW, 'service_type': 'CONTAINER'}]}]
    with pytest.raises(ValueError, match='different actual kind'):
        await node({'operation': 'get_service_status', 'project_id': PROJECT, 'environment_id': ENV, 'service_id': SERVICE, 'service_kind': 'application'}).execute({})
    assert not any(url.endswith('/status') for _, url, _ in wire.calls)
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': [SERVICE_ROW]}, SERVICE_STATUS]
    result = await node({'operation': 'get_service_status', 'project_id': PROJECT, 'environment_id': ENV, 'service_id': SERVICE, 'service_kind': 'application'}).execute({})
    assert result['deployment_request_id'] is None and 'private' not in json.dumps(result)


@pytest.mark.asyncio
async def test_environment_cluster_status_and_service_lists_project_only_metadata(wire):
    wire.responses = [PROJECT_ROW, ENV_ROW, ENV_STATUS]
    result = await node({'operation': 'get_environment_status', 'project_id': PROJECT, 'environment_id': ENV}).execute({})
    assert result['state'] == 'READY' and 'private' not in json.dumps(result)
    wire.responses = [{'results': [CLUSTER_ROW]}, {'cluster_id': CLUSTER, 'status': 'DEPLOYED', 'is_deployed': True, 'reason': 'UNSPECIFIED', 'cluster_lock': {'token': 'private-lock'}}]
    result = await node({'operation': 'get_cluster_status', 'cluster_id': CLUSTER}).execute({})
    assert result['is_deployed'] is True and 'private' not in json.dumps(result)
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': [SERVICE_ROW]}]
    result = await node({'operation': 'list_services', 'project_id': PROJECT, 'environment_id': ENV}).execute({})
    assert result['items'][0]['service_type'] == 'APPLICATION' and 'private' not in json.dumps(result)


@pytest.mark.asyncio
async def test_project_create_200_and_empty_separate_readback(wire):
    wire.responses = [PROJECT_ROW, PROJECT_ROW, {'results': []}]
    result = await node({'operation': 'create_empty_project', 'name': PROJECT_ROW['name'], 'description': PROJECT_ROW['description']}).execute({})
    assert result['created'] is True and result['empty_at_readback'] is True
    write = next(call for call in wire.calls if call[0] == 'POST')
    assert write[2]['json'] == {'name': PROJECT_ROW['name'], 'description': PROJECT_ROW['description']}
    assert wire.calls[-1][1].endswith('/project/' + PROJECT + '/environment')


@pytest.mark.asyncio
async def test_project_update_clear_preserve_and_nonempty_preflight(wire):
    before = p.project_record(PROJECT_ROW, ORG)
    config = {'operation': 'update_empty_project', 'project_id': PROJECT, 'name': 'Renamed', 'expected_snapshot': p.snapshot(before)}
    after = {**PROJECT_ROW, 'name': 'Renamed'}
    wire.responses = [PROJECT_ROW, {'results': []}, after, after, {'results': []}]
    result = await node(config).execute({})
    assert result['updated'] is True and result['atomic_precondition'] is False
    assert next(call for call in wire.calls if call[0] == 'PUT')[2]['json']['description'] == PROJECT_ROW['description']
    wire.calls.clear()
    cleared = {**after, 'description': ''}
    wire.responses = [PROJECT_ROW, {'results': []}, cleared, cleared, {'results': []}]
    await node({**config, 'clear_description': True}).execute({})
    assert next(call for call in wire.calls if call[0] == 'PUT')[2]['json']['description'] == ''
    wire.calls.clear()
    wire.responses = [{**PROJECT_ROW, 'associated_environments_count': 1}]
    with pytest.raises(ValueError, match='contains environments'): await node(config).execute({})
    assert not any(method != 'GET' for method, _, _ in wire.calls)


@pytest.mark.asyncio
async def test_environment_create_201_and_rename_do_not_deploy_or_change_mode(wire):
    wire.responses = [PROJECT_ROW, {'results': [CLUSTER_ROW]}, httpx.Response(201, json=ENV_ROW), ENV_ROW, {'results': []}]
    result = await node({'operation': 'create_empty_environment', 'project_id': PROJECT, 'cluster_id': CLUSTER, 'name': ENV_ROW['name']}).execute({})
    assert result['empty_at_readback'] is True and result['deployment_requested'] is False
    body = next(call for call in wire.calls if call[0] == 'POST')[2]['json']
    assert body == {'name': ENV_ROW['name'], 'cluster': CLUSTER, 'mode': 'DEVELOPMENT'}
    wire.calls.clear()
    renamed = {**ENV_ROW, 'name': 'Renamed environment'}
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': []}, renamed, renamed, {'results': []}]
    result = await node({'operation': 'rename_empty_environment', 'project_id': PROJECT, 'environment_id': ENV, 'name': renamed['name'], 'expected_snapshot': p.snapshot(p.environment_record(ENV_ROW, ORG, PROJECT))}).execute({})
    assert result['updated'] is True and result['deployment_requested'] is False
    assert next(call for call in wire.calls if call[0] == 'PUT')[2]['json'] == {'name': renamed['name']}
    assert all(not any(fragment in url for fragment in ['/deploy', '/clone', '/stop', '/secret']) for _, url, _ in wire.calls)


@pytest.mark.asyncio
async def test_picker_continuations_bind_search_inventory_parent_and_machine_grant(wire):
    rows = [{**PROJECT_ROW, 'id': str(__import__('uuid').UUID(int=i)), 'name': 'Project ' + str(i)} for i in range(1, 52)]
    wire.responses = [{'results': rows}]
    result = await p.QoveryNode.load_field_options('project_id', KEY)
    assert len(result['options']) == 50 and isinstance(result['options'][0]['value'], str)
    wire.responses = [{'results': rows}]
    continuation = await p.QoveryNode.load_field_options('project_id', KEY, page_token=result['next_page_token'])
    assert len(continuation['options']) == 1
    wire.responses = [{'results': rows}]
    with pytest.raises(ValueError, match='continuation'): await p.QoveryNode.load_field_options('project_id', KEY, page_token=result['next_page_token'], search='Project 1')
    wire.responses = [{'results': rows[:-1]}]
    with pytest.raises(ValueError, match='continuation'): await p.QoveryNode.load_field_options('project_id', KEY, page_token=result['next_page_token'])


def test_history_preserves_cursor_contract_and_full_page_uncertainty():
    page = {'page': 1, 'page_size': 1, 'results': [{**BASE, 'id': DEPLOYMENT, 'status': 'DEPLOYED', 'triggered_by': 'private-actor', 'applications': [{'commit': 'private-commit'}]}]}
    result = p.history_page(page, 'environment', None)
    assert result['has_more'] is None and result['next_start_id'] == DEPLOYMENT and 'private' not in json.dumps(result)
    recent = p.history_page(page, 'container', None)
    assert recent['recent_window_only'] is True and recent['next_start_id'] is None
    assert p.history_page({**page, 'results': [{**BASE, 'id': DEPLOYMENT, 'status': 'SUCCESS'}]}, 'application', None)['items'][0]['status'] == 'SUCCESS'
    with pytest.raises(ValueError): p.history_page(page, 'environment', DEPLOYMENT)
    with pytest.raises(ValueError): p.history_page({**page, 'results': page['results'] * 2}, 'environment', None)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [201, 202, 204, 301, 401, 403, 409, 429, 500])
async def test_status_contract_errors_are_redacted_and_never_retried(wire, status):
    wire.responses = [httpx.Response(status, json={'error': KEY['api_token'], 'private': 'response-secret'})]
    with pytest.raises(ValueError) as error: await p.request(p.guard(KEY), 'GET', '/project/' + PROJECT)
    assert KEY['api_token'] not in str(error.value) and 'response-secret' not in str(error.value)
    assert len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/organization/' + ORG + '/apiToken', '/environment/' + ENV + '/secret', '/application/' + SERVICE + '/deploy', 'https://private.example.test/x'])
async def test_no_arbitrary_or_hazardous_resource_escape(wire, path):
    with pytest.raises(ValueError): await p.request(p.guard(KEY), 'GET', path)
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments,envelopes,expected_id', [
    ('list_projects', {}, [{'results': [PROJECT_ROW]}], PROJECT),
    ('get_project', {'project_id': PROJECT}, [PROJECT_ROW], PROJECT),
    ('list_environments', {'project_id': PROJECT}, [PROJECT_ROW, {'results': [ENV_ROW]}], ENV),
    ('get_environment', {'project_id': PROJECT, 'environment_id': ENV}, [PROJECT_ROW, ENV_ROW], ENV),
    ('list_clusters', {}, [{'results': [CLUSTER_ROW]}], CLUSTER),
    ('get_cluster', {'cluster_id': CLUSTER}, [{'results': [CLUSTER_ROW]}], CLUSTER),
])
async def test_actual_factory_metadata_read_routes(wire, operation, arguments, envelopes, expected_id):
    wire.responses = deepcopy(envelopes)
    result = await node({'operation': operation, **arguments}).execute({})
    assert (result['items'][0]['id'] if 'items' in result else result['id']) == expected_id
    assert 'private' not in json.dumps(result) and wire.responses == []


@pytest.mark.asyncio
async def test_actual_factory_history_forwards_only_documented_cursor(wire):
    page = {'page': 2, 'page_size': 20, 'results': []}
    wire.responses = [PROJECT_ROW, ENV_ROW, page]
    result = await node({'operation': 'list_environment_deployments', 'project_id': PROJECT, 'environment_id': ENV, 'start_id': DEPLOYMENT}).execute({})
    assert result['page'] == 2 and result['has_more'] is False
    assert wire.calls[-1][2]['params'] == {'startId': DEPLOYMENT}
    row = {**SERVICE_ROW, 'service_type': 'CONTAINER'}
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': [row]}]
    with pytest.raises(ValueError, match='Only application/database'):
        await node({'operation': 'list_service_deployments', 'project_id': PROJECT, 'environment_id': ENV, 'service_kind': 'container', 'service_id': SERVICE, 'start_id': DEPLOYMENT}).execute({})
    assert not wire.calls[-1][1].endswith('/deploymentHistory')
    wire.responses = [PROJECT_ROW, ENV_ROW, {'results': [SERVICE_ROW]}, page]
    await node({'operation': 'list_service_deployments', 'project_id': PROJECT, 'environment_id': ENV, 'service_kind': 'application', 'service_id': SERVICE, 'start_id': DEPLOYMENT}).execute({})
    assert wire.calls[-1][2]['params'] == {'startId': DEPLOYMENT}

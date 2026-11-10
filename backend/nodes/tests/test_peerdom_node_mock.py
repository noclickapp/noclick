"""Native Peerdom factory tests using response examples copied from the published API docs."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import peerdom_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/peerdom/published_examples.json').read_text())
ID = '497f6eca-6276-4993-bfeb-53cbbbba6f08'
MAP = 'd6853b15-65cc-485b-a478-286f3c59e1a7'
PARENT = '70850378-7d3c-4f45-91b7-942d4dfbbd43'
KEY = 'unit-peerdom-api-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='peerdom-test', node_type='automation-peerdom',
        node_data={'config': config, 'credentials': {'credential_type': 'peerdom_api_key', 'api_key': KEY}})


REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def restore_client_constructor(monkeypatch):
    # Keep the real constructor when replacing the node module's shared httpx attribute.
    def install(payload, status=200, content=None):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(status, json=payload) if content is None else httpx.Response(status, content=content)
        def client(**kwargs):
            assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
            return REAL_CLIENT(transport=httpx.MockTransport(respond), **kwargs)
        monkeypatch.setattr(native.httpx, 'AsyncClient', client)
        return requests
    return install


def config_for(operation):
    config = {'operation': operation}
    if operation in {'get_peer', 'update_peer', 'delete_peer'}:
        config['peer_id'] = ID
    if operation in {'get_role', 'update_role', 'delete_role', 'assign_role', 'unassign_role', 'get_role_holder', 'update_role_holder'}:
        config['role_id'] = ID
    if operation in {'assign_role', 'unassign_role', 'get_role_holder', 'update_role_holder'}:
        config['peer_id'] = PARENT
    if operation in {'get_group', 'update_group', 'delete_group'}:
        config['group_id'] = ID
    if operation in {'get_project', 'update_project'}:
        config['project_id'] = ID
    if operation in {'create_role', 'create_group'}:
        config.update(name='Operations', map_id=MAP, parent_id=PARENT)
    if operation in {'create_project', 'update_project', 'update_role', 'update_group'}:
        config['name'] = 'Operations'
    if operation in {'create_peer', 'update_peer'}:
        config['first_name'] = 'Alex'
    if operation == 'update_role_holder':
        config.update(percentage='50', focus='Operations')
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_every_operation_one_contract_call_and_published_response(operation, restore_client_constructor):
    fixture = EXAMPLES[operation]
    requests = restore_client_constructor(fixture['response'], fixture['status'], content=b'' if operation == 'delete_peer' else None)
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'success', result
    assert result['data'] == fixture['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    path = fixture['path'].replace('{id}', ID).replace('{roleId}', ID).replace('{peerId}', PARENT)
    assert request.url.path == '/v1' + path
    assert request.url.host == 'api.peerdom.app'
    assert request.headers['X-Api-Key'] == KEY
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_peer_body_and_details_filters(restore_client_constructor):
    requests = restore_client_constructor(EXAMPLES['create_peer']['response'], 201)
    result = await node({'operation': 'create_peer', 'first_name': 'Zoë', 'last_name': 'Li',
        'email': 'zoe@example.com', 'birthdate': '1995-05-01', 'percentage': 50,
        'custom_fields': {'Office': 'Bern', 'List of Mentors': ['Alex']}}).execute({})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'firstName': 'Zoë', 'lastName': 'Li',
        'email': 'zoe@example.com', 'birthdate': '1995-05-01', 'percentage': 50,
        'customFields': {'Office': 'Bern', 'List of Mentors': ['Alex']}}
    requests = restore_client_constructor(EXAMPLES['get_peer']['response'])
    await node({'operation': 'get_peer', 'peer_id': ID, 'include_former': True,
        'include_roles': True, 'include_custom_fields': True}).execute({})
    assert dict(requests[0].url.params) == {'includeFormer': 'true', 'with': 'roles,customfields'}


@pytest.mark.asyncio
async def test_role_create_fields_false_zero_and_assignment_type_difference(restore_client_constructor):
    requests = restore_client_constructor(EXAMPLES['create_role']['response'])
    await node({'operation': 'create_role', 'name': 'Operations', 'map_id': MAP,
        'parent_id': PARENT, 'external': False, 'electable': False, 'target': 0,
        'color': '#abc', 'representing_id': PARENT}).execute({})
    assert json.loads(requests[0].content) == {'name': 'Operations', 'mapId': MAP,
        'parentId': PARENT, 'external': False, 'electable': False, 'target': 0,
        'color': '#abc', 'representingId': PARENT}
    requests = restore_client_constructor(EXAMPLES['assign_role']['response'], 201)
    await node({'operation': 'assign_role', 'role_id': ID, 'peer_id': PARENT,
        'percentage': 25, 'elected_until': '2027-06-09', 'focus': 'Operations'}).execute({})
    assert json.loads(requests[0].content) == {'peerId': PARENT, 'percentage': 25,
        'electedUntil': '2027-06-09', 'focus': 'Operations'}
    requests = restore_client_constructor(EXAMPLES['update_role_holder']['response'])
    await node({'operation': 'update_role_holder', 'role_id': ID, 'peer_id': PARENT,
        'percentage': '25'}).execute({})
    assert json.loads(requests[0].content) == {'percentage': '25'}


@pytest.mark.asyncio
async def test_page_bounds_filters_and_project_peer_pagination_exception(restore_client_constructor):
    requests = restore_client_constructor(EXAMPLES['list_roles']['response'])
    result = await node({'operation': 'list_roles', 'map_id': MAP, 'peer_id': ID,
        'group_id': PARENT, 'include_holders': True, 'include_groups': True,
        'include_representing': True, 'limit': 1, 'offset': 10}).execute({})
    assert result['has_more'] and result['next_offset'] == 11
    assert dict(requests[0].url.params) == {'mapId': MAP, 'peer': ID, 'group': PARENT,
        'with': 'holders,groups,representing', 'limit': '1', 'offset': '10'}
    requests = restore_client_constructor([])
    result = await node({'operation': 'list_peers', 'limit': 100, 'offset': 20}).execute({})
    assert result['has_more'] is False and result['next_offset'] is None
    requests = restore_client_constructor(EXAMPLES['list_projects']['response'])
    result = await node({'operation': 'list_projects', 'peer_id': ID, 'limit': 1, 'offset': 20}).execute({})
    assert dict(requests[0].url.params) == {'peer': ID}
    assert result['has_more'] is False


@pytest.mark.asyncio
async def test_project_patch_only_supplied_fields(restore_client_constructor):
    requests = restore_client_constructor(EXAMPLES['update_project']['response'])
    result = await node({'operation': 'update_project', 'project_id': ID,
        'archived': False, 'notes': 'Planning', 'external_url': 'https://example.com/project',
        'started_at': '2026-11-10T10:00:00Z'}).execute({})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'archived': False, 'notes': 'Planning',
        'externalUrl': 'https://example.com/project', 'startedAt': '2026-11-10T10:00:00Z'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_errors_do_not_redirect_retry_or_expose_key(status, restore_client_constructor):
    requests = restore_client_constructor({'message': 'Rejected ' + KEY}, status)
    result = await node({'operation': 'get_tenant'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert KEY not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,payload', [('get_peer', []), ('list_peers', {}), ('get_tenant', {'error': KEY})])
async def test_malformed_response_and_error_envelope_fail(operation, payload, restore_client_constructor):
    restore_client_constructor(payload)
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'error' and KEY not in str(result)


@pytest.mark.asyncio
async def test_empty_update_makes_no_request(restore_client_constructor):
    requests = restore_client_constructor({})
    result = await node({'operation': 'update_peer', 'peer_id': ID}).execute({})
    assert result['status'] == 'error' and requests == []


def test_credential_default_manual_input_and_schema():
    value = native.PeerdomAPIKeyCredential(api_key='  unit-peerdom-api-key  ')
    assert value.credential_type == 'peerdom_api_key' and value.api_key == KEY
    for bad in ['https://example.com/key', 'paste-key-here', 'abc\r\nInjected: yes']:
        with pytest.raises((ValueError, ValidationError)):
            native.PeerdomAPIKeyCredential(api_key=bad)
    schema = native.PeerdomFullConfig.model_json_schema()
    assert schema['$defs']['PeerdomAPIKeyCredential']['required'] == ['api_key']
    assert native.PeerdomNode.connection_evidence.identity_operation == 'get_tenant'
    for config in [{'operation': 'get_peer', 'peer_id': '../tenant'},
        {'operation': 'list_peers', 'limit': 101}, {'operation': 'list_peers', 'offset': -1}]:
        with pytest.raises((ValueError, ValidationError)):
            native.PeerdomNode.parse_config({'config': config, 'credentials': value.model_dump()})

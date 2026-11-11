"""Frozen Rumble contract wire tests; all calls are offline.

Fixture values are copied from the provider's published schema examples.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import rumble_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/rumble/schema_examples.json').read_text())
ID = EXAMPLES['asset']['id']
TOKEN = 'rumble-test-organization-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='rumble-test', node_type='automation-rumble',
        node_data={'config': config, 'credentials': {'credential_type': 'rumble_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


# Expectations transcribed independently from the pinned contract paths and schemas.
CASES = [
    ('get_organization', {}, 'GET', '/org', None, {}),
    ('list_sites', {}, 'GET', '/org/sites', None, {}),
    ('get_site', {'site_id': ID}, 'GET', '/org/sites/' + ID, None, {}),
    ('create_site', {'name': 'New Site', 'description': 'County Office', 'scope': '192.168.10.0/24', 'excludes': '192.168.10.1'}, 'PUT', '/org/sites', {'name': 'New Site', 'description': 'County Office', 'scope': '192.168.10.0/24', 'excludes': '192.168.10.1'}, {}),
    ('update_site', {'site_id': ID, 'name': 'New Site'}, 'PATCH', '/org/sites/' + ID, {'name': 'New Site'}, {}),
    ('delete_site', {'site_id': ID}, 'DELETE', '/org/sites/' + ID, None, {}),
    ('list_assets', {'search': 'os:Linux'}, 'GET', '/org/assets', None, {'search': 'os:Linux'}),
    ('get_asset', {'asset_id': ID}, 'GET', '/org/assets/' + ID, None, {}),
    ('delete_asset', {'asset_id': ID}, 'DELETE', '/org/assets/' + ID, None, {}),
    ('update_asset_comments', {'asset_id': ID, 'comments': 'Sales Laptop'}, 'PATCH', '/org/assets/' + ID + '/comments', {'comments': 'Sales Laptop'}, {}),
    ('update_asset_tags', {'asset_id': ID, 'tags': 'ThisTag=Value -OldTag'}, 'PATCH', '/org/assets/' + ID + '/tags', {'tags': 'ThisTag=Value -OldTag'}, {}),
    ('list_services', {'search': 'port:22'}, 'GET', '/org/services', None, {'search': 'port:22'}),
    ('get_service', {'service_id': ID}, 'GET', '/org/services/' + ID, None, {}),
    ('list_agents', {}, 'GET', '/org/agents', None, {}),
    ('get_agent', {'agent_id': ID}, 'GET', '/org/agents/' + ID, None, {}),
    ('list_tasks', {'status': 'active', 'search': 'scan'}, 'GET', '/org/tasks', None, {'status': 'active', 'search': 'scan'}),
    ('create_scan', {'site_id': ID, 'targets': 'defaults', 'scan_name': 'My Scan', 'scan_frequency': 'once', 'agent': ID}, 'PUT', '/org/sites/' + ID + '/scan', {'targets': 'defaults', 'scan-name': 'My Scan', 'scan-frequency': 'once', 'agent': ID}, {}),
    ('stop_task', {'task_id': ID}, 'POST', '/org/tasks/' + ID + '/stop', None, {}),
    ('export_assets', {'search': 'os:Linux', 'fields': 'id,names'}, 'GET', '/export/org/assets.json', None, {'search': 'os:Linux', 'fields': 'id,names'}),
    ('export_services', {}, 'GET', '/export/org/services.json', None, {}),
    ('get_task', {'task_id': ID}, 'GET', '/org/tasks/' + ID, None, {}),
    ('on_new_asset', {'since': 1576300370}, 'GET', '/export/org/assets/sync/created/assets.json', None, {'since': '1576300370'}),
    ('on_updated_asset', {'since': 1576300370}, 'GET', '/export/org/assets/sync/updated/assets.json', None, {'since': '1576300370'}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body,query', CASES)
async def test_contract_requests(monkeypatch, operation, config, method, path, body, query):
    response = EXAMPLES['organization'] if operation == 'get_organization' else (
        {'since': EXAMPLES['since'], 'assets': [EXAMPLES['asset']]} if operation.startswith('on_') else EXAMPLES['site'])
    requests = transport(monkeypatch, response, 204 if method == 'DELETE' else 200)
    instance = node({'operation': operation, **config})
    async def state(mutator, **kwargs):
        return mutator({'seen_ids': []})[1]
    instance._update_node_state = state
    result = await instance.execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith(native.BASE + path)
    assert request.url.path == '/api/v1.0' + path
    assert dict(request.url.params) == query
    if operation == 'create_scan':
        assert request.headers['Content-Type'] == 'application/json'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(result)
    if operation.startswith('on_'):
        assert result['count'] == 1
        event = native.RumbleNode.resolve_agent_event(result)
        assert ID in event['text'] and '192.168.0.1' in event['text']


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,timestamp', [('on_new_asset', 'created_at'), ('on_updated_asset', 'updated_at')])
async def test_poll_baseline_dedup_and_timestamp_changes(monkeypatch, operation, timestamp):
    asset = copy.deepcopy(EXAMPLES['asset'])
    transport(monkeypatch, {'since': EXAMPLES['since'], 'assets': [asset]})
    instance = node({'operation': operation})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(state)
        if new is not None:
            state = new
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))['count'] == 0  # arming baseline
    assert (await instance.execute({}))['count'] == 0
    asset[timestamp] += 1
    transport(monkeypatch, {'since': EXAMPLES['since'], 'assets': [asset]})
    assert (await instance.execute({}))['count'] == 1
    assert (await instance.execute({}))['count'] == 0
    # A different declared watch filter starts a fresh baseline.
    repointed = node({'operation': operation, 'search': 'os:Linux'})
    repointed._update_node_state = update
    assert (await repointed.execute({}))['count'] == 0


@pytest.mark.asyncio
async def test_connection_identity_omits_organization_secrets(monkeypatch):
    transport(monkeypatch, {**EXAMPLES['organization'], 'download_token': 'private-download', 'export_token': 'private-export'})
    result = await node({'operation': 'get_organization'}).execute({})
    assert result['data'] == EXAMPLES['organization']
    assert 'private-' not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 500])
async def test_provider_failure_is_not_success(monkeypatch, status):
    transport(monkeypatch, {'error': 'rejected ' + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'get_organization'}).execute({})
    assert TOKEN not in str(exc.value)
    assert str(status) in str(exc.value)


@pytest.mark.asyncio
async def test_malformed_poll_response_refuses_to_advance_state(monkeypatch):
    transport(monkeypatch, {'assets': [{'id': ID}]})
    with pytest.raises(ValueError, match='timestamps'):
        await node({'operation': 'on_updated_asset'}).execute({})


def test_manual_key_defaults_and_required_write_fields():
    assert native.RumbleAPIKeyCredential(api_key=TOKEN).credential_type == 'rumble_api_key'
    for invalid in ['https://example.com', 'Bearer abc def', '<token>']:
        with pytest.raises(ValidationError):
            native.RumbleAPIKeyCredential(api_key=invalid)
    for operation in ['create_site', 'update_asset_tags', 'get_asset']:
        with pytest.raises(ValidationError):
            native.MODELS[operation]()
    assert native.RumbleNode.resolve_agent_event({'assets': []}) is None


@pytest.mark.asyncio
async def test_manual_connect_evidence_names_the_organization(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    transport(monkeypatch, EXAMPLES['organization'])
    async def execute(**kwargs):
        assert kwargs['operation'] == 'get_organization'
        return await node({'operation': kwargs['operation']}).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', execute)
    result = await collect_evidence(node_type='automation-rumble', user_id='rumble-test',
        credential_data={'credential_type': 'rumble_api_key', 'api_key': TOKEN})
    assert result.reachable is True
    assert result.account_label == EXAMPLES['organization']['name']


@pytest.mark.asyncio
async def test_oversized_poll_does_not_advance_seen_state(monkeypatch):
    transport(monkeypatch, {'since': EXAMPLES['since'], 'assets': [EXAMPLES['asset']] * 10001})
    instance = node({'operation': 'on_updated_asset'})
    async def forbidden(*args, **kwargs):
        pytest.fail('An oversized poll must not consume any asset events')
    instance._update_node_state = forbidden
    with pytest.raises(ValueError, match='10,000 assets'):
        await instance.execute({})

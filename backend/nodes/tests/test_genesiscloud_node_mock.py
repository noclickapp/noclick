"""Instance contracts and provider-authored examples; no live provider calls."""
import json

import httpx
import pytest

import nodes.genesiscloud_node as native

TOKEN = 'fixture-genesiscloud-token-42'
INSTANCE = '9e8ce501-d692-402c-8fca-5a8f5d8ddd57'
OTHER = '5edc8119-619a-464e-82c9-dd4453b62fba'
IMAGE = 'e049b9ce-9e12-46ba-8c93-d6abc04a4f5a'


def make_node(operation, **fields):
    data = {'config': {'operation': operation, **fields}, 'credentials': {'credential_type': native.FAMILY, 'api_token': TOKEN}}
    return native.GenesisCloudNode('native', 'automation-genesiscloud', data, native.GenesisCloudNode.parse_config(data), user_id='actor')


def instance(**changes):
    return dict({'id': INSTANCE, 'name': 'Private instance', 'type': 'vcpu-8_memory-32g_nvidia-rtx-3080-1', 'region': 'NORD-NO-KRS-1',
        'status': 'active', 'disk_size': 80, 'image': {'id': IMAGE, 'name': 'Private image'}, 'created_at': '2020-03-23T10:09:29.152Z',
        'hostname': 'Private', 'dns_name': 'private.example.test', 'private_ip': '192.0.2.1', 'public_ip': '192.0.2.2',
        'floating_ip': {'ip': '192.0.2.3'}, 'ssh_keys': ['Private'], 'security_groups': ['Private'], 'volumes': ['Private'],
        'metadata': {'Private': True}, 'user_data': 'Private', 'startup_script': 'Private', 'password': 'Private', 'url': 'https://private.example.test'}, **changes)


def page(rows=None, **changes):
    return dict({'instances': [instance()] if rows is None else rows, 'page': 1, 'per_page': 50, 'total_count': 1}, **changes)


def transport(monkeypatch, handler):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_bearer_header_fixed_origin_exact_page_and_private_projection(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == 'GET' and request.url.host == 'api.genesiscloud.com'
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN and 'X-Auth-Token' not in request.headers
        assert request.url.path == '/compute/v1/instances' and dict(request.url.params) == {'page': '2', 'per_page': '3'}
        return httpx.Response(200, json=page(page=2, per_page=3, total_count=9))
    transport(monkeypatch, respond)
    result = (await make_node('list_instances', page=2, per_page=3).execute({}))['data']
    assert result['instances'][0] == {'id': INSTANCE, 'type': 'vcpu-8_memory-32g_nvidia-rtx-3080-1', 'region': 'NORD-NO-KRS-1',
        'status': 'active', 'disk_size': 80, 'image_id': IMAGE, 'created_at': '2020-03-23T10:09:29.152Z'}
    assert result['page'] == 2 and result['per_page'] == 3 and result['total_count'] == 9 and result['has_more_pages'] is True
    assert result['completion'] == 'unknown' and 'account_id' not in result and 'principal_id' not in result
    assert 'Private' not in str(result) and '192.0.2' not in str(result) and len(calls) == 1


@pytest.mark.asyncio
async def test_detail_wrapper_exact_id_names_opt_in_and_empty_catalog(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'instance': instance()}))
    result = (await make_node('get_instance', instance_id=INSTANCE, include_names=True).execute({}))['data']
    assert result['instance']['name'] == 'Private instance' and result['instance']['id'] == INSTANCE
    assert 'image_name' not in result['instance'] and 'hostname' not in result['instance']
    transport(monkeypatch, lambda request: httpx.Response(200, json=page([], total_count=0)))
    result = (await make_node('list_instances').execute({}))['data']
    assert result['instances'] == [] and result['returned_count'] == 0 and result['has_more_pages'] is False


@pytest.mark.parametrize('payload', [[], {'data': []}, {'instances': []}, page(page=2), page(per_page=100), page(total_count=True),
    page(total_count='1'), page(rows=[instance(), instance()], total_count=2), page(rows=[instance(id=7)]),
    page(rows=[instance(status='online')]), page(rows=[instance(disk_size=True)]), page(rows=[instance(disk_size=79)]),
    page(rows=[instance(created_at='2026-10-01 00:00:00')]), page(rows=[instance(image={'id': 'https://private.test'})])])
@pytest.mark.asyncio
async def test_exact_page_codec_refuses_guessed_wrappers_counters_and_fields(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(native.GenesisCloudError): await make_node('list_instances').execute({})


@pytest.mark.parametrize('payload', [instance(), {'data': instance()}, {'instance': instance(id=OTHER)}, {'instance': []}])
@pytest.mark.asyncio
async def test_detail_parent_and_documented_wrapper_refuse(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(native.GenesisCloudError): await make_node('get_instance', instance_id=INSTANCE).execute({})


@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 422, 429, 503])
@pytest.mark.asyncio
async def test_http_errors_no_follow_no_retry_no_provider_message(monkeypatch, status):
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(status, json={'code': '02044', 'message': TOKEN}, headers={'location': 'https://foreign.test/'}))
    with pytest.raises(native.GenesisCloudError) as error: await make_node('list_instances').execute({})
    assert error.value.status_code == status and TOKEN not in str(error.value) and len(calls) == 1
    assert f'HTTP {status}' in str(error.value)


@pytest.mark.asyncio
async def test_decoded_reflection_unresolved_references_closed_routes_and_actor_binding(monkeypatch):
    escaped = json.dumps(page(rows=[instance(debug=TOKEN)])).replace('fixture', '\\u0066ixture')
    transport(monkeypatch, lambda request: httpx.Response(200, content=escaped, headers={'content-type': 'application/json'}))
    with pytest.raises(native.GenesisCloudError, match='reflected'): await make_node('list_instances').execute({})
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, json=page()))
    with pytest.raises(native.GenesisCloudError, match='Resolve'):
        await make_node('get_instance', instance_id='{{vars.instance_id}}').execute({})
    node = make_node('list_instances'); node._frame = node._snapshot(); node._binding = None
    for route in ('/me', '/images', '/instances/' + INSTANCE + '/actions', '/instances/' + INSTANCE + '/snapshots'):
        with pytest.raises(native.GenesisCloudError, match='Unsupported'): await node._request(route)
    with pytest.raises(native.GenesisCloudError, match='Unsupported'): await node._request('/instances', {'cursor': 'next'})
    assert calls == []
    node = make_node('get_instance', instance_id=INSTANCE)
    async def changed(route, params=None):
        node.user_id = 'other-actor'
        return {'instance': instance()}
    node._request = changed
    with pytest.raises(native.GenesisCloudError, match='actor'): await node.execute({})


@pytest.mark.asyncio
async def test_page_overflow_and_transport_origin_guard(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json=page([instance(), instance(id=OTHER)], per_page=1, total_count=2)))
    with pytest.raises(native.GenesisCloudError, match='bound'): await make_node('list_instances', per_page=1).execute({})
    node = make_node('list_instances'); node._frame = node._snapshot(); node._binding = None
    for params in ({'page': True}, {'page': 0}, {'per_page': 101}):
        with pytest.raises(native.GenesisCloudError, match='bound'): await node._request('/instances', params)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def altered(**kwargs):
        await kwargs['event_hooks']['request'][0](httpx.Request('GET', 'https://foreign.test/compute/v1/instances'))
        raise AssertionError('Must stop before a client is usable')
        yield
    monkeypatch.setattr(native, 'guarded_async_client', altered)
    with pytest.raises(native.GenesisCloudError, match='origin'): await node._request('/instances')


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,fixture', [('list_instances', 'instances'), ('get_instance', 'instance')])
async def test_provider_documented_examples(monkeypatch, operation, fixture):
    # Verbatim response examples from https://developers.genesiscloud.com/compute-api/instances
    from pathlib import Path
    payload = json.loads((Path(__file__).parent / 'fixtures' / 'genesiscloud' / (fixture + '.json')).read_text())
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    fields = {'instance_id': payload['instance']['id']} if operation == 'get_instance' else {}
    result = await make_node(operation, **fields).execute({})
    assert result['success'] is True
    row = result['data']['instance'] if operation == 'get_instance' else result['data']['instances'][0]
    assert row['id'] == INSTANCE and row['disk_size'] == 128
    assert 'public_ip' not in row and 'ssh_keys' not in row

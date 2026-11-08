"""Factory-level HTTP contract coverage without live credentials."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import ipinfo_io_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = 'synthetic-ipinfo-test-token'
AUTH = {'credential_type': 'ipinfo_io_api_token', 'api_token': TOKEN}
USER = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        calls.append(request)
        assert request.url.host in {'ipinfo.io', 'api.ipinfo.io'}
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type='automation-ipinfo-io', operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(node.ROUTES))
async def test_every_operation_uses_one_exact_contract_route(transport, operation):
    method, route, origin = node.ROUTES[operation]
    args = {}
    for key, value in [('ip', '8.8.8.8'), ('asn', 15169), ('domain', 'google.com')]:
        if '{' + key + '}' in route:
            args[key] = value
            route = route.replace('{' + key + '}', str(value))
    if method == 'POST':
        args['ips'] = ['8.8.8.8', '1.1.1.1']
    body = {'ip': '8.8.8.8'}
    if operation == 'get_token_info':
        body = {'token': TOKEN, 'requests': {'limit': 50000}, 'features': {'core': {}}}
    elif operation == 'get_hosted_domains':
        body = {'total': 1, 'page': 0, 'domains': ['example.com']}
    elif operation == 'batch_enrich':
        body = {'8.8.8.8': {'ip': '8.8.8.8'}, '1.1.1.1': {'ip': '1.1.1.1'}}
    elif operation in {'map_ips', 'summarize_ips'}:
        body = {'status': 'Report Generated', 'reportUrl': origin + route + '/example'}
    transport[1].append((200, body))
    output = await run(operation, args)
    assert output['status'] == 'success'
    assert len(transport[0]) == 1 and not transport[1]
    request = transport[0][0]
    assert request.method == method
    assert str(request.url).split('?')[0] == origin + route
    assert TOKEN not in json.dumps(output)
    if operation == 'batch_enrich':
        assert json.loads(request.content) == args['ips']
    elif operation in {'map_ips', 'summarize_ips'}:
        assert request.content == b'8.8.8.8\n1.1.1.1\n'
        assert request.headers['Content-Type'] == 'text/plain'
        assert request.url.params['cli'] == '1'
    elif operation == 'get_hosted_domains':
        assert dict(request.url.params) == {'page': '0', 'limit': '100'}


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['https://evil.test', '../me', '8.8.8.8/privacy', '8.8.8.8?token=x', 'fe80::1%en0'])
async def test_ip_cannot_change_route_or_host(transport, bad):
    with pytest.raises(ValueError):
        await run('get_ip_info', {'ip': bad})
    assert not transport[0]


@pytest.mark.asyncio
async def test_error_and_secret_redaction(transport):
    transport[1].append((403, {'error': {'message': 'Invalid ' + TOKEN, 'token': TOKEN}}))
    result = await run('get_token_info')
    assert result['status'] == 'error'
    assert result['http_status'] == 403
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_incomplete_connection_response_is_not_proof(transport):
    transport[1].append((200, {'ip': '8.8.8.8'}))
    with pytest.raises(ValueError, match='incomplete'):
        await run('get_token_info')


@pytest.mark.asyncio
async def test_success_status_with_error_envelope_is_failure(transport):
    transport[1].append((200, {'error': 'Invalid token'}))
    assert (await run('get_token_info'))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('tag', ['other_api_token', '', None])
async def test_foreign_credential_refused(transport, tag):
    with pytest.raises(ValueError):
        await run('get_token_info', auth={**AUTH, 'credential_type': tag})
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['get_lookup_ip_info', 'get_current_lookup_info'])
async def test_official_core_documented_response_parses(transport, operation):
    from pathlib import Path
    body = json.loads((Path(__file__).parent / 'fixtures/ipinfo-io/core-response.json').read_text())
    transport[1].append((200, body))
    result = await run(operation, {'ip': '8.8.8.8'} if operation == 'get_lookup_ip_info' else {})
    assert result['data'] == body
    assert transport[0][0].url.host == 'api.ipinfo.io'


@pytest.mark.asyncio
async def test_residential_proxy_uses_documented_legacy_origin(transport):
    transport[1].append((200, {'ip': '175.107.211.204', 'last_seen': '2025-06-24', 'percent_days_seen': 14, 'service': 'ipfoxy'}))
    await run('get_residential_proxy', {'ip': '175.107.211.204'})
    assert str(transport[0][0].url) == 'https://ipinfo.io/resproxy/175.107.211.204'


@pytest.mark.asyncio
async def test_unsaved_token_evidence_proves_reachability_without_identity(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {'token': TOKEN, 'requests': {'limit': 50000}, 'features': {'core': {}}}))
    result = await collect_evidence(node_type='automation-ipinfo-io', credential_data=deepcopy(AUTH), user_id=USER)
    assert result.reachable is True
    assert result.account_label is None
    assert node.IpinfoIoNode.connection_evidence.proves == 'reachability'
    assert len(transport[0]) == 1

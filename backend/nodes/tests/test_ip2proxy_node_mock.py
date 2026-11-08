"""IP2Proxy wire-contract and credential regressions; no live provider calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ip2proxy_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-ip2proxy-api-key'
IP = '201.42.237.89'
EXAMPLE = json.loads((Path(__file__).parent / 'fixtures/ip2proxy/lookup.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation='get_proxy_status', ip=IP, credentials=None):
    return NodeFactory.create_node(node_id='proxy-fixture', node_type='automation-ip2proxy', node_data={
        'config': {'operation': operation, 'ip': ip},
        'credentials': credentials or {'credential_type': 'ip2proxy_api_key', 'api_key': TOKEN},
    })


def transport(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,package', native.PACKAGES.items())
async def test_ip2proxy_all_packages_exact_contract(monkeypatch, operation, package):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, text=json.dumps(EXAMPLE), headers={'Content-Type': 'text/html; charset=UTF-8'}))
    result = await node(operation).execute({})
    assert result == {'status': 'success', 'package': package, 'ip': IP, 'data': EXAMPLE}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET' and str(request.url).startswith('https://api.ip2proxy.com/?')
    assert dict(request.url.params) == {'ip': IP, 'key': TOKEN, 'package': package, 'format': 'json'}
    assert 'authorization' not in request.headers
    assert TOKEN not in str(result)
    assert type(result['data']['lastSeen']) is int and type(result['data']['creditsConsumed']) is int


@pytest.mark.asyncio
async def test_ip2proxy_ipv6_and_px1_minimal_fields(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={'response': 'OK', 'isProxy': 'NO', 'countryCode': 'US', 'countryName': 'United States'}))
    result = await node(ip='2001:4860:4860::8888').execute({})
    assert result['status'] == 'success'
    assert requests[0].url.params['ip'] == '2001:4860:4860::8888'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500])
async def test_ip2proxy_http_errors_never_leak_key(monkeypatch, status):
    transport(monkeypatch, lambda _: httpx.Response(status, text=TOKEN, headers={'location': 'https://other.example/?key='+TOKEN}))
    result = await node().execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_ip2proxy_network_error_hides_query(monkeypatch):
    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)
    transport(monkeypatch, fail)
    result = await node().execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['not json', '[]', '{}', '{"response":""}', '{"response":true}'])
async def test_ip2proxy_invalid_response_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, text=body))
    assert (await node().execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_ip2proxy_provider_rejection_preserves_message_redacts_key(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'response': 'INVALID KEY '+TOKEN}))
    assert await node().execute({}) == {'status': 'error', 'error': 'INVALID KEY [redacted]'}


@pytest.mark.asyncio
async def test_ip2proxy_success_does_not_echo_secrets(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'response': 'OK', 'extra': [TOKEN, {TOKEN: TOKEN}]}))
    result = await node().execute({})
    assert result['status'] == 'success' and TOKEN not in str(result)


@pytest.mark.parametrize('ip', ['hostname.test', '1.2.3.999', 'https://1.2.3.4', 'fe80::1%en0', '1.2.3.4/path'])
def test_ip2proxy_rejects_non_ip_inputs(ip):
    with pytest.raises(ValueError):
        node(ip=ip)


def test_ip2proxy_manual_key_and_connection_evidence():
    credential = native.Ip2ProxyAPIKey(api_key=TOKEN)
    assert credential.credential_type == 'ip2proxy_api_key'
    assert not native.Ip2ProxyAPIKey.model_fields['credential_type'].is_required()
    assert native.Ip2ProxyNode.connection_evidence.proves == 'reachability'
    assert native.Ip2ProxyNode.connection_evidence.operation_arguments == {'ip': IP}
    assert native.Ip2ProxyNode.connection_evidence.operation == 'get_proxy_status'
    assert len(native.PACKAGES) == 11
    with pytest.raises(ValidationError):
        native.Ip2ProxyAPIKey(api_key='https://example.test/key')

"""Exercise CraftMyPDF via native discovery and guarded HTTP, without network.

Published examples cover all operations; negative cases verify credential
shaping, malformed replies and the absence of automatic write retries.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import craftmypdf_node as provider
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/craftmypdf/published_examples.json').read_text())
CASES = FIXTURE['cases']
AUTH = {'credential_type': 'craftmypdf_api_key', 'api_key': 'fixture-craftmypdf-secret'}

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(provider, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(op, config=None, auth=None):
    return await run_node_operation(node_type='automation-craftmypdf', operation=op,
        arguments=deepcopy(config or {}), credential_data=deepcopy(auth or AUTH),
        user_id='00000000-0000-4000-8000-000000000001')

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_craftmypdf_published_operations(transport, case):
    requests, queue = transport
    queue.append((200, deepcopy(case['response'])))
    assert await run(case['operation'], case['config']) == case['response']
    assert len(requests) == 1 and not queue
    request = requests[0]
    assert request.method == case['method']
    assert request.url.path == '/v1' + case['path']
    assert request.url.host == 'api.craftmypdf.com'
    assert request.headers['X-API-KEY'] == AUTH['api_key']
    assert AUTH['api_key'] not in str(request.url) + request.content.decode()
    if case['method'] == 'POST':
        body = json.loads(request.content)
        for key, value in case['config'].items():
            assert body[key] == value
        if case['operation'] in {'create_pdf', 'create_image'}:
            assert body['export_type'] == 'json'
    elif case['operation'] == 'get_account_info':
        assert json.loads(request.content) == {}
    else:
        for key, value in case['config'].items():
            assert request.url.params[key] == str(value)

@pytest.mark.asyncio
@pytest.mark.parametrize('region,base', provider.BASES.items())
async def test_craftmypdf_region_and_account_evidence(transport, region, base):
    transport[1].append((200, {'status': 'success', 'username': 'hello@craftmypdf.com'}))
    assert (await run('get_account_info', auth={**AUTH, 'region': region}))['username'] == 'hello@craftmypdf.com'
    assert str(transport[0][0].url) == base + '/get-account-info'
    assert provider.CraftmypdfNode.connection_evidence.identity_operation == 'get_account_info'

@pytest.mark.asyncio
async def test_craftmypdf_update_json_alias_and_false_values(transport):
    transport[1].append((200, {'status': 'success'}))
    await run('update_template', {'template_id': '05f77b2b18ad809a', 'sample_json': '{"first_name":"Jack"}'})
    assert json.loads(transport[0][-1].content) == {'template_id': '05f77b2b18ad809a', 'json': '{"first_name":"Jack"}'}
    transport[1].append((200, {'status': 'success', 'versions': []}))
    await run('retain_template_versions', {'template_id': '05f77b2b18ad809a', 'versions': [1], 'keep': False})
    assert json.loads(transport[0][-1].content)['keep'] is False

@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [
    (401, {'status': 'error', 'message': 'Invalid API key'}),
    (200, {'status': 'error', 'message': 'Invalid template'}),
    (302, {'status': 'success'}), (429, {'status': 'error', 'message': 'Rate limit'}),
    (500, b'<html>error</html>'), (200, []), (200, {'status': 'success'}),
])
async def test_craftmypdf_unconfirmed_responses_fail_without_retry(transport, status, body):
    transport[1].append((status, body))
    with pytest.raises(ValueError):
        await run('create_pdf', {'template_id': '05f77b2b18ad809a', 'data': '{}'})
    assert len(transport[0]) == 1

@pytest.mark.asyncio
async def test_craftmypdf_error_message_and_redaction(transport):
    transport[1].append((401, {'status': 'error', 'message': 'Invalid API key'}))
    with pytest.raises(ValueError, match='Invalid API key'):
        await run('get_account_info')
    transport[1].append((401, {'status': 'error', 'message': 'Invalid ' + AUTH['api_key']}))
    with pytest.raises(ValueError) as error:
        await run('get_account_info')
    assert AUTH['api_key'] not in str(error.value)

@pytest.mark.asyncio
async def test_craftmypdf_async_requires_explicit_acceptance(transport):
    transport[1].append((200, {'status': 'success', 'transaction_ref': 'example'}))
    case = next(c for c in CASES if c['operation'] == 'create_pdf_async')
    with pytest.raises(ValueError, match='asynchronous acceptance'):
        await run('create_pdf_async', case['config'])

@pytest.mark.asyncio
@pytest.mark.parametrize('op,config', [
    ('create_pdf', {'template_id': 'one', 'data': 'not JSON'}),
    ('update_template', {'template_id': 'one'}),
    ('merge_pdfs', {'urls': ['file:///tmp/secret', 'https://example.com/a.pdf']}),
    ('get_pdf_info', {'url': 'https://user:password@example.com/private.pdf'}),
])
async def test_craftmypdf_bad_inputs_do_not_reach_http(transport, op, config):
    with pytest.raises(ValueError):
        await run(op, config)
    assert not transport[0]

@pytest.mark.parametrize('secret', ['https://app.craftmypdf.com', '<api-key>', 'key with spaces', 'key\nheader', 'keyé'])
def test_craftmypdf_manual_key_validation(secret):
    with pytest.raises(ValueError):
        provider.CraftmypdfApiKey(api_key=secret)

def test_craftmypdf_key_trim_and_foreign_family():
    assert provider.CraftmypdfApiKey(api_key=' fixture-secret\n').api_key == 'fixture-secret'
    with pytest.raises(ValueError, match='CraftMyPDF API key'):
        provider.CraftmypdfNode.parse_config({'config': {'operation': 'get_account_info'}, 'credentials': {**AUTH, 'credential_type': 'other_api_key'}})

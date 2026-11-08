"""Exercise Conversion Tools through the real discovery and factory seams.

Synthetic responses pin provider requests and cover rejection, asynchronous task
states, account evidence and binary output without contacting an account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import conversion_tools_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = 'synthetic-conversion-token-123'
CASES = json.loads((Path(__file__).parent / 'fixtures/conversion-tools/requests.json').read_text())['cases']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {'credential_type': 'conversion_tools_api_token', 'api_token': TOKEN}


def node(config):
    return NodeFactory.create_node(node_id='conversion-fixture', node_type='automation-conversion-tools',
        node_data={'config': config, 'credentials': credential()})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_conversion_tools_exact_requests_and_responses(monkeypatch, case):
    op = case['operation']
    def reply(request):
        if op == 'download_file':
            return httpx.Response(200, content=b'converted\x00file', headers={'Content-Type':'application/octet-stream'})
        return httpx.Response(202 if op == 'delete_task_files' else 200, json=case['response'])
    requests = transport(monkeypatch, reply)
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.url.host == 'api.conversiontools.io'
    assert req.method == case['method'] and req.url.path == case['path']
    if op in {'list_conversions','get_conversion'}:
        assert 'authorization' not in req.headers
    else:
        assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    if case['request_body'] is not None:
        assert json.loads(req.content) == case['request_body']
    if op == 'upload_file':
        assert req.headers['Content-Type'].startswith('multipart/form-data; boundary=')
        assert b'name="file"; filename="data.txt"' in req.content and b'hello\n' in req.content
    elif op == 'list_tasks':
        assert dict(req.url.params) == {'status':'SUCCESS'}
        assert result['history_limit'] == 50
    elif op == 'list_conversions':
        assert dict(req.url.params) == {'input':'xml', 'output':'xlsx', 'ai':'false'}
    elif op == 'download_file':
        assert isinstance(result['file'], BinaryOutput) and result['file'].data == b'converted\x00file'
    elif op == 'delete_task_files':
        assert result['deletion_scheduled'] is True
        assert 'deleted' not in result
    if op != 'download_file':
        assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_conversion_tools_connection_evidence_identifies_account(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {'error':None,'email':'user@example.com'})
    result = await collect_evidence(node_type='automation-conversion-tools', user_id='fixture', credential_data=credential())
    assert result.reachable is True and result.account_label == 'user@example.com'
    assert len(requests) == 1 and requests[0].url.path == '/v1/auth'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_conversion_tools_http_errors_are_not_success_and_redact_token(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={'error':'Rejected ' + TOKEN}, headers={'Location':'https://example.com'}))
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_auth_info'}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{}, [], {'email':None}, {'error':'Not authorized'}])
async def test_conversion_tools_malformed_and_error_envelopes_do_not_verify(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({'operation':'get_auth_info'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['PENDING','RUNNING','SUCCESS','ERROR'])
async def test_conversion_tools_all_documented_task_states(monkeypatch, status):
    response = {'status':status, 'error':'Wrong file format' if status == 'ERROR' else None,
                'file_id':'result-file' if status == 'SUCCESS' else None, 'conversionProgress':0}
    transport(monkeypatch, response)
    result = await node({'operation':'get_task_status','task_id':'task-123'}).execute({})
    assert result['data'] == response


@pytest.mark.parametrize('config', [
    {'operation':'get_file_info','file_id':'../auth'},
    {'operation':'upload_file','file_base64':'not base64'},
    {'operation':'upload_file','file_base64':'aGk=','filename':'../secret'},
    {'operation':'create_task','conversion_type':'convert.xml_to_excel','options_json':'[]'},
    {'operation':'create_task','conversion_type':'convert.xml_to_excel','options_json':'{"x":NaN}'},
    {'operation':'create_task','conversion_type':'convert.xml_to_excel','options_json':'{}','callback_url':'file:///tmp/x'},
    {'operation':'update_task_retention','task_id':'task-123','retention_mode':'forever'},
    {'operation':'list_tasks','page':2},
])
def test_conversion_tools_rejects_invalid_inputs(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_conversion_tools_discovered_and_credential_shaped():
    assert NODE_REGISTRY['automation-conversion-tools'] is native.ConversionToolsNode
    value = native.ConversionToolsAPITokenCredential.model_validate({**credential(),'api_token':'  '+TOKEN+'\n'})
    assert value.api_token == TOKEN
    for token in ['https://conversiontools.io/profile','<token>','Bearer abc','bad\nheader']:
        with pytest.raises(ValidationError):
            native.ConversionToolsAPITokenCredential.model_validate({**credential(),'api_token':token})

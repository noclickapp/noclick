"""OPA wire checks against exact examples copied from its official REST docs."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import openpolicy_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/openpolicy/contract_examples.json').read_text())['cases']
TOKEN = 'opa-test-token-42'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='opa-test', node_type='automation-openpolicy', node_data={
        'config': config, 'credentials': {'credential_type': 'openpolicy_token', 'api_token': TOKEN, 'base_url': 'https://opa.example.com:8181'}})

def mock(monkeypatch, status, body, *, raw=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=[c['config']['operation'] for c in CASES])
async def test_documented_requests_and_responses(monkeypatch, case):
    op = case['config']['operation']
    requests = mock(monkeypatch, case['status'], case['response'], raw=b'' if case['status'] == 204 else None)
    output = await node(case['config']).execute({})
    request, = requests
    assert request.method == case['method'] and request.url.path == case['route']
    assert request.url.host == 'opa.example.com' and request.url.port == 8181
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert output['data'] == case['response'] and output['http_status'] == case['status']
    assert TOKEN not in str(output)
    cfg = case['config']
    if op == 'put_policy':
        assert request.headers['content-type'] == 'text/plain'
        assert request.content.decode() == cfg['policy']
    elif op == 'get_query':
        assert request.url.params['q'] == cfg['query']
    elif case['method'] in {'POST', 'PUT', 'PATCH'}:
        assert request.headers['content-type'] == ('application/json-patch+json' if op == 'patch_document' else 'application/json')
        body = json.loads(request.content)
        if op == 'evaluate_document': assert body == {'input': cfg['input']}
        elif op in {'evaluate_webhook_document', 'simple_query'}: assert body == cfg['input']
        elif op == 'put_document':
            assert body == cfg['document'] and request.headers['If-None-Match'] == '*'
        elif op == 'patch_document': assert body == cfg['patches']
        else: assert body == {k: v for k, v in cfg.items() if k != 'operation'}
    else:
        assert not request.content

@pytest.mark.asyncio
async def test_no_overwrite_is_a_reported_nonwrite(monkeypatch):
    mock(monkeypatch, 304, None, raw=b'')
    result = await node({'operation':'put_document','path':'servers','document':{},'create_only':True}).execute({})
    assert result['written'] is False and result['http_status'] == 304

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_refusals_do_not_retry_and_redact_token(monkeypatch, status):
    requests = mock(monkeypatch, status, {'message': TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({'operation':'list_policies'}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [False, {}, {'result':False}, {'result':None}])
async def test_false_null_undefined_decisions_are_preserved(monkeypatch, payload):
    mock(monkeypatch, 200, payload)
    result = await node({'operation':'evaluate_document','path':'authz/allow','input':{}}).execute({})
    assert result['data'] == payload

@pytest.mark.asyncio
async def test_input_serialization_escaping_and_options(monkeypatch):
    requests = mock(monkeypatch, 200, {'result':False})
    await node({'operation':'evaluate_document','path':'team policies/allow','input':{'user':'a+b'},'metrics':True,'provenance':True}).execute({})
    assert requests[0].url.raw_path.startswith(b'/v1/data/team%20policies/allow?')
    assert dict(requests[0].url.params) == {'metrics':'true','provenance':'true'}
    assert json.loads(requests[0].content) == {'input':{'user':'a+b'}}

@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'result':{}}, {'code':'unauthorized','message':'rejected'}])
async def test_bad_policy_list_or_error_envelope_fails(monkeypatch, payload):
    mock(monkeypatch, 200, payload)
    with pytest.raises(ValueError): await node({'operation':'list_policies'}).execute({})

@pytest.mark.parametrize('url', ['http://opa.example.com', 'https://user:secret@opa.example.com', 'https://opa.example.com/v1', 'https://opa.example.com?q=x'])
def test_manual_credential_origin_validation(url):
    with pytest.raises(ValueError): native.OpenPolicyTokenCredential(base_url=url, api_token=TOKEN)

@pytest.mark.parametrize('path', ['../secrets','/servers','servers//id','servers/..','servers\\id'])
def test_paths_cannot_escape_document_route(path):
    with pytest.raises(ValueError): node({'operation':'delete_document','path':path})

def test_patch_required_values_and_source():
    with pytest.raises(ValidationError): native.JSONPatch(op='add',path='/x')
    with pytest.raises(ValidationError): native.JSONPatch(op='copy',path='/x')
    assert native.JSONPatch(op='replace',path='/x',value=None).model_dump(exclude_unset=True)['value'] is None
    assert native.OpenPolicyTokenCredential(base_url='https://OPA.example.com:8181/',api_token=TOKEN).credential_type == 'openpolicy_token'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['simple_query', 'evaluate_webhook_document'])
async def test_raw_decision_can_have_code_and_message(monkeypatch, operation):
    body = {'code': 'allow', 'message': 'Access granted'}
    mock(monkeypatch, 200, body)
    cfg = {'operation': operation, 'input': {}}
    if operation == 'evaluate_webhook_document': cfg['path'] = 'authz/decision'
    assert (await node(cfg).execute({}))['data'] == body

"""Offline request and failure regressions for the Bloom Growth integration."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import bloom_growth_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-bloom-growth-token'
CASES = json.loads((Path(__file__).parent / 'fixtures/bloom-growth/requests.json').read_text())['cases']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield  # These tests exercise HTTP only, without the shared PostgreSQL fixture.


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='bloom-fixture', node_type='automation-bloom-growth', node_data={
        'config': config, 'credentials': credentials or {'api_token': TOKEN},
    })


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_bloom_growth_exact_published_request(monkeypatch, case):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, content=b'') if case['empty'] else httpx.Response(200, json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.url.scheme == 'https' and request.url.host == 'app-next.bloomgrowth.com'
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if case['body'] is None:
        assert not request.content
    else:
        assert json.loads(request.content) == case['body']
        assert request.headers['content-type'] == 'application/json'
    if case['empty']:
        assert result['acknowledged'] is True
    else:
        assert result['data'] == case['response']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_bloom_growth_rejections_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text='Provider rejected token ' + TOKEN))
    result = await node({'operation':'create_todo','title':'Launch'}).execute({})
    assert result == {'status':'error','status_code':status,'error':'Provider rejected token [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'Name':'Ada'}, {'Id':7}, {'Id':7,'Name':None}, {'error':'Unauthorized'}, []])
async def test_bloom_growth_evidence_refuses_unidentified_or_error_response(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation':'get_me'}).execute({})


@pytest.mark.asyncio
async def test_bloom_growth_timeout_does_not_retry_write(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('token ' + TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({'operation':'create_goal','title':'Launch'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_bloom_growth_non_json_and_nested_redaction(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text='<html>Sign in</html>'))
    with pytest.raises(ValueError, match='non-JSON'):
        await node({'operation':'list_todos'}).execute({})
    transport(monkeypatch, lambda r: httpx.Response(200, json=[{'Name':TOKEN,'Nested':[TOKEN]}]))
    result = await node({'operation':'list_todos'}).execute({})
    assert TOKEN not in str(result)


@pytest.mark.parametrize('value', ['', 'Bearer secret', 'https://example.com/token', '<token>', 'secret\r\nheader', 'nonascii–token'])
def test_bloom_growth_manual_token_validation(value):
    with pytest.raises(ValidationError):
        native.BloomGrowthTokenCredential(api_token=value)


def test_bloom_growth_manual_defaults_and_evidence():
    from nodes.core.credential_connect import resolve_credential_class, shape_credential
    assert resolve_credential_class(native.CREDENTIAL_TYPE)[1] is native.BloomGrowthTokenCredential
    shaped, errors, resolved = shape_credential(native.CREDENTIAL_TYPE, {'api_token':'  '+TOKEN+'\n'})
    assert not errors and shaped['api_token'] == TOKEN
    assert resolved[1] is native.BloomGrowthTokenCredential
    assert native.BloomGrowthTokenCredential.model_validate(shaped).credential_type == native.CREDENTIAL_TYPE
    evidence = native.BloomGrowthNode.connection_evidence
    assert evidence.identity_operation == 'get_me' and evidence.identity_keys == ('Name',)
    assert len(CASES) == len(native.OPERATIONS) == 25


@pytest.mark.parametrize('config', [
    {'operation':'create_todo'}, {'operation':'get_todo','todo_id':'../users/mine'},
    {'operation':'get_goal','goal_id':0}, {'operation':'update_todo','todo_id':42},
    {'operation':'update_goal','goal_id':42}, {'operation':'update_score','score_id':42,'value':None},
    {'operation':'update_score','score_id':42,'value':float('nan')},
    {'operation':'create_milestone','goal_id':42,'title':'Launch','due_date':'2026-12-01T09:00:00'},
])
def test_bloom_growth_rejects_invalid_write_and_id_inputs(config):
    with pytest.raises(ValidationError):
        native.BloomGrowthFullConfig.model_validate({'config':config,'credentials':{'api_token':TOKEN}})


@pytest.mark.asyncio
async def test_bloom_growth_evidence_retains_http_rejection_code(monkeypatch):
    from nodes.core.connection_evidence import _raise_if_error_envelope, _ProviderRefused
    transport(monkeypatch, lambda r: httpx.Response(401, text='Credential refused'))
    result = await node({'operation':'get_me'}).execute({})
    with pytest.raises(_ProviderRefused, match='Credential refused.*HTTP 401'):
        _raise_if_error_envelope(result)

"""Exercise the native node against Bouncer's published request/response examples."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import bouncer_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/bouncer/examples.json').read_text())
CREDENTIAL = {'credential_type': 'bouncer_api_key', 'api_key': 'synthetic-bouncer-secret'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='bouncer-test', node_type='automation-bouncer',
        node_data={'config': config, 'credentials': CREDENTIAL})


def mock_client(monkeypatch, status, body):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e:e['config']['operation'])
async def test_documented_operations(monkeypatch, example):
    calls = mock_client(monkeypatch, example['http_status'], example['body'])
    out = await node(example['config']).execute({})
    assert out['status'] == 'success' and out['data'] == example['body']
    assert len(calls) == 1
    req = calls[0]
    assert req.method == example['method'] and req.url.path == example['path']
    assert req.url.host == 'api.usebouncer.com' and req.headers['x-api-key'] == CREDENTIAL['api_key']
    cfg = example['config']
    if 'emails' in cfg:
        expected = [{'email': x} for x in cfg['emails']] if cfg['operation'] in {'create_batch','create_batch_sample'} else cfg['emails']
        assert json.loads(req.content) == expected
        assert req.headers['Content-Type'] == 'application/json'
    else:
        assert not req.content
    expected_query = {'verify_email': {'email':'john@usebouncer.com','timeout':'10'},
        'get_batch': {'with-stats':'true'}, 'get_batch_results': {'download':'all'},
        'verify_domain': {'domain':'usebouncer.com'}}.get(cfg['operation'], {})
    assert dict(req.url.params) == expected_query


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_http_errors_are_not_success(monkeypatch, status):
    calls = mock_client(monkeypatch, status, {'message': 'rejected'})
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await node({'operation':'get_credits'}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_finish_acceptance_and_embedded_error(monkeypatch):
    mock_client(monkeypatch, 200, {'status':'400','error':'Bad Request','message':'batch has to be running to finish'})
    with pytest.raises(ValueError, match='batch has to be running'):
        await node({'operation':'finish_batch','batch_id':'batch-1'}).execute({})


@pytest.mark.asyncio
async def test_callback_and_path_isolation(monkeypatch):
    calls = mock_client(monkeypatch, 200, EXAMPLES[2]['body'])
    await node({'operation':'create_batch','emails':['john@usebouncer.com'], 'callback':'https://example.com/callback?a=b'}).execute({})
    assert dict(calls[0].url.params) == {'callback':'https://example.com/callback?a=b'}
    with pytest.raises(ValueError, match='single Bouncer resource ID'):
        await node({'operation':'get_batch','batch_id':'../other'}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'credits':True}, {'credits':-1}, [], {'error':'bad key'}])
async def test_credits_evidence_requires_a_real_balance(monkeypatch, body):
    mock_client(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({'operation':'get_credits'}).execute({})


def test_schema_credential_and_operation_count():
    assert len(native.ROUTES) == 15
    assert native.BouncerNode.connection_evidence.operation == 'get_credits'
    schema = native.BouncerNode.get_config_schema()
    assert schema['$defs']['BouncerAPIKeyCredential']['properties']['api_key']['ui:widget'] == 'password'

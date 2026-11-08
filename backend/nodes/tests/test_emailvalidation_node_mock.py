"""Provider-example transport tests, without a live account or provider calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import emailvalidation_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/emailvalidation/documented_responses.json').read_text())
KEY = 'synthetic-emailvalidation-key-42'
JOB = '629954218123464704'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='emailvalidation-test', node_type='automation-emailvalidation',
        node_data={'config': config, 'credentials': {'credential_type': 'emailvalidation_api_key', 'api_key': KEY}})


def transport(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        assert kwargs['timeout'] > 60
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,status,example', [
    ({'operation': 'validate_email', 'email': 'support@emailvalidation.io', 'catch_all': '1', 'timeout': 60}, 'GET', '/v1/info', 200, 'GET /v1/info'),
    ({'operation': 'create_bulk_job', 'emails': ['support@emailvalidation.io', 'info@example.com'], 'webhook_url': 'https://example.com/hooks/emailvalidation'}, 'POST', '/v1/bulk', 201, 'POST /v1/bulk'),
    ({'operation': 'get_bulk_job', 'job_id': JOB}, 'GET', '/v1/bulk/'+JOB, 200, 'GET /v1/bulk/{job_id}'),
    ({'operation': 'get_bulk_job_results', 'job_id': JOB}, 'GET', '/v1/bulk/'+JOB+'/results', 200, 'GET /v1/bulk/{job_id}/results'),
    ({'operation': 'get_account_status'}, 'GET', '/v1/status', 200, 'GET /v1/status'),
])
async def test_documented_responses_and_exact_wire_contract(monkeypatch, config, method, path, status, example):
    body = EXAMPLES[example]['body']
    calls = transport(monkeypatch, httpx.Response(status, json=body))
    result = await node(config).execute({})
    assert result == {'status': 'success', 'data': body}
    request, = calls
    assert request.method == method and request.url.path == path
    assert request.url.host == 'api.emailvalidation.io' and request.headers['apikey'] == KEY
    assert KEY not in str(request.url) and KEY not in str(result)
    if config['operation'] == 'validate_email':
        assert dict(request.url.params) == {'email': config['email'], 'catch_all': '1', 'timeout': '60'}
    elif method == 'POST':
        assert json.loads(request.content) == {k: v for k, v in config.items() if k != 'operation'} | {'catch_all': False}
        assert result['data']['webhook_secret'].startswith('whsec_')
    elif config['operation'] == 'get_bulk_job_results':
        assert dict(request.url.params) == {'format': 'json'}


@pytest.mark.asyncio
async def test_list_cursor_comes_from_last_job_and_stops_at_terminal_page(monkeypatch):
    job = EXAMPLES['GET /v1/bulk/{job_id}']['body']
    calls = transport(monkeypatch, httpx.Response(200, json={'data': [job], 'has_more': True}))
    result = await node({'operation': 'list_bulk_jobs', 'limit': 10, 'before': '629954218341568512'}).execute({})
    assert result['next_before'] == job['job_id']
    assert dict(calls[0].url.params) == {'limit': '10', 'before': '629954218341568512'}
    transport(monkeypatch, httpx.Response(200, json={'data': [], 'has_more': False}))
    assert (await node({'operation': 'list_bulk_jobs'}).execute({}))['next_before'] is None


@pytest.mark.asyncio
async def test_delete_requires_provider_acknowledgement_for_selected_job(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={'job_id': JOB, 'deleted': True}))
    result = await node({'operation': 'delete_bulk_job', 'job_id': JOB}).execute({})
    assert result['data']['deleted'] is True and calls[0].method == 'DELETE'
    assert not calls[0].content
    for body in ({'job_id': JOB, 'deleted': False}, {'job_id': '1', 'deleted': True}):
        transport(monkeypatch, httpx.Response(200, json=body))
        with pytest.raises(ValueError, match='confirm deletion'):
            await node({'operation': 'delete_bulk_job', 'job_id': JOB}).execute({})


@pytest.mark.asyncio
async def test_csv_is_a_binary_output(monkeypatch):
    content = EXAMPLES['GET /v1/bulk/{job_id}/results?format=csv']['body'].encode()
    calls = transport(monkeypatch, httpx.Response(200, content=content, headers={'content-type': 'text/csv; charset=utf-8'}))
    result = await node({'operation': 'get_bulk_job_results', 'job_id': JOB, 'format': 'csv'}).execute({})
    assert isinstance(result['file'], BinaryOutput) and result['file'].data == content
    assert calls[0].url.params['format'] == 'csv' and calls[0].headers['Accept'] == 'text/csv'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 409, 422, 429, 500])
async def test_errors_are_preserved_without_leaking_key_or_retrying(monkeypatch, code):
    calls = transport(monkeypatch, httpx.Response(code, json={'message': 'Provider refused '+KEY}))
    result = await node({'operation': 'get_account_status'}).execute({})
    assert result == {'status': 'error', 'http_status': code, 'error': 'Provider refused [redacted]'}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_rejects_html_and_error_envelopes_but_preserves_failed_job(monkeypatch):
    transport(monkeypatch, httpx.Response(200, text='<html>sign in</html>'))
    with pytest.raises(ValueError, match='JSON'):
        await node({'operation': 'get_account_status'}).execute({})
    transport(monkeypatch, httpx.Response(200, json={'error': {'message': 'Invalid key'}}))
    assert (await node({'operation': 'get_account_status'}).execute({}))['error'] == 'Invalid key'
    body = {**EXAMPLES['GET /v1/bulk/{job_id}']['body'], 'status': 'failed', 'error': 'Job failed'}
    transport(monkeypatch, httpx.Response(200, json=body))
    assert (await node({'operation': 'get_bulk_job', 'job_id': JOB}).execute({}))['data']['status'] == 'failed'


@pytest.mark.parametrize('config', [
    {'operation': 'validate_email', 'email': 'test@example.com', 'catch_all': 'true'},
    {'operation': 'validate_email', 'email': 'test@example.com', 'timeout': 61},
    {'operation': 'create_bulk_job', 'emails': []},
    {'operation': 'create_bulk_job', 'emails': ['x'*1001]},
    {'operation': 'create_bulk_job', 'emails': [''], 'webhook_url': 'http://example.com/hook'},
    {'operation': 'get_bulk_job', 'job_id': '../status'},
    {'operation': 'list_bulk_jobs', 'limit': 101},
    {'operation': 'get_bulk_job_results', 'job_id': JOB, 'format': 'xml'},
])
def test_contract_input_bounds(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_invalid_bulk_addresses_are_allowed_and_evidence_names_account():
    assert node({'operation': 'create_bulk_job', 'emails': ['', 'not-an-address']})
    evidence = native.EmailvalidationNode.connection_evidence
    assert evidence.identity_operation == 'get_account_status'
    assert evidence.identity_keys == ('account_id_str', 'account_id')
    assert native.EmailvalidationAPIKeyCredential(api_key=' '+KEY+'\n').api_key == KEY

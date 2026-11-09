"""Offline HTTP and manual-connect coverage for Senta Client API 1.6."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.senta_node import SentaAPIKeyCredential, SentaNode

FIXTURES = Path(__file__).parent / 'fixtures' / 'senta'
CREDENTIAL = {'credential_type': 'senta_api_key', 'practice': 'acme', 'api_key': 'senta-test-key'}


def node(config):
    data = {'config': config, 'credentials': CREDENTIAL}
    return SentaNode('senta-test', 'automation-senta', data, config=SentaNode.parse_config(data))


def stub(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr('nodes.senta_node.guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,query,body,fixture', [
    ({'operation':'list_clients','client_view_id':'v08a361263f4a'}, 'GET', '/api/clients/v08a361263f4a', {}, None, 'clients'),
    ({'operation':'get_client','client_id':'c260af21ede8f'}, 'GET', '/api/clients/c260af21ede8f', {}, None, 'client'),
    ({'operation':'search_clients','keywords':'Watchful & Cobweb'}, 'GET', '/api/clients/search', {'keywords':'Watchful & Cobweb'}, None, 'search'),
    ({'operation':'list_jobs'}, 'GET', '/api/jobs', {}, None, 'jobs'),
    ({'operation':'list_jobs','client_id':'c260af21ede8f','template_id':'w263ba3fa138b','status':'overdue'}, 'GET', '/api/jobs', {'cid':'c260af21ede8f','wid':'w263ba3fa138b','status':'overdue'}, None, 'jobs'),
    ({'operation':'list_client_jobs','client_id':'c260af21ede8f','status':'ready'}, 'GET', '/api/jobs', {'cid':'c260af21ede8f','status':'ready'}, None, 'jobs'),
    ({'operation':'list_template_jobs','template_id':'w263ba3fa138b'}, 'GET', '/api/jobs', {'wid':'w263ba3fa138b'}, None, 'jobs'),
    ({'operation':'create_client','doc_json':'{"title":"Mostly Harmless PLC"}'}, 'POST', '/api/clients', {}, {'doc':{'title':'Mostly Harmless PLC'}}, 'client'),
    ({'operation':'update_client','client_id':'c260af21ede8f','doc_json':'{"vatservice":true,"clientstate":"Client"}'}, 'PUT', '/api/clients/c260af21ede8f', {}, {'doc':{'vatservice':True,'clientstate':'Client'}}, 'client'),
    ({'operation':'delete_client','client_id':'c260af21ede8f'}, 'DELETE', '/api/clients/c260af21ede8f', {}, None, None),
    ({'operation':'create_client_note','client_id':'c260af21ede8f','text':'Called client'}, 'POST', '/api/notes', {}, {'cid':'c260af21ede8f','text':'Called client'}, 'note'),
    ({'operation':'create_job_note','client_id':'c260af21ede8f','job_id':'jgede54650fde','text':'Called client','note_type':'Phone call','date':'2019-08-26T00:00:00.000Z'}, 'POST', '/api/notes', {}, {'cid':'c260af21ede8f','jid':'jgede54650fde','text':'Called client','notetype':'Phone call','date':'2019-08-26T00:00:00.000Z'}, 'note'),
])
async def test_exact_contract_requests(monkeypatch, config, method, path, query, body, fixture):
    calls = []
    response = json.loads((FIXTURES / (fixture + '.json')).read_text()) if fixture else None
    def handler(request):
        calls.append(request)
        assert request.method == method
        assert request.url.host == 'acme.senta.co'
        assert request.url.path == path
        assert dict(request.url.params) == query
        assert request.headers['x-auth'] == CREDENTIAL['api_key']
        assert 'authorization' not in request.headers
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json=response) if fixture else httpx.Response(200)
    stub(monkeypatch, handler)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    if fixture:
        assert result['data'] == response
    else:
        assert result['deleted_client_id'] == config['client_id']


@pytest.mark.asyncio
async def test_connection_evidence_reads_account_jobs(monkeypatch):
    assert SentaNode.connection_evidence.operation == 'list_jobs'
    stub(monkeypatch, lambda r: httpx.Response(200, json=json.loads((FIXTURES/'jobs.json').read_text())))
    result = await node({'operation':'list_jobs'}).execute({})
    assert result['items'][0]['title'] == 'Accounts setup'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, 'API key invalid'), (403, 'Access denied'), (429, 'Too many requests'), (500, 'Malformed request')])
async def test_rejections_and_writes_never_retry(monkeypatch, status, body):
    calls = []
    def handler(r):
        calls.append(r)
        return httpx.Response(status, text=body)
    stub(monkeypatch, handler)
    result = await node({'operation':'create_client_note','client_id':'c260af21ede8f','text':'Hello'}).execute({})
    assert result == {'status':'error','http_status':status,'error':body}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'docs':{}}, {'error':'invalid_auth'}, ['bad'], {'doc':{}}])
async def test_malformed_lists_fail_closed(monkeypatch, body):
    stub(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert (await node({'operation':'list_jobs'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_secret_redaction(monkeypatch):
    stub(monkeypatch, lambda r: httpx.Response(401, text='Rejected ' + CREDENTIAL['api_key']))
    result = await node({'operation':'list_jobs'}).execute({})
    assert CREDENTIAL['api_key'] not in str(result)


@pytest.mark.parametrize('practice', ['evil.example', 'acme.senta.co', '../acme', 'a/b', 'a:443', 'https://acme.senta.co', 'acme@evil'])
def test_workspace_cannot_escape_provider(practice):
    with pytest.raises(ValidationError):
        SentaAPIKeyCredential(practice=practice, api_key='valid-key')


def test_manual_credential_defaults_and_normalization():
    credential = SentaAPIKeyCredential(practice=' Acme ', api_key=' real-key ')
    assert credential.credential_type == 'senta_api_key'
    assert credential.practice == 'acme'
    assert credential.api_key == 'real-key'


@pytest.mark.parametrize('config', [
    {'operation':'get_client','client_id':'c123/../search'},
    {'operation':'list_clients','client_view_id':'c123'},
    {'operation':'list_jobs','status':'invented'},
    {'operation':'create_client','doc_json':'{}'},
    {'operation':'create_client','doc_json':'{"doc":{"title":"Test"}}'},
    {'operation':'create_client','doc_json':'{"title":NaN}'},
    {'operation':'create_job_note','client_id':'c123','text':'Hello'},
    {'operation':'create_client_note','client_id':'c123','text':'Hello','date':'tomorrow'},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)

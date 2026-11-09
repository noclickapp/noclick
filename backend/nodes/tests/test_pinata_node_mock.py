"""Exercise all native Pinata operations against recorded contract examples.

Request assertions cover route, auth, query and JSON serialization; no account or
network access is used. Error and credential tests prevent false connection proofs.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import pinata_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-pinata-jwt-42'
CASES = json.loads((Path(__file__).parent / 'fixtures/pinata/contract.json').read_text())['cases']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='pinata-fixture', node_type='automation-pinata', node_data={
        'config': config, 'credentials': credentials or {'credential_type': 'pinata_jwt', 'jwt': TOKEN}})


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
@pytest.mark.parametrize('case', CASES, ids=lambda row: row['operation'])
async def test_each_contract_operation(monkeypatch, case):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'api.pinata.cloud'
    assert request.url.path == case['path']
    assert dict(request.url.params) == case['params']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == case['body']
    if request.method != 'GET':
        assert result['acknowledged'] is True
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_filters_boolean_metadata_and_pagination(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={'data': {'files': [], 'next_page_token': 'opaque-next'}}))
    result = await node({'operation':'list_files','network':'private','cid_pending':False,'mime_type':'text/plain',
        'metadata':{'topic':'art + music'},'page_token':'opaque-previous','limit':25}).execute({})
    assert dict(requests[0].url.params) == {'cidPending':'false','mimeType':'text/plain','metadata[topic]':'art + music','pageToken':'opaque-previous','limit':'25'}
    assert result['has_more'] is True and result['next_page_token'] == 'opaque-next'
    assert requests[0].url.path == '/v3/files/private'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 429, 500])
async def test_non_success_never_proves_connection_or_write(monkeypatch, code):
    requests = transport(monkeypatch, lambda _: httpx.Response(code, text='Provider rejected ' + TOKEN, headers={'Location':'https://other.test'}))
    result = await node({'operation':'list_files'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert result['message'] == 'Provider rejected [redacted]'
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'data':{}}, {'data':{'files':'bad'}}, {'error':'denied'}, {'data':{'files':[],'next_page_token':7}}])
async def test_bad_page_never_proves_connection(monkeypatch, payload):
    transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    assert (await node({'operation':'list_files'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_uncertain_write_and_async_acknowledgement(monkeypatch):
    transport(monkeypatch, lambda request: (_ for _ in ()).throw(httpx.ReadTimeout('timeout',request=request)))
    result = await node({'operation':'delete_file','file_id':'file-123'}).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unverified'
    transport(monkeypatch, lambda _: httpx.Response(200,json={'data':{'id':'pin-123','status':'prechecking'}}))
    result = await node({'operation':'pin_by_cid','cid':'cid-123'}).execute({})
    assert result['pin_completion_verified'] is False


@pytest.mark.parametrize('config', [
    {'operation':'get_file','file_id':'../escape'}, {'operation':'get_group','group_id':'https://evil.test'},
    {'operation':'update_file','file_id':'file-123'}, {'operation':'update_group','group_id':'group-123'},
    {'operation':'create_download_link','url':'https://evil.test/files/cid','date':1},
])
def test_invalid_input(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_and_account_evidence():
    credential = native.PinataJWTCredential.model_validate({'jwt':'  '+TOKEN+'  '})
    assert credential.jwt == TOKEN and credential.credential_type == 'pinata_jwt'
    assert native.PinataNode.connection_evidence.operation == 'list_files'
    for token in ['Bearer abc', 'https://example.test/token', '<token>', '']:
        with pytest.raises(ValidationError):
            native.PinataJWTCredential.model_validate({'jwt': token})

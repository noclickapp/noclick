"""Listclean HTTP-boundary tests with synthetic credentials; no account calls."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import listclean_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/listclean/operations.json').read_text())
TOKEN = 'synthetic-listclean-api-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='listclean-test', node_type='automation-listclean',
        node_data={'config': config, 'credentials': {'credential_type':'listclean_api_key', 'api_key':TOKEN}})


def mock_client(monkeypatch, respond):
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_listclean_wire_contract(operation, monkeypatch):
    case, calls = CASES[operation], []
    payload = {'success': 1, 'message': 'Completed', 'data': {'credits': 99}}
    if operation == 'list_lists':
        payload['data'] = {'total': 1, 'cursor': 1, 'lists': [{'list_id': 1, 'filename': 'sample-list.csv'}]}
    content = b'email\nuser1@example.com\n' if operation == 'download_csv' else b'[{"email":"user1@example.com"}]'
    def respond(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.listclean.xyz'
        assert request.headers['X-Auth-Token'] == TOKEN
        assert 'X-Auth-Token' not in request.url.params
        expected = '/v1' + case['path']
        for key,value in case['config'].items():
            expected = expected.replace('{'+key+'}', str(value))
        assert request.url.path == expected
        assert dict(request.url.params) == ({k:str(v) for k,v in case['config'].items() if k != 'operation'} if operation == 'list_logs' else {})
        if request.method == 'POST':
            assert json.loads(request.content) == {k:v for k,v in case['config'].items() if k not in {'operation','upload_id'}}
        else:
            assert not request.content
        if operation.startswith('download_'):
            return httpx.Response(200, content=content, headers={'content-type':'text/csv' if operation == 'download_csv' else 'application/json'})
        return httpx.Response(200, json=payload)
    mock_client(monkeypatch, respond)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and len(calls) == 1
    if operation.startswith('download_'):
        assert isinstance(result['file'], BinaryOutput) and result['file'].data == content
        assert result['file'].filename.endswith('.csv' if operation == 'download_csv' else '.json')
    else:
        assert result['data'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,422,429,500,302])
async def test_listclean_http_failure_no_retry_or_secret(status, monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=TOKEN)
    mock_client(monkeypatch, respond)
    result=await node({'operation':'verify_batch','emails':['user1@example.com']}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in str(result) and len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['get_credits','download_csv','download_json'])
async def test_listclean_application_failure(operation, monkeypatch):
    mock_client(monkeypatch, lambda r:httpx.Response(200,json={'success':0,'message':'Rejected '+TOKEN}))
    config={'operation':operation, **({'list_id':1,'type':'clean'} if operation.startswith('download_') else {})}
    result=await node(config).execute({})
    assert result['status']=='error' and result['message']=='Rejected [redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{},{'success':1},{'success':1,'data':{}},{'success':1,'data':{'credits':True}},{'success':1,'data':{'credits':-1}}])
async def test_listclean_incomplete_evidence(body, monkeypatch):
    mock_client(monkeypatch, lambda r:httpx.Response(200,json=body))
    with pytest.raises(ValueError):
        await node({'operation':'get_credits'}).execute({})


@pytest.mark.parametrize('value', ['', 'https://example.com/key', 'a\nb'])
def test_listclean_invalid_key(value):
    with pytest.raises(ValidationError):
        native.ListcleanAPIKeyCredential(api_key=value)


@pytest.mark.parametrize('config', [
    {'operation':'verify_batch','emails':[]},
    {'operation':'verify_batch','emails':['test@example.com']*3001},
    {'operation':'get_list','list_id':0},
    {'operation':'get_upload','upload_id':'../credits'},
    {'operation':'download_csv','list_id':1,'type':'all'},
    {'operation':'list_logs','start_date':'2026-11-01','end_date':'2026-11-05','limit':101},
])
def test_listclean_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_listclean_transport_failure_hides_secret(monkeypatch):
    def respond(request):
        raise httpx.ReadTimeout(TOKEN,request=request)
    mock_client(monkeypatch, respond)
    with pytest.raises(ValueError,match='could not be confirmed') as exc:
        await node({'operation':'get_credits'}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_listclean_download_rejects_html(monkeypatch):
    mock_client(monkeypatch,lambda r:httpx.Response(200,text='<html>Sign in</html>',headers={'content-type':'text/html'}))
    with pytest.raises(ValueError,match='results file'):
        await node({'operation':'download_csv','list_id':1,'type':'clean'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [{}, {'lists':None}, {'lists':[{}]}])
async def test_listclean_list_evidence_requires_real_rows(data,monkeypatch):
    mock_client(monkeypatch,lambda r:httpx.Response(200,json={'success':1,'data':data}))
    with pytest.raises(ValueError):
        await node({'operation':'list_lists'}).execute({})


@pytest.mark.asyncio
async def test_listclean_list_evidence_names_the_users_files(monkeypatch):
    from nodes.core.connection_evidence import _rows_from_operation, _label_from
    payload={'success':1,'data':{'total':1,'cursor':1,'lists':[{'list_id':1,'filename':'sample-list.csv'}]}}
    mock_client(monkeypatch,lambda r:httpx.Response(200,json=payload))
    result=await node({'operation':'list_lists'}).execute({})
    spec=native.ListcleanNode.connection_evidence
    assert [_label_from(row,spec.label_keys) for row in _rows_from_operation(result)]==['sample-list.csv']

"""Offline request/response checks for the fixed ConvertAPI v2 operations."""
from urllib.parse import parse_qs
import httpx
import pytest
from nodes import convertapi_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

async def run(monkeypatch, config, response):
    seen = []
    original = httpx.AsyncClient
    def handler(request):
        seen.append(request)
        return response
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    node = NodeFactory.create_node(node_id='convertapi-test', node_type='automation-convertapi', node_data={
        'config':config,'credentials':{'credential_type':'convertapi_api_secret','api_secret':'synthetic-secret-123'}})
    async def emit(output): pass
    monkeypatch.setattr(node, 'emit', emit)
    result = await node.execute({})
    return seen[0], result

@pytest.mark.asyncio
async def test_account_redacts_secret(monkeypatch):
    request, result = await run(monkeypatch, {'operation':'get_account'}, httpx.Response(200,json={
        'Email':'owner@example.com','Secret':'synthetic-secret-123','ApiKey':123,'Active':True}))
    assert str(request.url) == native.BASE+'/user'
    assert request.headers['Authorization'] == 'Bearer synthetic-secret-123'
    assert result['data'] == {'Email':'owner@example.com','Active':True}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path',native.ROUTES.items())
async def test_conversion_routes_and_temporary_storage(monkeypatch,operation,path):
    request, result = await run(monkeypatch, {'operation':operation,'file':'https://example.com/file.pdf','file_name':'result'},
        httpx.Response(200,json={'ConversionCost':1,'Files':[{'FileName':'result.pdf','Url':'https://v2.convertapi.com/d/result','FileData':'private-base64'}]}))
    assert request.method == 'POST' and request.url.path == path
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {"File":["https://example.com/file.pdf"], "StoreFile":["true"], "FileName":["result"]}
    assert 'FileData' not in result['data']['Files'][0]

@pytest.mark.asyncio
async def test_statistics(monkeypatch):
    request,result=await run(monkeypatch,{'operation':'get_statistics','start_date':'2023-09-01','end_date':'2023-09-30'},httpx.Response(200,json=[]))
    assert dict(request.url.params)=={'startDate':'2023-09-01','endDate':'2023-09-30'}
    assert result['data']==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method',[('get_file_info','HEAD'),('delete_file','DELETE')])
async def test_files(monkeypatch,operation,method):
    request,result=await run(monkeypatch,{'operation':operation,'file_id':'25811safe8e61dd3f51ef00ee5f58b92'},httpx.Response(200,headers={'file-name':'result.pdf'}))
    assert request.method==method and request.url.path=='/d/25811safe8e61dd3f51ef00ee5f58b92'
    assert result['data']==({'file-name':'result.pdf'} if method=='HEAD' else {'file_id':'25811safe8e61dd3f51ef00ee5f58b92','deleted':True})

@pytest.mark.asyncio
async def test_rejection_redacts_credential(monkeypatch):
    with pytest.raises(ValueError,match=r'HTTP 401: rejected \[redacted\]'):
        await run(monkeypatch,{'operation':'get_account'},httpx.Response(401,text='rejected synthetic-secret-123'))

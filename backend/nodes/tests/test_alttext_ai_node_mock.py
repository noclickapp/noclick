import json
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.alttext_ai_node import AlttextAiNode, AlttextAiFullConfig
from nodes.core.registry import NodeFactory

CASES = [
    ({'operation':'get_account'}, 'GET','/account',None),
    ({'operation':'update_account','name':'My New Company'},'PUT','/account',{'account':{'name':'My New Company'}}),
    ({'operation':'list_images'},'GET','/images',None),
    ({'operation':'search_images','q':'butterfly'},'GET','/images/search',None),
    ({'operation':'create_image','url':'https://example.com/image.jpg'},'POST','/images',{'image':{'url':'https://example.com/image.jpg'},'overwrite':False}),
    ({'operation':'get_image','asset_id':'butterfly-123456'},'GET','/images/butterfly-123456',None),
    ({'operation':'update_image','asset_id':'butterfly-123456','alt_text':'Butterfly'},'PUT','/images/butterfly-123456',{'image':{'alt_text':'Butterfly'}}),
    ({'operation':'delete_image','asset_id':'butterfly-123456'},'DELETE','/images/butterfly-123456',None),
    ({'operation':'scrape_page','url':'https://example.com/gallery.html'},'POST','/images/page_scrape',{'page_scrape':{'url':'https://example.com/gallery.html'},'include_existing':False}),
    ({'operation':'list_api_keys'},'GET','/api_keys',None),
    ({'operation':'get_api_key','id':12},'GET','/api_keys/12',None),
    ({'operation':'get_api_key_history','id':12},'GET','/api_keys/12/history',None),
]

@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES)
async def test_alttext_ai_requests(monkeypatch,config,method,path,body):
    seen=[]
    def handle(request):
        seen.append(request)
        assert request.method == method
        assert request.url.path == '/api/v1'+path
        assert request.headers['X-API-Key']=='test-realistic-key'
        if body is not None: assert json.loads(request.content)==body
        return httpx.Response(200,json={'name':'Example account','token':'secret-token'})
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c: yield c
    monkeypatch.setattr('nodes.alttext_ai_node.guarded_async_client',client)
    node=NodeFactory.create_node(node_id='test',node_type='automation-alttext-ai',node_data={'config':config,'credentials':{'credential_type':'alttext_ai_api_key','api_key':'test-realistic-key'}})
    result=await node.execute({})
    assert len(seen)==1
    assert result['status']=='success'
    assert result['data']=={'name':'Example account'}

@pytest.mark.parametrize('asset_id',['../escape','a/b','a?b','..'])
def test_alttext_ai_rejects_path_injection(asset_id):
    with pytest.raises(ValueError):
        AlttextAiFullConfig.model_validate({'config':{'operation':'get_image','asset_id':asset_id}})

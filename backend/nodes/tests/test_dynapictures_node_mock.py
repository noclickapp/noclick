"""Exercise the real node through HTTPX's transport, without provider writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.dynapictures_node import DynapicturesNode, DynapicturesAPIKeyCredential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/dynapictures/responses.json').read_text())
KEY = 'dnp_unit_test_secret_abc123'


def node(config, credentials=None):
    parsed = DynapicturesNode.parse_config({'config': config, 'credentials': credentials or {'api_key': KEY}})
    return DynapicturesNode('test', 'automation-dynapictures', {}, config=parsed)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,query,body', [
    ({'operation':'generate_image','uid':'debcaw6f99','params':[{'name':'text1','text':'Suspendisse tempus odio'}]}, 'POST','/designs/debcaw6f99',{}, {'params':[{'name':'text1','text':'Suspendisse tempus odio'}], 'responseFormat':'json'}),
    ({'operation':'search_generated_images','keyword':'Summer Sale','metadata':'customer 42','startDate':'2026-06-01T00:00:00Z'},'GET','/generated-images',{'keyword':'Summer Sale','metadata':'customer 42','startDate':'2026-06-01T00:00:00Z'},None),
    ({'operation':'delete_generated_image','teamUid':'ff01d10f8d','filename':'9be4738250.png'},'DELETE','/images/ff01d10f8d/9be4738250.png',{},None),
    ({'operation':'start_ai_generation','modelId':'flux-2-pro','prompt':'A photorealistic cup of coffee','ratio':'16:9'},'POST','/ai/generate',{}, {'modelId':'flux-2-pro','prompt':'A photorealistic cup of coffee','ratio':'16:9'}),
    ({'operation':'get_ai_generation','jobUid':'aBcD1234eFgH5678iJkL9012'},'GET','/ai/generate/aBcD1234eFgH5678iJkL9012',{},None),
    ({'operation':'list_templates','workspace_id':'74b5b2c96a'},'GET','/templates',{'workspace_id':'74b5b2c96a'},None),
    ({'operation':'get_template','uid':'000d61e4f7'},'GET','/templates/000d61e4f7',{},None),
    ({'operation':'create_design','workspaceUid':'74b5b2c96a','name':'Summer sale'},'POST','/designs',{}, {'workspaceUid':'74b5b2c96a','name':'Summer sale','width':650,'height':500}),
    ({'operation':'add_layer','uid':'000d61e4f7','type':'text','text':'Sale','x':0,'y':20},'POST','/designs/000d61e4f7/layers',{}, {'type':'text','text':'Sale','x':0,'y':20}),
    ({'operation':'update_layer','uid':'000d61e4f7','layerId':'text1','text':'Updated','styles':{'fontWeight':'bold'}},'PATCH','/designs/000d61e4f7/layers/text1',{}, {'text':'Updated','styles':{'fontWeight':'bold'}}),
    ({'operation':'delete_layer','uid':'000d61e4f7','layerId':'text1'},'DELETE','/designs/000d61e4f7/layers/text1',{},None),
    ({'operation':'reorder_layer','uid':'000d61e4f7','layerId':'text1','op':'toFront'},'POST','/designs/000d61e4f7/layers/text1/z-index',{}, {'op':'toFront'}),
    ({'operation':'resize_canvas','uid':'000d61e4f7','width':1080,'height':1080},'POST','/designs/000d61e4f7/canvas/resize',{}, {'width':1080,'height':1080}),
    ({'operation':'list_workspaces'},'GET','/workspaces',{},None),
    ({'operation':'create_workspace','name':'Banners for client 22'},'POST','/workspaces',{}, {'name':'Banners for client 22'}),
    ({'operation':'update_workspace','workspaceId':'74b5b2c96a','name':'Banners for client 1234'},'PUT','/workspaces/74b5b2c96a',{}, {'name':'Banners for client 1234'}),
    ({'operation':'delete_workspace','workspaceId':'74b5b2c96a'},'DELETE','/workspaces/74b5b2c96a',{},None),
    ({'operation':'list_media_assets','workspaceId':'74b5b2c96a','p':2},'GET','/media/74b5b2c96a/assets',{'p':'2'},None),
    ({'operation':'upload_media_asset_from_url','workspaceId':'74b5b2c96a','url':'https://dynapictures.com/images/banners/cat1.jpeg','name':'Cat'},'POST','/media/74b5b2c96a/assets/from-url',{}, {'url':'https://dynapictures.com/images/banners/cat1.jpeg','name':'Cat'}),
    ({'operation':'get_media_asset','workspaceId':'74b5b2c96a','assetId':'5a12844966'},'GET','/media/74b5b2c96a/assets/5a12844966',{},None),
    ({'operation':'delete_media_asset','workspaceId':'74b5b2c96a','assetId':'5a12844966'},'DELETE','/media/74b5b2c96a/assets/5a12844966',{},None),
    ({'operation':'subscribe_webhook','targetUrl':'https://mycompany.com/webhooks/my-endpoint','eventType':'NEW_IMAGE','templateId':'000d61e4f7'},'POST','/hooks',{}, {'targetUrl':'https://mycompany.com/webhooks/my-endpoint','eventType':'NEW_IMAGE','templateId':'000d61e4f7'}),
    ({'operation':'unsubscribe_webhook','targetUrl':'https://mycompany.com/webhooks/my-endpoint','templateId':'000d61e4f7'},'DELETE','/hooks',{}, {'targetUrl':'https://mycompany.com/webhooks/my-endpoint','eventType':'NEW_IMAGE','templateId':'000d61e4f7'}),
])
async def test_wire_contract(monkeypatch,config,method,path,query,body):
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.method == method
        assert request.url.host == 'api.dynapictures.com'
        assert request.url.path == path
        assert dict(request.url.params) == query
        assert request.headers['authorization'] == 'Bearer '+KEY
        assert (json.loads(request.content) if request.content else None) == body
        assert KEY not in str(request.url)
        op=config['operation']
        if op=='delete_generated_image':return httpx.Response(200)
        data = FIXTURES['workspaces'] if op=='list_workspaces' else [] if op in {'list_templates','search_generated_images'} else FIXTURES['queued'] if op=='start_ai_generation' else FIXTURES['image']
        return httpx.Response(202 if op=='start_ai_generation' else 200,json=data)
    transport(monkeypatch,handler)
    result=await node(config).execute({})
    assert result['success'] is True
    assert len(requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[400,401,402,403,404,429,500,504])
async def test_errors_are_not_retried_or_reported_as_success(monkeypatch,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':True,'message':'Valid API Key is required'})
    transport(monkeypatch,handler)
    out=await node({'operation':'list_workspaces'}).execute({})
    assert out['success'] is False
    assert out['http_status']==status
    assert out['error']=='Valid API Key is required'
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('fixture',['running','done'])
async def test_ai_job_states_and_result_url_are_preserved(monkeypatch,fixture):
    transport(monkeypatch,lambda request:httpx.Response(200,json=FIXTURES[fixture]))
    out=await node({'operation':'get_ai_generation','jobUid':'aBcD1234eFgH5678iJkL9012'}).execute({})
    assert out['data']==FIXTURES[fixture]


@pytest.mark.asyncio
async def test_error_envelope_on_200_and_secret_redaction(monkeypatch):
    transport(monkeypatch,lambda request:httpx.Response(200,json={'error':True,'message':'Rejected '+KEY}))
    out=await node({'operation':'list_workspaces'}).execute({})
    assert not out['success']
    assert KEY not in str(out)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[None,'oops',{'workspaces':[]},[1],[{}]])
async def test_invalid_workspace_response_is_not_connection_evidence(monkeypatch,payload):
    transport(monkeypatch,lambda request:httpx.Response(200,json=payload))
    with pytest.raises(ValueError):await node({'operation':'list_workspaces'}).execute({})


@pytest.mark.parametrize('key',['https://dynapictures.com/app/account','Bearer secret','<api_key>','{{ secret }}','a\nb'])
def test_credential_rejects_urls_headers_and_placeholders(key):
    with pytest.raises(ValidationError):DynapicturesAPIKeyCredential(api_key=key)


def test_manual_credential_needs_only_a_key_and_defaults_type():
    credential=DynapicturesAPIKeyCredential(api_key='  '+KEY+'  ')
    assert credential.credential_type=='dynapictures_api_key'
    assert credential.api_key==KEY


@pytest.mark.asyncio
async def test_path_segments_cannot_change_route_or_host(monkeypatch):
    seen=[]
    def handler(request):
        seen.append(request)
        assert request.url.raw_path==b'/templates/other%2Ftemplate%3Fq%3Dx'
        return httpx.Response(200,json={'id':'other/template?q=x','name':'Test'})
    transport(monkeypatch,handler)
    assert (await node({'operation':'get_template','uid':'other/template?q=x'}).execute({}))['success']
    assert len(seen)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,route', [
    ('generate_image', {'uid':'debcaw6f99'}, 'POST /designs/{uid}'),
    ('start_ai_generation', {'modelId':'flux-2-pro','prompt':'Coffee'}, 'POST /ai/generate'),
    ('get_ai_generation', {'jobUid':'aBcD1234eFgH5678iJkL9012'}, 'GET /ai/generate/{jobUid}'),
    ('list_templates', {}, 'GET /templates'),
    ('get_template', {'uid':'000d61e4f7'}, 'GET /templates/{uid}'),
    ('list_workspaces', {}, 'GET /workspaces'),
    ('create_workspace', {'name':'Banners for client 22'}, 'POST /workspaces'),
    ('update_workspace', {'workspaceId':'74b5b2c96a','name':'Banners for client 1234'}, 'PUT /workspaces/{workspaceId}'),
    ('delete_workspace', {'workspaceId':'74b5b2c96a'}, 'DELETE /workspaces/{workspaceId}'),
    ('list_media_assets', {'workspaceId':'74b5b2c96a'}, 'GET /media/{workspaceId}/assets'),
    ('get_media_asset', {'workspaceId':'74b5b2c96a','assetId':'5a12844966'}, 'GET /media/{workspaceId}/assets/{assetId}'),
    ('delete_media_asset', {'workspaceId':'74b5b2c96a','assetId':'5a12844966'}, 'DELETE /media/{workspaceId}/assets/{assetId}'),
    ('subscribe_webhook', {'targetUrl':'https://mycompany.com/webhooks/my-endpoint','templateId':'000d61e4f7'}, 'POST /hooks'),
    ('unsubscribe_webhook', {'targetUrl':'https://mycompany.com/webhooks/my-endpoint','templateId':'000d61e4f7'}, 'DELETE /hooks'),
])
async def test_documented_provider_responses(monkeypatch,operation,config,route):
    examples=json.loads((Path(__file__).parent / 'fixtures/dynapictures/documented.json').read_text())
    body=examples[route]['body']
    transport(monkeypatch,lambda request:httpx.Response(202 if operation=='start_ai_generation' else 200,json=body))
    out=await node({'operation':operation,**config}).execute({})
    assert out['data']==body
    assert out['success']

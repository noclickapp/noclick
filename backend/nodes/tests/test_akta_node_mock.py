"""Offline Akta request contract regressions."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import akta_node as native
from nodes.core.registry import NodeFactory
CASES = json.loads((Path(__file__).parent / 'fixtures/akta/operations.json').read_text())
TOKEN = 'synthetic-akta-key'

def node(config):
    return NodeFactory.create_node(node_id='akta-test', node_type='automation-akta', node_data={'config':config,'credentials':{'credential_type':'akta_api_key','api_key':TOKEN}})

def transport(monkeypatch, status=200, body=None):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_contract_routes_auth_and_fields(monkeypatch, operation):
    case=CASES[operation]
    requests=transport(monkeypatch, body=case['response'])
    result=await node(case['config']).execute({})
    assert result['status']=='success' and result['data']==case['response']['data']
    request=requests[0]
    assert request.method==case['method'] and request.url.host=='api.akta.pro'
    assert request.url.path=='/api'+case['path'].replace('{request_id}', 'test-request')
    assert request.headers['x-api-key']==TOKEN
    values={k:v for k,v in case['config'].items() if k not in {'operation','request_id'}}
    sent=dict(request.url.params) if request.method=='GET' else json.loads(request.content)
    assert all(sent[k]==v for k,v in values.items()) and len(requests)==1

@pytest.mark.asyncio
async def test_products_repeat_and_pagination_survives(monkeypatch):
    requests=transport(monkeypatch, body={'data':{},'limit':2,'offset':4})
    result=await node({'operation':'get_product_reviews','company':'canva.com','products':['a','b'],'limit':2,'offset':4}).execute({})
    assert requests[0].url.params.get_list('products')==['a','b']
    assert result['limit']==2 and result['offset']==4

@pytest.mark.asyncio
async def test_structured_list_filters(monkeypatch):
    filters={'firmographic.country':{'$in':['US']}}
    requests=transport(monkeypatch, body={'data':[]})
    await node({'operation':'generate_company_list','filters':filters,'sections':['firmographic'],'limit':20}).execute({})
    assert json.loads(requests[0].content)=={'filters':filters,'sections':['firmographic'],'limit':20}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['get_news','search_companies','search_industries'])
async def test_no_content(monkeypatch,operation):
    transport(monkeypatch,status=204)
    assert (await node(CASES[operation]['config']).execute({}))['data']==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,429,500])
async def test_rejection_redacts_key(monkeypatch,status):
    requests=transport(monkeypatch,status=status,body={'message':'Rejected '+TOKEN})
    result=await node({'operation':'search_companies','query':'canva'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in str(result) and len(requests)==1

def test_invalid_config():
    for config in [{'operation':'enrich_company'},{'operation':'get_news','company':'a','primary_company':'b'},{'operation':'generate_company_list','query':'a','filters':{}},{'operation':'get_product_reviews','company':'a','limit':51},{'operation':'get_news','limit':101},{'operation':'get_news','start_date':'2026-02-30'}]:
        with pytest.raises(ValidationError): native.AktaFullConfig.model_validate({'config':config})
    with pytest.raises(ValidationError): native.AktaAPIKeyCredential.model_validate({'credential_type':'other','api_key':TOKEN})

@pytest.mark.asyncio
async def test_provider_documented_list_envelope(monkeypatch):
    # https://docs.akta.pro/docs/list-generation/quickstart.md
    body=json.loads((Path(__file__).parent/'fixtures/akta/documented_list.json').read_text())
    transport(monkeypatch,body=body)
    result=await node({'operation':'generate_company_list','limit':50,'query':'SaaS companies in the US with Series A funding'}).execute({})
    assert result['count']==50 and result['data']==body['data']
    assert result['filters']==body['filters'] and result['query_translated'] is True

@pytest.mark.asyncio
@pytest.mark.parametrize('body',[[],{}, {'data':None}, {'data':{},'status':'error'}])
async def test_unexpected_and_error_responses(monkeypatch,body):
    transport(monkeypatch,body=body)
    assert (await node({'operation':'search_companies','query':'canva'}).execute({}))['status']=='error'

@pytest.mark.asyncio
async def test_date_serializes_and_path_is_encoded(monkeypatch):
    requests=transport(monkeypatch,body={'data':[]})
    await node({'operation':'get_news','start_date':'2026-01-01','end_date':'2026-01-02'}).execute({})
    assert requests[0].url.params['start_date']=='2026-01-01'
    for value in ['../admin','..','x/y','x?query=secret']:
        with pytest.raises(ValidationError):native.AktaGetRequestStatusConfig(request_id=value)

@pytest.mark.asyncio
async def test_json_text_from_config_editor(monkeypatch):
    requests=transport(monkeypatch,body={'data':[]})
    await node({'operation':'generate_company_list','filters':'{"location.hq.country":["USA"]}','sections':'["firmographic"]'}).execute({})
    assert json.loads(requests[0].content)=={'filters':{'location.hq.country':['USA']},'sections':['firmographic']}
    with pytest.raises(ValidationError):native.AktaGetProductReviewsConfig(company='canva.com',products='not json')

@pytest.mark.asyncio
async def test_documented_search_accepts_provider_casing_and_bare_domains(monkeypatch):
    # https://docs.akta.pro/docs/supporting-apis/company-search.md
    body=json.loads((Path(__file__).parent/'fixtures/akta/documented_search.json').read_text())
    transport(monkeypatch,body=body)
    result=await node({'operation':'search_companies','query':'Canva'}).execute({})
    assert result['data']==body['data']
    assert result['data'][0]['website']=='canva.com' and result['data'][0]['company_status']=='Private'


def test_enrichment_sections_remain_comma_separated_text():
    config=native.AktaEnrichCompanyConfig(company='canva.com',sections='firmographic,business_model')
    assert config.sections=='firmographic,business_model'

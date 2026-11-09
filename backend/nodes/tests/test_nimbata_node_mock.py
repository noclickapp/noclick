"""Exercise the real factory against synthetic Nimbata HTTP boundary fixtures."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import nimbata_node as native
from nodes.core.registry import NodeFactory

HTTP_CLIENT = httpx.AsyncClient
TOKEN = 'synthetic-nimbata-token'
UID = '019a6312-1b2c-7000-8000-000000000001'
CASES = json.loads((Path(__file__).parent / 'fixtures/nimbata/requests.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='fixture-nimbata', node_type='automation-nimbata', node_data={
        'config': config, 'credentials': {'credential_type': 'nimbata_api_token', 'api_token': TOKEN}})


def mock_http(monkeypatch, reply):
    requests=[]
    original=HTTP_CLIENT
    def handler(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['config']['operation'])
async def test_nimbata_exact_single_request(monkeypatch,case):
    requests=mock_http(monkeypatch,lambda req:httpx.Response(case['status'],json=case['response']) if case['status']!=204 else httpx.Response(204))
    result=await node(case['config']).execute({})
    assert result['status']=='success'
    assert len(requests)==1
    r=requests[0]
    assert r.method==case['method'] and r.url.path==case['path']
    assert r.url.host=='api.nimbata.com' and r.headers['authorization']=='Bearer '+TOKEN
    assert dict(r.url.params)==case['query']
    assert (json.loads(r.content) if r.content else None)==case['body']
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,302,400,401,403,404,429,500])
async def test_nimbata_rejection_no_retry_and_no_secret_echo(monkeypatch,status):
    requests=mock_http(monkeypatch,lambda req:httpx.Response(status,json={'detail':'Rejected '+TOKEN},headers={'Location':'https://example.test/'}))
    result=await node({'operation':'get_current_user'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in str(result) and len(requests)==1


@pytest.mark.asyncio
async def test_nimbata_paging_and_date_filters(monkeypatch):
    page='/orgs/'+UID+'/projects/'+UID+'/calls?cursor=opaque%2Btoken'
    requests=mock_http(monkeypatch,lambda req:httpx.Response(200,json={'items':[],'page':{'next':page}}))
    result=await node({'operation':'list_calls','org_id':UID,'project_id':UID,'start_date':'2026-11-01','end_date':'2026-11-09','utm_source':'Google + search','cursor':'opaque+token','page_size':100}).execute({})
    assert result['has_more'] and result['page']['next']==page and len(requests)==1
    q=dict(requests[0].url.params)
    assert json.loads(q['dateRange'])=={'startDate':'2026-11-01','endDate':'2026-11-09'}
    assert q['utm_source']=='Google + search' and q['cursor']=='opaque+token'


@pytest.mark.asyncio
@pytest.mark.parametrize('body',[{},[],{'id':UID},{'status':400,'detail':'Bad'},'html'])
async def test_nimbata_incomplete_identity_is_not_connection_evidence(monkeypatch,body):
    mock_http(monkeypatch,lambda req:httpx.Response(200,json=body))
    result=await node({'operation':'get_current_user'}).execute({})
    assert result['status']=='error'


@pytest.mark.asyncio
async def test_nimbata_204_reads_and_uncertain_transport(monkeypatch):
    case=next(c for c in CASES if c['config']['operation']=='get_call')
    mock_http(monkeypatch,lambda req:httpx.Response(204))
    result=await node(case['config']).execute({})
    assert result['data'] is None and result['http_status']==204
    def fail(req):raise httpx.ReadTimeout('secret '+TOKEN,request=req)
    mock_http(monkeypatch,fail)
    result=await node(next(c for c in CASES if c['config']['operation']=='set_call_rating')['config']).execute({})
    assert result['status']=='error' and result['write_outcome']=='unverified' and TOKEN not in str(result)


def test_nimbata_manual_credential_and_bounds():
    assert native.NimbataAPITokenCredential(api_token=TOKEN).credential_type=='nimbata_api_token'
    for value in ['Bearer '+TOKEN,'https://example.test/key','<token>','']:
        with pytest.raises((ValueError,ValidationError)):
            native.NimbataAPITokenCredential(api_token=value)
    for cfg in [
        {'operation':'get_project','org_id':UID,'project_id':'../other'},
        {'operation':'get_call','org_id':UID,'project_id':UID,'call_id':'..'},
        {'operation':'list_calls','org_id':UID,'project_id':UID,'start_date':'2026-11-01'},
        {'operation':'list_projects','org_id':UID,'page_size':101},
        {'operation':'list_leads','org_id':UID,'project_id':UID,'email':'invalid'},
        {'operation':'set_call_rating','org_id':UID,'project_id':UID,'call_id':'test','value':6},
        {'operation':'add_call_tags','org_id':UID,'project_id':UID,'call_id':'test','tag_ids':[]},
    ]:
        with pytest.raises((ValueError,ValidationError)):
            node(cfg)


@pytest.mark.asyncio
async def test_nimbata_incomplete_page_is_not_success(monkeypatch):
    mock_http(monkeypatch,lambda req:httpx.Response(200,json={'items':[]}))
    result=await node({'operation':'list_projects','org_id':UID}).execute({})
    assert result['status']=='error'


@pytest.mark.asyncio
async def test_nimbata_identity_accepts_empty_display_name(monkeypatch):
    # full_name is required but has no minLength in the published contract.
    profile={'id':UID,'org_id':UID,'full_name':'','email':'alex@example.test','phone_number':None,'is_org_owner':True}
    mock_http(monkeypatch,lambda req:httpx.Response(200,json=profile))
    result=await node({'operation':'get_current_user'}).execute({})
    assert result['status']=='success' and result['data']['email']=='alex@example.test'

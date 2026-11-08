"""Offline HTTP and parser checks using provider-published response examples."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import hlr_lookup_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/hlr-lookup/documented_responses.json').read_text())
CREDS = {'credential_type': 'hlr_lookup_api_key', 'api_key': 'synthetic-api-key', 'api_secret': 'synthetic-api-secret'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

def node(config):
    return NodeFactory.create_node(node_id='hlr-fixture', node_type='automation-hlr-lookup', node_data={'config':config,'credentials':CREDS})

def transport(monkeypatch, body, status=200):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(status,json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond),**kwargs)
    monkeypatch.setattr(native,'guarded_async_client',client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,route',native.ROUTES.items())
async def test_every_action_published_request_and_response(monkeypatch,operation,route):
    requests=transport(monkeypatch,FIXTURE['responses'][route])
    cfg={'operation':operation}
    if operation!='get_balance':
        cfg.update({'requests':[{'telephone_number':'447790606023'}]} if operation in {'lookup_numbers','lookup_portabilities','validate_numbers'} else {'telephone_number':'447790606023'})
    result=await node(cfg).execute({})
    assert result['status']=='success',result
    assert len(requests)==1
    request=requests[0]
    assert request.method=='POST' and str(request.url)==native.BASE_URL+route
    sent=json.loads(request.content)
    assert sent['api_key']==CREDS['api_key'] and sent['api_secret']==CREDS['api_secret']
    assert request.headers['content-type']=='application/json' and not request.url.query
    flags={'lookup_ported_date':'get_ported_date','lookup_landline_status':'get_landline_status','lookup_imsi_hash':'get_imsi_hash','lookup_usa_status':'usa_status'}
    if operation in flags: assert sent[flags[operation]]=='YES'
    assert all(secret not in str(result) for secret in (CREDS['api_key'],CREDS['api_secret']))
    if route=='/apiv2/mnp': assert 'telephone_number_type' not in result['results'][0]
    if operation=='get_balance': assert sent=={k:v for k,v in CREDS.items() if k!='credential_type'} and result['credits']==1234.5

@pytest.mark.asyncio
async def test_cache_zero_age_and_per_number_batch_options(monkeypatch):
    requests=transport(monkeypatch,FIXTURE['responses']['/apiv2/hlr'])
    cfg={'operation':'lookup_numbers','requests':[{'telephone_number':'447790606023','cache_days_global':0,'cache_days_private':30,'save_to_cache':'PRIVATE','get_ported_date':'YES'},{'telephone_number':'16175551212','usa_status':'YES'}]}
    assert (await node(cfg).run({}))['status']=='success'
    assert json.loads(requests[0].content)['requests']==cfg['requests']

@pytest.mark.asyncio
async def test_partial_and_all_failed_batches(monkeypatch):
    good=FIXTURE['responses']['/apiv2/hlr']['results'][0]
    transport(monkeypatch,{'results':[good,{'error':'INSUFFICIENT_CREDIT'}]})
    cfg={'operation':'lookup_numbers','requests':[{'telephone_number':'447790606023'},{'telephone_number':'16175551212'}]}
    result=await node(cfg).execute({})
    assert result['status']=='partial' and result['failed_count']==1
    transport(monkeypatch,{'results':[{'error':'INSUFFICIENT_CREDIT'},{'error':'TOO_MANY_REQUESTS'}]})
    result=await node(cfg).execute({})
    assert result['status']=='error' and result['failed_count']==2

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,302,400,401,403,429,500])
async def test_failures_redact_credentials_and_do_not_retry(monkeypatch,status):
    requests=transport(monkeypatch,{'error':'UNAUTHORIZED','message':'Invalid api_key or api_secret '+CREDS['api_secret']},status)
    result=await node({'operation':'get_balance'}).execute({})
    assert result['status']=='error' and result['status_code']==status and len(requests)==1
    assert CREDS['api_secret'] not in str(result) and 'Invalid api_key or api_secret' in result['error']

@pytest.mark.asyncio
@pytest.mark.parametrize('body',[{},[],{'Status':'OK','Credits':True},{'Status':'OK','Credits':'123'},{'Status':'NO','Credits':12}])
async def test_connection_requires_confirmed_numeric_balance(monkeypatch,body):
    transport(monkeypatch,body)
    assert (await node({'operation':'get_balance'}).execute({}))['status']=='error'

@pytest.mark.asyncio
async def test_prose_balance_and_malformed_lookup(monkeypatch):
    transport(monkeypatch,{'body':{'Status':'OK','Credits':15000}})
    assert (await node({'operation':'get_balance'}).execute({}))['credits']==15000
    for body in [{'results':[]},{'results':[{'error':'NONE'}]},{'results':['bad']}]:
        transport(monkeypatch,body)
        assert (await node({'operation':'lookup_number','telephone_number':'447790606023'}).execute({}))['status']=='error'

@pytest.mark.parametrize('config',[
    {'operation':'lookup_numbers','requests':[]},
    {'operation':'lookup_numbers','requests':[{'telephone_number':'447790606023'}]*81},
    {'operation':'lookup_number'},
    {'operation':'lookup_number','telephone_number':'447790606023','cache_days_global':31},
    {'operation':'lookup_number','telephone_number':'447790606023','cache_days_private':True},
    {'operation':'validate_number','telephone_number':'447790606023','save_to_cache':'YES'},
    {'operation':'lookup_ported_date','telephone_number':'447790606023','get_ported_date':'NO'},
    {'operation':'get_balance','telephone_number':'447790606023'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises(ValueError): node(config)

def test_manual_credential_default_and_evidence():
    assert native.HlrLookupApiKeyCredential(api_key='key',api_secret='secret').credential_type==CREDS['credential_type']
    data,errors,resolved=shape_credential(CREDS['credential_type'],{k:v for k,v in CREDS.items() if k!='credential_type'})
    assert not errors and resolved[1] is native.HlrLookupApiKeyCredential
    assert resolved[1].model_validate(data).credential_type==CREDS['credential_type']
    assert native.HlrLookupNode.connection_evidence.operation=='get_balance'

@pytest.mark.asyncio
@pytest.mark.parametrize('body,status,expected',[
    ({'error':'UNAUTHORIZED','message':'Invalid api_key or api_secret'},401,False),
    ({'Status':'OK','Credits':1234.5},200,True),
    ({'Status':'OK','Credits':'invalid'},200,None),
])
async def test_connect_verdict_uses_real_balance_parser(monkeypatch,body,status,expected):
    from nodes.core import run_op, connection_evidence as evidence
    requests=transport(monkeypatch,body,status)
    async def run(**kwargs):
        assert kwargs['credential_data']==CREDS and kwargs['operation']=='get_balance'
        return await node({'operation':kwargs['operation']}).execute({})
    monkeypatch.setattr(run_op,'run_node_operation',run)
    verdict=await evidence.collect_evidence(node_type='automation-hlr-lookup',credential_data=CREDS,user_id='fixture-user')
    assert verdict.reachable is expected and len(requests)==1
    if expected is False: assert 'Invalid api_key or api_secret' in verdict.error

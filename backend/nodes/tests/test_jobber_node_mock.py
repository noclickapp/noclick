"""Official examples, GraphQL serialization and HTTP-200 error handling."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes.core.registry import NodeFactory
from nodes.jobber_node import JobberConfig, JobberOAuthCredential, build_query
from nodes.oauth.jobber_oauth import OAUTH_PROVIDER
from nodes.jobber_operations import QUERIES

FIXTURES=json.loads((Path(__file__).parent/'fixtures/jobber/documented_examples.json').read_text())

def node(config):
    n=NodeFactory.create_node(node_id='jobber-test',node_type='automation-jobber',node_data={
        'config':config,'credentials':{'credential_type':'jobber_oauth','access_token':'unit-test-token'}})
    n.emit=AsyncMock()
    return n

def transport(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))

@pytest.mark.asyncio
async def test_documented_nullable_job(monkeypatch):
    def handler(request):
        assert request.method=='POST'
        assert str(request.url)=='https://api.getjobber.com/api/graphql'
        assert request.headers['X-JOBBER-GRAPHQL-VERSION']=='2026-09-25'
        assert request.headers['Authorization']=='Bearer unit-test-token'
        assert json.loads(request.content)['query']=='query { job(id: "MTc1") { id title } }'
        return httpx.Response(200,json=FIXTURES['response_examples']['SampleQuery2']['value'])
    transport(monkeypatch,handler)
    assert (await node({'operation':'get_job','job_id':'MTc1'}).execute({}))['data']=={'job':None}

@pytest.mark.parametrize('op,example',[('get_account','GetAccount'),('list_clients','SampleQuery'),
    ('list_jobs','GetJobs'),('list_quotes','quotesQuery'),('list_custom_field_configurations','GetAllConfigurationsExample')])
def test_fixed_selections_are_pinned(op,example):
    assert QUERIES[op]==FIXTURES['request_examples'][example]['value']

def test_mutation_arguments_and_escaping():
    adapter=TypeAdapter(JobberConfig)
    query=build_query(adapter.validate_python({'operation':'create_client','first_name':'"}) { appDisconnect } #','last_name':'Test'}))
    assert '\\"' in query
    assert 'emails' not in query
    assert 'userErrors { message path }' in query
    query=build_query(adapter.validate_python({'operation':'create_link_configuration','name':'Link Example','text':'View link here','url':'https://www.example.com'}))
    assert 'appliesTo: ALL_JOBS' in query and 'transferable: false' in query and 'readOnly: false' in query
    query=build_query(adapter.validate_python({'operation':'edit_client_custom_fields','client_id':'MQ==','custom_fields':[
        {'customFieldConfigurationId':'Mg==','valueNumeric':5285}]}))
    assert 'clientId: "MQ=="' in query and 'valueNumeric: 5285' in query

@pytest.mark.parametrize('body',[{'errors':[{'message':'Denied'}]},
    {'data':{'clientCreate':{'client':None,'userErrors':[{'message':'Invalid','path':['input']}]}}},{},[]])
@pytest.mark.asyncio
async def test_graphql_failure_is_not_success(monkeypatch,body):
    transport(monkeypatch,lambda request:httpx.Response(200,json=body))
    n=node({'operation':'get_account'})
    with pytest.raises(ValueError):await n.execute({})
    n.emit.assert_not_awaited()

@pytest.mark.asyncio
async def test_http_rejection(monkeypatch):
    transport(monkeypatch,lambda request:httpx.Response(401,json={'message':'Unauthorized'}))
    with pytest.raises(httpx.HTTPStatusError):await node({'operation':'get_account'}).execute({})

@pytest.mark.parametrize('body,valid',[
    ({'data':{'account':{'id':'MQ==','name':'Test Account'}}},True),
    ({'errors':[{'message':'Denied'}],'data':{'account':None}},False),
    ({'data':{'account':{'name':'Test Account'}}},False)])
@pytest.mark.asyncio
async def test_oauth_post_identity(monkeypatch,body,valid):
    def handler(request):
        assert request.method=='POST'
        assert json.loads(request.content)=={'query':'{ account { id name } }'}
        assert request.headers['X-JOBBER-GRAPHQL-VERSION']
        return httpx.Response(200,json=body)
    original=httpx.AsyncClient
    monkeypatch.setattr(type(OAUTH_PROVIDER),'_client',lambda *args:original(transport=httpx.MockTransport(handler)))
    if valid:assert await OAUTH_PROVIDER.account_name('unit-test-token')=='Test Account'
    else:
        with pytest.raises(ValueError):await OAUTH_PROVIDER.account_name('unit-test-token')

def test_manual_credential_default():
    assert JobberOAuthCredential.model_validate({'access_token':'unit-test-token'}).credential_type=='jobber_oauth'
    with pytest.raises(ValidationError):JobberOAuthCredential.model_validate({})


def test_custom_field_configuration_scopes_are_separate_from_job_scopes():
    from nodes.scopes.jobber import JOBBER_SCOPES
    assert JOBBER_SCOPES.require('list_custom_field_configurations').scopes == ('read_custom_field_configurations',)
    assert JOBBER_SCOPES.require('create_link_configuration').scopes == ('read_custom_field_configurations', 'write_custom_field_configurations')
    assert 'write_jobs' not in JOBBER_SCOPES.declared_scopes()

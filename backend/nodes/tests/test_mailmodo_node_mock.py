"""Exercise every Mailmodo operation at the real HTTP boundary with published examples.

These tests pin request routing, API-key placement and error/partial-result behavior
without requiring a Mailmodo account or delivering email.
"""
import json
from pathlib import Path
import httpx
import pytest
from nodes import mailmodo_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/mailmodo/operations.json').read_text())
TOKEN = 'synthetic-mailmodo-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='mailmodo-test', node_type='automation-mailmodo', node_data={
        'config': config, 'credentials': {'credential_type':'mailmodo_api_key', 'api_key':TOKEN}})


def transport(monkeypatch, body, status=200):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native,'guarded_async_client',client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_published_contract_requests_and_responses(monkeypatch, operation):
    fixture=FIXTURES[operation]
    requests=transport(monkeypatch,fixture['response'])
    output=await node(fixture['config']).execute({})
    assert output['status']=='success'
    assert len(requests)==1
    request=requests[0]
    assert request.url.host=='api.mailmodo.com' and request.headers['mmApiKey']==TOKEN
    expected=fixture['path']
    for field in ['campaign','journey']:
        expected=expected.replace('{'+field+'-id}',fixture['config'].get(field+'_id',''))
    if not expected.startswith('/hooks/'):
        expected='/api/v1'+expected
    assert request.url.path==expected and request.method==fixture['method']
    config={k:v for k,v in fixture['config'].items() if k not in ['operation','campaign_id','journey_id']}
    if request.method=='GET':
        assert dict(request.url.params)==config and request.content==b''
    else:
        body=json.loads(request.content)
        assert all(body[k]==v for k,v in config.items())
        assert 'operation' not in body and 'campaign_id' not in body and 'journey_id' not in body
        if operation=='start_journey': assert body['allowDuplicateEmail'] is False
        if operation=='update_subscription': assert set(body)=={'email','reSubscribeTo','unsubscribeFrom'}
    assert TOKEN not in str(output)


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[302,401,403,404,429,500])
async def test_errors_keep_provider_message_without_secret_or_retry(monkeypatch,status):
    requests=transport(monkeypatch,{'message':'rejected '+TOKEN},status)
    output=await node({'operation':'list_contact_lists'}).execute({})
    assert output['status']=='error' and output['http_status']==status
    assert output['error']=='rejected [redacted]' and len(requests)==1


@pytest.mark.asyncio
async def test_partial_batch_and_application_failure(monkeypatch):
    body={'message':'Some contacts were not added','errors':[{'email':'invalid','failure reason':'invalid email'}]}
    transport(monkeypatch,body,207)
    output=await node(FIXTURES['bulk_add_contacts']['config']).execute({})
    assert output['status']=='partial' and output['data']['errors']==body['errors']
    transport(monkeypatch,{'success':False,'message':'Invalid API key'})
    output=await node(FIXTURES['send_campaign_email']['config']).execute({})
    assert output['status']=='error' and output['error']=='Invalid API key'


@pytest.mark.asyncio
@pytest.mark.parametrize('body',[{}, {'listDetails':None}, {'listDetails':['invalid']}])
async def test_connection_read_refuses_malformed_success(monkeypatch,body):
    transport(monkeypatch,body)
    with pytest.raises(ValueError,match='unexpected list'):
        await node({'operation':'list_contact_lists'}).execute({})


def test_manual_credential_default_and_connection_evidence():
    credential=native.MailmodoAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type=='mailmodo_api_key'
    assert native.MailmodoNode.connection_evidence.operation=='list_contact_lists'


@pytest.mark.asyncio
async def test_connect_evidence_contains_account_lists(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch,{'listDetails':[{'id':'owned-list','name':'Newsletter subscribers'}]})
    result=await collect_evidence(node_type='automation-mailmodo', user_id='mailmodo-user', credential_data={
        'credential_type':'mailmodo_api_key','api_key':TOKEN})
    assert result.reachable is True
    assert 'Newsletter subscribers' in str(result.samples)


@pytest.mark.asyncio
async def test_reflected_secret_is_removed_from_nested_payload(monkeypatch):
    transport(monkeypatch,{'success':True,'message':'accepted','debug':{'key':TOKEN}})
    output=await node(FIXTURES['send_campaign_email']['config']).execute({})
    assert TOKEN not in str(output) and output['data']['debug']['key']=='[redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,reachable', [(401,False), (403,False), (503,None)])
async def test_connection_rejection_and_transient_failure_differ(monkeypatch,status,reachable):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch,{'message':'Provider request failed'},status)
    result=await collect_evidence(node_type='automation-mailmodo',user_id='mailmodo-user',credential_data={
        'credential_type':'mailmodo_api_key','api_key':TOKEN})
    assert result.reachable is reachable
    if reachable is False:
        assert 'Provider request failed' in result.error

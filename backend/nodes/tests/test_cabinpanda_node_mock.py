"""Offline transport tests; response examples here are synthetic, not provider evidence."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import cabinpanda_node as native
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / 'fixtures/cabinpanda/contract.json').read_text())
TOKEN = 'cabinpanda-test-secret-123456'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def config_for(operation):
    values = {'operation': operation, 'form_key': 'contact-form', 'template_id': 2,
        'type_id': 1, 'name': 'Contact form', 'submission_id': 17,
        'fields': {'name-field': 'Jane'}, 'notify_respondent': False,
        'reply_to': {'email': 'reply@example.com'}, 'subject': 'Thank you', 'message': 'Received'}
    model = next(m for m in native.CabinpandaConfig.__args__[0].__args__
        if m.model_fields['operation'].default == operation)
    return {key: value for key, value in values.items() if key in model.model_fields}

def make_node(config):
    return NodeFactory.create_node(node_id='cabinpanda-test', node_type='automation-cabinpanda',
        node_data={'config': config, 'credentials': {'credential_type': 'cabinpanda_api_token', 'api_token': TOKEN}})

def transport(monkeypatch, status=200, body=None, raw=None, media='application/json'):
    requests=[]
    def respond(request):
        requests.append(request)
        if raw is not None:
            return httpx.Response(status, content=raw, headers={'Content-Type': media})
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.ROUTES)
async def test_cabinpanda_contract_wire(monkeypatch, operation):
    requests=transport(monkeypatch)
    node=make_node(config_for(operation))
    result=await node.execute({})
    assert result['status']=='success' and result['data'] is None
    assert len(requests)==1
    request=requests[0]
    values=node.config.config.model_dump(mode='json', exclude_none=True)
    method,path=native.ROUTES[operation]
    contract_path=path.replace('{form_key}','{key}').replace('{template_id}','{id}').replace('{submission_id}','{id}')
    assert method.lower() in CONTRACT['paths'][contract_path]
    assert request.method==method
    assert str(request.url).split('?')[0]==native.BASE_URL+path.format(**values)
    assert request.headers['Authorization']=='Bearer '+TOKEN
    assert dict(request.url.params)=={k:str(values[k]) for k in native.QUERY_FIELDS.get(operation,()) if k in values}
    fields=native.BODY_FIELDS.get(operation)
    assert (json.loads(request.content) if request.content else None)==({k:values[k] for k in fields if k in values} if fields else None)

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,404,429,500])
async def test_cabinpanda_rejection_no_retry(monkeypatch,status):
    requests=transport(monkeypatch,status,raw=('rejected '+TOKEN).encode())
    result=await make_node({'operation':'list_forms'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in json.dumps(result) and len(requests)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{'success':False,'message':'Denied'},{'errors':{'name':['Required']}}])
async def test_cabinpanda_error_envelope(monkeypatch,payload):
    transport(monkeypatch,body=payload)
    assert (await make_node({'operation':'list_forms'}).execute({}))['status']=='error'

@pytest.mark.asyncio
async def test_cabinpanda_json_preserved_and_secret_redacted(monkeypatch):
    transport(monkeypatch,body={'data':[{'name':'Contact','key':'abc'}],'meta':{'total':1},'echo':TOKEN})
    result=await make_node({'operation':'list_forms'}).execute({})
    assert result['data']['data'][0]['key']=='abc' and result['data']['meta']['total']==1
    assert TOKEN not in json.dumps(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('raw,media',[(b'<html>Login</html>','text/html'),(b'{broken','application/json')])
async def test_cabinpanda_invalid_response(monkeypatch,raw,media):
    transport(monkeypatch,raw=raw,media=media)
    with pytest.raises(ValueError):
        await make_node({'operation':'list_forms'}).execute({})

@pytest.mark.parametrize('key',['../other','x/y','a?b','a#b'])
def test_cabinpanda_path_injection_refused(key):
    with pytest.raises(ValidationError): native.GetForm(form_key=key)

@pytest.mark.parametrize('token',['Bearer '+TOKEN,'https://example.com','<token>','abc\nxyz'])
def test_cabinpanda_token_refused(token):
    with pytest.raises(ValidationError): native.CabinpandaAPITokenCredential(api_token=token)

def test_cabinpanda_manual_connect():
    assert native.CabinpandaAPITokenCredential(api_token=TOKEN).credential_type=='cabinpanda_api_token'
    assert native.CabinpandaNode.connection_evidence.operation=='list_forms'
    assert len(native.ROUTES)==19

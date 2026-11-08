"""Offline request and documented response regressions for Moneybird v2."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import moneybird_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/moneybird/contract.json').read_text())
TOKEN = 'synthetic-moneybird-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='moneybird-test', node_type='automation-moneybird', node_data={
        'config': config, 'credentials': {'credential_type':'moneybird_token', 'api_token':TOKEN}})

def transport(monkeypatch, status, body):
    requests=[]
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_contract_route_body_and_published_response(monkeypatch, operation):
    fixture=FIXTURES[operation]
    requests=transport(monkeypatch, fixture['status'], fixture['response'])
    result=await node(fixture['config']).execute({})
    assert result['status']=='success'
    assert result['data']==fixture['response']
    assert len(requests)==1
    req=requests[0]
    assert req.method==fixture['method'] and req.url.path=='/api/v2'+fixture['path']
    assert req.url.host=='moneybird.com' and req.headers['Authorization']=='Bearer '+TOKEN
    body_field=native.ROUTES[operation][2]
    if body_field:
        assert json.loads(req.content)=={body_field:fixture['config'][body_field]}
    else:
        assert not req.content
    assert TOKEN not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_failures_are_sanitized_and_never_retried(monkeypatch, status):
    requests=transport(monkeypatch,status,{'error':TOKEN})
    result=await node({'operation':'list_administrations'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert TOKEN not in str(result) and len(requests)==1

@pytest.mark.asyncio
async def test_pagination_is_explicit_one_page(monkeypatch):
    requests=transport(monkeypatch,200,[{'id':'1'}, {'id':'2'}])
    result=await node({'operation':'list_contacts','administration_id':'123','page':2,'per_page':2,'query':'A + B'}).execute({})
    assert result['next_page']==3
    assert dict(requests[0].url.params)=={'page':'2','per_page':'2','query':'A + B'}

@pytest.mark.parametrize('config', [
    {'operation':'get_contact','administration_id':'../x','id':'1'},
    {'operation':'list_contacts','administration_id':'1','per_page':101},
    {'operation':'create_contact','administration_id':'1','contact':{}},
    {'operation':'create_sales_invoice','administration_id':'1','sales_invoice':{}},
    {'operation':'create_product','administration_id':'1','product':{'price':'1'}},
])
def test_invalid_inputs(config):
    with pytest.raises((ValidationError,ValueError)):
        native.MoneybirdNode.parse_config({'config':config,'credentials':{'credential_type':'moneybird_token','api_token':TOKEN}})

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'error':'no'}, 'html'])
async def test_connection_requires_an_array(monkeypatch,body):
    transport(monkeypatch,200,body)
    assert (await node({'operation':'list_administrations'}).execute({}))['status']=='error'

def test_documented_comma_decimal_price():
    product=native.NewProduct(price='50,50', ledger_account_id='503052477730391740')
    assert product.price=='50,50'

"""Offline native factory tests; no real token or account is used."""
import httpx
import pytest
from nodes import loyverse_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

TOKEN = 'offline-loyverse-secret'

def node(config):
    return NodeFactory.create_node(node_id='loyverse-test', node_type='automation-loyverse',
        node_data={'config': config, 'credentials': {'credential_type': 'loyverse_token', 'access_token': TOKEN}})

def transport(monkeypatch, body, status=200):
    seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['customers','items','variants','receipts','stores','categories','suppliers','inventory','employees','payment_types','taxes'])
async def test_lists_preserve_records_and_page_cursor(monkeypatch, kind):
    key = 'inventory_levels' if kind == 'inventory' else kind
    seen = transport(monkeypatch, {key: [{'id': 'owned', 'name': 'Account record'}], 'cursor': 'next-page'})
    result = await node({'operation': 'list_' + kind}).execute({})
    assert result['items'][0]['id'] == 'owned' and result['next_cursor'] == 'next-page'
    assert result['has_more'] and len(seen) == 1
    assert seen[0].url.path == '/v1.0/' + kind + ('/' if kind == 'suppliers' else '')
    assert seen[0].headers['Authorization'] == 'Bearer ' + TOKEN

@pytest.mark.asyncio
async def test_customer_search_and_pagination(monkeypatch):
    seen = transport(monkeypatch, {'customers': []})
    result = await node({'operation':'list_customers','email':'customer@example.test','limit':10,'cursor':'opaque-page'}).execute({})
    assert dict(seen[0].url.params) == {'email':'customer@example.test','limit':'10','cursor':'opaque-page'}
    assert result['has_more'] is False

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['customer','item','variant','receipt','store','category','supplier'])
async def test_details_use_the_selected_identifier(monkeypatch, kind):
    seen = transport(monkeypatch, {'id': '42dc2cec-6f40-11ea-bde9-1269e7c5a22d'})
    field = 'receipt_number' if kind == 'receipt' else kind + '_id'
    result = await node({'operation':'get_'+kind,field:'42dc2cec-6f40-11ea-bde9-1269e7c5a22d'}).execute({})
    resource = {'category':'categories'}.get(kind, kind+'s')
    assert seen[0].url.path == '/v1.0/'+resource+'/42dc2cec-6f40-11ea-bde9-1269e7c5a22d'
    assert result['data']['id'] == '42dc2cec-6f40-11ea-bde9-1269e7c5a22d'

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['customer','category','supplier'])
@pytest.mark.parametrize('updating', [False,True])
async def test_save_create_and_update_share_documented_post(monkeypatch, kind, updating):
    import json
    seen = transport(monkeypatch, {'id':'saved-id','name':'Saved'})
    config = {'operation':'save_'+kind,'name':'Saved'}
    if updating: config['id'] = 'saved-id'
    result = await node(config).execute({})
    assert seen[0].method == 'POST'
    assert json.loads(seen[0].content) == {k:v for k,v in config.items() if k!='operation'}
    assert result['data']['id'] == 'saved-id' and len(seen)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,429,500])
async def test_errors_do_not_claim_success_or_leak_tokens(monkeypatch,status):
    transport(monkeypatch, {'error':TOKEN},status)
    result = await node({'operation':'save_customer','name':'Saved'}).execute({})
    assert result['status']=='error' and result['http_status']==status
    assert result['write_outcome']=='unverified' and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_malformed_list_and_secret_redaction(monkeypatch):
    transport(monkeypatch, {'customers': 'invalid'})
    with pytest.raises(ValueError,match='unexpected response'):
        await node({'operation':'list_customers'}).execute({})
    transport(monkeypatch, {'customers': [{'name':TOKEN}]})
    result=await node({'operation':'list_customers'}).execute({})
    assert TOKEN not in str(result)

@pytest.mark.parametrize('config', [
    {'operation':'get_customer','customer_id':'../other'},
    {'operation':'list_customers','limit':251},
    {'operation':'save_category','name':'Saved','color':'invalid'},
    {'operation':'save_supplier','name':'x'*65},
    {'operation':'save_customer','name':'Saved','first_visit':'2020-01-01'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises(ValueError): node(config)

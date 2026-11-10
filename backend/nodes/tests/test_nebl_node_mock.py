"""Wire tests for Neblio's public mainnet API; no wallet keys or live writes."""
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.nebl_node import NeblioNode

CASES = [
    ({'operation': 'get_token_id', 'tokensymbol': 'NIBBL'}, 'GET', '/ntp1/tokenid/NIBBL', {}, None),
    ({'operation': 'get_address_info', 'address': 'NAddress'}, 'GET', '/ntp1/addressinfo/NAddress', {}, None),
    ({'operation': 'get_transaction_info', 'txid': 'a'*64}, 'GET', '/ntp1/transactioninfo/'+'a'*64, {}, None),
    ({'operation': 'get_token_metadata', 'tokenid': 'Token', 'verbosity': 1}, 'GET', '/ntp1/tokenmetadata/Token', {'verbosity': 1}, None),
    ({'operation': 'get_token_metadata_of_utxo', 'tokenid': 'Token', 'utxo': 'a:0'}, 'GET', '/ntp1/tokenmetadata/Token/a%3A0', {}, None),
    ({'operation': 'get_token_holders', 'tokenid': 'Token'}, 'GET', '/ntp1/stakeholders/Token', {}, None),
    ({'operation': 'get_block', 'blockhash': 'b'*64}, 'GET', '/ins/block/'+'b'*64, {}, None),
    ({'operation': 'get_block_index', 'blockindex': 123}, 'GET', '/ins/block-index/123', {}, None),
    ({'operation': 'get_tx', 'txid': 'a'*64}, 'GET', '/ins/tx/'+'a'*64, {}, None),
    ({'operation': 'get_raw_tx', 'txid': 'a'*64}, 'GET', '/ins/rawtx/'+'a'*64, {}, None),
    *[({'operation': op, 'address': 'NAddress'}, 'GET', '/ins/addr/NAddress'+suffix, {}, None) for op,suffix in [
        ('get_address', ''), ('get_address_balance', '/balance'), ('get_address_unconfirmed_balance','/unconfirmedBalance'),
        ('get_address_total_received','/totalReceived'), ('get_address_utxos','/utxo'), ('get_address_total_sent','/totalSent')]],
    ({'operation': 'get_txs', 'address': 'NAddress', 'pageNum': 2}, 'GET', '/ins/txs', {'address': 'NAddress', 'pageNum': 2}, None),
    ({'operation': 'get_sync'}, 'GET', '/ins/sync', {}, None),
    ({'operation': 'get_status', 'q': 'getBestBlockHash'}, 'GET', '/ins/status', {'q': 'getBestBlockHash'}, None),
    ({'operation': 'broadcast_tx', 'body': {'txHex': '01000000'}}, 'POST', '/ntp1/broadcast', {}, {'txHex': '01000000'}),
    ({'operation': 'send_tx', 'body': {'rawtx': '01000000'}}, 'POST', '/ins/tx/send', {}, {'rawtx': '01000000'}),
    ({'operation': 'send_token', 'body': {'fee': 10000, 'from': ['NFrom'], 'to': [{'address':'NTo','amount':1,'tokenId':'Token'}], 'flags': {'splitChange': True}}}, 'POST', '/ntp1/sendtoken', {}, {'fee':10000, 'from':['NFrom'], 'to':[{'address':'NTo','amount':1,'tokenId':'Token'}], 'flags': {'splitChange':True}}),
    ({'operation': 'burn_token', 'body': {'fee': 10000, 'from':['NFrom'], 'burn':[{'amount':1,'tokenId':'Token'}]}}, 'POST', '/ntp1/burntoken', {}, {'fee':10000, 'from':['NFrom'], 'burn':[{'amount':1,'tokenId':'Token'}]}),
    ({'operation': 'issue_token', 'body': {'issueAddress':'NFrom','amount':10,'divisibility':0,'fee':1000000000,'reissuable':False,'transfer':[{'address':'NTo','amount':10}], 'metadata': {'tokenName':'NIBBL'}}}, 'POST', '/ntp1/issue', {}, {'issueAddress':'NFrom','amount':10,'divisibility':0,'fee':1000000000,'reissuable':False,'transfer':[{'address':'NTo','amount':10}], 'metadata': {'tokenName':'NIBBL'}}),
]


def node(config):
    return NodeFactory.create_node(node_id='nebl-test', node_type='automation-nebl', node_data={'config':config, 'credentials':{}})


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,params,body', CASES)
async def test_wire_contract(monkeypatch, config, method, path, params, body):
    calls=[]
    async def request(self, actual_method, url, **kwargs):
        calls.append(url)
        assert actual_method == method
        assert url == 'https://ntp1node.nebl.io'+path
        assert kwargs['params'] == params
        assert kwargs.get('json') == body
        assert kwargs['headers'] == {'Accept':'application/json'}
        return httpx.Response(200, json=0 if config['operation'] in {'get_address_balance','get_address_unconfirmed_balance','get_address_total_received','get_address_total_sent'} else [] if config['operation']=='get_address_utxos' else {'txid':'recorded-result'})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    result=await node(config).execute({})
    assert result['status'] == 'success'
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('get_address_balance',0), ('get_address_balance',123456789), ('get_address_utxos',[]), ('get_address_utxos',[{'txid':'abc','vout':0}]), ('get_txs',{'pagesTotal':1,'txs':[]}), ('get_sync',{'status':'finished'})])
async def test_response_preservation(monkeypatch, operation, body):
    async def request(*args, **kwargs): return httpx.Response(200, json=body)
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    assert (await node({'operation':operation, **({'address':'NAddress'} if operation.startswith('get_address') else {})}).execute({}))['data']==body


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302,400,401,404,429,500])
async def test_failure_is_not_retried(monkeypatch, status):
    calls=[]
    async def request(*args, **kwargs):
        calls.append(1)
        return httpx.Response(status,json={'error':'rejected'})
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    result=await node({'operation':'broadcast_tx','body':{'txHex':'01000000'}}).execute({})
    assert result['status']=='error'
    assert result['http_status']==status
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, True, {'errors':['failed']}])
async def test_error_envelopes(monkeypatch, body):
    async def request(*args, **kwargs):return httpx.Response(200,json=body)
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    with pytest.raises(ValueError):await node({'operation':'get_sync'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation':'get_address','address':'..'},
    {'operation':'get_tx','txid':'a\nheader'},
    {'operation':'send_token','body':{'to':[]}},
    {'operation':'issue_token','body':{'amount':10}},
    {'operation':'broadcast_tx','body':{'private_key':'never'}},
    {'operation':'get_txs','pageNum':-1},
    {'operation':'get_status','q':'stop'},
])
def test_invalid_configs(config):
    assert not NeblioNode.validate_config({'config':config})['valid']


def test_public_reachability():
    assert node({'operation':'get_sync'}).config.credentials is None
    assert NeblioNode.connection_evidence.operation=='get_sync'
    assert NeblioNode.connection_evidence.proves=='reachability'


@pytest.mark.asyncio
async def test_sync_preserves_documented_recent_error(monkeypatch):
    body={'status':'finished','blockChainHeight':123,'height':123,'syncPercentage':100,'error':'','type':'neblio'}
    async def request(*args, **kwargs):return httpx.Response(200,json=body)
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    assert (await node({'operation':'get_sync'}).execute({}))['data']==body


@pytest.mark.asyncio
async def test_non_sync_error_rejected(monkeypatch):
    async def request(*args, **kwargs):return httpx.Response(200,json={'error':'failed'})
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    with pytest.raises(ValueError):await node({'operation':'get_status'}).execute({})

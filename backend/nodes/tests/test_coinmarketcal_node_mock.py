"""Published v2 examples replayed through the native factory and HTTP transport."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import coinmarketcal_node as module
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/coinmarketcal/responses.json').read_text())
TOKEN = 'fixture-coinmarketcal-key'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, content=payload.encode(), headers={'content-type': 'text/csv'}) if isinstance(payload, str) else httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(module, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, **config):
    return NodeFactory.create_node(node_id='coinmarketcal-test', node_type='automation-coinmarketcal', node_data={
        'config': {'operation': operation, **config}, 'credentials': {'credential_type': 'coinmarketcal_api_key', 'api_key': TOKEN}})


CONFIGS = {'get_event': {'event_id': '48291'}, 'get_coin': {'slug': 'bitcoin'},
           'export_events_csv': {'from_date': '2026-01-01T00:00:00Z', 'to_date': '2026-02-01T00:00:00Z'}}


@pytest.mark.parametrize('operation', list(module.ROUTES))
async def test_documented_operations(transport, operation):
    requests, replies = transport
    payload = EXAMPLES[operation]
    replies.append((200, payload))
    output = await node(operation, **CONFIGS.get(operation, {})).execute({})
    assert output['status'] == 'success'
    assert len(requests) == 1
    req = requests[0]
    assert req.method == 'GET'
    assert req.url.host == 'api.coinmarketcal.com'
    assert req.url.path == module.ROUTES[operation].replace('{id}', '48291').replace('{slug}', 'bitcoin')
    assert req.headers['x-api-key'] == TOKEN
    assert not req.content and TOKEN not in str(req.url)
    if operation == 'export_events_csv':
        assert isinstance(output['file'], BinaryOutput)
        assert output['file'].data == payload.encode()
        assert req.url.params['from'] == CONFIGS[operation]['from_date']
        assert req.url.params['to'] == CONFIGS[operation]['to_date']
    else:
        assert output['data'] == payload


async def test_filters_and_cursor_roundtrip(transport):
    requests, replies = transport
    replies.extend([(200, EXAMPLES['list_events']), (200, EXAMPLES['list_coins'])])
    await node('list_events', coins='bitcoin,ethereum', categories='release', from_date='2026-01-01T00:00:00Z',
               to_date='2026-02-01T00:00:00Z', impact_min=7.5, sort_by='impact_desc', cursor='opaque+/=', keyword='upgrade', limit=100).execute({})
    assert dict(requests[0].url.params) == {'coins':'bitcoin,ethereum','categories':'release','from':'2026-01-01T00:00:00Z',
        'to':'2026-02-01T00:00:00Z','impactMin':'7.5','sortBy':'impact_desc','cursor':'opaque+/=','keyword':'upgrade','limit':'100'}
    await node('list_coins', tracked=False, q='bitcoin', limit=200).execute({})
    assert dict(requests[1].url.params) == {'tracked':'false','q':'bitcoin','limit':'200'}


@pytest.mark.parametrize('status', [400, 401, 403, 404, 410, 429, 500, 503])
async def test_provider_errors_are_not_success(transport, status):
    requests, replies = transport
    replies.append((status, {'error': 'Provider says no'}))
    result = await node('get_usage').execute({})
    assert result == {'status':'error', 'http_status':status, 'error':'Provider says no'}
    assert len(requests) == 1


@pytest.mark.parametrize('operation,config', [('get_event', {'event_id':'../usage'}), ('get_coin', {'slug':'bitcoin/../../usage'}),
    ('list_events', {'limit':101}), ('list_coins', {'limit':201}),
    ('export_events_csv', {'from_date':'2026-02-01T00:00:00Z','to_date':'2026-01-01T00:00:00Z'}),
    ('list_events', {'from_date':'2026-01-01'}), ('list_event_cancellations', {'since':'2026-99-99'})])
def test_invalid_inputs(operation, config):
    with pytest.raises(ValueError): node(operation, **config)


async def test_unlimited_usage_and_tier_fields(transport):
    _, replies = transport
    usage = {**EXAMPLES['get_usage'], 'tier':'enterprise', 'remaining':None, 'monthlyQuota':None}
    replies.append((200, usage))
    assert (await node('get_usage').execute({}))['data'] == usage
    event = {**EXAMPLES['get_event'], 'impact':None, 'description':None, 'dateEnd':'', 'isEstimated':True, 'displayedDate':'Q2 2026'}
    replies.append((200, event))
    assert (await node('get_event', event_id='48291').execute({}))['data'] == event


@pytest.mark.parametrize('operation,payload', [('get_usage', {}), ('list_events', {'data':[]}),
    ('get_coin', {'slug':'ethereum'}), ('get_event', {'id':'wrong'}), ('get_events_snapshot', {})])
async def test_malformed_responses(transport, operation, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError): await node(operation, **CONFIGS.get(operation, {})).execute({})


async def test_connection_evidence_uses_account_usage(transport, monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    _, replies = transport
    replies.append((200, EXAMPLES['get_usage']))
    async def run(**kwargs):
        assert kwargs['operation'] == 'get_usage'
        return await node('get_usage').execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run)
    evidence = await collect_evidence(node_type='automation-coinmarketcal', credential_data={
        'credential_type':'coinmarketcal_api_key', 'api_key':TOKEN}, user_id='fixture-user', pool=None)
    assert evidence.reachable is True
    assert evidence.samples[0].label == 'pro: 12450 requests in 2026-07'

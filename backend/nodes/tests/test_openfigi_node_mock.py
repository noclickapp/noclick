"""Provider-documented response and wire-contract tests, without a live key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import openfigi_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/openfigi/documented.json').read_text())['responses']
TOKEN = 'openfigi-test-key-12345'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='openfigi-test', node_type='automation-openfigi', node_data={
        'config': config, 'credentials': {'credential_type': 'openfigi_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, payload, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,key', native.VALUE_KEYS.items())
async def test_reference_lookup_fixed_paths_and_header(monkeypatch, operation, key):
    requests = transport(monkeypatch, EXAMPLES['values'])
    assert await node({'operation': operation}).execute({}) == EXAMPLES['values']
    assert len(requests) == 1 and requests[0].method == 'GET'
    assert str(requests[0].url) == native.BASE + '/mapping/values/' + key
    assert requests[0].headers['X-OPENFIGI-APIKEY'] == TOKEN
    assert not requests[0].content

@pytest.mark.asyncio
async def test_mapping_documented_batch_preserves_warnings_errors_order(monkeypatch):
    jobs = [{'idType': 'ID_BB_GLOBAL', 'idValue': 'BBG000BLNNH6'}, {'idType': 'TICKER', 'idValue': 'IBM', 'exchCode': 'US'}]
    payload = EXAMPLES['mapping'] + [{'warning': 'No identifier found.'}]
    requests = transport(monkeypatch, payload)
    result = await node({'operation': 'map_identifiers', 'jobs': jobs}).execute({})
    assert result == {'results': payload}
    assert requests[0].method == 'POST' and requests[0].url.path == '/v3/mapping'
    assert json.loads(requests[0].content) == jobs
    payload[1] = {'error': 'Single job result exceeds 15,000 FIGIs.'}
    assert (await node({'operation': 'map_identifiers', 'jobs': jobs}).execute({}))['results'][1] == payload[1]

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,kind,config', [
    ('search_instruments', 'search', {'query': 'ibm', 'exchCode': 'US'}),
    ('filter_instruments', 'filter', {'exchCode': 'US'}),
])
async def test_documented_objects_and_opaque_continuation(monkeypatch, operation, kind, config):
    payload = EXAMPLES[kind]
    requests = transport(monkeypatch, payload)
    assert await node({'operation': operation, **config}).execute({}) == payload
    assert json.loads(requests[0].content) == config
    assert requests[0].url.path == '/v3/' + kind
    assert await node({'operation': operation, **config, 'start': payload['next']}).execute({}) == payload
    assert json.loads(requests[1].content) == {**config, 'start': payload['next']}
    assert len(requests) == 2

@pytest.mark.asyncio
async def test_filters_keep_false_and_serialize_date_intervals(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['mapping'])
    job = {'idType':'BASE_TICKER','idValue':'TSLA 10 C100','securityType2':'Option',
           'expiration':['2018-10-01','2018-12-01'], 'includeUnlistedEquities':False, 'strike':[0,None]}
    await node({'operation':'map_identifiers','jobs':[job]}).execute({})
    assert json.loads(requests[0].content) == [job]

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_failure_is_not_success_and_key_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'error': TOKEN}, status)
    with pytest.raises(ValueError, match=f'HTTP {status}') as error:
        await node({'operation':'list_identifier_types'}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, [], {'error':'Invalid API key.'}, {'values':None}])
async def test_invalid_response_and_provider_error_do_not_prove_connection(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({'operation':'list_identifier_types'}).execute({})

@pytest.mark.parametrize('config', [
    {'operation':'filter_instruments'},
    {'operation':'map_identifiers','jobs':[]},
    {'operation':'map_identifiers','jobs':[{'idType':'MADE_UP','idValue':'IBM'}]},
    {'operation':'map_identifiers','jobs':[{'idType':'BASE_TICKER','idValue':'IBM'}]},
    {'operation':'map_identifiers','jobs':[{'idType':'TICKER','idValue':'IBM','securityType2':'Option'}]},
    {'operation':'filter_instruments','strike':[None,None]},
    {'operation':'filter_instruments','strike':[5,1]},
    {'operation':'filter_instruments','exchCode':'US','micCode':'XNYS'},
    {'operation':'filter_instruments','expiration':['2020-01-01','2022-01-01']},
])
def test_invalid_configuration(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)

def test_manual_credential_default_and_secret_shape():
    assert native.OpenFIGIAPIKeyCredential(api_key=TOKEN).credential_type == 'openfigi_api_key'
    for value in ['https://www.openfigi.com/api', 'key\nheader', '<token>']:
        with pytest.raises((ValueError, ValidationError)):
            native.OpenFIGIAPIKeyCredential(api_key=value)

"""Offline execution against published examples (closing delimiters restored after documentation ellipses) published in the provider's v4 guide."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import the_odds_api_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/the_odds_api/documented_reads.json').read_text())
KEY = 'synthetic-odds-key-12345'


def node(config, credential=None):
    return NodeFactory.create_node(node_id='odds-fixture', node_type='automation-the-odds-api',
        node_data={'config': config, 'credentials': credential or {'credential_type': 'the_odds_api_key', 'api_key': KEY}})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs == {'timeout': 30.0, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_reads_preserve_payload_and_exact_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture['body'], headers={'x-requests-used': '4', 'x-requests-remaining': '496', 'x-requests-last': '1'})
    result = await node(fixture['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == fixture['body']
    assert result['usage'] == {'used': '4', 'remaining': '496', 'last': '1'}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == 'GET' and req.url.host == 'api.the-odds-api.com'
    assert req.url.path == fixture['path']
    expected = {'apiKey': KEY, **fixture['query']}
    if operation not in {'list_sports', 'list_participants'}:
        expected.setdefault('dateFormat', 'iso')
    if 'odds' in operation:
        expected.setdefault('oddsFormat', 'decimal')
        expected.setdefault('markets', 'h2h')
    assert dict(req.url.params) == expected
    assert 'authorization' not in req.headers
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_all_filters_wire_names_false_booleans_and_empty_lists(monkeypatch):
    config = {'operation': 'get_odds', 'sport': 'americanfootball_nfl', 'regions': 'us,uk',
        'markets': 'h2h,spreads', 'date_format': 'unix', 'odds_format': 'american',
        'event_ids': 'event-a,event-b', 'bookmakers': 'draftkings,fanduel',
        'commence_time_from': '2023-09-09T00:00:00Z', 'commence_time_to': '2023-09-10T00:00:00Z',
        'include_links': False, 'include_sids': True, 'include_bet_limits': False, 'include_rotation_numbers': True}
    requests = transport(monkeypatch, [])
    result = await node(config).run({})
    assert result['status'] == 'success' and result['data'] == []
    assert dict(requests[0].url.params) == {'apiKey': KEY, 'regions': 'us,uk', 'markets': 'h2h,spreads',
        'dateFormat': 'unix', 'oddsFormat': 'american', 'eventIds': 'event-a,event-b',
        'bookmakers': 'draftkings,fanduel', 'commenceTimeFrom': '2023-09-09T00:00:00Z',
        'commenceTimeTo': '2023-09-10T00:00:00Z', 'includeLinks': 'false', 'includeSids': 'true',
        'includeBetLimits': 'false', 'includeRotationNumbers': 'true'}


@pytest.mark.asyncio
async def test_include_multipliers_and_all_sports(monkeypatch):
    fixture = FIXTURES['get_event_odds']
    requests = transport(monkeypatch, fixture['body'])
    assert (await node({**fixture['config'], 'include_multipliers': True}).execute({}))['status'] == 'success'
    assert requests[0].url.params['includeMultipliers'] == 'true'
    requests = transport(monkeypatch, [])
    assert (await node({'operation': 'list_sports', 'all': False}).execute({}))['status'] == 'success'
    assert dict(requests[0].url.params) == {'all': 'false', 'apiKey': KEY}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_do_not_follow_redirects_or_leak_key(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Invalid key ' + KEY}, status,
        headers={'Location': 'https://other.example/test'})
    result = await node({'operation': 'list_sports'}).run({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Invalid key [redacted]'
    assert KEY not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, {}, {'message': 'bad'}, ['bad'], {'data': []}])
async def test_malformed_list_response_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'list_sports'}).run({})
    assert result['status'] == 'error' and 'data' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('get_event_odds', []), ('get_event_markets', {}),
    ('get_historical_odds', []), ('get_historical_odds', {'timestamp': '2021-10-18T11:55:00Z'}),
    ('get_historical_event_odds', {'timestamp': '2021-10-18T11:55:00Z', 'data': []})])
async def test_wrong_event_or_historical_envelope_fails(monkeypatch, operation, body):
    transport(monkeypatch, body)
    assert (await node(FIXTURES[operation]['config']).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'get_odds', 'sport': '../sports'},
    {'operation': 'get_event_odds', 'sport': 'basketball_nba', 'event_id': 'one/two'},
    {'operation': 'get_scores', 'sport': 'basketball_nba', 'days_from': 4},
    {'operation': 'get_historical_odds', 'sport': 'basketball_nba'},
    {'operation': 'get_historical_odds', 'sport': 'basketball_nba', 'date': 'yesterday'},
    {'operation': 'list_events', 'sport': 'basketball_nba', 'commence_time_from': '2023-09-10T00:00:00Z', 'commence_time_to': '2023-09-09T00:00:00Z'},
    {'operation': 'list_participants', 'sport': 'basketball_nba', 'regions': 'us'},
])
def test_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_connect_default_and_schema():
    credential = native.TheOddsAPIKeyCredential(api_key='  '+KEY+'  ')
    assert credential.credential_type == 'the_odds_api_key' and credential.api_key == KEY
    assert KEY not in repr(credential) and 'api_key=' not in repr(credential)
    evidence = native.TheOddsAPINode.connection_evidence
    assert evidence.operation == 'list_sports' and evidence.proves == 'reachability'
    assert len(native.ROUTES) == 11
    assert native.TheOddsAPIConfig.model_json_schema()['$defs']['GetHistoricalOddsConfig']['x-tier-label'] == 'Paid plan'

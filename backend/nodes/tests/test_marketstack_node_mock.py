"""Provider request contracts and documented Marketstack response shapes; no live key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import marketstack_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-marketstack-secret-42'
ROUTES = json.loads((Path(__file__).parent / 'fixtures/marketstack/operations.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='marketstack-test', node_type='automation-marketstack',
        node_data={'config': config, 'credentials': {'credential_type': 'marketstack_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'location': 'https://example.test'})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    route = ROUTES[operation]
    config = {'operation': operation}
    for field, value in {'mic': 'XNAS', 'symbol': 'AAPL', 'date': '2024-09-27'}.items():
        if '{'+field+'}' in route:
            config[field] = value
    if operation in {'list_eod', 'get_latest_eod', 'get_eod_on_date', 'list_intraday', 'get_latest_intraday', 'get_intraday_on_date', 'list_splits', 'list_dividends'}:
        config['symbols'] = 'AAPL,MSFT'
    if operation in {'get_ticker_info', 'get_stock_price'}:
        config['ticker'] = 'AAPL'
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ROUTES)
async def test_one_operation_one_get_exact_path_and_query_key(monkeypatch, operation):
    requests = transport(monkeypatch, {'data': [{'symbol': 'AAPL'}]})
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'success' and result['data'] == [{'symbol': 'AAPL'}]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == 'GET' and req.url.host == 'api.marketstack.com'
    expected = ROUTES[operation].replace('{symbol}', 'AAPL').replace('{mic}', 'XNAS').replace('{date}', '2024-09-27')
    assert req.url.path == expected and req.url.params['access_key'] == TOKEN
    assert 'authorization' not in req.headers and 'operation' not in req.url.params
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_filters_boolean_dates_and_pagination_are_preserved(monkeypatch):
    body = {'data': [{'symbol': 'AAPL', 'close': 100.25}], 'pagination': {'offset': 20, 'limit': 20, 'count': 20, 'total': 43}}
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'list_intraday', 'symbols': 'AAPL', 'after_hours': False,
        'interval': '5min', 'date_from': '2024-09-26', 'date_to': '2024-09-27', 'limit': 20, 'offset': 20}).execute({})
    assert result['has_more'] and result['next_offset'] == 40
    assert requests[0].url.params['after_hours'] == 'false'
    assert requests[0].url.params['date_from'] == '2024-09-26'
    body['pagination'].update(offset=40, count=3)
    assert (await node({'operation': 'list_intraday', 'symbols': 'AAPL'}).execute({}))['next_offset'] is None


@pytest.mark.asyncio
async def test_direct_ticker_object_empty_dataset_and_redaction(monkeypatch):
    transport(monkeypatch, {'name': 'Apple', 'symbol': 'AAPL', 'api_key': TOKEN})
    result = await node({'operation': 'get_ticker', 'symbol': 'AAPL'}).execute({})
    assert result['data']['symbol'] == 'AAPL' and TOKEN not in str(result)
    transport(monkeypatch, {'data': []})
    assert (await node({'operation': 'list_exchanges'}).execute({}))['data'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_http_failures_no_redirects_and_provider_message_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'error': {'info': 'Rejected '+TOKEN}}, status)
    result = await node({'operation': 'list_exchanges'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'success': False, 'error': {'info': TOKEN}}, {'data': [], 'pagination': {'offset': 0, 'count': 0, 'total': 3}}])
async def test_unconfirmed_or_stalled_response_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'list_exchanges'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)


@pytest.mark.parametrize('config', [
    {'operation': 'list_eod'}, {'operation': 'get_ticker', 'symbol': '../AAPL'},
    {'operation': 'list_exchanges', 'limit': 1001}, {'operation': 'list_exchanges', 'offset': -1},
    {'operation': 'get_eod_on_date', 'symbols': 'AAPL', 'date': '2024-02-30'},
    {'operation': 'list_eod', 'symbols': 'AAPL', 'date_from': '2024-10-01', 'date_to': '2024-09-01'},
    {'operation': 'create_stock'}, {'operation': 'list_exchanges', 'base_url': 'https://example.test'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_credential_default_and_reachability_declaration():
    key = native.MarketstackAPIKeyCredential(api_key=TOKEN)
    assert key.credential_type == 'marketstack_api_key'
    assert native.MarketstackNode.connection_evidence.proves == 'reachability'
    assert len(ROUTES) == 25

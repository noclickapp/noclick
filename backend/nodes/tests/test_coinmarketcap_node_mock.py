"""Wire contract, credential boundaries, and failure handling."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import coinmarketcap_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'cmc-fixture-secret'
ROUTES = json.loads((Path(__file__).parent / 'fixtures/coinmarketcap/routes.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(operation, config=None):
    return NodeFactory.create_node(node_id='cmc-test', node_type='automation-coinmarketcap', node_data={
        'config': {'operation': operation, **(config or {})},
        'credentials': {'credential_type': 'coinmarketcap_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, body=None, status=200, failure=None):
    requests = []
    def reply(request):
        requests.append(request)
        if failure:
            raise failure('request failed', request=request)
        return httpx.Response(status, json=body)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs == {'timeout': 30.0, 'follow_redirects': False, 'trust_env': False}
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests

def success(data):
    return {'status': {'error_code': 0, 'error_message': None, 'credit_count': 1}, 'data': data}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ROUTES)
async def test_one_get_per_operation_exact_route_and_parameters(monkeypatch, operation):
    fixture = ROUTES[operation]
    data = {'plan': {'credit_limit_monthly': 10000}, 'usage': {'current_month': {'credits_used': 1}}} if operation == 'get_key_info' else [{'id': 1, 'name': 'Bitcoin'}]
    requests = transport(monkeypatch, success(data))
    instance = node(operation, fixture['config'])
    result = await instance.execute({})
    assert result['status'] == 'success' and result['data'] == data
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET' and request.url.host == 'pro-api.coinmarketcap.com'
    assert request.url.path == fixture['path']
    expected = instance.config.config.model_dump(exclude={'operation'}, exclude_none=True)
    assert dict(request.url.params) == {k: str(v) for k, v in expected.items()}
    assert request.headers['X-CMC_PRO_API_KEY'] == TOKEN
    assert TOKEN not in str(request.url) and request.content == b''
    assert TOKEN not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 429, 500])
async def test_provider_rejection_and_redirect_are_errors(monkeypatch, status):
    requests = transport(monkeypatch, {'status': {'error_message': 'Rejected ' + TOKEN}}, status)
    result = await node('get_key_info').execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'data': []}, {'status': {}, 'data': []}, {'status': {'error_code': 0}}, success(None), success({})])
async def test_unconfirmed_or_malformed_key_response_cannot_verify(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node('get_key_info').execute({}))['status'] == 'error'

@pytest.mark.asyncio
async def test_error_envelope(monkeypatch):
    transport(monkeypatch, {'status': {'error_code': 1001, 'error_message': 'Invalid ' + TOKEN}})
    result = await node('get_fear_and_greed').execute({})
    assert result['status'] == 'error' and result['error_code'] == 1001 and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_timeout_does_not_leak_key(monkeypatch):
    transport(monkeypatch, failure=httpx.ReadTimeout)
    result = await node('get_key_info').execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_explicit_history_inputs(monkeypatch):
    requests = transport(monkeypatch, success([]))
    await node('get_historical_ohlcv', {'id': '1,1027', 'convert': 'USD,EUR', 'time_start': '2024-01-01', 'time_end': '2024-02-01', 'count': 30}).execute({})
    assert dict(requests[0].url.params) == {'id': '1,1027', 'convert': 'USD,EUR', 'time_start': '2024-01-01', 'time_end': '2024-02-01', 'time_period': 'daily', 'count': '30'}

@pytest.mark.parametrize('config', [
    {'operation': 'get_latest_quotes'},
    {'operation': 'get_latest_quotes', 'id': '../bad'},
    {'operation': 'list_cryptocurrencies', 'start': 0},
    {'operation': 'get_fear_and_greed_history', 'limit': 501},
    {'operation': 'convert_price', 'id': '1,2', 'amount': 1},
    {'operation': 'convert_price', 'id': '1', 'amount': -1},
    {'operation': 'get_historical_ohlcv', 'id': '1'},
    {'operation': 'get_key_info', 'base_url': 'https://evil.test'},
])
def test_invalid_inputs_rejected_before_request(config):
    with pytest.raises(ValueError):
        native.CoinMarketCapNode.parse_config({'config': config})

def test_hand_connect_defaults_secret_and_readonly_contract():
    credential = native.CoinMarketCapAPIKey(api_key=TOKEN)
    assert credential.credential_type == 'coinmarketcap_api_key'
    assert TOKEN not in repr(credential) and len(native.ROUTES) == 16
    assert native.CoinMarketCapNode.connection_evidence.operation == 'get_key_info'
    for bad in ['https://example.com/key', 'abc\nInjected: header', '']:
        with pytest.raises(ValidationError):
            native.CoinMarketCapAPIKey(api_key=bad)

DOCUMENTED = json.loads((Path(__file__).parent / 'fixtures/coinmarketcap/responses.json').read_text())

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', [op for op, spec in ROUTES.items() if 'GET ' + spec['path'] in DOCUMENTED])
async def test_parses_provider_published_success_examples(monkeypatch, operation):
    documented = DOCUMENTED['GET ' + ROUTES[operation]['path']]
    transport(monkeypatch, documented['body'])
    result = await node(operation, ROUTES[operation]['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == documented['body']['data']

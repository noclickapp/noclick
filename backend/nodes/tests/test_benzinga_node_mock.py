"""Exercise Benzinga operations through the native factory and HTTP seam."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import benzinga_node as native
from nodes.core.registry import NodeFactory

CONFIGS = json.loads((Path(__file__).parent / 'fixtures/benzinga/operations.json').read_text())
TOKEN = 'synthetic-benzinga-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='benzinga-test', node_type='automation-benzinga',
        node_data={'config': config, 'credentials': {'credential_type': 'benzinga_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json={} if body is None else body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CONFIGS)
async def test_operations_send_exact_route_auth_and_input_filters(monkeypatch, operation):
    cfg = CONFIGS[operation]
    expected = {'news': [{'id': 123, 'title': 'Market update'}]}
    requests = transport(monkeypatch, body=expected)
    result = await node(cfg).execute({})
    request = requests[0]
    assert request.method == 'GET'
    assert request.url.host == 'api.benzinga.com'
    assert request.url.path == native.ROUTES[operation].replace('{nodeID}', '123')
    assert request.url.params['token'] == TOKEN
    assert request.headers['accept'] == 'application/json'
    assert result['data'] == expected
    if 'symbols' in cfg:
        assert request.url.params['symbols'] == 'AAPL'
    if 'from_date' in cfg:
        assert request.url.params['from'] == cfg['from_date']
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_failures_never_echo_secret_url(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={'error': TOKEN})
    result = await node({'operation': 'list_news'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_optional_filters_preserve_provider_spelling(monkeypatch):
    requests = transport(monkeypatch, body=[])
    await node({'operation': 'list_earnings', 'parameters_tickers': 'AAPL,MSFT', 'page': 2, 'pagesize': 30}).execute({})
    assert dict(requests[0].url.params) == {'parameters[tickers]': 'AAPL,MSFT', 'page': '2', 'pagesize': '30', 'token': TOKEN}


@pytest.mark.asyncio
async def test_error_envelope_and_invalid_json_shape(monkeypatch):
    transport(monkeypatch, body={'error': TOKEN})
    assert (await node({'operation': 'list_news'}).execute({}))['status'] == 'error'
    transport(monkeypatch, body='bad data')
    with pytest.raises(ValueError, match='could not be completed'):
        await node({'operation': 'list_news'}).execute({})


@pytest.mark.asyncio
async def test_delayed_quotes_accepts_contract_string_or_object(monkeypatch):
    for body in ('contract string response', {'quotes': []}):
        transport(monkeypatch, body=body)
        result = await node({'operation': 'get_delayed_quotes', 'symbols': 'AAPL'}).execute({})
        assert result['status'] == 'success' and result['data'] == body

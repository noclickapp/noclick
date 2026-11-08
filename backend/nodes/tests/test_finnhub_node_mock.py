"""Offline wire and failure regressions for Finnhub API v1."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import finnhub_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-finnhub-secret'
CASES = json.loads((Path(__file__).parent / 'fixtures/finnhub/operations.json').read_text())


def node(config):
    return NodeFactory.create_node(node_id='finnhub-test', node_type='automation-finnhub',
        node_data={'config': config, 'credentials': {'credential_type': 'finnhub_api_key', 'api_key': TOKEN}})


def mock(monkeypatch, status=200, body=None, content_type='application/json'):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'Content-Type': content_type})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CASES))
async def test_one_request_per_contract_operation(monkeypatch, operation):
    method, path, shape = native.ROUTES[operation]
    config = {'operation': operation}
    if operation == 'ai_chat':
        config['messages'] = [{'role': 'user', 'content': 'What is the latest AAPL news?'}]
    else:
        # Supply every documented query field, including optional filters.
        cls = next(c for c in native.FinnhubOperation.__args__[0].__args__ if c.model_fields['operation'].default == operation)
        for name, field in cls.model_fields.items():
            if name == 'operation': continue
            alias = field.alias or name
            config[alias] = {'q': 'Apple + Inc', 'exchange': 'US', 'symbol': 'AAPL', 'category': 'general',
                'isin': 'US0378331005', 'cusip': '037833100', 'metric': 'all', 'grouping': 'sector',
                'mic': 'XNAS', 'currency': 'USD', 'securityType': 'Common Stock', 'resolution': 'D',
                'base': 'USD', 'date': '2024-01-01', 'minId': 0, 'limit': 4, 'international': False}.get(alias,
                1704067200 if operation in {'stock_candles', 'crypto_candles'} else '2024-01-01')
    body = [] if shape == 'list' else {'value': TOKEN, 's': 'no_data'}
    requests = mock(monkeypatch, body=body)
    out = await node(config).execute({})
    assert out['status'] == 'success' and TOKEN not in str(out)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == CASES[operation]['method'] and req.url.path == '/api/v1' + CASES[operation]['path']
    assert req.url.host == 'finnhub.io' and req.url.params['token'] == TOKEN
    if method == 'POST':
        assert dict(req.url.params) == {'token': TOKEN}
        assert json.loads(req.content) == {'messages': config['messages'], 'stream': False}
    else:
        expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k != 'operation'}
        assert dict(req.url.params) == {'token': TOKEN, **expected}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_provider_failure_not_success_and_secret_redacted(monkeypatch, status):
    requests = mock(monkeypatch, status=status, body={'error': 'Rejected ' + TOKEN})
    out = await node({'operation': 'get_market_news'}).execute({})
    assert out['status'] == 'error' and out['http_status'] == status
    assert TOKEN not in str(out) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body,mime', [([], 'application/json'), ({'error': TOKEN}, 'application/json'), ({}, 'text/html')])
async def test_bad_response_refused(monkeypatch, body, mime):
    mock(monkeypatch, body=body, content_type=mime)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'quote', 'symbol': 'AAPL'}).execute({})
    assert TOKEN not in str(error.value)


def test_manual_defaults_and_input_validation():
    credential = native.FinnhubAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'finnhub_api_key'
    assert native.FinnhubNode.connection_evidence.proves == 'reachability'
    for value in ['https://example.test/key', 'bad key', 'key\nvalue']:
        with pytest.raises((ValueError, ValidationError)):
            native.FinnhubAPIKeyCredential(api_key=value)
    for config in [
        {'operation': 'quote'},
        {'operation': 'company_news', 'symbol': 'AAPL', 'from': '2024-02-01', 'to': '2024-01-01'},
        {'operation': 'ai_chat', 'messages': []},
        {'operation': 'ai_chat', 'messages': [{'role': 'user', 'content': 'Hi'}], 'stream': True},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(config)


def test_full_config_validation_does_not_echo_a_secret():
    with pytest.raises(ValidationError) as error:
        native.FinnhubFullConfig.model_validate({
            'config': {'operation': 'quote', 'symbol': 'AAPL'},
            'credentials': {'api_key': TOKEN + '\ninvalid'},
        })
    assert TOKEN not in str(error.value)

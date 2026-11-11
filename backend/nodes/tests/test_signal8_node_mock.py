"""Request and polling behavior against Signal8's published examples."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.signal8_node import Signal8Node, Signal8APIKeyCredential
from nodes.core.poll_trigger import poll_scope

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/signal8/filings.json').read_text())

def node(config):
    data = {'config': config, 'credentials': {'credential_type': 'signal8_api_key', 'api_key': 'sk_live_test123'}}
    return Signal8Node('test', 'automation-signal8', data, config=Signal8Node.parse_config(data))

@pytest.mark.asyncio
async def test_batch_quotes_is_documented_read_post(monkeypatch):
    n = node({'operation': 'get_batch_quotes', 'tickers': 'AAPL,MSFT'})
    request = AsyncMock(return_value={'data': {'quotes': {'AAPL': None}}})
    monkeypatch.setattr(n, '_request', request)
    assert (await n.execute({}))['data']['quotes']['AAPL'] is None
    request.assert_awaited_once_with('sk_live_test123', 'POST', '/market/quotes', params=None, body={'tickers': 'AAPL,MSFT'})

@pytest.mark.asyncio
async def test_ticker_query_and_null_caveats_preserved(monkeypatch):
    n = node({'operation': 'get_dilution_risk', 'ticker': 'VNRX'})
    body = {'data': {'score': None, 'scoreWithheldReason': 'no_dilution_snapshot'}}
    request = AsyncMock(return_value=body)
    monkeypatch.setattr(n, '_request', request)
    assert await n.execute({}) == body
    request.assert_awaited_once_with('sk_live_test123', 'GET', '/dilution/VNRX/risk', params={}, body=None)

@pytest.mark.asyncio
async def test_poll_uses_documented_filing_ids_and_agent_context(monkeypatch):
    n = node({'operation': 'on_new_filing', 'ciks': '0000320193', 'formTypes': '10-Q'})
    request = AsyncMock(return_value=FIXTURE)
    monkeypatch.setattr(n, '_request', request)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, value = mutator(state)
        if new is not None: state = new
        return value
    monkeypatch.setattr(n, '_update_node_state', update)
    assert (await n.execute({}))['new_filing_count'] == 0
    # A later documented filing appears after a baseline containing only the older one.
    state['seen_ids'] = [str(FIXTURE['data'][1]['id'])]
    out = await n.execute({})
    assert out['filings'] == [FIXTURE['data'][0]]
    text = n.resolve_agent_event(out)['text']
    assert 'Apple Inc.' in text and '0000320193-26-000013' in text
    assert not n.should_propagate_output({'new_filing_count': 0}, {'operation': 'on_new_filing'})
    request.assert_awaited_with('sk_live_test123', 'GET', '/edgar/filings', params={'sort': 'newest', 'pageSize': 100, 'ciks': '0000320193', 'formTypes': '10-Q'})
    assert (await n.execute({}))['new_filing_count'] == 0

def test_manual_credential_and_poll_scope():
    assert Signal8APIKeyCredential(api_key='sk_live_test123').credential_type == 'signal8_api_key'
    a = {'operation': 'on_new_filing', 'ciks': '0000320193'}
    assert poll_scope(Signal8Node, a) == poll_scope(Signal8Node, {**a, 'goal': 'cosmetic'})
    assert poll_scope(Signal8Node, a) != poll_scope(Signal8Node, {**a, 'ciks': '0001018724'})

@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'error': {'message': 'Invalid API key'}}), (200, {'error': {'message': 'Denied'}}), (302, {})])
async def test_errors_and_redirects_are_not_success(monkeypatch, status, body):
    @asynccontextmanager
    async def client():
        mock = AsyncMock()
        mock.request.return_value = httpx.Response(status, json=body)
        yield mock
    monkeypatch.setattr('nodes.signal8_node.guarded_async_client', client)
    with pytest.raises(ValueError):
        await Signal8Node._request('sk_live_test123', 'GET', '/edgar/filings')

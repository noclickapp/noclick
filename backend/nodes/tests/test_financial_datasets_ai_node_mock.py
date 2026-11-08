"""Exercise native factory calls with synthetic provider data; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import financial_datasets_ai_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/financial-datasets-ai/contract.json').read_text())
KEY = 'synthetic-financial-datasets-key'


def node(config):
    return NodeFactory.create_node(node_id='financial-fixture', node_type=native.FinancialDatasetsAINode.integration_type,
        node_data={'config': config, 'credentials': {'credential_type': 'financial_datasets_ai_api_key', 'api_key': KEY}})


def transport(monkeypatch, body, code=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(code, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c: c['config']['operation'])
async def test_pinned_operation_wire_and_response_preservation(monkeypatch, case):
    # Deliberately retain empty data, nulls, nested provider metadata and source
    # attribution; consumers need these fields for analysis and display.
    body = {key: [] for key in case['response_keys'] if key != 'next_page_url'}
    body.update(metadata={'source': 'SEC', 'nullable': None}, attribution='Fixture source')
    requests = transport(monkeypatch, body)
    n = node(case['config'])
    result = await n.execute({})
    request, = requests
    assert request.method == case['method']
    assert request.url.path == case['path']
    assert request.url.host == 'api.financialdatasets.ai'
    assert request.headers['X-API-KEY'] == KEY
    assert KEY not in str(request.url) and KEY not in request.content.decode()
    values = n.config.config.model_dump(mode='json', exclude_none=True, exclude={'operation'})
    if case['method'] == 'POST':
        assert json.loads(request.content) == values
        assert request.headers['content-type'] == 'application/json'
    else:
        for key, value in values.items():
            if isinstance(value, list): assert request.url.params.get_list(key) == value
            else: assert request.url.params[key] == (str(value).lower() if isinstance(value, bool) else str(value))
    assert result == {**body, 'status': 'success', 'next_cursor': None}


@pytest.mark.asyncio
async def test_post_search_nested_filters_and_sort(monkeypatch):
    requests = transport(monkeypatch, {'results': [{'ticker': 'AAPL', 'revenue': 50000000001}]})
    await node({'operation': 'search_financials', 'filters': [{'field': 'ticker', 'operator': 'in', 'value': ['AAPL', 'MSFT']}],
        'order_by': {'field': 'revenue', 'direction': 'asc'}, 'as_of': '2024-01-31'}).execute({})
    assert json.loads(requests[0].content)['filters'][0]['value'] == ['AAPL', 'MSFT']
    assert json.loads(requests[0].content)['order_by'] == {'field': 'revenue', 'direction': 'asc'}


@pytest.mark.asyncio
async def test_one_page_opaque_cursor_and_boolean_filters(monkeypatch):
    next_url = native.BASE_URL + '/beneficial-ownership?cursor=opaque%2B%2F%3D'
    requests = transport(monkeypatch, {'beneficial_ownership': [], 'next_page_url': next_url})
    result = await node({'operation': 'list_beneficial_ownership', 'history': True, 'ticker': 'AAPL'}).execute({})
    assert requests[0].url.params['history'] == 'true'
    assert len(requests) == 1 and result['next_cursor'] == 'opaque+/='
    transport(monkeypatch, {'beneficial_ownership': []})
    requests = transport(monkeypatch, {'beneficial_ownership': []})
    await node({'operation': 'list_beneficial_ownership', 'cursor': result['next_cursor'], 'ticker': 'MSFT'}).execute({})
    assert requests[0].url.params['cursor'] == 'opaque+/='
    assert requests[0].url.params['ticker'] == 'MSFT'


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['https://evil.test/news?cursor=next', 'https://api.financialdatasets.ai/prices?cursor=next',
    'http://api.financialdatasets.ai/news?cursor=next', native.BASE_URL + '/news?limit=10'])
async def test_untrusted_continuation_never_followed(monkeypatch, url):
    requests = transport(monkeypatch, {'news': [], 'next_page_url': url})
    with pytest.raises(ValueError):
        await node({'operation': 'list_news'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [400, 401, 402, 404, 429, 500])
async def test_provider_errors_remain_errors_and_redact_key(monkeypatch, code):
    transport(monkeypatch, {'error': 'Rejected', 'message': 'provider says ' + KEY}, code)
    result = await node({'operation': 'list_news'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert 'provider says' in result['error'] and KEY not in str(result)


@pytest.mark.asyncio
async def test_error_envelope_and_unexpected_json(monkeypatch):
    transport(monkeypatch, {'error': 'Invalid key'})
    assert (await node({'operation': 'list_news'}).execute({}))['status'] == 'error'
    transport(monkeypatch, [])
    with pytest.raises(ValueError): await node({'operation': 'list_news'}).execute({})


def test_manual_credential_default_and_input_validation():
    assert native.FinancialDatasetsAIAPIKey(api_key=KEY).credential_type == 'financial_datasets_ai_api_key'
    for config in [
        {'operation': 'get_company_facts'},
        {'operation': 'get_prices', 'ticker': 'AAPL', 'interval': 'day', 'start_date': '2024-02-01', 'end_date': '2024-01-01'},
        {'operation': 'get_prices', 'ticker': 'AAPL', 'interval': 'day', 'start_date': 'not-a-date', 'end_date': '2024-01-01'},
        {'operation': 'list_news', 'limit': 11},
        {'operation': 'list_filings', 'filing_type': ['invalid-form']},
        {'operation': 'list_index_funds'},
        {'operation': 'list_index_funds', 'ticker': 'SPY', 'holding': 'AAPL'},
        {'operation': 'search_financials', 'filters': []},
        {'operation': 'search_line_items', 'tickers': [], 'line_items': ['revenue']},
        {'operation': 'search_financials', 'filters': [{'field': 'revenue', 'operator': 'in', 'value': 1}]},
    ]:
        with pytest.raises(ConfigValidationError): node(config)


@pytest.mark.asyncio
async def test_index_funds_documented_envelope_and_ambiguous_provider_schema(monkeypatch):
    from jsonschema import Draft4Validator
    fixture = json.loads((Path(__file__).parent / 'fixtures/financial-datasets-ai/index-funds-spec-defect.json').read_text())
    schema, body = fixture['schema'], fixture['synthetic_response']
    # The provider documents ticker -> fund + holdings. Its oneOf has no
    # required fields or closed branches, so that shape matches both arms.
    assert not Draft4Validator(schema).is_valid(body)
    for branch in schema['oneOf']:
        assert Draft4Validator({**schema, 'oneOf': [branch]}).is_valid(body)
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'list_index_funds', 'ticker': 'SPY'}).execute({})
    assert result['fund'] == body['fund'] and result['holdings'] == body['holdings']
    assert requests[0].url.params['ticker'] == 'SPY'


@pytest.mark.asyncio
async def test_line_item_documented_numbers_preserved_despite_provider_schema(monkeypatch):
    from jsonschema import Draft4Validator
    fixture = json.loads((Path(__file__).parent / 'fixtures/financial-datasets-ai/line-items-spec-defect.json').read_text())
    body = fixture['documented_response']
    assert not Draft4Validator(fixture['schema']).is_valid(body)
    transport(monkeypatch, body)
    result = await node({'operation': 'search_line_items', 'tickers': ['NVDA', 'AAPL'],
        'line_items': ['net_income', 'total_debt']}).execute({})
    assert result['search_results'][0]['net_income'] == 53008000000
    assert isinstance(result['search_results'][0]['net_income'], int)


@pytest.mark.asyncio
async def test_continuation_trailing_slash_and_nonadvancing_cursor(monkeypatch):
    transport(monkeypatch, {'news': [], 'next_page_url': native.BASE_URL + '/news/?cursor=next'})
    assert (await node({'operation': 'list_news'}).execute({}))['next_cursor'] == 'next'
    with pytest.raises(ValueError, match='did not advance'):
        await node({'operation': 'list_news', 'cursor': 'next'}).execute({})

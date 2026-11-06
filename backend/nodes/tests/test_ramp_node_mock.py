"""Exercise Ramp's real HTTP serialization and parsing without network access.

Fixtures are verbatim examples from Ramp's official v1 OpenAPI document:
https://docs.ramp.com/openapi/developer-api.json
Each operation records its source URL beside the response and realistic input.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.ramp_node import RampNode, RampNodeConfig, OPERATIONS, RAMP_SCOPES
from nodes.core.connection_evidence import collect_evidence

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/ramp/responses.json').read_text())
TOKEN = 'ramp_business_tok_mock_for_tests'


def node(operation, config=None):
    return RampNode(
        node_id='ramp-test', node_type='automation-ramp', node_data={}, sio=Mock(),
        config=RampNodeConfig.model_validate({
            'config': {'operation': operation, **(FIXTURES[operation]['config'] if config is None else config)},
            'credentials': {'credential_type': 'ramp_access_token', 'access_token': TOKEN},
        }),
    )


def client_factory(transport):
    original = httpx.AsyncClient
    return lambda *args, **kwargs: original(*args, **{**kwargs, 'transport': httpx.MockTransport(transport)})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    requests = []

    def transport(request):
        requests.append(request)
        if fixture['status_code'] == 204:
            return httpx.Response(204)
        return httpx.Response(fixture['status_code'], json=fixture['response'])

    with patch('httpx.AsyncClient', client_factory(transport)):
        output = await node(operation).execute({})
    assert output['status'] == 'success', output
    assert output['data'] == ({'success': True} if fixture['status_code'] == 204 else fixture['response'])
    assert output['timing_ms']['api_request'] >= 0
    request, = requests
    assert request.method == fixture['method']
    expected_path = fixture['path']
    expected_values = dict(fixture['config'])
    for key in ('card_id', 'transaction_id', 'reimbursement_id', 'bill_id'):
        if key in expected_values:
            expected_path = expected_path.replace('{' + key + '}', expected_values.pop(key))
    assert request.url.path == expected_path
    assert request.url.host == 'api.ramp.com'
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(request.url)
    if request.method == 'GET':
        assert dict(request.url.params) == {k: str(v) for k, v in expected_values.items()}
        assert not request.content
    elif expected_values:
        for key in ('shipping_address', 'line_items', 'payment_details'):
            if key in expected_values:
                expected_values[key] = json.loads(expected_values[key])
        if "payment_details" in expected_values:
            expected_values["payment_details"]["payment_method"] = expected_values["payment_method"]
        assert json.loads(request.content) == expected_values
        assert not request.url.query
    else:
        assert not request.content


def test_fixture_and_scope_coverage():
    assert set(FIXTURES) == set(OPERATIONS) == set(RAMP_SCOPES)
    assert all(f['source'] == 'https://docs.ramp.com/openapi/developer-api.json' for f in FIXTURES.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 429, 500])
async def test_provider_errors_preserve_words_and_redact_token(status):
    def transport(request):
        return httpx.Response(status, json={'error': {'message': 'Token rejected: ' + TOKEN}})
    with patch('httpx.AsyncClient', client_factory(transport)):
        result = await node('get_business').execute({})
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert 'Token rejected' in result['error']
    assert TOKEN not in json.dumps(result)
    assert result['timing_ms']['api_request'] >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'id': 'x'}, {'id': 'x', 'business_name_legal': ''},
    {'id': 'x', 'business_name_legal': 'Example', 'error': 'invalid_auth'}])
async def test_connection_probe_rejects_unrecognizable_or_error_envelopes(body):
    with patch('httpx.AsyncClient', client_factory(lambda request: httpx.Response(200, json=body))):
        result = await node('get_business').execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_connection_evidence_names_the_business():
    with patch('httpx.AsyncClient', client_factory(lambda request: httpx.Response(200, json=FIXTURES['get_business']['response']))):
        result = await collect_evidence(node_type='automation-ramp', user_id='ramp-test', credential_data={
            'credential_type': 'ramp_access_token', 'access_token': TOKEN,
        })
    assert result.reachable is True
    assert result.account_label == FIXTURES['get_business']['response']['business_name_legal']


@pytest.mark.asyncio
async def test_empty_page_and_next_cursor_are_preserved():
    body = {'data': [], 'page': {'next': 'https://api.ramp.com/developer/v1/transactions?start=cursor-2'}}
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=body)
    with patch('httpx.AsyncClient', client_factory(transport)):
        result = await node('list_transactions', {'page_size': 2, 'start': 'cursor-1'}).execute({})
    assert result['data'] == body
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {'page_size': '2', 'start': 'cursor-1'}


@pytest.mark.asyncio
@pytest.mark.parametrize('value', ['../bills', 'id?query=true', 'id#fragment'])
async def test_path_injection_is_rejected_before_http(value):
    with patch('httpx.AsyncClient') as client:
        with pytest.raises(ValueError, match='resource ID'):
            await node('get_physical_card', {'card_id': value}).execute({})
        client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('value', ['{invalid', '{}', '[1]'])
async def test_malformed_split_json_is_rejected_before_http(value):
    with patch('httpx.AsyncClient') as client:
        with pytest.raises(ValueError, match='line_items'):
            await node('update_transaction', {'transaction_id': FIXTURES['update_transaction']['config']['transaction_id'], 'line_items': value}).execute({})
        client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['timeout', 'network', 'html'])
async def test_transport_and_non_json_failures(kind):
    def transport(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('secret ' + TOKEN, request=request)
        if kind == 'network':
            raise httpx.ConnectError('secret ' + TOKEN, request=request)
        return httpx.Response(200, text='<html>not an API response</html>')
    with patch('httpx.AsyncClient', client_factory(transport)):
        result = await node('get_business').execute({})
    assert result['status'] == 'error'
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_credential():
    n = node('get_business')
    n.config.credentials = None
    with pytest.raises(ValueError, match='access token'):
        await n.execute({})

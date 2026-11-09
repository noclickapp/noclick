"""Exercise PostalDataPI's real node factory against documented request/response fixtures.

These tests verify body authentication, parameter mapping and provider failures without an account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import postal_data_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-postal-api-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/postal-data-api/contract.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="postal-fixture", node_type=native.PostalDataApiNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "postal_data_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda v: v['operation'])
async def test_postal_data_api_documented_contract(monkeypatch, fixture):
    requests = transport(monkeypatch, fixture['response'])
    result = await node({"operation": fixture['operation'], **fixture['config']}).execute({})
    assert result['status'] == 'success'
    assert result['data'] == fixture['response']
    assert len(requests) == 1
    assert requests[0].method == 'POST'
    assert str(requests[0].url) == native.BASE + fixture['path']
    assert json.loads(requests[0].content) == {**fixture['config'], 'apiKey': TOKEN}
    assert 'apiKey' not in requests[0].headers
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 402, 404, 429, 500])
async def test_postal_data_api_errors_and_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {'error': 'Rejected ' + TOKEN, 'apiKey': TOKEN, 'retryAfter': 5}, status)
    result = await node({'operation': 'lookup_postal_code', 'zipcode': '90210'}).execute({})
    assert result['success'] is False and result['http_status'] == status
    assert TOKEN not in str(result) and 'apiKey' not in result['data']
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_postal_data_api_invalid_is_valid_result(monkeypatch):
    transport(monkeypatch, {'valid': False, 'zipcode': '00000', 'balance': 4.99})
    result = await node({'operation': 'validate_postal_code', 'zipcode': '00000'}).execute({})
    assert result['success'] is True and result['data']['valid'] is False


def test_postal_data_api_input_and_manual_credential_contract():
    assert native.PostalDataApiKeyCredential(api_key=TOKEN).credential_type == 'postal_data_api_key'
    with pytest.raises(ValidationError):
        native.SearchByCity(city='Beverly Hills')
    assert native.SearchByCity(city='Berlin', country='DE').state is None
    for records in ([], [{'postalCode': '90210', 'countryCode': 'US'}] * 1001):
        with pytest.raises(ValidationError):
            native.ValidateBulkPostalCodes(records=records)
    assert native.LookupPostalCode(zipcode='06000').zipcode == '06000'
    with pytest.raises(ValidationError):
        native.LookupPostalCode(zipcode='90210', country='USA')


@pytest.mark.asyncio
async def test_postal_data_api_timeout_does_not_retry(monkeypatch):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('sensitive ' + TOKEN, request=request)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kw))
    result = await node({'operation': 'lookup_postal_code', 'zipcode': '90210'}).execute({})
    assert result['success'] is False and TOKEN not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'city': 42}])
async def test_postal_data_api_malformed_success_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'lookup_postal_code', 'zipcode': '90210'}).execute({})
    assert result['success'] is False

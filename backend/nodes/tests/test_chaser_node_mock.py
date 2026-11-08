"""Synthetic contract regressions; no Chaser account or live writes are used."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import chaser_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/chaser/operations.json').read_text())
CREDENTIAL = {'credential_type': 'chaser_api_key', 'api_key': 'synthetic-key-42', 'api_secret': 'synthetic-secret-42'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='chaser-test', node_type='automation-chaser',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_each_operation_makes_one_authenticated_contract_request(monkeypatch, case):
    payload = {'object': 'list' if case['config']['operation'].startswith('list_') else 'customer',
               'data': [{'id': 'cust_42', 'company_name': 'Example Ltd'}] if case['config']['operation'].startswith('list_') else {'id': 'cust_42'},
               'page_number': 0, 'page_size': 100, 'total_count': 1}
    requests = transport(monkeypatch, payload)
    result = await node(case['config']).execute({})
    assert result == {**payload, 'status': 'success'}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'openapi.chaserhq.com'
    assert request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert request.headers['Authorization'] == 'Basic ' + base64.b64encode(b'synthetic-key-42:synthetic-secret-42').decode()


@pytest.mark.asyncio
async def test_explicit_page_and_zero_balance_filter_are_preserved(monkeypatch):
    requests = transport(monkeypatch, {'data': [], 'total_count': 0})
    result = await node({'operation': 'list_invoices', 'page': 3, 'limit': 25, 'amount_due': 0, 'status': 'PAID'}).execute({})
    assert result['data'] == []
    assert dict(requests[0].url.params) == {'page': '3', 'limit': '25', 'amount_due': '0.0', 'status': 'PAID'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_invoice_write_preserves_zero_and_optional_timestamp(monkeypatch):
    config = next(c['config'] for c in CASES if c['config']['operation'] == 'create_invoice')
    requests = transport(monkeypatch, {'data': {'id': 'inv_42'}})
    await node({**config, 'amount_due': 0, 'amount_paid': 100, 'expect_payment_date': '2026-11-10T10:00:00Z'}).execute({})
    body = json.loads(requests[0].content)
    assert body['amount_due'] == 0
    assert body['amount_paid'] == 100
    assert body['expect_payment_date'] == '2026-11-10T10:00:00Z'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_provider_rejections_keep_message_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={'message': 'requested resource is forbidden'}))
    result = await node({'operation': 'pause_invoice_chasing', 'invoice_id': 'inv_42'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'requested resource is forbidden'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_credential_echo_is_redacted(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(403, json={'message': 'invalid ' + CREDENTIAL['api_secret']}))
    result = await node({'operation': 'get_organisation'}).execute({})
    assert CREDENTIAL['api_secret'] not in str(result)


@pytest.mark.asyncio
async def test_empty_delete_and_invalid_success_shape(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(204))
    assert await node({'operation': 'delete_customer_note', 'customer_id': 'cust_42', 'note_id': 'note_42'}).execute({}) == {'status': 'success', 'data': None}
    transport(monkeypatch, [])
    with pytest.raises(ValueError, match='JSON object'):
        await node({'operation': 'get_organisation'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_customer', 'customer_id': '../other'},
    {'operation': 'get_invoice', 'invoice_id': 'inv_42?x=y'},
    {'operation': 'list_customers', 'limit': 101},
    {'operation': 'list_invoices', 'page': -1},
    {'operation': 'create_customer', 'external_id': '42', 'company_name': ''},
    {'operation': 'create_customer', 'external_id': '42', 'company_name': 'Example', 'contact_email_address': 'invalid'},
    {'operation': 'update_customer', 'customer_id': 'cust_42'},
    {'operation': 'update_invoice', 'invoice_id': 'inv_42'},
    {'operation': 'create_customer_note', 'customer_id': 'cust_42', 'message': 'Follow up', 'reminder_date': '2026-11-10'},
])
def test_invalid_config_is_rejected_before_network(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_secret_shape():
    credential = native.ChaserAPIKeyCredential(api_key=' synthetic-key-42 ', api_secret=' synthetic-secret-42 ')
    assert credential.credential_type == 'chaser_api_key'
    assert credential.api_key == 'synthetic-key-42'
    for key in ['api_key', 'api_secret']:
        with pytest.raises(ValidationError):
            native.ChaserAPIKeyCredential(**{**CREDENTIAL, key: 'https://example.com/token'})


@pytest.mark.asyncio
async def test_saved_workflow_metadata_never_enters_provider_request(monkeypatch):
    requests = transport(monkeypatch, {'data': {'id': 'cust_42'}})
    await node({'operation': 'update_customer', 'customer_id': 'cust_42', 'company_name': 'Updated Ltd',
                'label': 'Collections', 'goal': 'Keep accounting records current',
                'credentialIds': {'chaser_api_key': 'saved-credential'}, 'disabled': False}).execute({})
    assert json.loads(requests[0].content) == {'company_name': 'Updated Ltd'}
    assert requests[0].url.path == '/v1/customers/cust_42'

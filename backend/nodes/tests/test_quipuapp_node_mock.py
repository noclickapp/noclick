"""Published Quipu examples and schema-shaped transport/error regressions; no live account."""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import quipuapp_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/quipuapp/published_examples.json').read_text())
CREDS = {'credential_type': native.CREDENTIAL_TYPE, 'client_id': 'fixture-client-id',
         'client_secret': 'fixture-client-secret', 'owner_slug': 'example-business'}
TOKEN = EXAMPLES['responses']['POST /oauth/token']['body']['access_token']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='quipu-fixture', node_type='automation-quipuapp',
                                  node_data={'config': config, 'credentials': credential or CREDS})


def transport(monkeypatch, reply, *, token_reply=None):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == '/oauth/token':
            return token_reply or httpx.Response(200, json=EXAMPLES['responses']['POST /oauth/token']['body'])
        return reply(request) if callable(reply) else reply

    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.OPERATIONS)
async def test_all_operations_fixed_routes_grant_and_media(monkeypatch, operation):
    method, resource = native.OPERATIONS[operation]
    config = EXAMPLES['inputs'].get(operation, {}).get('config', {}).copy()
    config['operation'] = operation
    detail = operation.startswith(('get_', 'update_', 'delete_'))
    if detail:
        config['resource_id'] = 101
    row = {'id': '101', 'type': 'tickets' if resource in {'simplified_invoices', 'additional_incomes'} else resource,
           'attributes': {'name': 'Acme Corp'}}
    body = {'data': [row], 'meta': {'pagination_info': {'total_pages': 2, 'current_page': 1, 'total_results': 26}}} if operation.startswith('list_') else {'data': row}
    response = httpx.Response(204) if method == 'DELETE' else httpx.Response(201 if method == 'POST' else 200, json=body)
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 2
    auth, request = requests
    assert auth.method == 'POST' and auth.url == native.BASE + '/oauth/token'
    assert auth.headers['Authorization'] == 'Basic ' + base64.b64encode(b'fixture-client-id:fixture-client-secret').decode()
    assert parse_qs(auth.content.decode()) == {'grant_type': ['client_credentials'], 'scope': ['ecommerce']}
    assert auth.headers['Content-Type'].startswith('application/x-www-form-urlencoded')
    assert request.method == method
    assert request.url.path == '/example-business/' + resource + ('/101' if detail else '')
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['Accept'] == native.MEDIA
    if method in {'POST', 'PATCH'}:
        assert request.headers['Content-Type'] == native.MEDIA
        assert json.loads(request.content)['data']['type'] == resource
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'page[number]': '1', 'page[size]': '25'}
        assert result['next_page'] == 2 and result['pagination_known']
        assert result['items'][0]['name'] == 'Acme Corp'


@pytest.mark.asyncio
async def test_documented_invoice_preserves_attributes_relationships_and_lines(monkeypatch):
    expected = EXAMPLES['requests']['POST /{owner_slug}/invoices']
    config = {'operation': 'create_invoice', **EXAMPLES['inputs']['create_invoice']['config']}
    requests = transport(monkeypatch, httpx.Response(201, json={'data': {'id': '101', 'type': 'invoices'}}))
    await node(config).execute({})
    assert json.loads(requests[-1].content) == expected


@pytest.mark.asyncio
async def test_patch_omits_unsupplied_fields_preserves_null_and_line_ids(monkeypatch):
    config = {'operation': 'update_invoice', 'resource_id': 101, 'paid_at': None,
              'items_json': json.dumps([{'id': '5', 'concept': 'Consulting services', 'unitary_amount': '1500.00', 'accounting_subcategory_id': 5}])}
    requests = transport(monkeypatch, httpx.Response(200, json={'data': {'id': '101', 'type': 'invoices'}}))
    await node(config).execute({})
    data = json.loads(requests[-1].content)['data']
    assert data['attributes'] == {'paid_at': None}
    line = data['relationships']['items']['data'][0]
    assert line['id'] == '5'
    assert line['relationships'] == {'accounting_subcategory': {'data': {'id': '5', 'type': 'accounting_subcategories'}}}
    assert line['attributes']['quantity'] == 1


@pytest.mark.asyncio
async def test_filters_and_boolean_are_exact_and_next_page_is_explicit(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={'data': [], 'meta': {'pagination_info': {'total_pages': 1, 'current_page': 1, 'total_results': 0}}}))
    result = await node({'operation': 'list_contacts', 'query': 'Acme + Madrid', 'kind': 'client', 'sort': '-name'}).execute({})
    assert dict(requests[-1].url.params) == {'page[number]': '1', 'page[size]': '25', 'filter[q]': 'Acme + Madrid', 'filter[kind]': 'client', 'sort': '-name'}
    assert result['next_page'] is None and result['pagination_known']
    await node({'operation': 'list_numbering_series', 'amending': False}).execute({})
    assert requests[-1].url.params['filter[amending]'] == 'false'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 422, 429, 500])
async def test_errors_preserve_rejection_but_redact_secrets(monkeypatch, status):
    transport(monkeypatch, httpx.Response(status, json={'errors': [{'detail': 'Not authorized ' + CREDS['client_secret'] + ' ' + TOKEN}]}))
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_contacts'}).execute({})
    assert str(status) in str(error.value) and 'Not authorized' in str(error.value)
    assert CREDS['client_secret'] not in str(error.value) and TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_auth_rejection_makes_no_resource_request_and_does_not_retry_write(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(201, json={}), token_reply=httpx.Response(400, json={'error': 'invalid_scope', 'error_description': 'scope is required'}))
    with pytest.raises(ValueError, match='scope is required'):
        await node({'operation': 'create_contact', 'name': 'Acme Corp', 'country_code': 'ES'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': None}, {'data': {}}, {'errors': [{'detail': 'Not authorized'}]}])
async def test_malformed_list_and_error_envelope_fail(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_contacts'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_contact', 'resource_id': '../invoices'},
    {'operation': 'list_contacts', 'page_size': 101},
    {'operation': 'create_contact', 'name': 'Acme Corp'},
    {'operation': 'create_invoice', 'contact_id': 101, 'kind': 'expenses', 'items_json': '[]'},
    {'operation': 'create_invoice', 'contact_id': 101, 'items_json': '[{"concept":"Consulting services","unitary_amount":"1500.00"}]', 'kind': 'expenses'},
    {'operation': 'create_additional_income', 'issue_date': '2024-03-15', 'items_json': '[]'},
    {'operation': 'update_invoice', 'resource_id': 101, 'items_json': '[{"concept":"Consulting services","unitary_amount":"1500.00","unknown":true}]'},
    {'operation': 'update_invoice', 'resource_id': 101, 'items_json': '[{"concept":"Consulting services","unitary_amount":"1500.00","quantity":NaN}]'},
    {'operation': 'list_contacts', 'arbitrary_query': 'no'},
])
def test_invalid_input_is_rejected_before_io(config):
    with pytest.raises((ValidationError, ValueError)):
        native.QuipuNode.parse_config({'config': config, 'credentials': CREDS})


def test_manual_credential_default_and_business_slug_validation():
    assert native.QuipuAPICredential.model_validate({k: v for k, v in CREDS.items() if k != 'credential_type'}).credential_type == native.CREDENTIAL_TYPE
    for slug in ['https://getquipu.com/business', '../business', 'business/contacts', 'business?x=1']:
        with pytest.raises(ValidationError):
            native.QuipuAPICredential.model_validate({**CREDS, 'owner_slug': slug})

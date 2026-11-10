"""Channel API wire behavior using Smily's pinned, published JSON examples."""
import copy
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import smily_node as smily
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/smily/published_examples.json').read_text())
EXAMPLES = FIXTURE['examples']
CREDENTIAL = {'credential_type': 'smily_api_key', 'api_key': 'smily-fixture-key-42', 'host': 'https://demo.platforms.bookingsync.com'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='smily-test', node_type='automation-smily', node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(smily, 'guarded_async_client', client)
    return requests


def attributes(example):
    return {k.replace('-', '_'): v for k, v in EXAMPLES[example]['data']['attributes'].items()}


CASES = [
    ('list_accounts', {}, 'GET', '/accounts', 'AccountsResponseExample'),
    ('get_account', {'account_id': 1}, 'GET', '/accounts/1', 'AccountResponseExample'),
    ('list_rentals', {}, 'GET', '/rentals', 'RentalsResponseExample'),
    ('get_rental', {'rental_id': 1}, 'GET', '/rentals/1', 'RentalResponseExample'),
    ('create_quote', {**attributes('QuoteRequestExample'), 'rental_id': '1'}, 'POST', '/quotes', 'QuoteResponseExample'),
    ('list_bookings', {}, 'GET', '/bookings', 'BookingsResponseExample'),
    ('get_booking', {'booking_id': 1}, 'GET', '/bookings/1', 'BookingResponseExample'),
    ('create_booking', attributes('BookingRequestExample'), 'POST', '/bookings', 'BookingResponseExample'),
    ('cancel_booking', {'booking_id': 1, **attributes('BookingCancelationRequestExample')}, 'PATCH', '/bookings/1/cancel', 'BookingResponseExample'),
    ('list_payments', {}, 'GET', '/payments', 'PaymentsResponseExample'),
    ('get_payment', {'payment_id': 1}, 'GET', '/payments/1', 'PaymentResponseExample'),
    ('create_payment', {**{k: v for k, v in attributes('PaymentRequestExample').items() if k != 'kind'}, 'payment_kind': 'credit-card'}, 'POST', '/payments', 'PaymentResponseExample'),
    ('list_los_records', {'los_rental_id': 10648, 'day': '2021-01-27'}, 'GET', '/los-records', 'LosRecordsResponseExample'),
    ('list_live_los_records', {}, 'GET', '/live-los-records', 'LiveLosRecordsResponseExample'),
    ('get_rental_live_los_records', {'rental_id': 500}, 'GET', '/rentals/500/live-los-records', 'LiveLosRecordsResponseExample'),
    ('list_los_export_urls', {}, 'GET', '/los-record-export-urls', 'LosRecordExportUrlsResponseExample'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,example', CASES)
async def test_all_published_routes(monkeypatch, operation, config, method, path, example):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=EXAMPLES[example]))
    result = await node({'operation': operation, **config}).execute({})
    assert result == EXAMPLES[example]
    request = requests[0]
    assert len(requests) == 1
    assert request.method == method
    assert request.url.path == '/api/ota/v1' + path
    assert request.headers['Authorization'] == 'Bearer ' + CREDENTIAL['api_key']
    if operation in {'create_booking', 'create_quote', 'create_payment', 'cancel_booking'}:
        body = json.loads(request.content)
        assert request.headers['Content-Type'] == 'application/vnd.api+json'
        assert body['data']['type'] == ('payments' if operation == 'create_payment' else 'quotes' if operation == 'create_quote' else 'bookings')
        expected = {('kind' if k == 'payment_kind' else k.replace('_', '-')): v for k, v in config.items() if k != 'booking_id' or operation == 'create_payment'}
        actual = body['data']['attributes']
        for key in ('start-at', 'end-at', 'paid-at'):
            if key in actual and 'T' in actual[key]:
                assert datetime.fromisoformat(actual[key]) == datetime.fromisoformat(expected[key])
                expected[key] = actual[key]
        assert actual == expected


@pytest.mark.asyncio
async def test_filters_sparse_fields_pagination_cursor_and_idempotency(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={'data': []}))
    await node({'operation': 'list_rentals', 'filter_account_id': '1', 'filter_id': '1,2,3', 'page_number': 1, 'page_size': 50, 'fields': 'name,currency', 'sort': '-name'}).execute({})
    assert dict(requests[-1].url.params) == {'filter[account-id]': '1', 'filter[id]': '1,2,3', 'page[number]': '1', 'page[size]': '50', 'fields[rentals]': 'name,currency', 'sort': '-name'}
    await node({'operation': 'list_live_los_records', 'kind': 'rental_price', 'cursor': 'opaque'}).execute({})
    assert dict(requests[-1].url.params) == {'kind': 'rental_price', 'cursor': 'opaque'}
    key = '550e8400-e29b-41d4-a716-446655440000'
    await node({'operation': 'create_booking', **attributes('BookingRequestExample'), 'idempotency_key': key}).execute({})
    assert requests[-1].headers['Idempotency-Key'] == key
    assert 'idempotency-key' not in json.loads(requests[-1].content)['data']['attributes']


@pytest.mark.asyncio
async def test_evidence_uses_account_names(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=EXAMPLES['AccountsResponseExample']))
    options = await smily.SmilyNode.load_field_options('account_id', CREDENTIAL)
    assert options['options'][0]['label'] == EXAMPLES['AccountsResponseExample']['data'][0]['attributes']['name']
    assert requests[0].method == 'GET'


@pytest.mark.parametrize('host', ['https://evil.test', 'https://demo.platforms.bookingsync.com.evil.test', 'http://demo.platforms.bookingsync.com', 'https://demo.platforms.bookingsync.com:443', 'https://a.b.platforms.bookingsync.com', 'https://user@demo.platforms.bookingsync.com', 'https://127.0.0.1', 'https://demo.platforms.bookingsync.com/api'])
def test_host_restriction(host):
    with pytest.raises(ValueError):
        smily.SmilyAPIKeyCredential.model_validate({**CREDENTIAL, 'host': host})


def test_manual_connect_default_and_validation():
    c = smily.SmilyAPIKeyCredential.model_validate({'api_key': 'smily-fixture-key-42\n', 'host': 'demo'})
    assert c.credential_type == 'smily_api_key' and c.host == CREDENTIAL['host']
    for config in [
        {'operation': 'get_booking', 'booking_id': -1},
        {'operation': 'get_booking', 'booking_id': '../accounts'},
        {'operation': 'create_booking'},
        {'operation': 'list_live_los_records', 'cursor': 'opaque', 'changed_since': '2026-08-13T09:00:00Z'},
        {'operation': 'on_los_records_changed', 'kind': 'bad'},
    ]:
        with pytest.raises(ValueError):
            node(config)
    for key in ['Bearer key', 'https://bad.test/key', '<token>']:
        with pytest.raises(ValidationError):
            smily.SmilyAPIKeyCredential.model_validate({**CREDENTIAL, 'api_key': key})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 422, 429, 500])
async def test_failure_is_not_success_or_retry_and_key_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, text='Rejected ' + CREDENTIAL['api_key'], headers={'Location': 'https://evil.test'}))
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_accounts'}).execute({})
    assert str(status) in str(error.value) and CREDENTIAL['api_key'] not in str(error.value)
    assert len(requests) == 1


def stateful(node, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    node._update_node_state = update


@pytest.mark.asyncio
async def test_poll_complete_snapshot_baseline_changes_repeat_reversion_and_scope(monkeypatch):
    # Provider example data is copied; terminal pagination and price mutations
    # below are synthetic edge cases, not claims about published examples.
    payload = copy.deepcopy(EXAMPLES['LiveLosRecordsResponseExample'])
    payload['meta'] = {'has_more': False, 'next_cursor': None}
    transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    n = node({'operation': 'on_los_records_changed', 'rental_id': 500})
    state = {}
    stateful(n, state)
    assert (await n.execute({}))['changed_count'] == 0
    assert (await n.execute({}))['changed_count'] == 0
    initial = payload['data'][0]['rows'][0][3][0]
    payload['data'][0]['rows'][0][3][0] = '999.00'
    changed = await n.execute({})
    assert changed['changed_count'] == 1 and n.trigger_emitted_event(changed)
    event = n.resolve_agent_event(changed)
    assert 'rental 500' in event['text'] and 'Account 200' in event['text'] and 'USD' in event['text']
    assert (await n.execute({}))['changed_count'] == 0
    payload['data'][0]['rows'][0][3][0] = initial
    assert (await n.execute({}))['changed_count'] == 1
    changed_scope = node({'operation': 'on_los_records_changed', 'rental_id': 500, 'kind': 'rental_price'})
    stateful(changed_scope, state)
    assert (await changed_scope.execute({}))['changed_count'] == 0


@pytest.mark.asyncio
async def test_poll_uses_single_rental_endpoint_and_failure_preserves_state(monkeypatch):
    page = copy.deepcopy(EXAMPLES['LiveLosRecordsResponseExample'])
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=page))
    n = node({'operation': 'on_los_records_changed', 'rental_id': 500})
    state = {'seen_ids': []}
    stateful(n, state)
    result = await n.execute({})
    assert result['changed_count'] == 1 and len(requests) == 1
    assert requests[0].url.path == '/api/ota/v1/rentals/500/live-los-records'
    assert dict(requests[0].url.params) == {'kind': 'final_price'}
    before = copy.deepcopy(state)
    transport(monkeypatch, lambda _: httpx.Response(429, text='Slow down'))
    with pytest.raises(ValueError, match='429'):
        await n.execute({})
    assert state == before
    page['data'][0]['rental_id'] = 501
    transport(monkeypatch, lambda _: httpx.Response(200, json=page))
    with pytest.raises(ValueError, match='outside the selected rental'):
        await n.execute({})
    assert state == before

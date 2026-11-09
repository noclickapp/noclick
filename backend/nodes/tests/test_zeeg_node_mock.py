"""Exercise Zeeg's real factory and HTTP request construction using contract fixtures.

Provider examples and explicitly marked synthetic successes are offline fixtures; no account is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import zeeg_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/zeeg/contract_examples.json').read_text())
TOKEN = 'synthetic-zeeg-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='zeeg-test', node_type='automation-zeeg', node_data={
        'config': config, 'credentials': {'credential_type': 'zeeg_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, status, body):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_contract_responses_through_native_factory(monkeypatch, operation):
    case = EXAMPLES[operation]
    calls = transport(monkeypatch, case['status'], case['body'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['http_status'] == case['status']
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    path = case['path']
    identifier = next((case['config'][k] for k in ('event_id', 'invitee_id', 'page_id', 'note_id') if k in case['config']), None)
    assert request.url.path == '/v2' + path.replace('{uuid}', identifier or '').replace('{id}', identifier or '')
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert request.url.host == 'api.zeeg.me'
    assert TOKEN not in str(result)
    if isinstance(case['body'], dict):
        for key, value in case['body'].items():
            if key != 'status':
                assert result[key] == value


@pytest.mark.asyncio
async def test_booking_preserves_answers_location_and_timezone(monkeypatch):
    calls = transport(monkeypatch, 200, EXAMPLES['create_booking']['body'])
    config = {**EXAMPLES['create_booking']['config'], 'location': 'PHONE_CALL', 'phone': '+49 170 9876543',
        'locationOptions': {'callType': 'I_WILL_CALL'},
        'question_answers': [{'question_id': 1, 'answer': ['Demo', 'Pricing']}], 'guests': ['alex.chen@northwind.io']}
    await node(config).execute({})
    body = json.loads(calls[0].content)
    assert body['date'] == '2026-04-15' and body['start'] == '09:00' and body['timeZone'] == 'Europe/Paris'
    assert body['locationOptions'] == {'callType': 'I_WILL_CALL'}
    assert body['question_answers'] == config['question_answers'] and body['guests'] == config['guests']
    assert 'operation' not in body and 'event_id' not in body


@pytest.mark.asyncio
async def test_filters_pagination_and_boolean_queries(monkeypatch):
    calls = transport(monkeypatch, 200, EXAMPLES['list_events']['body'])
    await node({'operation': 'list_events', 'count': 10, 'page': 2, 'keyword': 'Café + demo',
        'minStartTime': '2026-04-01T00:00:00Z', 'status': 'confirmed'}).execute({})
    assert dict(calls[0].url.params) == {'count': '10', 'page': '2', 'sort': 'asc', 'keyword': 'Café + demo',
        'minStartTime': '2026-04-01T00:00:00Z', 'status': 'confirmed'}
    calls = transport(monkeypatch, 200, EXAMPLES['list_schedules']['body'])
    await node({'operation': 'list_schedules', 'email': 'lena.meier@horizondigital.de', 'includeSchedulingPages': True}).execute({})
    assert calls[0].url.params['includeSchedulingPages'] == 'true'


@pytest.mark.asyncio
async def test_note_and_page_bodies_and_explicit_null(monkeypatch):
    calls = transport(monkeypatch, 201, EXAMPLES['create_note']['body'])
    await node(EXAMPLES['create_note']['config']).execute({})
    assert json.loads(calls[0].content) == {'relation': 'event', 'uuid': 'zg-O69bac566950c6', 'note': EXAMPLES['create_note']['config']['note']}
    calls = transport(monkeypatch, 201, EXAMPLES['create_scheduling_page']['body'])
    await node({'operation': 'create_scheduling_page', 'title': 'Intro call'}).execute({})
    assert json.loads(calls[0].content) == {'type': 'ONE_ON_ONE', 'title': 'Intro call', 'isActive': False}
    calls = transport(monkeypatch, 200, EXAMPLES['update_scheduling_page']['body'])
    await node({'operation': 'update_scheduling_page', 'page_id': 'page-42', 'description': None}).execute({})
    assert json.loads(calls[0].content) == {'description': None}


@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
@pytest.mark.asyncio
async def test_http_failures_never_claim_success_or_retry(monkeypatch, status):
    calls = transport(monkeypatch, status, {'error': {'message': 'Rejected ' + TOKEN}})
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'check_connection'}).execute({})
    assert TOKEN not in str(exc.value) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'success': False}, {'error': 'rejected'}, {'email': None}])
async def test_connection_requires_account_identity(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({'operation': 'check_connection'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_event', 'event_id': '../whoami'},
    {'operation': 'get_note', 'note_id': 'https://evil.test'},
    {'operation': 'get_event', 'event_id': 'id?scope=all'},
    {'operation': 'list_scheduling_pages', 'email': 'a@example.com', 'userSlug': 'other'},
    {'operation': 'update_scheduling_page', 'page_id': 'p1'},
    {'operation': 'create_booking', 'eventTypeId': 'p1', 'date': '2026-04-15', 'start': '25:00', 'name': 'Sophie', 'email': 's@example.com', 'timeZone': 'Europe/Paris'},
    {'operation': 'get_availability', 'page_id': 'p1', 'startDate': '2026-04-15', 'endDate': '2026-04-01'},
])
def test_invalid_inputs_rejected_before_request(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


@pytest.mark.parametrize('token', ['', '<token>', 'https://example.com/key', 'Bearer abc', 'abc\r\nInjected:yes'])
def test_bad_credentials(token):
    with pytest.raises(ValidationError):
        native.ZeegAPITokenCredential(api_token=token)


def test_manual_connect_has_default_type():
    credential = native.ZeegAPITokenCredential(api_token='  ' + TOKEN + '\n')
    assert credential.credential_type == 'zeeg_api_token' and credential.api_token == TOKEN
    assert native.ZeegNode.connection_evidence.identity_operation == 'check_connection'

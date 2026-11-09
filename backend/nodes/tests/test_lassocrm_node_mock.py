"""Exercise LassoCRM's real factory and published HTTP request mappings offline.

These synthetic responses verify write bodies, pagination boundaries and provider
rejections without using a LassoCRM account or sending a live mutation.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import lassocrm_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-lasso-jwt-42'
CREDENTIAL = {'credential_type': 'lassocrm_api_key', 'api_key': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='lasso-test', node_type='automation-lassocrm',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})


def transport(monkeypatch, body, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


WRITE_CASES = [
    ({'operation': 'create_registrant', 'first_name': 'Jane', 'last_name': 'Doe', 'email': 'test_registrant@lassocrm.com', 'automatically_merge': False},
     'POST', '/v1/registrants', 202, {'person': {'firstName': 'Jane', 'lastName': 'Doe'}, 'emails': [{'email': 'test_registrant@lassocrm.com', 'primary': True}], 'automaticallyMerge': False}),
    ({'operation': 'update_registrant', 'registrant_id': '123', 'first_name': 'Jane', 'last_name': 'Doe', 'contact_preference': 'noEmail'},
     'PUT', '/v1/registrants/123', 200, {'firstName': 'Jane', 'lastName': 'Doe', 'contactPreference': 'noEmail'}),
    ({'operation': 'set_rating', 'registrant_id': '123', 'rating': 'A'},
     'PUT', '/v1/registrants/123/rating', 200, {'rating': 'A'}),
    ({'operation': 'add_email', 'registrant_id': '123', 'email': 'test_registrant@lassocrm.com', 'contact_type': 'Personal', 'primary': True},
     'POST', '/v1/registrants/123/emails', 201, {'email': 'test_registrant@lassocrm.com', 'type': 'Personal', 'primary': True}),
    ({'operation': 'add_phone', 'registrant_id': '123', 'phone': '123-456-7890'},
     'POST', '/v1/registrants/123/phones', 201, {'phone': '123-456-7890', 'primary': False}),
    ({'operation': 'create_note', 'registrant_id': '123', 'note': 'Offer a $10.000 credit'},
     'POST', '/v1/registrants/123/notes', 201, {'note': 'Offer a $10.000 credit'}),
    ({'operation': 'create_activity', 'registrant_id': '123', 'activity_type': 'Phone Call', 'details': 'Follow-up call about the floor plan', 'activity_date': '2026-10-21', 'complete': False},
     'POST', '/v1/registrants/123/activities', 201, {'type': 'Phone Call', 'details': 'Follow-up call about the floor plan', 'date': '2026-10-21', 'complete': False}),
    ({'operation': 'create_appointment', 'registrant_id': '123', 'name': 'Design Center Selections', 'start_time': '2019-01-31T10:30:00-08:00', 'end_time': '2019-01-31T11:30:00-08:00'},
     'POST', '/v1/registrants/123/appointments', 201, {'name': 'Design Center Selections', 'startTime': '2019-01-31T18:30:00Z', 'endTime': '2019-01-31T19:30:00Z'}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,status,body', WRITE_CASES)
async def test_writes_use_one_exact_contract_request(monkeypatch, config, method, path, status, body):
    requests = transport(monkeypatch, {'id': '123'}, status)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['http_status'] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == 'api.lassocrm.com'
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert json.loads(request.content) == body
    assert request.headers['content-type'] == 'application/json'
    if status == 202:
        assert result['accepted'] is True and result['processing_complete'] is False


@pytest.mark.asyncio
async def test_read_page_filters_and_documented_next_link(monkeypatch):
    payload = {'items': [{'registrantId': '123', 'person': {'firstName': 'Jane', 'lastName': 'Doe'}}], 'links': {'next': '/registrants?cursor=fdslkb32b3o2o'}}
    requests = transport(monkeypatch, payload)
    result = await node({'operation': 'list_registrants', 'rating': 'A + B', 'last_modified_after': '2026-10-21', 'cursor': 'a+/='}).execute({})
    assert result['data'] == payload and result['next_cursor'] == 'fdslkb32b3o2o' and result['has_more']
    assert dict(requests[0].url.params) == {'rating': 'A + B', 'lastModifiedAfter': '2026-10-21', 'cursor': 'a+/='}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_search_false_and_array_result_are_preserved(monkeypatch):
    requests = transport(monkeypatch, {'items': None, 'links': None})
    result = await node({'operation': 'search_registrants', 'email': 'a+b@example.com', 'fuzzy': False}).execute({})
    assert result['status'] == 'success' and result['next_cursor'] is None
    assert dict(requests[0].url.params) == {'email': 'a+b@example.com', 'fuzzy': 'false'}
    transport(monkeypatch, [{'id': '123', 'details': 'Follow-up'}])
    result = await node({'operation': 'list_activities', 'registrant_id': '123'}).execute({})
    assert result['data'][0]['id'] == '123' and result['provider_limit'] == 150


@pytest.mark.asyncio
@pytest.mark.parametrize('link', ['https://evil.example/registrants?cursor=x', '/inventory?cursor=x', '/registrants?cursor=x&cursor=y', '/registrants?foo=x'])
async def test_bad_pagination_links_never_followed(monkeypatch, link):
    requests = transport(monkeypatch, {'items': [], 'links': {'next': link}})
    result = await node({'operation': 'list_registrants'}).execute({})
    assert result['status'] == 'error' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_rejections_preserve_provider_text_without_secret_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Denied ' + TOKEN}, status)
    result = await node({'operation': 'list_registrants'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Denied [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', ['not an object', [], {'error': 'Denied'}])
async def test_bad_shapes_and_error_envelopes_cannot_pass(monkeypatch, payload):
    transport(monkeypatch, payload)
    assert (await node({'operation': 'list_registrants'}).execute({}))['status'] == 'error'


def test_manual_credential_defaults_schema_and_operation_contract():
    assert native.LassoCRMAPIKeyCredential(api_key='  '+TOKEN+'  ').model_dump() == CREDENTIAL
    for secret in ['https://example.com/key', '<token>', 'Bearer abc']:
        with pytest.raises(ValidationError):
            native.LassoCRMAPIKeyCredential(api_key=secret)
    fixture = json.loads((Path(__file__).parent / 'fixtures/lassocrm/operations.json').read_text())
    assert fixture == native.ROUTES and len(fixture) == 21
    assert native.LassoCRMNode.connection_evidence.operation == 'list_registrants'
    for cfg in [
        {'operation': 'get_registrant', 'registrant_id': '../123'},
        {'operation': 'create_registrant', 'first_name': 'Jane'},
        {'operation': 'create_appointment', 'registrant_id': '123', 'name': 'Tour', 'start_time': '2026-10-21T19:00:00Z', 'end_time': '2026-10-21T18:00:00Z'},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(cfg)


@pytest.mark.asyncio
async def test_project_appointment_documented_short_next_path(monkeypatch):
    cursor = 'ewogICJ2IjogIjEuMCIsCiAgIm8iOiAiMTIzIiwKICAibCI6ICIxMDAiCn0='
    requests = transport(monkeypatch, {'items': [], 'links': {'next': '/appointments?cursor=' + cursor}})
    result = await node({'operation': 'list_project_appointments'}).execute({})
    assert result['status'] == 'success' and result['next_cursor'] == cursor
    assert len(requests) == 1 and requests[0].url.path == '/v1/projects/appointments'

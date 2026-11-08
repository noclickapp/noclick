"""Exercise WaiverFile through its real factory and HTTP serialization.

Fixtures are synthetic representations of the provider's documented formats.
Pinned request metadata is copied from its published Swagger contract.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import waiverfile_node as native
from nodes.core.registry import NodeFactory
SITE = '11111111-1111-4111-8111-111111111111'
RESOURCE = '22222222-2222-4222-8222-222222222222'
KEY = 'waiverfile-synthetic-private-key'
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/waiverfile/contract.json').read_text())
START, END = ('2024-06-01T14:00:00Z', '2024-06-01T17:00:00Z')
DATES = {'start_date': START, 'end_date': END}
EVENT = {**DATES, 'event_name': 'Sample Event', 'event_category_id': RESOURCE}
CASES = {'get_site_details': {}, 'get_waiver': {'waiver_id': RESOURCE}, 'get_waiver_lite': {'waiver_id': RESOURCE}, 'search_waivers': {'terms': 'Taylor + café'}, 'get_waivers_by_reference_id': {'ref_id_any': 'booking-42'}, 'count_waivers': DATES, 'list_waivers': DATES, 'list_waivers_lite': DATES, 'get_waiver_data': DATES, 'count_waiver_data': DATES, 'list_active_waiver_forms': {}, 'list_all_waiver_forms': {}, 'list_events': DATES, 'list_events_by_category': {**DATES, 'event_category_id': RESOURCE}, 'list_upcoming_events': DATES, 'list_event_waivers': {'event_id': RESOURCE}, 'list_event_categories': {}, 'create_event': {**EVENT, 'signing_cutoff': END}, 'update_event': {**EVENT, 'event_id': RESOURCE, 'waiver_form_ids': [RESOURCE]}, 'delete_event': {'event_id': RESOURCE}, 'create_event_category': {'name': 'Classes'}, 'update_event_category': {'event_category_id': RESOURCE, 'name': 'Renamed Classes'}, 'delete_event_category': {'event_category_id': RESOURCE}, 'list_subscribers': DATES, 'list_opted_out_subscribers': DATES}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(operation, **changes):
    return NodeFactory.create_node(node_id='waiverfile-test', node_type='automation-waiverfile', node_data={'config': {'operation': operation, **CASES[operation], **changes}, 'credentials': {'credential_type': 'waiverfile_api_key', 'api_key': KEY, 'site_id': SITE}})

def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if not isinstance(body, bytes) else httpx.Response(status, content=body)

    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

def response_for(operation):
    if operation == 'get_site_details':
        return {'ID': SITE, 'Name': 'Fixture Site', 'Url': 'fixture'}
    if operation.startswith('count_'):
        return 42
    if operation == 'list_upcoming_events':
        return json.dumps([{'WaiverEventID': RESOURCE, 'EventName': 'Sample Event'}])
    if operation in {'get_waiver', 'get_waiver_lite'}:
        return {'Waiver': {'WaiverID': RESOURCE, 'Particpants': {'WaiverParticipant': {'NameFirst': 'Taylor'}}}}
    if operation in {'search_waivers', 'get_waivers_by_reference_id', 'list_waivers', 'list_waivers_lite'}:
        return {'ArrayOfWaiver': {'Waiver': {'WaiverID': RESOURCE, 'SignedName': 'Taylor'}}}
    if operation == 'get_waiver_data':
        return {'Table': [{'WaiverID': RESOURCE, 'RowNum': 1}]}
    if operation.startswith(('create_', 'update_', 'delete_')):
        return {'ID': RESOURCE, 'Name': 'Fixture'}
    return [{'ID': RESOURCE, 'Name': 'Fixture'}]

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CASES))
async def test_published_method_route_query_body_and_auth(monkeypatch, operation):
    body = response_for(operation)
    requests = transport(monkeypatch, body)
    result = await node(operation).execute({})
    assert result['status'] == 'success' and KEY not in str(result)
    assert result['data'] == (json.loads(body) if operation == 'list_upcoming_events' else body)
    assert len(requests) == 1
    req, contract = (requests[0], CONTRACT['operations'][operation])
    assert req.url.host == 'api.waiverfile.com'
    assert (req.method, req.url.path) == (contract['method'], contract['path'])
    query = dict(req.url.params)
    allowed = {p['name'] for p in contract['parameters'] if p['in'] == 'query'}
    required = {p['name'] for p in contract['parameters'] if p['in'] == 'query' and p.get('required')}
    assert required <= query.keys() <= allowed
    if operation == 'create_event':
        payload = json.loads(req.content)
        assert not query and payload['APIKey'] == KEY and (payload['SiteID'] == SITE)
        assert payload['DateStart'] == '2024-06-01T14:00:00Z' and payload['SigningCutoff'] == '2024-06-01T17:00:00Z'
        assert payload['MaxParticipants'] == 0 and payload['IsAllDay'] is False
        assert 'ManagerEmailList' not in payload
    else:
        assert query['apiKey'] == KEY and query['siteID'] == SITE
        if operation == 'update_event':
            assert json.loads(req.content) == [RESOURCE]
            assert query['isAllDay'] == 'false' and query['dateStart'] == '2024-06-01T14:00:00Z'
        else:
            assert req.content == b''
    if operation == 'get_waiver_data':
        assert query['pageIndex'] == '1'
    if operation in {'list_waivers', 'list_waivers_lite'}:
        assert query['pageIndex'] == '0'
    if operation == 'search_waivers':
        assert query['terms'] == 'Taylor + café'

@pytest.mark.asyncio
async def test_utc_conversion_and_redaction(monkeypatch):
    requests = transport(monkeypatch, {'Table': [{'Note': KEY}]})
    result = await node('get_waiver_data', start_date='2024-06-01T16:00:00+02:00').execute({})
    assert requests[0].url.params['startDate'] == '2024-06-01T14:00:00'
    assert result['data']['Table'][0]['Note'] == '[redacted]'

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_http_failures_preserve_provider_text_without_key(monkeypatch, status):
    requests = transport(monkeypatch, ('API key rejected: ' + KEY).encode(), status)
    result = await node('get_site_details').execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'API key rejected: [redacted]' and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'Error running waiver search', b'<html>sign in</html>', b'null', b'"error"', b'{"error":"denied"}'])
async def test_200_error_and_invalid_representations_are_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node('search_waivers').execute({})

@pytest.mark.asyncio
async def test_connection_identity_rejects_other_site(monkeypatch):
    transport(monkeypatch, {'ID': RESOURCE, 'Name': 'Another Site'})
    with pytest.raises(ValueError):
        await node('get_site_details').execute({})

@pytest.mark.parametrize('operation, changes', [('get_waiver', {'waiver_id': '../bad'}), ('get_waiver_data', {'page_index': 0}), ('list_waivers', {'page_size': 501}), ('list_waivers', {'page_size': 9}), ('list_events', {'end_date': '2024-05-01T00:00:00Z'}), ('get_waivers_by_reference_id', {'ref_id_any': ''}), ('create_event', {'waiver_form_id_list': 'not-a-guid'})])
def test_invalid_inputs_are_refused_before_network(operation, changes):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **changes)

"""Exercise the real factory and YouCanBookMe HTTP/parser boundary.

Synthetic provider transport covers metadata filtering, ancestry and pagination.
Shared credential authorization stays owned by staging's existing loaders.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import socket
from unittest.mock import AsyncMock
import httpx
import pytest
import pytest_asyncio
from nodes import youcanbookme_node as native
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation

USER = '00000000-0000-0000-0000-000000000001'
CID = '00000000-0000-0000-0000-000000000002'
ORG = '00000000-0000-0000-0000-000000000003'
OTHER = '00000000-0000-0000-0000-000000000004'
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
KEY = 'synthetic-youcanbookme-api-key'
NODE = 'automation-youcanbookme'
BASE = {'credential_type': 'youcanbookme_api_key', 'api_key': KEY, 'account_id': 'syntheticaccount', 'auth_username': 'syntheticaccount'}
PROFILE = {'id': 'profile1', 'accountId': 'syntheticaccount', 'title': 'Synthetic Profile', 'status': 'OFFLINE', 'timeZone': 'Europe/Lisbon', 'accessCode': 'private-access-code', 'actions': [{'body': KEY}], 'calendars': {'items': [{'id': 'private-calendar'}]}}
FULL = {**PROFILE, 'teamMembers': {'active': True, 'items': [{'id': 'member1', 'name': 'Synthetic Member', 'email': 'private@example.invalid', 'calendarId': 'private-calendar'}]}, 'appointmentTypes': {'active': True, 'items': [{'id': 'type1', 'name': 'Synthetic Appointment', 'slotLength': 'PT15M', 'numberOfSlots': 1, 'price': 5000, 'pic': 'https://private.invalid'}]}}
BOOKING = {'id': 'booking1', 'accountId': 'syntheticaccount', 'profileId': 'profile1', 'bookingPageId': 'profile1', 'title': 'Synthetic Booking', 'createdAt': '2026-01-02T10:00:00Z', 'startsAt': '2026-01-03T10:00:00', 'endsAt': '2026-01-03T10:30:00', 'timeZone': 'Europe/Lisbon', 'status': 'no_show', 'questions': [{'answer': 'private@example.invalid'}], 'payment': {'provider': 'private-payment'}, 'intentId': 'private-intent', 'linkFields': 'https://private.invalid?secret=withheld'}
QUERY_PATH = '/v1/accounts/syntheticaccount/bookings/query'
QUERY = {'from_time': '2026-01-01T00:00:00Z', 'to_time': '2026-02-01T00:00:00Z', 'profile_id': 'profile1'}

class Boundary:
    def __init__(self):
        self.blob = deepcopy(BASE)
        self.requests = []; self.responses = {}; self.links = {}; self.after_http = None
        self.profiles = [deepcopy(PROFILE)]; self.pages = None
    def wire(self, request):
        self.requests.append(request)
        path = request.url.path
        assert request.method == 'GET' and not request.content
        assert request.url.scheme == 'https' and request.url.host == 'api.youcanbook.me'
        expected = 'Basic ' + base64.b64encode((self.blob['auth_username'] + ':' + self.blob['api_key']).encode()).decode()
        assert request.headers['authorization'] == expected and KEY not in str(request.url)
        if path == '/v1/profiles':
            assert request.url.params == httpx.QueryParams({'ownerId': 'syntheticaccount'}); payload = self.profiles
        elif path == '/v1/profiles/profile1':
            assert request.url.params['fields'] in (native.PROFILE_FIELDS, native.TEAM_FIELDS, native.TYPE_FIELDS); payload = FULL
        elif path == '/v1/bookings/booking1':
            assert request.url.params['fields'] == native.BOOKING_FIELDS; payload = BOOKING
        elif path == QUERY_PATH:
            assert 10 <= int(request.url.params['pageSize']) <= 500
            payload = [BOOKING] if self.pages is None else self.pages[request.url.params.get('fromBookingId', '')]
        else: raise AssertionError('Unexpected native endpoint')
        override = self.responses.get(path)
        if isinstance(override, Exception): raise override
        if isinstance(override, int): return httpx.Response(override, json={'message': KEY + ' private@example.invalid'}, request=request)
        if isinstance(override, bytes): return httpx.Response(200, content=override, headers={'content-type': 'application/json'}, request=request)
        if override is not None: payload = deepcopy(override)
        if self.after_http: self.after_http(path)
        return httpx.Response(200, json=payload, headers={'link': self.links[path]} if path in self.links else {}, request=request)

@pytest_asyncio.fixture
async def boundary(monkeypatch):
    value = Boundary()
    def transport(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(value.wire), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', transport)
    return value

async def run(boundary, operation='test_connection', args=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_data=BASE, user_id=USER)

OPERATIONS = {'test_connection': {}, 'get_account_scope': {}, 'list_profiles': {}, 'get_profile': {'profile_id': 'profile1'}, 'list_team_members': {'profile_id': 'profile1'}, 'get_team_member': {'profile_id': 'profile1', 'team_member_id': 'member1'}, 'list_appointment_types': {'profile_id': 'profile1'}, 'get_appointment_type': {'profile_id': 'profile1', 'appointment_type_id': 'type1'}, 'get_booking': {'profile_id': 'profile1', 'booking_id': 'booking1'}, 'query_bookings': QUERY}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_actual_ten_factory_actions_and_account_parent_privacy(boundary, operation):
    result = await run(boundary, operation, OPERATIONS[operation])
    assert NODE_REGISTRY[NODE] is native.YouCanBookMeNode and result['status'] == 'success'
    for private in (KEY, 'private.invalid', 'secret=', 'private@example.invalid', 'private-calendar', 'private-intent', 'private-payment', 'private-access-code'): assert private not in json.dumps(result)
    if operation == 'test_connection': assert result['data']['authentication_verified'] is True and result['data']['account_identity_verified'] is True and result['data']['subject_identity_verified'] is None and result['data']['paid_entitlement_verified'] is None
    if operation == 'get_booking': assert result['data']['public_representation'] is True and result['data']['booking_response_authentication_verified'] is None
    if operation in ('get_booking', 'query_bookings'):
        row = result['data'] if operation == 'get_booking' else result['data']['items'][0]
        assert row['startsAt'] == BOOKING['startsAt'] and row['timeZone'] == BOOKING['timeZone'] and row['status'] == 'no_show'

@pytest.mark.asyncio
@pytest.mark.parametrize('parent', ['list_account', 'profile_account', 'booking_account', 'booking_profile', 'missing_profile'])
async def test_actual_protected_ancestry_precedes_public_booking(boundary, parent):
    if parent == 'list_account': boundary.profiles = [{**PROFILE, 'accountId': 'foreign'}]
    elif parent == 'profile_account': boundary.responses['/v1/profiles/profile1'] = {**FULL, 'accountId': 'foreign'}
    elif parent == 'booking_account': boundary.responses['/v1/bookings/booking1'] = {**BOOKING, 'accountId': 'foreign'}
    elif parent == 'booking_profile': boundary.responses['/v1/bookings/booking1'] = {**BOOKING, 'profileId': 'foreign', 'bookingPageId': 'foreign'}
    else: boundary.profiles = []
    with pytest.raises(native.YouCanBookMeDenied): await run(boundary, 'get_booking', OPERATIONS['get_booking'])
    if parent in ('list_account', 'profile_account', 'missing_profile'): assert all('/v1/bookings/' not in req.url.path for req in boundary.requests)

@pytest.mark.asyncio
async def test_actual_snapshot_pagination_refuses_changed_collection_or_filters(boundary):
    boundary.profiles.append({**PROFILE, 'id': 'profile2', 'title': 'Second Synthetic Profile'})
    first = await run(boundary, 'list_profiles', {'per_page': 1})
    token = first['data']['next_page_token']
    second = await run(boundary, 'list_profiles', {'per_page': 1, 'page_token': token})
    assert second['data']['items'][0]['id'] == 'profile2'
    with pytest.raises(ValueError): await run(boundary, 'list_profiles', {'per_page': 1, 'page_token': token, 'search': 'changed'})
    boundary.profiles.reverse()
    with pytest.raises(ValueError): await run(boundary, 'list_profiles', {'per_page': 1, 'page_token': token})

def link_query(**changes):
    values = {'from': QUERY['from_time'], 'to': QUERY['to_time'], 'direction': 'forwards', 'searchTimeRangeCriteria': 'startsAt', 'sortBy': 'startsAt', 'pageSize': '50', 'bookingPageIds': 'profile1', 'fromBookingId': 'booking1', **changes}
    return '<https://api.youcanbook.me' + QUERY_PATH + '?' + str(httpx.QueryParams(values)) + '>; rel="next"'

@pytest.mark.asyncio
@pytest.mark.parametrize('link', ['<https://private.invalid/x>; rel="next"', '<https://api.youcanbook.me/v1/accounts/foreign/bookings/query>; rel="next"', link_query(pageSize='500'), link_query(bookingPageIds='foreign'), link_query(api_key='secret'), link_query(**{'from': '2025-01-01T00:00:00Z'}), 'malformed Link header'])
async def test_real_link_never_changes_origin_account_parent_or_filters(boundary, link):
    boundary.links[QUERY_PATH] = link
    with pytest.raises(native.YouCanBookMeUnavailable): await run(boundary, 'query_bookings', QUERY)
    assert len(boundary.requests) == 2 and all(req.url.host == 'api.youcanbook.me' for req in boundary.requests)

@pytest.mark.asyncio
async def test_actual_query_link_is_rebuilt_and_cycles_refused(boundary):
    boundary.pages = {'': [BOOKING], 'booking1': [{**BOOKING, 'id': 'booking2'}]}
    boundary.links[QUERY_PATH] = link_query()
    first = await run(boundary, 'query_bookings', QUERY)
    token = first['data']['next_page_token']; assert token and 'https://' not in token
    boundary.links.clear()
    second = await run(boundary, 'query_bookings', {**QUERY, 'page_token': token})
    assert second['data']['items'][0]['id'] == 'booking2' and boundary.requests[-1].url.params['fromBookingId'] == 'booking1'
    boundary.links[QUERY_PATH] = link_query()
    with pytest.raises(native.YouCanBookMeUnavailable): await run(boundary, 'query_bookings', {**QUERY, 'page_token': token})

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [401, 403, 404, 429, 500, b'', b'{"error":"private"}', httpx.ReadTimeout('private-key-details')])
async def test_real_transport_failure_is_private_and_not_retried(boundary, failure, caplog):
    boundary.responses['/v1/profiles'] = failure
    with pytest.raises(ValueError) as error: await run(boundary)
    assert len(boundary.requests) == 1
    assert KEY not in str(error.value) + caplog.text and 'private@example.invalid' not in str(error.value) + caplog.text

@pytest.mark.parametrize('data', [
    {'operation': 'query_bookings', 'from_time': '2026-01-01'},
    {'operation': 'query_bookings', 'from_time': '2026-01-01T00:00:00Z', 'page_size': 501},
    {'operation': 'query_bookings', 'from_time': '2026-01-01T00:00:00Z', 'page_size': True},
    {'operation': 'get_profile', 'profile_id': '../foreign'},
])
def test_actual_typed_parse_refuses_malformed_query_and_path(data):
    with pytest.raises(ValueError): native.YouCanBookMeNode.parse_config({'config': data, 'credentials': BASE})


@pytest.mark.asyncio
@pytest.mark.parametrize('response,valid', [(401, False), (403, False), (302, None), (429, None), (500, None), (b'{bad', None), ({'error': KEY}, None)])
async def test_validation_keeps_denied_and_unknown_distinct(boundary, response, valid):
    boundary.responses['/v1/profiles'] = response
    verdict = await native.YouCanBookMeNode.validate_credential_access(BASE)
    assert verdict['valid'] is valid and KEY not in json.dumps(verdict)

@pytest.mark.asyncio
async def test_empty_profiles_do_not_verify_identity(boundary):
    boundary.profiles = []
    with pytest.raises(native.YouCanBookMeUnavailable): await run(boundary)
    assert (await run(boundary, 'get_account_scope'))['data']['authentication_verified'] is None
    assert (await native.YouCanBookMeNode.validate_credential_access(BASE))['valid'] is None

@pytest.mark.asyncio
async def test_picker_uses_parent_profile_and_current_key(boundary):
    result = await native.YouCanBookMeNode.load_field_options('team_member_id', credential_data=BASE, user_id=USER, context={'profile_id':'profile1'})
    assert result['options'] == [{'value':'member1', 'label':'Synthetic Member', 'metadata':{'account_id':BASE['account_id'], 'profile_id':'profile1'}}]
    with pytest.raises(native.YouCanBookMeDenied):
        await native.YouCanBookMeNode.load_field_options('team_member_id', credential_data=BASE, user_id=USER, context={'profile_id':'foreign'})

@pytest.mark.asyncio
async def test_unsaved_connect_uses_staging_evidence(boundary):
    from nodes.core.connection_evidence import collect_evidence
    evidence = await collect_evidence(node_type=NODE, credential_data=BASE, user_id=USER)
    assert evidence.reachable is True and evidence.samples[0].label == PROFILE['title']

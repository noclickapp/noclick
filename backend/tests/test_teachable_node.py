"""Exercise staging native seams with DB/crypto/DNS/transport/socket boundaries fake."""
import asyncio
import json
import socket
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from nodes import teachable_node as native
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation, run_node_lookup
from nodes.core.connection_evidence import collect_evidence
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL
from utils import credentials, encryption, ssrf
from wss.handlers import credentials_handler, workflow_handler
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

USER = '00000000-0000-0000-0000-000000000001'
CID = '00000000-0000-0000-0000-000000000002'
ORG = '00000000-0000-0000-0000-000000000003'
AID = '00000000-0000-0000-0000-000000000004'
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
WHEN = '2026-01-01T00:00:00Z'
TOKEN = 'synthetic-only-teachable-token'
SECRET = 'synthetic-only-teachable-client-secret'
NODE = 'automation-teachable'
BASE = {'credential_type': native.TYPES[0], 'api_key': TOKEN, 'expected_course_id': '41'}
COURSE = {'id': 41, 'name': 'Synthetic Course', 'is_published': True, 'is_listed': False,
          'created_at': WHEN, 'updated_at': WHEN, 'description': 'private lesson content', 'href': 'https://private.invalid/course'}
LECTURE = {'id': 61, 'name': 'Synthetic Lecture', 'position': 1, 'is_published': True, 'free_preview': False,
           'section': {'id': 51, 'href': 'https://private.invalid/section'}, 'description': 'private lesson content'}


def oauth(**extra):
    return {'credential_type': native.TYPES[1], 'access_token': TOKEN, 'expected_user_id': '42', 'expected_course_id': '41', **extra}


def person(rid=42, name='Synthetic Student', email='withheld@example.invalid'):
    return {'id': rid, 'name': name, 'email': email, 'phone_number': 'private phone', 'role': 'student', 'created_at': WHEN, 'updated_at': WHEN, 'metrics': {'transactions': 'private billing'}}


def enrollment(sale=71):
    return {'user': {'id': 42, 'href': 'https://private.invalid/user'}, 'status': 'active', 'sale': {'id': sale, 'href': 'https://private.invalid/sale'},
            'enrolled_at': WHEN, 'created_at': WHEN, 'updated_at': WHEN, 'expires_at': None, 'progress': {'percent_complete': 25, 'completed_at': None}}


class Boundary:
    def __init__(self):
        self.blob = deepcopy(BASE)
        self.row = {'id': CID, 'metadata': {}, 'created_at': STAMP, 'credential_type': BASE['credential_type'], 'owner_id': USER, 'token_version': 7, 'updated_at': STAMP, 'revoked_at': None,
                    'credential': 'synthetic-cipher', 'approval_revision': 1, 'name': 'Synthetic Teachable', 'approval_operations': []}
        self.allowed = True; self.missing = False; self.pending = None
        self.decrypts = self.admissions = self.loads = self.persists = 0
        self.requests = []; self.responses = {}; self.sent = []; self.after_http = None
        self.student_name = 'Synthetic Student'; self.created = False; self.enrolled = True
        self.encrypted = None
    @asynccontextmanager
    async def acquire(self): yield self
    @asynccontextmanager
    async def transaction(self): yield self
    async def fetchrow(self, sql, *args):
        if sql.strip() == PRIMARY_ORG_SQL.strip():
            assert args == (USER,); return {'organization_id': ORG}
        if 'SELECT name,owner_id,approval_operations' in sql:
            assert args == (CID,); self.admissions += 1
            return None if self.missing else deepcopy(self.row)
        if 'SELECT id,status,consumed_at,expires_at FROM approval_requests' in sql:
            assert args[0] == CID
            return {'id': AID, 'status': self.pending, 'consumed_at': None, 'expires_at': STAMP} if self.pending else None
        if 'FROM credentials c' in sql:
            assert credential_access_predicate() in sql
            assert tuple(str(x) if x is not None else None for x in args[:3]) == (CID, USER, ORG)
            if len(args) == 6:
                assert args[3] == USER and type(args[4]) is bool and args[5] is None
                assert 'workflow_authorized_credentials' in sql
            self.loads += 1
            return deepcopy(self.row) if self.allowed and not self.missing else None
        raise AssertionError('Unexpected real native SQL shape')
    async def fetchval(self, sql, *args): raise AssertionError('Unexpected native DB scalar')
    async def execute(self, sql, *args):
        assert 'UPDATE credentials' in sql and 'token_version = $5' in sql
        assert args[0] == 'synthetic-refreshed-cipher' and args[2:] == (None, CID, self.row['token_version'])
        assert args[1]['expires_at'] == self.encrypted['expires_at']
        assert self.encrypted is not None
        self.persists += 1; self.blob = deepcopy(self.encrypted); self.row['token_version'] += 1
        return 'UPDATE 1'
    def decrypt_credential(self, value):
        assert value == 'synthetic-cipher'; self.decrypts += 1; return deepcopy(self.blob)
    def encrypt_credential(self, value):
        self.encrypted = deepcopy(value); return 'synthetic-refreshed-cipher'
    async def get_session(self, sid): return {'user_id': USER}
    def page(self, request, rows):
        page, per = int(request.url.params.get('page', 1)), int(request.url.params.get('per_page', 100))
        return {'data': rows, 'meta': {'page': page, 'per_page': per, 'total_count': len(rows), 'total_pages': 1 if rows else 0}}
    def wire(self, request):
        self.requests.append(request); path = request.url.path
        assert request.url.host == 'developers.teachable.com' and request.url.scheme == 'https'
        assert request.headers['accept'] == 'application/json'
        if path == native.TOKEN_PATH:
            assert request.method == 'POST' and path == '/v2/current_user/oauth2/token'
            assert 'authorization' not in request.headers and 'apikey' not in request.headers
            assert json.loads(request.content) == {'grant_type': 'refresh_token', 'client_id': 'synthetic-client', 'client_secret': SECRET, 'refresh_token': 'synthetic-refresh'}
            payload = {'access_token': 'synthetic-refreshed-token', 'refresh_token': 'synthetic-rotated-refresh', 'token_type': 'bearer', 'expires_in': 7200}
        else:
            own = path.startswith('/v2/current_user/')
            if own:
                assert self.row['credential_type'] == native.TYPES[1]
                assert request.headers['authorization'] == 'Bearer ' + self.blob['access_token'] and 'apikey' not in request.headers
            else:
                assert self.row['credential_type'] == native.TYPES[0]
                assert request.headers['apikey'] == self.blob['api_key'] and 'authorization' not in request.headers
            if path == '/v2/current_user/me': payload = {'data': person()}
            elif path.endswith('/products/courses'): payload = self.page(request, [deepcopy(COURSE)])
            elif path.endswith('/products/courses/41'): payload = {'data': deepcopy(COURSE)}
            elif path.endswith('/sections'): payload = self.page(request, [{'id': 51, 'name': 'Synthetic Section', 'position': 1}])
            elif path.endswith('/lectures'): payload = self.page(request, [deepcopy(LECTURE)])
            elif path.endswith('/lectures/61'): payload = {'data': deepcopy(LECTURE)}
            elif '/enrollments' in path:
                if request.method in ('PUT', 'DELETE'):
                    assert request.content == b''  # no invented PUT/DELETE body
                    self.enrolled = request.method == 'PUT'
                    payload = {'data': enrollment()} if self.enrolled else None
                else: payload = self.page(request, [enrollment(), enrollment(72)] if self.enrolled else [])
            elif path.endswith('/progress'):
                payload = {'data': {'id': 901, 'percent_complete': 25, 'enrolled_at': WHEN, 'completed_at': None,
                    'sections': [{'id': 51, 'name': 'Synthetic Section', 'percent_complete': 25}],
                    'certificate': {'href': 'https://private.invalid/cert', 'serial_number': 'private serial'}}}
                if own: payload['meta'] = {'page': int(request.url.params['page']), 'per_page': int(request.url.params['per_page']), 'total_count': 1, 'total_pages': 1}
            elif path.endswith('/completion'): payload = {'data': {'completed': False, 'completed_at': None, 'percent_complete': 25}}
            elif path == '/v2/users':
                if request.method == 'POST':
                    assert json.loads(request.content) == {'name': 'New Student', 'email': 'new@example.invalid', 'role': 'student', 'allow_marketing_emails': False}
                    self.created = True; payload = {'data': person(43, 'New Student', 'new@example.invalid')}
                else: payload = self.page(request, [person(name=self.student_name)])
            elif path == '/v2/users/42':
                if request.method == 'PATCH':
                    assert json.loads(request.content) == {'name': 'Updated Student'}; self.student_name = 'Updated Student'
                payload = {'data': person(name=self.student_name)}
            elif path == '/v2/users/43':
                assert self.created; payload = {'data': person(43, 'New Student', 'new@example.invalid')}
            else: raise AssertionError('Unexpected native endpoint')
        override = self.responses.get((request.method, path))
        if isinstance(override, Exception): raise override
        if callable(override): payload = override(payload)
        elif isinstance(override, int): return httpx.Response(override, json={'error': TOKEN + SECRET + ' private provider body'}, request=request)
        elif isinstance(override, bytes): return httpx.Response(200, content=override, headers={'content-type': 'application/json'}, request=request)
        elif override is not None: payload = deepcopy(override)
        if self.after_http: self.after_http(request)
        status = 204 if request.method == 'DELETE' else 201 if request.method == 'POST' and path == '/v2/users' else 200
        return httpx.Response(status, request=request) if status == 204 else httpx.Response(status, json=payload, request=request)


@pytest_asyncio.fixture
async def boundary(monkeypatch):
    value = Boundary()
    monkeypatch.setattr(credentials, 'get_encryption', lambda: value)
    monkeypatch.setattr(encryption, 'get_encryption', lambda: value)
    monkeypatch.setattr(credentials_handler, 'get_encryption', lambda: value)
    monkeypatch.setattr(workflow_handler, 'get_encryption', lambda: value)
    from nodes.core import oauth_refresh
    monkeypatch.setattr(oauth_refresh, 'record_refresh_event', AsyncMock())
    original = ssrf.guarded_async_client
    @asynccontextmanager
    async def transport(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with original(transport=httpx.MockTransport(value.wire), **kwargs) as client: yield client
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]))
    monkeypatch.setattr(native, 'guarded_async_client', transport)
    monkeypatch.setattr(credentials_handler, 'send_event', AsyncMock(side_effect=lambda sio, sid, event: value.sent.append(event)))
    monkeypatch.setattr(workflow_handler, 'send_event', AsyncMock(side_effect=lambda sio, sid, event: value.sent.append(event)))
    return value


async def run(boundary, operation='test_connection', args=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_id=CID, user_id=USER, organization_id=ORG, pool=boundary)


OPERATIONS = {
    'test_connection': {}, 'list_courses': {}, 'get_course': {'course_id': '41'},
    **{op: {'course_id': '41'} for op in ('list_course_sections', 'list_course_lectures', 'list_course_enrollments')},
    **{op: {'course_id': '41', 'user_id': '42'} for op in ('get_user_enrollments', 'get_course_progress', 'enroll_user', 'unenroll_user')},
    'get_lecture_completion': {'course_id': '41', 'user_id': '42', 'lecture_id': '61'},
    'list_users': {}, 'get_user': {'user_id': '42'}, 'create_student': {'name': 'New Student', 'email': 'new@example.invalid'},
    'update_user_name': {'user_id': '42', 'name': 'Updated Student'}, 'get_current_user': {}, 'list_my_courses': {},
    **{op: {'course_id': '41'} for op in ('get_my_course', 'get_my_progress', 'get_my_course_completion')},
}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_twenty_actual_factory_current_row_operations(boundary, operation):
    if operation in native.TEACHABLE_SCOPES and native.TEACHABLE_SCOPES.require(operation).credential_types == (native.TYPES[1],):
        boundary.row['credential_type'] = native.TYPES[1]; boundary.blob = oauth()
    if operation in ('create_student', 'update_user_name', 'enroll_user', 'unenroll_user'): boundary.blob['allow_management_writes'] = True
    output = await run(boundary, operation, OPERATIONS[operation])
    assert NODE_REGISTRY[NODE] is native.TeachableNode and output['action'] == operation
    assert boundary.admissions == 1 and boundary.loads >= 1
    assert all(secret not in json.dumps(output) for secret in (TOKEN, SECRET, 'withheld@example.invalid', 'new@example.invalid', 'private phone', 'private lesson content', 'private.invalid', 'private serial', 'private billing'))
    if operation == 'get_user_enrollments': assert [row['sale_id'] for row in output['data']['items']] == ['71', '72']
    if operation == 'get_my_progress': assert output['data']['progress_id'] == '901' and output['data']['course_id'] == '41'
    if operation in ('create_student', 'update_user_name', 'enroll_user', 'unenroll_user'):
        assert output['data']['readback_verified'] is True and output['data']['billing_effect_verified'] is None and output['data']['notification_delivery_verified'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['foreign_row', 'revoked', 'missing', 'inaccessible'])
async def test_inaccessible_or_foreign_credentials_never_reach_provider(boundary, kind):
    if kind == 'foreign_row': boundary.row['credential_type'] = 'foreign_api_key'
    if kind == 'revoked': boundary.row['revoked_at'] = STAMP
    if kind == 'missing': boundary.missing = True
    if kind == 'inaccessible': boundary.allowed = False
    with pytest.raises(ValueError): await run(boundary)
    # Staging resolves and decrypts before the native model rejects a foreign type.
    assert boundary.decrypts == (1 if kind == 'foreign_row' else 0) and boundary.requests == []


@pytest.mark.asyncio
async def test_native_row_type_overrides_stale_blob_and_carrier_canonicalizes(boundary):
    boundary.blob['credential_type'] = 'foreign_stale_blob'
    output = await run(boundary)
    assert output['data']['authentication_verified'] is True and output['data']['account_identity_verified'] is False
    assert output['data']['grant_scope_verified'] is None
    boundary.blob['credential_type'] = native.TYPES[0]
    saved = await native.TeachableNode.freshen_credential({**boundary.blob, 'token_version': 7, 'updated_at': STAMP.isoformat()}, credential_id=CID, user_id=USER, pool=boundary)
    assert saved['token_version'] == 7 and 'updated_at' in saved
    assert native.TeachableNode.parse_config({'credentials': saved, 'config': {'operation': 'list_courses'}}).credentials.credential_type == native.TYPES[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'rejected'])
async def test_real_admission_collector_does_not_claim_access(boundary, status):
    boundary.row['approval_operations'] = ['*']; boundary.pending = status
    output = await run(boundary); assert output['executed'] is False
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, organization_id=ORG, pool=boundary)
    assert evidence.reachable is not True and native.TeachableNode.connection_evidence.proves == 'reachability'
    assert evidence.account_label is None and evidence.samples == [] and boundary.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('code,valid', [(200, True), (401, False), (403, False), (402, None), (429, None), (500, None)])
async def test_actual_typed_socket_post_connect_tri_state(boundary, code, valid):
    if code != 200: boundary.responses[('GET', '/v2/products/courses')] = code
    handler = credentials_handler.CredentialsHandler(boundary); handler.get_pool = AsyncMock(return_value=boundary)
    await handler.validate_access('synthetic', CredentialValidateAccessRequest(request_id='request', node_type=NODE, credential_id=CID))
    assert boundary.sent[-1].data['valid'] is valid
    assert TOKEN not in json.dumps(boundary.sent[-1].data) and SECRET not in json.dumps(boundary.sent[-1].data)


@pytest.mark.asyncio
@pytest.mark.parametrize('field,context,expected', [('course_id', {}, '41'), ('user_id', {}, '42'), ('lecture_id', {'course_id': '41'}, '61')])
async def test_saved_picker_actual_lookup_and_runtime_carrier(boundary, field, context, expected):
    result = await run_node_lookup(node_type=NODE, field_name=field, context=context, credential_id=CID, user_id=USER, organization_id=ORG, pool=boundary)
    assert result['options'][0]['value'] == expected and boundary.admissions >= 1


@pytest.mark.asyncio
async def test_actual_socket_picker_uses_native_saved_credential(boundary):
    handler = workflow_handler.WorkflowHandler(boundary); handler.get_pool = AsyncMock(return_value=boundary)
    await handler.load_node_options('synthetic', WorkflowNodeLoadOptionsRequest(request_id='request', node_type=NODE, field_name='lecture_id', credential_id=CID, context={'course_id': '41'}))
    assert boundary.sent[-1].data['success'] is True and boundary.sent[-1].data['options'][0]['value'] == '61'


@pytest.mark.asyncio
@pytest.mark.parametrize('args', [{'course_id': '99'}, {'course_id': ['41']}, {}])
async def test_selected_parent_rejected_before_dependent_http(boundary, args):
    with pytest.raises(ValueError): await run(boundary, 'list_course_lectures', args)
    assert not any(request.url.path.endswith('/lectures') for request in boundary.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['default_off', 'timeout', 'unexpected202', 'wrong_receipt', 'readback_failed'])
async def test_management_uncertainty_preserves_receipt_without_retry(boundary, phase):
    boundary.blob['allow_management_writes'] = phase != 'default_off'
    path = '/v2/products/courses/41/enrollments/42'
    if phase == 'timeout': boundary.responses[('PUT', path)] = httpx.ReadTimeout(TOKEN + ' private diagnostic')
    if phase == 'unexpected202': boundary.responses[('PUT', path)] = 202
    if phase == 'wrong_receipt': boundary.responses[('PUT', path)] = lambda raw: {'data': {**raw['data'], 'user': {'id': 99}}}
    if phase == 'readback_failed': boundary.responses[('GET', path)] = 500
    if phase == 'default_off':
        with pytest.raises(native.TeachableDenied): await run(boundary, 'enroll_user', OPERATIONS['enroll_user'])
        assert boundary.requests == []
    else:
        output = await run(boundary, 'enroll_user', OPERATIONS['enroll_user'])
        assert output['status'] == 'unknown' and output['data']['readback_verified'] is False
        assert output['data']['billing_effect_verified'] is None
        assert sum(request.method == 'PUT' for request in boundary.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['no_expiry', 'fresh', 'expired_no_refresh', 'expired_saved_refresh', 'wrong_user', 'v1'])
async def test_actual_user_grant_version_subject_and_refresh_seams(boundary, phase, caplog):
    boundary.row['credential_type'] = native.TYPES[1]; boundary.blob = oauth()
    if phase == 'fresh': boundary.blob['expires_at'] = '2099-01-01T00:00:00Z'
    if phase.startswith('expired'): boundary.blob['expires_at'] = '2020-01-01T00:00:00Z'
    if phase == 'expired_saved_refresh': boundary.blob.update(refresh_token='synthetic-refresh', client_id='synthetic-client', client_secret=SECRET)
    if phase == 'wrong_user': boundary.blob['expected_user_id'] = '99'
    if phase == 'v1': boundary.blob['api_version'] = 'v1'
    if phase in ('expired_no_refresh', 'wrong_user', 'v1'):
        with pytest.raises(ValueError): await run(boundary, 'list_my_courses')
        assert not any(request.url.path.endswith('/products/courses') for request in boundary.requests)
    else:
        output = await run(boundary, 'list_my_courses'); assert output['data']['items'][0]['id'] == '41'
        assert boundary.persists == (phase == 'expired_saved_refresh')
        assert sum(request.url.path == native.TOKEN_PATH for request in boundary.requests) == (phase == 'expired_saved_refresh')
    assert all(secret not in caplog.text for secret in (TOKEN, SECRET, 'synthetic-refreshed-token', 'synthetic-rotated-refresh'))


@pytest.mark.asyncio
async def test_cursor_matches_actual_page_and_rejects_changed_parent_or_policy(boundary):
    boundary.responses[('GET', '/v2/products/courses/41/lectures')] = lambda raw: {**raw, 'meta': {**raw['meta'], 'total_count': 2, 'total_pages': 2}}
    first = await run(boundary, 'list_course_lectures', {'course_id': '41', 'limit': 1})
    token = first['data']['next_page_token']
    second = await run(boundary, 'list_course_lectures', {'course_id': '41', 'limit': 1, 'page_token': token})
    assert second['data']['has_more'] is False
    boundary.blob['allow_management_writes'] = True
    before = len(boundary.requests)
    with pytest.raises(ValueError): await run(boundary, 'list_course_lectures', {'course_id': '41', 'limit': 1, 'page_token': token})
    assert not any(request.url.path.endswith('/lectures') for request in boundary.requests[before:])


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'data': []}, {'data': [{'id': 41, 'name': TOKEN, 'is_published': True}], 'meta': {'page': 1, 'per_page': 1, 'total_count': 1, 'total_pages': 1}}, b'{"data":NaN}', {'data': [{'id': 99, 'name': 'Other', 'is_published': True}]}])
async def test_malformed_parent_paging_and_echoed_secret_refused(boundary, payload):
    boundary.blob.pop('expected_course_id')
    boundary.responses[('GET', '/v2/products/courses')] = payload
    with pytest.raises(ValueError): await run(boundary, "list_courses", {"limit": 1})


@pytest.mark.asyncio
async def test_public_dns_guard_still_rejects_private_resolution(boundary, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]))
    monkeypatch.setattr(ssrf, 'allow_private_hosts', lambda: False)
    with pytest.raises(ValueError): await run(boundary)
    assert boundary.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['timeout', 'malformed_mint'])
async def test_real_refresh_failure_never_persists_or_uses_unverified_mint(boundary, phase, caplog):
    boundary.row['credential_type'] = native.TYPES[1]
    boundary.blob = oauth(expires_at='2020-01-01T00:00:00Z', refresh_token='synthetic-refresh', client_id='synthetic-client', client_secret=SECRET)
    if phase == 'timeout': boundary.responses[('POST', native.TOKEN_PATH)] = httpx.ReadTimeout(TOKEN + SECRET)
    if phase == 'malformed_mint': boundary.responses[('POST', native.TOKEN_PATH)] = {'access_token': 'synthetic-refreshed-token', 'token_type': 'bearer'}
    with pytest.raises(ValueError): await run(boundary, 'get_current_user')
    assert boundary.persists == 0 and sum(request.url.path == native.TOKEN_PATH for request in boundary.requests) == 1
    assert not any(request.url.path == '/v2/current_user/me' for request in boundary.requests)
    assert all(secret not in caplog.text for secret in (TOKEN, SECRET, 'synthetic-refreshed-token'))


@pytest.mark.asyncio
@pytest.mark.parametrize('family,operation', [(native.TYPES[0], 'get_current_user'), (native.TYPES[1], 'list_users')])
async def test_native_auth_families_are_not_interchangeable(boundary, family, operation):
    boundary.row['credential_type'] = family; boundary.blob = deepcopy(BASE) if family == native.TYPES[0] else oauth()
    with pytest.raises(native.TeachableDenied): await run(boundary, operation)
    assert boundary.requests == []


@pytest.mark.asyncio
async def test_delete204_and_actual404_readback_preserve_absence_without_billing_claim(boundary):
    boundary.blob['allow_management_writes'] = True
    path = '/v2/products/courses/41/enrollments/42'
    boundary.responses[('GET', path)] = 404
    output = await run(boundary, 'unenroll_user', OPERATIONS['unenroll_user'])
    assert output['data']['active_enrollment_absent'] is True and output['data']['receipt_id'] is None
    assert output['data']['billing_effect_verified'] is None
    assert sum(request.method == 'DELETE' for request in boundary.requests) == 1


@pytest.mark.asyncio
async def test_empty_protected_list_collector_has_no_account_sample(boundary):
    boundary.blob.pop('expected_course_id')
    boundary.responses[('GET', '/v2/products/courses')] = {'data': [], 'meta': {'page': 1, 'per_page': 1, 'total_count': 0, 'total_pages': 0}}
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, organization_id=ORG, pool=boundary)
    assert evidence.reachable is True and native.TeachableNode.connection_evidence.proves == 'reachability'
    assert evidence.account_label is None and evidence.samples == []


@pytest.mark.asyncio
async def test_validation_without_row_context_never_consumes_expired_refresh_grant(boundary):
    grant = oauth(expires_at='2020-01-01T00:00:00Z', refresh_token='synthetic-refresh', client_id='synthetic-client', client_secret=SECRET)
    result = await native.TeachableNode.validate_credential_access(grant)
    assert result['valid'] is None
    with pytest.raises(native.TeachableDenied):
        await native.TeachableNode.freshen_credential(grant)
    assert boundary.requests == [] and boundary.persists == 0

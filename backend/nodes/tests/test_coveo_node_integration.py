"""Coveo factory, transport, parser, picker and evidence regression fixtures.

Only DB/crypto, DNS, HTTP and socket output boundaries are synthetic.
"""
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
from nodes import coveo_node as native
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
OTHER = '00000000-0000-0000-0000-000000000004'
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN = 'synthetic-coveo-api-key'
NODE = 'automation-coveo'
BASE = {'credential_type': 'coveo_api_key', 'api_key': TOKEN, 'organization_id': 'syntheticorg', 'region': 'eu'}
ADMIN = '/rest/organizations/syntheticorg'
SOURCE = {'id': 'source1', 'name': 'Synthetic source', 'sourceType': 'PUSH', 'pushEnabled': True,
          'information': {'sourceStatus': {'type': 'PUSH_READY'}}, 'configuration': {'password': 'private-provider-value'}, 'owner': 'private@example.invalid'}
FIELD = {'name': 'author', 'type': 'STRING', 'facet': True}

class Boundary:
    def __init__(self):
        self.blob = deepcopy(BASE)
        self.row = {'credential_type': BASE['credential_type'], 'owner_id': USER, 'token_version': 7, 'updated_at': STAMP, 'revoked_at': None, 'credential': 'synthetic-cipher', 'approval_revision': 1, 'name': 'Synthetic Coveo', 'approval_operations': []}
        self.allowed = True; self.missing = False; self.pending = None; self.saved_error = False
        self.loads = self.decrypts = self.admissions = 0; self.requests = []; self.sent = []; self.responses = {}; self.after_http = None
        self.grants = [{'owner': 'SEARCH_API', 'targetDomain': 'EXECUTE_QUERY', 'type': 'ENABLE', 'targetId': '*'}]
        self.source = deepcopy(SOURCE); self.page = None; self.search = None
    @asynccontextmanager
    async def acquire(self): yield self
    @asynccontextmanager
    async def transaction(self): yield self
    async def fetchrow(self, sql, *args):
        if sql.strip() == PRIMARY_ORG_SQL.strip():
            assert args == (USER,); return {'organization_id': ORG}
        if 'SELECT name,owner_id,approval_operations' in sql:
            assert args == (CID,); self.admissions += 1; return None if self.missing else deepcopy(self.row)
        if 'SELECT id,status,consumed_at,expires_at FROM approval_requests' in sql:
            assert args[0] == CID
            return {'id': OTHER, 'status': self.pending, 'consumed_at': None, 'expires_at': STAMP} if self.pending else None
        if 'FROM credentials c' in sql:
            assert credential_access_predicate() in sql
            assert tuple(str(value) if value is not None else None for value in args[:3]) == (CID, USER, ORG)
            if len(args) == 6:
                assert args[3:] == (USER, True, None) and 'workflow_authorized_credentials' in sql
                if self.saved_error: raise RuntimeError('Synthetic storage unavailable')
            self.loads += 1; return deepcopy(self.row) if self.allowed and not self.missing else None
        raise AssertionError('Unexpected actual native SQL')
    async def fetchval(self, sql, *args): raise AssertionError('Unexpected DB scalar')
    async def execute(self, sql, *args): raise AssertionError('No token mint/storage writes')
    def decrypt_credential(self, value):
        assert value == 'synthetic-cipher'; self.decrypts += 1; return deepcopy(self.blob)
    async def get_session(self, sid): return {'user_id': USER}
    def wire(self, request):
        self.requests.append(request)
        path, method = request.url.path, request.method
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        assert TOKEN not in str(request.url) and 'accessToken' not in request.url.params
        assert request.url.host == ({'search': 'syntheticorg.org.coveo.com', 'admin': 'syntheticorg.admin.org.coveo.com', 'push': 'api-eu.cloud.coveo.com'}['push' if path.startswith('/push/') else 'search' if path == '/rest/search/v2' else 'admin'])
        body = json.loads(request.content) if request.content else None
        if path == ADMIN: payload = {'id': 'syntheticorg', 'displayName': 'Synthetic Organization', 'owner': {'email': 'private@example.invalid'}}
        elif path == ADMIN + '/privileges/token': payload = self.grants
        elif path == '/rest/search/v2':
            assert method == 'POST' and body['enableQuerySyntax'] is False and body['debug'] is False
            assert not set(body).intersection({'viewAllContent', 'impersonate', 'userIds', 'aq', 'cq', 'token', 'context'})
            if 'facets' in body:
                payload = {'results': [], 'totalCount': 1, 'facets': [{'facetId': 'noclick-facet', 'field': 'author', 'moreValuesAvailable': False, 'values': [{'value': 'Synthetic Author', 'state': 'idle', 'numberOfResults': 1}]}]}
            else:
                payload = self.search or {'results': [{'uniqueId': 'uri$https://private.invalid/file?secret=withheld', 'title': 'Synthetic Document', 'excerpt': 'Synthetic excerpt', 'raw': {'password': 'withheld'}}] if body['numberOfResults'] else [], 'totalCount': 1}
        elif path == ADMIN + '/sources/pages': payload = self.page or {'sourceModels': [deepcopy(self.source)], 'totalEntries': 1, 'totalPages': 1}
        elif path == ADMIN + '/indexes/fields/search':
            assert method == 'POST' and set(body) == {'page', 'perPage', 'sortBy', 'order', 'filters'}
            payload = {'items': [FIELD], 'totalEntries': 1, 'totalPages': 1}
        elif path == ADMIN + '/indexes/fields/author': payload = FIELD
        elif path == ADMIN + '/sources/source1': payload = deepcopy(self.source)
        elif path == ADMIN + '/sources/source1/itemTypes': payload = ['Document']
        elif path == ADMIN + '/sources/source1/schedules': payload = [{'id': 'schedule1', 'organizationId': 'syntheticorg', 'resourceId': 'source1', 'scheduleType': 'SOURCE', 'enabled': True, 'refreshType': 'INCREMENTAL_REFRESH'}]
        elif path.rsplit('/', 1)[-1] in native.LIFECYCLE.values():
            assert method == 'POST' and not body
            self.source['information']['sourceStatus']['type'] = 'REFRESHING'; payload = deepcopy(self.source)
        elif path == '/push/v1/organizations/syntheticorg/sources/source1/status':
            assert method == 'POST' and request.url.params['statusType'] == 'REFRESH' and not body
            payload = None
        else: raise AssertionError('Unexpected native endpoint')
        override = self.responses.get((method, path))
        if isinstance(override, Exception): raise override
        if isinstance(override, int): return httpx.Response(override, json={'error': TOKEN}, request=request)
        if isinstance(override, bytes): return httpx.Response(200, content=override, headers={'content-type': 'application/json'}, request=request)
        if override is not None: payload = deepcopy(override)
        if self.after_http: self.after_http(method, path)
        if payload is None: return httpx.Response(201, content=b'', request=request)
        return httpx.Response(200, json=payload, request=request)

@pytest_asyncio.fixture
async def boundary(monkeypatch):
    value = Boundary()
    monkeypatch.setattr(credentials, 'get_encryption', lambda: value)
    monkeypatch.setattr(encryption, 'get_encryption', lambda: value)
    monkeypatch.setattr(credentials_handler, 'get_encryption', lambda: value)
    original = ssrf.guarded_async_client
    @asynccontextmanager
    async def transport(**kwargs):
        assert kwargs['require_public'] is True and kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with original(transport=httpx.MockTransport(value.wire), **kwargs) as client: yield client
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]))
    monkeypatch.setattr(native, 'guarded_async_client', transport)
    monkeypatch.setattr(credentials_handler, 'send_event', AsyncMock(side_effect=lambda sio, sid, event: value.sent.append(event)))
    monkeypatch.setattr(workflow_handler, 'send_event', AsyncMock(side_effect=lambda sio, sid, event: value.sent.append(event)))
    return value

async def run(boundary, operation='test_connection', args=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)

OPERATIONS = {'test_connection': {}, 'get_organization': {}, 'list_sources': {}, 'get_source': {'source_id': 'source1'}, 'list_source_item_types': {'source_id': 'source1'}, 'list_source_schedules': {'source_id': 'source1'}, 'list_fields': {}, 'get_field': {'field_id': 'author'}, 'search': {'query': 'synthetic'}, 'query_facets': {'field_id': 'author'}, **{op: {'source_id': 'source1', 'management_confirmed': True} for op in native.LIFECYCLE}, 'set_push_source_status': {'source_id': 'source1', 'management_confirmed': True, 'status_type': 'REFRESH'}}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_actual_16_factory_actions_and_bound_readbacks(boundary, operation):
    boundary.blob.update(allow_management_writes=True)
    result = await run(boundary, operation, OPERATIONS[operation])
    assert NODE_REGISTRY[NODE] is native.CoveoNode and result['action'] == operation
    assert boundary.admissions >= 1 and boundary.loads >= 1
    for private in (TOKEN, 'private.invalid', 'secret=', 'private@example.invalid', 'private-provider-value'): assert private not in json.dumps(result)
    if operation in native.LIFECYCLE or operation == 'set_push_source_status':
        assert result['data']['request_accepted'] is True and result['data']['readback_verified'] is True
        assert result['data']['job_completion_verified'] is None
    if operation == 'test_connection': assert result['data']['account_identity_verified'] is False and result['data']['subject_identity_verified'] is None

@pytest.mark.asyncio
async def test_actual_saved_carrier_socket_picker_and_honest_evidence(boundary):
    saved = await native.CoveoNode.freshen_credential(BASE, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)
    assert saved['credential_type'] == 'coveo_api_key' and saved['api_key'] == TOKEN
    parsed = native.CoveoNode.parse_config({'credentials': saved, 'config': {'operation': 'list_sources'}})
    assert parsed.credentials.organization_id == 'syntheticorg'
    options = await run_node_lookup(node_type=NODE, field_name='source_id', credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG, context={})
    assert options['options'][0]['value'] == 'source1' and options['options'][0]['metadata']['organization_id'] == 'syntheticorg'
    handler = workflow_handler.WorkflowHandler(boundary); handler.get_pool = AsyncMock(return_value=boundary)
    await handler.load_node_options('synthetic-session', WorkflowNodeLoadOptionsRequest(request_id='synthetic-picker', node_type=NODE, field_name='field_id', credential_id=CID))
    assert boundary.sent[-1].data['success'] is True and boundary.sent[-1].data['options'][0]['value'] == 'author'
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)
    assert evidence.reachable is True and evidence.proves == 'reachability' and not evidence.account_label and not evidence.samples

@pytest.mark.asyncio
@pytest.mark.parametrize('domain', ['VIEW_ALL_CONTENT', 'IMPERSONATE_SEARCH_API', 'VIEW_ALL', 'IMPERSONATE'])
async def test_actual_current_privileges_refuse_bypass_before_query(boundary, domain):
    boundary.grants.append({'owner': 'SEARCH_API', 'targetDomain': domain})
    with pytest.raises(native.CoveoDenied): await run(boundary, 'search')
    assert len(boundary.requests) == 1 and boundary.requests[0].url.path.endswith('/privileges/token')

@pytest.mark.asyncio
async def test_actual_continuation_filter_scope_and_offset_rebuild(boundary):
    boundary.search = {'results': [{'uniqueId': 'opaque-1', 'title': 'one'}], 'totalCount': 3}
    first = await run(boundary, 'search', {'query': 'one', 'per_page': 1})
    token = first['data']['next_page_token']
    assert token and TOKEN not in token
    await run(boundary, 'search', {'query': 'one', 'per_page': 1, 'page_token': token})
    assert json.loads(boundary.requests[-1].content)['firstResult'] == 1
    with pytest.raises(ValueError): await run(boundary, 'search', {'query': 'changed', 'per_page': 1, 'page_token': token})
    boundary.blob['region'] = 'ca'
    with pytest.raises(ValueError): native._ticket(native._credential(boundary.blob), None, 'wrong-scope', token=token)

@pytest.mark.asyncio
@pytest.mark.parametrize('malformed', [{'sourceModels': [], 'totalEntries': 2, 'totalPages': 2}, {'sourceModels': [SOURCE, SOURCE], 'totalEntries': 2, 'totalPages': 1}, {'sourceModels': [SOURCE], 'totalEntries': True, 'totalPages': 1}])
async def test_actual_list_rejects_incoherent_page_metadata(boundary, malformed):
    boundary.page = malformed
    with pytest.raises(native.CoveoUnavailable): await run(boundary, 'list_sources')

@pytest.mark.asyncio
async def test_actual_parent_bindings_and_management_content_off_defaults(boundary):
    with pytest.raises(native.CoveoDenied): await run(boundary, 'full_refresh_source', {'source_id': 'source1', 'management_confirmed': True})
    with pytest.raises(native.CoveoDenied): await run(boundary, 'search', {'include_excerpt': True})
    assert not boundary.requests
    boundary.responses[('GET', ADMIN + '/sources/source1')] = {**SOURCE, 'id': 'foreign'}
    with pytest.raises(native.CoveoDenied): await run(boundary, 'list_source_schedules', {'source_id': 'source1'})
    assert len(boundary.requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [500, b'{bad', httpx.ReadTimeout('synthetic private details')])
async def test_actual_possible_write_stays_unknown_without_retry(boundary, failure):
    boundary.blob['allow_management_writes'] = True
    boundary.responses[('POST', ADMIN + '/sources/source1/rebuild')] = failure
    result = await run(boundary, 'rebuild_source', {'source_id': 'source1', 'management_confirmed': True})
    assert result['status'] == 'unknown' and result['data']['retry_safe'] is False and result['data']['job_completion_verified'] is None
    assert sum(row.method == 'POST' for row in boundary.requests) == 1

def test_actual_typed_parse_rejects_foreign_family_raw_flags_and_nonboolean_confirmation():
    for config in ({'operation': 'search', 'viewAllContent': True}, {'operation': 'search', 'userIds': ['someone']}, {'operation': 'rebuild_source', 'source_id': 'source1', 'management_confirmed': 1}):
        with pytest.raises(ValueError): native.CoveoNode.parse_config({'credentials': BASE, 'config': config})
    with pytest.raises(ValueError): native.CoveoNode.parse_config({'credentials': {**BASE, 'credential_type': 'bearer_token'}, 'config': {'operation': 'search'}})
    with pytest.raises(ValueError): native.CoveoNode.parse_config({'credentials': {**BASE, 'organization_id': 'https://private.invalid'}, 'config': {'operation': 'search'}})

def test_actual_typed_parse_preserves_default_hub_and_refuses_empty_or_control_text():
    assert native.CoveoNode.parse_config({'credentials': BASE, 'config': {'operation': 'search'}}).credentials.search_hub == 'NoClick'
    assert native.CoveoNode.parse_config({'credentials': {**BASE, 'search_hub': 'RestrictedHub'}, 'config': {'operation': 'search'}}).credentials.search_hub == 'RestrictedHub'
    for hub in ('', '\n', 'NoClick\x00', 'hub\x7f'):
        with pytest.raises(ValueError):
            native.CoveoNode.parse_config({'credentials': {**BASE, 'search_hub': hub}, 'config': {'operation': 'search'}})

@pytest.mark.asyncio
async def test_optional_actual_organization_probe_proves_only_returned_account(boundary):
    boundary.blob['connection_probe'] = 'organization'
    result = await run(boundary)
    assert result['data']['organization_id'] == 'syntheticorg' and result['data']['organization_name'] == 'Synthetic Organization'
    assert result['data']['account_identity_verified'] is True and result['data']['subject_identity_verified'] is None
    boundary.responses[('GET', ADMIN)] = {'id': 'differentorg', 'displayName': 'Foreign'}
    with pytest.raises(native.CoveoDenied): await run(boundary)

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'results': [], 'totalCount': 0, 'errors': ['synthetic private error']}, {'results': [], 'totalCount': 0, 'exception': {'code': 'synthetic-private'}}, {'results': [], 'totalCount': True}])
async def test_http_200_query_errors_and_malformed_counts_stay_unverified(boundary, body):
    boundary.responses[('POST', '/rest/search/v2')] = body
    with pytest.raises(native.CoveoUnavailable): await run(boundary)

@pytest.mark.asyncio
async def test_actual_dns_private_address_refuses_before_http(boundary, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]))
    with pytest.raises(native.CoveoUnavailable): await run(boundary)
    assert boundary.requests == []

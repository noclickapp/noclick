"""Native factory/current-row/admission/socket/transport fixtures.

Only DB/crypto, DNS, provider HTTP and socket output boundaries are synthetic.
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
from nodes import humanitec_node as native
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
TOKEN = 'synthetic-humanitec-service-token'
NODE = 'automation-humanitec'
BASE = {'credential_type': 'humanitec_service_token', 'service_token': TOKEN, 'organization_id': 'syntheticorg'}
ROOT = '/orgs/syntheticorg'
APP_PATH = ROOT + '/apps/sample-app'
ENV_PATH = APP_PATH + '/envs/development'
PIPE_PATH = APP_PATH + '/pipelines/metadata-pipeline'
APP = {'id': 'sample-app', 'org_id': 'syntheticorg', 'name': 'Synthetic App', 'status': 'active', 'envs': [{'id': 'development', 'name': 'Development', 'type': 'development'}], 'created_by': 'private@example.invalid'}
ENV = {'id': 'development', 'name': 'Development', 'type': 'development', 'status': 'active', 'last_deploy': {'export_file': 'https://private.invalid?secret=withheld'}}
DEPLOY = {'id': 'deploy1', 'env_id': 'development', 'status': 'succeeded', 'export_file': 'https://private.invalid?secret=withheld', 'created_by': 'private@example.invalid'}
PIPE = {'id': 'metadata-pipeline', 'org_id': 'syntheticorg', 'app_id': 'sample-app', 'name': 'Synthetic Pipeline', 'version': 'version1', 'status': 'active', 'trigger_types': ['pipeline_call'], 'metadata': {'private': TOKEN}}
RUN = {'id': 'run1', 'org_id': 'syntheticorg', 'app_id': 'sample-app', 'pipeline_id': 'metadata-pipeline', 'pipeline_version': 'version1', 'env_ids': ['development'], 'status': 'successful', 'inputs': {'secret': TOKEN}, 'status_message': 'private-provider-value', 'run_as': 'private@example.invalid'}

class Boundary:
    def __init__(self):
        self.blob = deepcopy(BASE)
        self.row = {'credential_type': BASE['credential_type'], 'owner_id': USER, 'token_version': 7, 'updated_at': STAMP, 'revoked_at': None, 'credential': 'synthetic-cipher', 'approval_revision': 1, 'name': 'Synthetic Humanitec', 'approval_operations': [], 'id': CID, 'metadata': {}, 'created_at': STAMP}
        self.allowed = True; self.missing = False; self.pending = None; self.saved_error = False
        self.loads = self.decrypts = self.admissions = 0; self.requests = []; self.sent = []; self.responses = {}; self.links = {}; self.after_http = None
        self.app = deepcopy(APP); self.env = deepcopy(ENV); self.apps = None; self.pipeline_pages = None
        self.created = {}
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
            if self.saved_error: raise RuntimeError('Synthetic storage unavailable')
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
        assert request.url.host == 'api.humanitec.io' and request.url.scheme == 'https'
        assert request.headers['authorization'] == 'Bearer ' + TOKEN and TOKEN not in str(request.url)
        body = json.loads(request.content) if request.content else None
        assert not any(part in path for part in ('/values', '/secrets', '/resources', '/keys', '/users', '/logs'))
        assert not (method != 'GET' and ('/deploys' in path or '/pipelines' in path))
        if path == ROOT: payload = {'id': 'syntheticorg', 'name': 'Synthetic Organization', 'created_by': 'private@example.invalid', 'scaffolding_url': 'https://private.invalid?secret=withheld'}
        elif path == ROOT + '/apps' and method == 'POST':
            assert set(body) == {'id', 'name', 'skip_environment_creation'} and body['skip_environment_creation'] is True
            self.created[body['id']] = {'id': body['id'], 'name': body['name'], 'org_id': 'syntheticorg', 'status': 'active', 'envs': []}
            payload = self.created[body['id']]
        elif path == ROOT + '/apps': payload = self.apps if self.apps is not None else [self.app]
        elif path == ROOT + '/env-types': payload = [{'id': 'development', 'description': 'Synthetic environment type'}]
        elif path == APP_PATH:
            if method == 'PATCH': assert set(body) == {'name'}; self.app['name'] = body['name']
            payload = self.app
        elif path.startswith(ROOT + '/apps/') and path.rsplit('/', 1)[-1] in self.created: payload = self.created[path.rsplit('/', 1)[-1]]
        elif path == APP_PATH + '/envs': payload = [self.env]
        elif path == ENV_PATH:
            if method == 'PATCH': assert set(body) == {'name'}; self.env['name'] = body['name']
            payload = self.env
        elif path == ENV_PATH + '/deploys': payload = [DEPLOY]
        elif path == ENV_PATH + '/deploys/deploy1': payload = DEPLOY
        elif path == APP_PATH + '/pipelines':
            assert request.url.params['per_page'] in ('1', '25', '100')
            payload = [PIPE] if self.pipeline_pages is None else self.pipeline_pages[request.url.params.get('page', '')]
        elif path == PIPE_PATH: payload = PIPE
        elif path == PIPE_PATH + '/runs': payload = [RUN]
        elif path == PIPE_PATH + '/runs/run1': payload = RUN
        else: raise AssertionError('Unexpected native endpoint')
        override = self.responses.get((method, path))
        if isinstance(override, Exception): raise override
        if isinstance(override, int): return httpx.Response(override, json={'error': TOKEN}, request=request)
        if isinstance(override, bytes): return httpx.Response(201 if method == 'POST' else 200, content=override, headers={'content-type': 'application/json'}, request=request)
        if override is not None: payload = deepcopy(override)
        if self.after_http: self.after_http(method, path)
        headers = {'link': self.links[(method, path)]} if (method, path) in self.links else {}
        return httpx.Response(201 if method == 'POST' else 200, json=payload, headers=headers, request=request)

@pytest_asyncio.fixture
async def boundary(monkeypatch):
    value = Boundary()
    monkeypatch.setattr(credentials, 'get_encryption', lambda: value)
    monkeypatch.setattr(encryption, 'get_encryption', lambda: value)
    monkeypatch.setattr(credentials_handler, 'get_encryption', lambda: value)
    monkeypatch.setattr(workflow_handler, 'get_encryption', lambda: value)
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
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)

OPERATIONS = {'test_connection': {}, 'get_organization': {}, 'list_applications': {}, 'get_application': {'app_id': 'sample-app'}, 'list_environment_types': {}, 'list_environments': {'app_id': 'sample-app'}, 'get_environment': {'app_id': 'sample-app', 'environment_id': 'development'}, 'list_deployments': {'app_id': 'sample-app', 'environment_id': 'development'}, 'get_deployment': {'app_id': 'sample-app', 'environment_id': 'development', 'deployment_id': 'deploy1'}, 'list_pipelines': {'app_id': 'sample-app'}, 'get_pipeline': {'app_id': 'sample-app', 'pipeline_id': 'metadata-pipeline'}, 'list_pipeline_runs': {'app_id': 'sample-app', 'pipeline_id': 'metadata-pipeline'}, 'get_pipeline_run': {'app_id': 'sample-app', 'pipeline_id': 'metadata-pipeline', 'run_id': 'run1'}, 'create_application': {'app_id': 'new-app', 'name': 'Synthetic New App', 'metadata_confirmed': True}, 'rename_application': {'app_id': 'sample-app', 'name': 'Synthetic Renamed App', 'expected_name': 'Synthetic App', 'metadata_confirmed': True}, 'rename_environment': {'app_id': 'sample-app', 'environment_id': 'development', 'name': 'Synthetic Renamed Environment', 'expected_name': 'Development', 'metadata_confirmed': True}}

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_actual_16_factory_actions_and_bound_readbacks(boundary, operation):
    boundary.blob['allow_metadata_writes'] = True
    result = await run(boundary, operation, OPERATIONS[operation])
    assert NODE_REGISTRY[NODE] is native.HumanitecNode and result['action'] == operation
    assert boundary.admissions >= 1 and boundary.loads > 1
    for private in (TOKEN, 'private.invalid', 'secret=', 'private@example.invalid', 'private-provider-value'): assert private not in json.dumps(result)
    if operation in native.WRITES:
        assert result['data']['request_accepted'] is True and result['data']['readback_verified'] is True
        assert result['data']['concurrency_verified'] is None and result['data']['automation_effects_verified'] is None
    if operation == 'create_application': assert result['data']['resource']['environments'] == [] and result['data']['cleanup_available_in_node'] is False
    if operation == 'test_connection': assert result['data']['account_identity_verified'] is True and result['data']['subject_identity_verified'] is None and result['data']['paid_entitlement_verified'] is None

@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['foreign', 'missing', 'revoked', 'denied'])
async def test_actual_saved_row_refuses_before_crypto_and_transport(boundary, state):
    if state == 'foreign': boundary.row['credential_type'] = 'bearer_token'
    if state == 'missing': boundary.missing = True
    if state == 'revoked': boundary.row['revoked_at'] = STAMP
    if state == 'denied': boundary.allowed = False
    with pytest.raises(ValueError): await run(boundary)
    # Staging resolves/decrypts before the node's own family check.
    assert boundary.requests == []
    if state != 'foreign': assert boundary.decrypts == 0

@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'rejected'])
async def test_actual_admission_blocks_probe_and_picker(boundary, status):
    boundary.row.update(owner_id=OTHER, approval_operations=['automation-humanitec.test_connection', 'automation-humanitec.list_applications']); boundary.pending = status
    assert (await run(boundary))['status'] in ('pending_approval', 'rejected')
    result = await run_node_lookup(node_type=NODE, field_name='app_id', credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG, context={})
    assert result['status'] in ('pending_approval', 'rejected') and boundary.requests == []

@pytest.mark.asyncio
async def test_real_saved_carrier_socket_picker_and_empty_account_evidence(boundary):
    saved = await native.HumanitecNode._freshen_for_execution(BASE, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)
    assert saved['token_version'] == 7
    assert native.HumanitecNode.parse_config({'credentials': saved, 'config': {'operation': 'list_applications'}}).credentials.organization_id == 'syntheticorg'
    handler = workflow_handler.WorkflowHandler(boundary); handler.get_pool = AsyncMock(return_value=boundary)
    await handler.load_node_options('synthetic-session', WorkflowNodeLoadOptionsRequest(request_id='synthetic-picker', node_type=NODE, field_name='app_id', credential_id=CID))
    assert boundary.sent[-1].data['success'] is True and boundary.sent[-1].data['options'][0]['value'] == 'sample-app'
    options = await run_node_lookup(node_type=NODE, field_name='environment_id', credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG, context={'app_id': 'sample-app'})
    assert options['options'][0]['value'] == 'development' and options['options'][0]['metadata']['app_id'] == 'sample-app'
    boundary.apps = []
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=boundary, organization_id=ORG)
    assert evidence.reachable is True and native.HumanitecNode.connection_evidence.proves == 'account' and evidence.account_label == 'Synthetic Organization'

@pytest.mark.asyncio
@pytest.mark.parametrize('response,valid', [(401, False), (403, False), (302, None), (404, None), (429, None), (500, None), (b'{bad', None), ({'id': 'syntheticorg'}, None), ({'error': TOKEN, 'message': 'private-provider-value'}, None)])
async def test_actual_validator_denied_unknown_and_error_privacy(boundary, response, valid, caplog):
    boundary.responses[('GET', ROOT)] = response
    handler = credentials_handler.CredentialsHandler(boundary); handler.get_pool = AsyncMock(return_value=boundary)
    await handler.validate_access('synthetic-session', CredentialValidateAccessRequest(request_id='synthetic-validator', credential_id=CID, node_type=NODE))
    assert boundary.sent[-1].data['valid'] is valid and TOKEN not in json.dumps(boundary.sent[-1].data) and TOKEN not in caplog.text

@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['owner', 'version', 'key', 'organization', 'policy', 'database'])
async def test_actual_current_authority_changes_refuse_further_reads(boundary, change):
    def after(method, path):
        if change == 'owner': boundary.row['owner_id'] = OTHER
        elif change == 'version': boundary.row['token_version'] += 1
        elif change == 'key': boundary.blob['service_token'] = 'synthetic-other-token'
        elif change == 'organization': boundary.blob['organization_id'] = 'differentorg'
        elif change == 'policy': boundary.blob['allow_metadata_writes'] = True
        else: boundary.saved_error = True
    boundary.after_http = after
    with pytest.raises(ValueError): await run(boundary, 'get_environment', OPERATIONS['get_environment'])
    assert len(boundary.requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('parent', ['organization', 'pipeline', 'environment'])
async def test_actual_foreign_response_parents_are_refused(boundary, parent):
    if parent == 'organization': boundary.responses[('GET', APP_PATH)] = {**APP, 'org_id': 'differentorg'}; operation = 'get_application'
    elif parent == 'pipeline': boundary.responses[('GET', PIPE_PATH + '/runs/run1')] = {**RUN, 'pipeline_id': 'different-pipeline'}; operation = 'get_pipeline_run'
    else: boundary.responses[('GET', ENV_PATH + '/deploys/deploy1')] = {**DEPLOY, 'env_id': 'different-env'}; operation = 'get_deployment'
    with pytest.raises(native.HumanitecDenied): await run(boundary, operation, OPERATIONS[operation])
    assert all(request.method == 'GET' for request in boundary.requests)

@pytest.mark.asyncio
async def test_actual_local_snapshot_and_filter_bound_continuation(boundary):
    boundary.apps = [APP, {**APP, 'id': 'second-app', 'name': 'Second Synthetic App'}]
    first = await run(boundary, 'list_applications', {'per_page': 1})
    token = first['data']['next_page_token']
    second = await run(boundary, 'list_applications', {'per_page': 1, 'page_token': token})
    assert second['data']['items'][0]['id'] == 'second-app'
    assert all(not request.url.params for request in boundary.requests)
    with pytest.raises(ValueError): await run(boundary, 'list_applications', {'per_page': 1, 'page_token': token, 'search': 'changed'})
    boundary.apps.reverse()
    with pytest.raises(ValueError): await run(boundary, 'list_applications', {'per_page': 1, 'page_token': token})

@pytest.mark.asyncio
@pytest.mark.parametrize('link', ['<https://private.invalid/x?page=other>; rel="next"', '<https://api.humanitec.io/orgs/foreign/apps/foreign/pipelines?page=other>; rel="next"', '<https://api.humanitec.io' + APP_PATH + '/pipelines?page=other&per_page=100>; rel="next"', '<https://api.humanitec.io' + APP_PATH + '/pipelines?page=other&credential=private>; rel="next"', 'malformed Link header'])
async def test_actual_provider_link_never_changes_origin_parents_or_filters(boundary, link):
    boundary.links[('GET', APP_PATH + '/pipelines')] = link
    with pytest.raises(native.HumanitecUnavailable): await run(boundary, 'list_pipelines', {'app_id': 'sample-app', 'per_page': 1})
    assert len(boundary.requests) == 2 and all(request.url.host == 'api.humanitec.io' for request in boundary.requests)

@pytest.mark.asyncio
async def test_actual_link_token_is_rebuilt_and_repeated_page_refused(boundary):
    boundary.pipeline_pages = {'': [PIPE], 'next-page': [{**PIPE, 'id': 'other-pipeline'}]}
    boundary.links[('GET', APP_PATH + '/pipelines')] = '<https://api.humanitec.io' + APP_PATH + '/pipelines?per_page=1&page=next-page>; rel="next"'
    first = await run(boundary, 'list_pipelines', {'app_id': 'sample-app', 'per_page': 1})
    token = first['data']['next_page_token']
    boundary.links.clear()
    second = await run(boundary, 'list_pipelines', {'app_id': 'sample-app', 'per_page': 1, 'page_token': token})
    assert second['data']['items'][0]['id'] == 'other-pipeline' and boundary.requests[-1].url.params['page'] == 'next-page'
    boundary.links[('GET', APP_PATH + '/pipelines')] = '<https://api.humanitec.io' + APP_PATH + '/pipelines?per_page=1&page=next-page>; rel="next"'
    with pytest.raises(native.HumanitecUnavailable): await run(boundary, 'list_pipelines', {'app_id': 'sample-app', 'per_page': 1, 'page_token': token})

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [500, b'', httpx.ReadTimeout('synthetic private details')])
async def test_possible_name_write_without_valid_readback_is_unknown_no_retry(boundary, failure):
    boundary.blob['allow_metadata_writes'] = True
    boundary.responses[('PATCH', APP_PATH)] = failure
    result = await run(boundary, 'rename_application', OPERATIONS['rename_application'])
    assert result['status'] == 'unknown' and result['data']['retry_safe'] is False and result['data']['readback_verified'] is None
    assert sum(request.method == 'PATCH' for request in boundary.requests) == 1

@pytest.mark.asyncio
async def test_actual_write_default_and_expected_name_refuse_before_mutation(boundary):
    with pytest.raises(native.HumanitecDenied): await run(boundary, 'rename_application', OPERATIONS['rename_application'])
    assert boundary.requests == []
    boundary.blob['allow_metadata_writes'] = True
    with pytest.raises(native.HumanitecDenied): await run(boundary, 'rename_application', {**OPERATIONS['rename_application'], 'expected_name': 'Wrong old name'})
    assert all(request.method == 'GET' for request in boundary.requests)

@pytest.mark.asyncio
async def test_actual_postwrite_authority_loss_keeps_acceptance_unknown(boundary):
    boundary.blob['allow_metadata_writes'] = True
    def after(method, path):
        if method == 'PATCH': boundary.row['token_version'] += 1
    boundary.after_http = after
    result = await run(boundary, 'rename_application', OPERATIONS['rename_application'])
    assert result['status'] == 'unknown' and result['data']['request_accepted'] is True and result['data']['readback_verified'] is None
    assert sum(request.method == 'PATCH' for request in boundary.requests) == 1

def test_actual_typed_parse_rejects_foreign_auth_secret_fields_and_confirmation_coercion():
    for credential in ({**BASE, 'credential_type': 'bearer_token'}, {**BASE, 'organization_id': 'https://private.invalid'}, {**BASE, 'allow_metadata_writes': 1}, {**BASE, 'refresh_token': 'not-supported'}):
        with pytest.raises(ValueError): native.HumanitecNode.parse_config({'credentials': credential, 'config': {'operation': 'test_connection'}})
    for config in ({**OPERATIONS['create_application'], 'metadata_confirmed': 1}, {**OPERATIONS['create_application'], 'skip_environment_creation': False}, {**OPERATIONS['rename_application'], 'description': 'not-supported'}, {'operation': 'deploy'}):
        with pytest.raises(ValueError): native.HumanitecNode.parse_config({'credentials': BASE, 'config': config})

@pytest.mark.asyncio
async def test_actual_private_dns_address_refuses_before_http(boundary, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]))
    with pytest.raises(native.HumanitecUnavailable): await run(boundary)
    assert boundary.requests == []


@pytest.mark.parametrize('filename,org', [
    ('application-api-example.json', 'sample-org'),
    ('application-operator-example.json', 'my-org'),
])
def test_published_application_responses(filename, org):
    from pathlib import Path
    example = json.loads((Path(__file__).parent / 'fixtures' / 'humanitec' / filename).read_text())
    result = native._application(example['body'], org, 'my-app')
    assert result['id'] == 'my-app'
    assert result['environments'] == [{'id': 'development', 'name': 'Development', 'type': 'development'}]
    assert 'status' not in result and 'status_changed_at' not in result
    with pytest.raises(native.HumanitecDenied):
        native._application({**example['body'], 'org_id': 'foreign-org'}, org, 'my-app')
    with pytest.raises(native.HumanitecUnavailable):
        native._application({**example['body'], 'status': 'made-up'}, org, 'my-app')

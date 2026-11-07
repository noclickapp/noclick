"""Native dbt factory, connect, dispatcher and saved-row regressions.

Provider transport and storage are synthetic; no live API calls are made.
They exercise real consumer seams without treating token shape as proof.
"""
import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from nodes import dbt_cloud_node as provider
from nodes.dbt_cloud_node import DbtCloudNode as Node, OPERATIONS, TAGS, NODE_TYPE, MAX_BYTES
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect as cc, connection_evidence as ce, run_op

TOKEN = 'SyntheticDbtPrivateToken42'
PRIVATE = 'SyntheticWarehousePrivate42'
ACCOUNT = {'id': 1, 'name': 'Fixture Account', 'billing_email': PRIVATE, 'token': TOKEN}
PROJECT = {'id': 2, 'account_id': 1, 'name': 'Fixture Project', 'state': 1, 'repository': {'git_clone_strategy': TOKEN}, 'description': PRIVATE}
ENVIRONMENT = {'id': 3, 'account_id': 1, 'project_id': 2, 'name': 'Fixture Environment', 'state': 1, 'type': 'deployment', 'credentials': {'password': TOKEN}, 'connection': {'database': PRIVATE}}
JOB = {'id': 4, 'account_id': 1, 'project_id': 2, 'environment_id': 3, 'name': 'Fixture Job', 'state': 1, 'execute_steps': [PRIVATE], 'triggers': {'schedule': False}, 'custom_environment_variables': {'secret': TOKEN}}
RUN = {'id': 5, 'account_id': 1, 'project_id': 2, 'environment_id': 3, 'job_definition_id': 4, 'status': 10, 'debug_logs': TOKEN, 'status_message': PRIVATE, 'artifact_s3_path': PRIVATE, 'href': TOKEN}
RESOURCES = {'projects': PROJECT, 'environments': ENVIRONMENT, 'jobs': JOB, 'runs': RUN}


def credential(tag=TAGS[0]):
    return {'credential_type': tag, 'access_token': TOKEN, 'account_id': '1', 'deployment': 'cell', 'region': 'us1', 'account_prefix': 'fixture-account', 'project_ids': ['2'], 'allowed_operations': list(OPERATIONS)}


def arguments(op):
    result = {} if op in ('check_connection', 'list_accounts') else {'account_id': '1'}
    if op not in ('check_connection', 'list_accounts', 'get_account', 'list_projects'): result['project_id'] = '2'
    if op not in ('check_connection', 'list_accounts', 'get_account', 'list_projects', 'get_project', 'list_environments'): result['environment_id'] = '3'
    if op in ('get_job', 'list_runs', 'get_run', 'get_run_status', 'list_run_artifacts', 'get_run_artifact_summary'): result['job_id'] = '4'
    if op in ('get_run', 'get_run_status', 'list_run_artifacts', 'get_run_artifact_summary'): result['run_id'] = '5'
    if op == 'get_run_artifact_summary': result['artifact'] = 'run_results.json'
    return result


def node(op, raw=None, **changes):
    return NodeFactory.create_node(node_id='dbt-fixture', node_type=NODE_TYPE, node_data={'config': {'operation': op, **arguments(op), **changes}, 'credentials': deepcopy(raw or credential())}, sio=None, user_id='fixture-user')


def envelope(data, **extra):
    return {'status': {'code': 200, 'is_success': True, 'user_message': TOKEN, 'developer_message': PRIVATE}, 'data': data, **extra}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest_asyncio.fixture
async def transport(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], override=None, on_request=None, addresses=['93.184.216.34'])
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(side_effect=lambda *a, **k: [(2 if ':' not in ip else 10, 1, 6, '', (ip, 443)) for ip in state.addresses]))

    def response(request):
        state.requests.append(request)
        if state.on_request: state.on_request(request)
        if state.override:
            answer = state.override(request)
            if answer is not None: return answer
        assert request.method == 'GET' and not request.content and request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert request.url.host == 'fixture-account.us1.dbt.com'
        path = request.url.path
        if path == '/api/v2/accounts/1/': return httpx.Response(200, json=envelope(ACCOUNT))
        if path == '/api/v3/accounts/': return httpx.Response(200, json=envelope([ACCOUNT]))
        if '/artifacts/' in path:
            if path.endswith('/artifacts/'): return httpx.Response(200, json=envelope(['manifest.json', 'run_results.json', 'catalog.json', PRIVATE + '.sql']))
            assert path.endswith(('manifest.json', 'run_results.json', 'catalog.json'))
            assert not dict(request.url.params) or dict(request.url.params) == {'step': '2'}
            return httpx.Response(200, json={'metadata': {'dbt_version': '1.12.0', 'env': {'secret': TOKEN}}, 'results': [{'status': 'success', 'compiled_code': PRIVATE, 'message': TOKEN}], 'nodes': {PRIVATE: {'raw_code': TOKEN}}, 'sources': {PRIVATE: {'database': TOKEN}}})
        kind = next(part for part in reversed(path.split('/')) if part in RESOURCES)
        version = 'v3' if kind in ('projects', 'environments') else 'v2'
        assert path.startswith('/api/' + version + '/accounts/1/')
        if kind == 'environments': assert '/projects/2/environments/' in path
        row = deepcopy(RESOURCES[kind])
        if path.endswith('/' + kind + '/'):
            params = dict(request.url.params)
            assert set(params) == {'limit', 'offset'} | ({'project_id', 'environment_id'} if kind in ('jobs', 'runs') else set()) | ({'job_definition_id'} if kind == 'runs' else set())
            return httpx.Response(200, json=envelope([row], extra={'pagination': {'count': 1, 'total_count': 1}}))
        assert path.endswith('/' + str(row['id']) + '/') and not request.url.query
        return httpx.Response(200, json=envelope(row))

    def client(**kwargs):
        assert kwargs == {'timeout': 60, 'follow_redirects': False, 'trust_env': False}
        return ssrf.guarded_async_client(transport=httpx.MockTransport(response), **kwargs)
    monkeypatch.setattr(provider, 'guarded_async_client', client)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('op', OPERATIONS)
async def test_actual_factory_all_operations_private_output_and_get_only(transport, caplog, op):
    result = await node(op).run({})
    assert result['status'] == 'success' and result['action'] == op and result['account_identity_verified'] is False and result['mutation_performed'] is False
    assert TOKEN not in json.dumps(result) + caplog.text and PRIVATE not in json.dumps(result) + caplog.text
    assert all(r.method == 'GET' and not r.content for r in transport.requests)
    assert not any(hazard in str(r.url) for r in transport.requests for hazard in ('/run/', '/retry/', '/cancel/', '/credentials/', '/connections/', '/service-tokens/', '/repositories/'))


@pytest.mark.asyncio
async def test_preparsed_config_credentials_execute_without_raw_duplicate(transport):
    config = provider.DbtCloudFullConfig.model_validate({'config': {'operation': 'check_connection'}, 'credentials': credential()})
    instance = Node(node_id='dbt-parsed', node_type=NODE_TYPE, node_data={}, config=config)
    result = await instance.execute({})
    assert result['status'] == 'success' and result['account_access_verified'] is True
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', [None, {**credential(), 'account_id': '9'}, {**credential(), 'credential_type': 'stripe_api_key'}])
async def test_preparsed_config_rejects_conflicting_raw_credentials(transport, raw):
    config = provider.DbtCloudFullConfig.model_validate({'config': {'operation': 'check_connection'}, 'credentials': credential()})
    instance = Node(node_id='dbt-parsed', node_type=NODE_TYPE, node_data={'credentials': raw}, config=config)
    assert (await instance.execute({}))['status'] == 'error'
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('tag', TAGS)
async def test_actual_manual_shape_connect_and_honest_evidence(transport, monkeypatch, tag):
    monkeypatch.setattr(cc, '_collect_evidence', ce.collect_evidence)
    raw = credential(tag); raw.pop('credential_type')
    shaped, errors, _ = cc.shape_credential(tag, raw)
    assert errors == {} and shaped['credential_type'] == tag
    result = await cc.validate_for_connect(credential_type=tag, credential_data=raw, user_id='fixture-user')
    assert result.ok and result.evidence.reachable is True and Node.connection_evidence.proves == 'reachability'
    assert result.evidence.account_label is None and result.evidence.samples == [] and len(transport.requests) == 1
    assert TOKEN not in json.dumps(asdict(result.evidence)) and 'verified_as' not in result.verified_metadata()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['foreign', 'url', 'prefix', 'region', 'project', 'account', 'operation'])
async def test_authority_rejected_before_request(transport, case):
    raw = credential(); changes = {}
    if case == 'foreign':
        raw['credential_type'] = 'stripe_api_key'
        assert not Node.validate_config({'operation': 'check_connection', 'credentials': raw})['valid']
        assert not (await cc.validate_for_connect(credential_type=TAGS[0], credential_data=raw, user_id='fixture-user')).ok
        with pytest.raises(ValueError): await Node.load_field_options('account_id', raw)
    elif case in ('url', 'prefix', 'region'):
        raw.update({'api_base_url': 'https://example.invalid'} if case == 'url' else {'account_prefix': 'example.invalid'} if case == 'prefix' else {'region': 'unknown'})
        with pytest.raises(ValueError): node('check_connection', raw)
    else:
        if case == 'project': changes['project_id'] = '9'
        if case == 'account': changes['account_id'] = '9'
        if case == 'operation': raw['allowed_operations'] = ['check_connection']
        assert (await node('get_run', raw, **changes).run({}))['status'] == 'error'
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['202', '204', '401', '403', '429', 'redirect', 'text', 'oversize', 'empty', 'false-status', 'wrong-id', 'foreign-parent'])
async def test_documented_status_envelope_and_parent_failures(transport, case):
    def response(request):
        if not request.url.path.endswith('/runs/5/'): return None
        if case.isdigit(): return httpx.Response(int(case), json={'error': TOKEN})
        if case == 'redirect': return httpx.Response(302, headers={'location': 'https://example.invalid/' + TOKEN})
        if case == 'text': return httpx.Response(200, text=PRIVATE)
        if case == 'oversize': return httpx.Response(200, content=b'x' * (MAX_BYTES + 1), headers={'content-type': 'application/json'})
        return httpx.Response(200, json={} if case == 'empty' else {'status': {'is_success': False}, 'data': RUN} if case == 'false-status' else envelope({**RUN, **({'id': 9} if case == 'wrong-id' else {'job_definition_id': 9})}))
    transport.override = response
    result = await node('get_run').run({})
    assert result['status'] == 'error' and TOKEN not in json.dumps(result) and PRIVATE not in json.dumps(result)


@pytest.mark.asyncio
async def test_real_run_op_parent_chain_artifact_projection_and_step(transport):
    result = await run_op.run_node_operation(node_type=NODE_TYPE, operation='get_run_artifact_summary', arguments={**arguments('get_run_artifact_summary'), 'operation': 'run_job', 'step': 2}, credential_data=credential(), user_id='fixture-user')
    assert result['status'] == 'success' and result['summary'] == {'artifact': 'run_results.json', 'raw_artifact_returned': False, 'dbt_version': '1.12.0', 'result_count': 1, 'status_counts': {'success': 1}}
    assert [r.url.path for r in transport.requests] == ['/api/v2/accounts/1/', '/api/v3/accounts/1/projects/2/', '/api/v3/accounts/1/projects/2/environments/3/', '/api/v2/accounts/1/jobs/4/', '/api/v2/accounts/1/runs/5/', '/api/v2/accounts/1/runs/5/artifacts/run_results.json']
    transport.override = lambda r: httpx.Response(200, json=envelope({**RUN, 'status': 3})) if r.url.path.endswith('/runs/5/') else None
    assert (await node('list_run_artifacts').run({}))['status'] == 'error'
    assert not any('/artifacts/' in r.url.path for r in transport.requests[6:])


@pytest.mark.asyncio
async def test_actual_picker_parent_chain_counts_and_offset(transport):
    context = {'account_id': '1', 'project_id': '2', 'environment_id': '3', 'job_id': '4'}
    result = await Node.load_field_options('run_id', credential(), context=context)
    assert result['options'][0]['metadata'] == context and result['next_page_token'] is None
    before = len(transport.requests)
    for bad in ({}, {'account_id': '9'}, {'account_id': '1', 'project_id': '9'}):
        with pytest.raises(ValueError): await Node.load_field_options('run_id', credential(), context=bad)
    assert len(transport.requests) == before
    transport.override = lambda r: httpx.Response(200, json=envelope([PROJECT], extra={'pagination': {'count': 1, 'total_count': 30}})) if r.url.path == '/api/v3/accounts/1/projects/' else None
    result = await Node.load_field_options('project_id', credential(), context={'account_id': '1'})
    assert result['next_page_token'] == '1'
    with pytest.raises(ValueError): await Node.load_field_options('project_id', credential(), context={'account_id': '1'}, page_token='https://example.invalid/next')


@pytest.mark.asyncio
async def test_explicit_publisher_us_host_without_region_fallback(transport):
    raw = credential(); raw.update(deployment='us_multi_tenant', region=None, account_prefix=None)
    def response(request):
        assert request.url.host == 'cloud.getdbt.com' and request.url.path == '/api/v2/accounts/1/'
        return httpx.Response(200, json=envelope(ACCOUNT))
    transport.override = response
    assert (await node('check_connection', raw).run({}))['status'] == 'success'
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['count', 'total', 'duplicate', 'missing-pagination'])
async def test_actual_list_refuses_false_pagination(transport, case):
    rows = [PROJECT, PROJECT] if case == 'duplicate' else [PROJECT]
    page = {'count': len(rows), 'total_count': len(rows)}
    if case == 'count': page['count'] = 0
    if case == 'total': page['total_count'] = 0
    transport.override = lambda r: httpx.Response(200, json=envelope(rows, extra={} if case == 'missing-pagination' else {'pagination': page})) if r.url.path == '/api/v3/accounts/1/projects/' else None
    assert (await node('list_projects').run({}))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'rejected'])
async def test_actual_admission_precedes_evidence_and_provider(transport, monkeypatch, status):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, 'resolve_credential_with_owner_fallback', AsyncMock(return_value=credential()))
    monkeypatch.setattr(CredentialApprovalRepo, 'admit', AsyncMock(return_value={'id': 'approval-fixture', 'status': status, 'new_request': False}))
    kwargs = {'node_type': NODE_TYPE, 'credential_id': 'row-fixture', 'user_id': 'fixture-user', 'pool': object()}
    result = await run_op.run_node_operation(operation='check_connection', arguments={}, **kwargs)
    evidence = await ce.collect_evidence(**kwargs)
    assert result['executed'] is False and evidence.reachable is None and transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['::1'], ['93.184.216.34', '10.0.0.1'], []])
async def test_public_transport_denies_before_token_use(transport, monkeypatch, addresses):
    from utils import ssrf
    monkeypatch.setattr(ssrf, 'allow_private_hosts', lambda: False)
    transport.addresses = addresses
    assert (await node('check_connection').run({}))['status'] == 'error' and transport.requests == []


def test_saved_config_closed_operations_and_raw_tag_guard():
    assert Node.validate_saved_config({'operation': 'get_run', **arguments('get_run')})['valid']
    for op in ('run_job', 'retry_run', 'cancel_run', 'create_job', 'update_environment', 'execute_sql', 'create_service_token'):
        with pytest.raises(ValueError): node(op)
    for artifact in ('../../credentials', 'dbt.log', 'metadata/telemetry-1-otel.parquet'):
        with pytest.raises(ValueError): node('get_run_artifact_summary', artifact=artifact)


@pytest.mark.asyncio
@pytest.mark.parametrize('tag', TAGS)
async def test_static_tokens_refresh_without_rotation(tag):
    raw = credential(tag)
    assert await Node.freshen_credential(raw, credential_id='row', user_id='user') == raw


@pytest.mark.asyncio
@pytest.mark.parametrize('status, valid', [(200, True), (401, False), (403, False), (429, None)])
async def test_access_hook_uses_protected_account(transport, status, valid):
    if status != 200:
        transport.override = lambda _: httpx.Response(status, json={'detail': TOKEN})
    result = await Node.validate_credential_access(credential())
    assert result['valid'] is valid
    assert TOKEN not in json.dumps(result)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'token', 'project'])
async def test_saved_row_rechecked_before_provider_request(transport, monkeypatch, change):
    from utils import credentials
    current = credential()
    if change == 'token': current['access_token'] = 'OtherSyntheticToken42'
    if change == 'project': current['project_ids'] = ['9']
    resolver = AsyncMock(return_value=None if change == 'missing' else current)
    monkeypatch.setattr(credentials, 'resolve_credential_with_owner_fallback', resolver)
    instance = node('check_connection')
    instance.node_data['credential_id'] = 'row'
    instance._approval_pool = object()
    assert (await instance.execute({}))['status'] == 'error'
    resolver.assert_awaited_once()
    assert transport.requests == []

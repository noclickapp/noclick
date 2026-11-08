"""Offline HTTP protocol tests; responses below are synthetic, not live evidence."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes import deployhq_node as dhq
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/deployhq/requests.json').read_text())
AUTH = {'credential_type': 'deployhq_api_key', 'account': 'example', 'email': 'user@example.com', 'api_key': 'offline-deployhq-key'}
LISTS = {'list_projects', 'list_servers', 'list_server_groups', 'list_scheduled_deployments', 'list_teams'}


async def run(monkeypatch, config, body, status=200, headers=None):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {'timeout': 30, 'trust_env': False, 'follow_redirects': False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as session:
            yield session

    monkeypatch.setattr(dhq, 'guarded_async_client', client)
    node = NodeFactory.create_node(node_id='deployhq-offline', node_type='automation-deployhq',
        node_data={'config': config, 'credentials': AUTH}, sio=Mock())
    return await node.execute({}), requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', sorted(CASES))
async def test_operation_wire_contract(monkeypatch, operation):
    case = CASES[operation]
    config = {'operation': operation, **case['config']}
    body = [{'identifier': 'resource-123', 'name': 'Website'}] if operation in LISTS else {'identifier': 'resource-123'}
    if operation == 'list_deployments':
        body = {'records': [{'identifier': 'deploy-123'}], 'pagination': {'current_page': 1, 'total_pages': 3}}
    if operation == 'list_branches':
        body = {'branches': ['main', 'release/v1']}
    if operation == 'get_latest_revision':
        body = {'ref': 'abc123'}
    result, requests = await run(monkeypatch, config, body)
    assert result['status'] == 'success' and result['data'] == body
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (case['method'], case['path'])
    assert request.url.host == 'example.deployhq.com'
    expected_auth = httpx.BasicAuth(AUTH['email'], AUTH['api_key'])._auth_header
    assert request.headers['Authorization'] == expected_auth
    assert request.headers['Accept'] == request.headers['Content-Type'] == 'application/json'
    if operation == 'list_deployments':
        assert dict(request.url.params) == {'page': '1', 'per_page': '10'}
    elif operation in {'get_latest_revision', 'list_recent_commits'}:
        assert dict(request.url.params) == {'branch': 'main'}
    else:
        assert not request.url.params
    if operation in {'create_project', 'update_project'}:
        assert json.loads(request.content) == {'project': {'name': 'Website'}}
    elif operation == 'create_deployment':
        assert json.loads(request.content) == {'deployment': {
            'branch': 'main', 'parent_identifier': 'server-123', 'end_revision': 'abc123', 'mode': 'queue',
            'copy_config_files': True, 'run_build_commands': True, 'use_build_cache': True, 'skip_if_not_changes': False,
        }}
    else:
        assert request.content == b''


@pytest.mark.asyncio
async def test_query_encoding_and_provider_pagination(monkeypatch):
    result, requests = await run(monkeypatch, {'operation': 'list_deployments', 'project_id': 'website',
        'page': 2, 'per_page': 5, 'to': 'server-123', 'currently_running': True},
        {'records': [], 'pagination': {'current_page': 2, 'total_pages': 8}})
    assert dict(requests[0].url.params) == {'page': '2', 'per_page': '5', 'to': 'server-123', 'currently_running': '1'}
    assert result['data']['pagination']['total_pages'] == 8
    _, requests = await run(monkeypatch, {'operation': 'get_latest_revision', 'project_id': 'website', 'branch': 'release/v1 & main'}, {'ref': 'abc123'})
    assert requests[0].url.params['branch'] == 'release/v1 & main'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,headers', [
    (401, {'error': 'Invalid API key'}, None), (429, {'hint': 'Try later'}, None),
    (302, {}, {'Location': 'https://evil.example'}), (200, {'error_code': 'record_not_found'}, None),
    (200, {'projects': []}, None), (200, [], {'Content-Type': 'text/html'}),
])
async def test_errors_never_become_evidence(monkeypatch, status, body, headers):
    result, requests = await run(monkeypatch, {'operation': 'list_projects'}, body, status, headers)
    assert result['status'] == 'error' and len(requests) == 1
    if status == 401:
        assert result['error'] == 'Invalid API key'


@pytest.mark.asyncio
async def test_key_redacted_from_rejection(monkeypatch):
    result, _ = await run(monkeypatch, {'operation': 'list_projects'}, {'error': 'Rejected ' + AUTH['api_key']}, 401)
    assert AUTH['api_key'] not in json.dumps(result)


@pytest.mark.parametrize('account', ['localhost', 'example.com', '../tenant', 'foo/bar', 'https://foo.deployhq.com', 'foo:443', 'FOO', 'a\n'])
def test_account_host_validation(account):
    # A single valid subdomain, including localhost, is provider-bound; it cannot become a private hostname.
    if account == 'localhost':
        assert dhq.DeployHQAPIKeyCredential.model_validate({**AUTH, 'account': account}).account == account
    else:
        with pytest.raises(ValueError):
            dhq.DeployHQAPIKeyCredential.model_validate({**AUTH, 'account': account})


@pytest.mark.parametrize('identifier', ['..', '.', 'x/y', 'x%2Fy', 'x?secret=y', 'https://evil.example', 'x\n'])
def test_resource_validation(identifier):
    with pytest.raises(ValueError):
        dhq.DeployHQNodeConfig.model_validate({'config': {'operation': 'get_project', 'project_id': identifier}, 'credentials': AUTH})


def test_manual_connect_defaults_and_closed_operations():
    assert dhq.DeployHQAPIKeyCredential.model_validate({k: v for k, v in AUTH.items() if k != 'credential_type'}).credential_type == 'deployhq_api_key'
    with pytest.raises(ValueError):
        dhq.DeployHQAPIKeyCredential.model_validate({**AUTH, 'credential_type': 'foreign_token'})
    with pytest.raises(ValueError):
        dhq.DeployHQNodeConfig.model_validate({'config': {'operation': 'create_project', 'name': 'Website', 'arbitrary_body': {}}, 'credentials': AUTH})


@pytest.mark.asyncio
async def test_provider_authored_branch_map(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/deployhq/branches.json').read_text())
    result, _ = await run(monkeypatch, {'operation': 'list_branches', 'project_id': 'project'}, fixture['body'])
    assert result['status'] == 'success' and result['data'] == fixture['body']

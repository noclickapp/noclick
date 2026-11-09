"""Offline TiDB Cloud request and credential regression tests.

Exercise the actual registered node against a Digest challenge and API-shaped
responses, including rejected credentials, pagination and mutation bodies.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import tidb_cloud_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/tidb-cloud/requests.json').read_text())
CREDENTIAL = {'credential_type': 'tidb_cloud_api_key', 'public_key': 'test-public-key', 'private_key': 'test-private-key'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='test-tidb', node_type='automation-tidb-cloud',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, respond):
    requests = []
    def handle(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_operation_contract(monkeypatch, case):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    request, = requests
    assert request.method == case['method']
    assert str(request.url.copy_with(query=None)) == case['url']
    assert dict(request.url.params) == case['params']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert all(secret not in str(result) for secret in [*CREDENTIAL.values(), 'my-shining-password'])
    if case['config']['operation'].startswith('list_') and case['config']['operation'] != 'list_regions':
        assert result['next_page_token'] == 'next-page'
        assert result['items'][0]['displayName'] == 'my-resource'


@pytest.mark.asyncio
async def test_digest_authentication_and_account_evidence(monkeypatch):
    def respond(request):
        if 'Authorization' not in request.headers:
            return httpx.Response(401, headers={'WWW-Authenticate': 'Digest realm="tidb-cloud", nonce="test-nonce", qop="auth", algorithm=MD5'})
        auth = request.headers['Authorization']
        assert auth.startswith('Digest ') and 'username="test-public-key"' in auth
        assert 'response="' in auth and 'test-private-key' not in auth
        return httpx.Response(200, json={'projects': [{'id': '123', 'name': 'My project'}]})
    requests = transport(monkeypatch, respond)
    result = await node({'operation': 'list_projects'}).execute({})
    assert len(requests) == 2 and result['items'][0]['name'] == 'My project'
    assert native.TiDBCloudNode.connection_evidence.operation == 'list_projects'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500])
async def test_errors_never_report_success_or_follow_redirects(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status,
        json={'message': 'Denied test-private-key'}, headers={'Location': 'https://example.com'}))
    result = await node({'operation': 'list_projects'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Denied [redacted]' and len(requests) == 1


@pytest.mark.asyncio
async def test_empty_success_error_envelope_and_invalid_shapes(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(204))
    assert (await node({'operation': 'cancel_import', 'cluster_id': '123', 'import_id': '456'}).execute({}))['status'] == 'success'
    transport(monkeypatch, lambda r: httpx.Response(200, json={'code': 7, 'message': 'permission denied'}))
    assert (await node({'operation': 'list_projects'}).execute({}))['status'] == 'error'
    transport(monkeypatch, lambda r: httpx.Response(200, json={'projects': {}}))
    with pytest.raises(ValueError):
        await node({'operation': 'list_projects'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('resource_id', ['../other', 'https://example.com', 'foo/bar', '.', 'foo?bar'])
async def test_resource_ids_cannot_change_routes(monkeypatch, resource_id):
    requests = transport(monkeypatch, lambda r: pytest.fail('No request should be sent'))
    with pytest.raises(ValueError):
        await node({'operation': 'get_cluster', 'cluster_id': resource_id}).execute({})
    assert not requests


def test_manual_credential_shape_and_schema():
    credential = native.TiDBCloudAPIKeyCredential(public_key='test-public-key', private_key='test-private-key')
    assert credential.credential_type == 'tidb_cloud_api_key'
    for field in ('public_key', 'private_key'):
        with pytest.raises((ValueError, ValidationError)):
            native.TiDBCloudAPIKeyCredential(**{**CREDENTIAL, field: 'https://example.com/key'})
    schema = native.TiDBCloudFullConfig.model_json_schema()
    assert len(schema['$defs']) > 23
    for config in [{'operation': 'list_clusters', 'page_size': 101}, {'operation': 'create_cluster'}, {'operation': 'update_cluster', 'cluster_id': '123'}]:
        with pytest.raises(ValueError):
            native.TiDBCloudNode.parse_config({'config': config, 'credentials': CREDENTIAL})

"""PlanetScale factory-to-HTTP regressions; all credentials and responses are fake."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import planetscale_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-planetscale-service-token"
CASES = json.loads((Path(__file__).parent / 'fixtures/planetscale/operations.json').read_text())


def node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-planetscale", node_data={
        "config": config, "credentials": {"credential_type": "planetscale_service_token", "service_token": TOKEN}})


def transport(monkeypatch, status=200, body=None, content=None):
    calls = []
    def respond(request):
        calls.append(request)
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body if body is not None else {"id": "fixture", "state": "pending"})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_each_operation_has_one_exact_provider_request(monkeypatch, operation):
    case = CASES[operation]
    status = 204 if operation.startswith('delete_') else 201 if operation.startswith('create_') else 200
    calls = transport(monkeypatch, status, content=b'' if status == 204 else None)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert result['http_status'] == status
    assert len(calls) == 1
    req = calls[0]
    assert req.method == case['method']
    assert req.url.path == '/v1' + case['path']
    assert req.url.host == 'api.planetscale.com'
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    if status == 204:
        assert result['deletion_acknowledged']
    else:
        assert result['data']['state'] == 'pending'


@pytest.mark.asyncio
async def test_pagination_remains_one_page(monkeypatch):
    page = {'data': [{'id': 'org-1', 'name': 'Owned organization'}], 'current_page': 2,
            'next_page': 3, 'next_page_url': 'https://evil.example.test/capture'}
    calls = transport(monkeypatch, body=page)
    result = await node({'operation': 'list_organizations', 'page': 2, 'per_page': 10}).execute({})
    assert result['data'] == page
    assert dict(calls[0].url.params) == {'page': '2', 'per_page': '10'}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_write_body_excludes_route_and_config_fields(monkeypatch):
    calls = transport(monkeypatch, 201)
    result = await node({'operation': 'create_deploy_request', 'organization': 'acme', 'database': 'app-db',
                         'branch': 'feature', 'into_branch': 'main', 'notes': 'Ship change',
                         'auto_cutover': False, 'auto_delete_branch': False}).execute({})
    assert result['status'] == 'success'
    assert json.loads(calls[0].content) == {'branch': 'feature', 'into_branch': 'main', 'notes': 'Ship change',
                                         'auto_cutover': False, 'auto_delete_branch': False}
    calls = transport(monkeypatch)
    await node({'operation': 'close_deploy_request', 'organization': 'acme', 'database': 'app-db', 'number': 7}).execute({})
    assert json.loads(calls[0].content) == {'state': 'closed'}


@pytest.mark.asyncio
async def test_delete_query_boolean_and_backup_options(monkeypatch):
    calls = transport(monkeypatch, 204, content=b'')
    await node({'operation': 'delete_branch', 'organization': 'acme', 'database': 'app-db',
                'branch': 'feature', 'delete_descendants': False}).execute({})
    assert dict(calls[0].url.params) == {'delete_descendants': 'false'}
    calls = transport(monkeypatch, 201)
    await node({'operation': 'create_backup', 'organization': 'acme', 'database': 'app-db',
                'branch': 'main', 'name': 'daily', 'retention_unit': 'day', 'retention_value': 7,
                'emergency': False}).execute({})
    assert json.loads(calls[0].content) == {'name': 'daily', 'retention_unit': 'day', 'retention_value': 7, 'emergency': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_errors_are_not_success_or_retried_and_secrets_are_redacted(monkeypatch, status):
    calls = transport(monkeypatch, status, body={'message': 'Denied ' + TOKEN})
    result = await node({'operation': 'list_organizations'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Denied [redacted]'}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('content', [b'<html>bad gateway</html>', b'null', b'"text"'])
async def test_invalid_responses_fail(monkeypatch, content):
    transport(monkeypatch, content=content)
    result = await node({'operation': 'list_organizations'}).execute({})
    assert result['status'] == 'error'


def test_hand_connection_defaults_and_validation():
    credential = native.PlanetScaleServiceToken(service_token=TOKEN)
    assert credential.credential_type == 'planetscale_service_token'
    for token in ['Bearer ' + TOKEN, 'id:' + TOKEN, 'https://example.com', '']:
        with pytest.raises(ValidationError):
            native.PlanetScaleServiceToken(service_token=token)
    for config in [
        {'operation': 'get_branch', 'organization': '../acme', 'database': 'db', 'branch': 'main'},
        {'operation': 'get_deploy_request', 'organization': 'acme', 'database': 'db', 'number': 0},
        {'operation': 'create_database', 'organization': 'acme', 'name': 'db'},
        {'operation': 'create_deploy_request', 'organization': 'acme', 'database': 'db', 'branch': 'feature'},
        {'operation': 'list_organizations', 'page': 0},
    ]:
        with pytest.raises(ValueError):
            node(config)

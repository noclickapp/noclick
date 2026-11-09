"""Exercise Cloudsmith's native factory and wire contract without an account.

Fixtures are synthetic and cover all exposed operations, failure handling,
manual credentials and the account-evidence read.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import cloudsmith_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'cloudsmith-synthetic-key'
AUTH = {'credential_type': 'cloudsmith_api_key', 'api_key': TOKEN}
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/cloudsmith/contract.json').read_text())['operations']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id='cloudsmith-fixture', node_type='automation-cloudsmith',
        node_data={'config': {'operation': operation, **config}, 'credentials': AUTH})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CONTRACT)
async def test_each_operation_is_one_contract_request(monkeypatch, operation):
    contract = CONTRACT[operation]
    method, template = contract['method'], contract['path']
    wire = {'owner': 'acme', 'repo': 'packages', 'identifier': 'pkg_123'}
    config = {'owner': 'acme'} if '{owner}' in template else {}
    if '{repo}' in template or (template.startswith('/repos/') and '{identifier}' in template):
        config['repo'] = 'packages'
    if '{identifier}' in template and not template.startswith('/repos/'):
        config['identifier'] = 'pkg_123'
    elif '{identifier}' in template:
        wire['identifier'] = 'packages'
    if operation == 'create_repository':
        config['name'] = 'Build Artifacts'
    if operation in {'copy_package', 'move_package'}:
        config['destination'] = 'production'
    if operation == 'tag_package':
        config.update(action='Replace', tags=['release', 'stable'])
    body = [] if operation.startswith('list_') else {'authenticated': True, 'name': 'Fixture', 'slug': 'fixture'}
    status = contract['success_status']
    requests = transport(monkeypatch, None if status == 204 else body, status)
    result = await node(operation, **config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'api.cloudsmith.io'
    assert request.url.path == template.format(**wire)
    assert request.headers['X-Api-Key'] == TOKEN
    assert 'Authorization' not in request.headers
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'page': '1', 'page_size': '30'}
    else:
        assert not request.url.params
    expected_bodies = {
        'create_repository': {'name': 'Build Artifacts', 'repository_type_str': 'Private'},
        'update_repository': {},
        'copy_package': {'destination': 'production', 'republish': False},
        'move_package': {'destination': 'production'},
        'tag_package': {'action': 'Replace', 'tags': ['release', 'stable']},
        'quarantine_package': {'release': False},
    }
    if operation in expected_bodies:
        assert json.loads(request.content) == expected_bodies[operation]
    else:
        assert not request.content
    assert result['http_status'] == status
    if method != 'GET':
        assert result['accepted'] is True and result['background_completion_verified'] is False
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_private_creation_and_selective_update(monkeypatch):
    requests = transport(monkeypatch, {'slug': 'builds'}, 201)
    await node('create_repository', owner='acme', name='Builds').execute({})
    assert json.loads(requests[0].content) == {'name': 'Builds', 'repository_type_str': 'Private'}
    requests = transport(monkeypatch, {'slug': 'builds'})
    await node('update_repository', owner='acme', repo='builds', description='New description').execute({})
    assert json.loads(requests[0].content) == {'description': 'New description'}


@pytest.mark.asyncio
async def test_paging_filters_are_explicit_and_never_follow_links(monkeypatch):
    requests = transport(monkeypatch, [{'slug': 'artifact'}])
    result = await node('list_packages', owner='acme', repo='builds', page=3, page_size=10, query='name:artifact').execute({})
    assert dict(requests[0].url.params) == {'page': '3', 'page_size': '10', 'query': 'name:artifact'}
    assert result['page'] == 3 and result['data'] == [{'slug': 'artifact'}]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_entitlement_tokens_and_echoed_key_are_redacted(monkeypatch):
    requests = transport(monkeypatch, {'name': 'Distribution', 'token': 'private-download-token',
                                     'metadata': {'api_key': TOKEN, 'note': TOKEN}})
    result = await node('get_entitlement', owner='acme', repo='builds', identifier='dist').execute({})
    assert 'show_tokens' not in requests[0].url.params
    assert 'private-download-token' not in str(result) and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_fail_with_redacted_provider_detail(monkeypatch, status):
    requests = transport(monkeypatch, {'detail': 'Invalid API key ' + TOKEN}, status)
    with pytest.raises(ValueError) as caught:
        await node('get_current_user').execute({})
    assert TOKEN not in str(caught.value)
    assert str(status) in str(caught.value) and 'Invalid API key' in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'authenticated': False}, {}, []])
async def test_anonymous_or_malformed_identity_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node('get_current_user').execute({})


@pytest.mark.parametrize('bad', ['../escape', 'a/b', 'a%2Fb', 'https://example.com', 'bad\n'])
def test_path_injection_refused(bad):
    with pytest.raises(ValueError):
        node('get_repository', owner=bad, repo='builds')


def test_paste_credential_has_default_tag_and_foreign_tags_are_refused():
    assert native.CloudsmithApiKeyCredential(api_key=TOKEN).credential_type == 'cloudsmith_api_key'
    with pytest.raises(ValueError):
        native.CloudsmithNode.parse_config({'config': {'operation': 'get_current_user'},
            'credentials': {**AUTH, 'credential_type': 'other_api_key'}})
    with pytest.raises(ValidationError):
        native.CloudsmithApiKeyCredential(api_key='has whitespace')

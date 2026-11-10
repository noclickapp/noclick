"""Execute Conjur requests against the provider's published example responses."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import conjur_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'conjur'
CREDENTIAL = {'credential_type': 'conjur_api_key', 'server_url': 'https://conjur.example.com',
              'account': 'dev', 'login': 'host/prod@ops', 'api_key': '14m9cf91wfsesv1kkhevg12cdywm2wvqy6s8sk53z1ngtazp1t9tykc'}
TOKEN = base64.b64encode(json.dumps(json.loads((FIXTURES / 'authentication.json').read_text())['body']).encode()).decode()


def documented(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())['body']


def node(config, credential=None):
    return NodeFactory.create_node(node_id='conjur-test', node_type='automation-conjur',
        node_data={'config': config, 'credentials': credential or CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def handle(req):
        requests.append(req)
        if len(requests) == 1:
            assert req.method == 'POST'
            assert req.url.raw_path == b'/authn/dev/host%2Fprod%40ops/authenticate'
            assert req.content == CREDENTIAL['api_key'].encode()
            assert req.headers['Content-Type'] == 'text/plain'
            assert req.headers['Accept-Encoding'] == 'base64'
            assert 'Authorization' not in req.headers
            return httpx.Response(200, text=TOKEN)
        assert req.headers['Authorization'] == 'Token token=' + TOKEN
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ({'operation': 'get_identity'}, 'GET', '/whoami', {}, httpx.Response(200, json=documented('identity'))),
    ({'operation': 'get_secret', 'identifier': 'prod/aws/db-password', 'version': 2}, 'GET', '/secrets/dev/variable/prod%2Faws%2Fdb-password', {'version': '2'}, httpx.Response(200, text='supersecret')),
    ({'operation': 'set_secret', 'identifier': 'prod/aws/db-password', 'value': 'supersecret'}, 'POST', '/secrets/dev/variable/prod%2Faws%2Fdb-password', {}, httpx.Response(201)),
    ({'operation': 'get_secrets', 'variable_ids': 'myorg:variable:secret1,myorg:variable:secret2'}, 'GET', '/secrets', {'variable_ids': 'myorg:variable:secret1,myorg:variable:secret2'}, httpx.Response(200, json={'myorg:variable:secret1': 'secret1Value', 'myorg:variable:secret2': 'secret2Value'})),
    ({'operation': 'list_resources', 'kind': 'variable', 'search': 'password', 'limit': 1}, 'GET', '/resources', {'kind': 'variable', 'search': 'password', 'limit': '1', 'offset': '0'}, httpx.Response(200, json=[documented('resources')])),
    ({'operation': 'list_account_resources'}, 'GET', '/resources/dev', {'limit': '100', 'offset': '0'}, httpx.Response(200, json=[documented('resources')])),
    ({'operation': 'list_kind_resources', 'kind': 'policy', 'offset': 20}, 'GET', '/resources/dev/policy', {'limit': '100', 'offset': '20'}, httpx.Response(200, json=[])),
    ({'operation': 'get_resource', 'kind': 'policy', 'identifier': 'root'}, 'GET', '/resources/dev/policy/root', {}, httpx.Response(200, json=documented('resources'))),
    ({'operation': 'get_role', 'kind': 'user', 'identifier': 'admin', 'view': 'members'}, 'GET', '/roles/dev/user/admin', {'members': 'true', 'limit': '100', 'offset': '0'}, httpx.Response(200, json={'created_at': '2020-12-31:12:34:56.789+00:00', 'id': 'myorg:user:admin', 'members': []})),
    ({'operation': 'add_role_member', 'kind': 'group', 'identifier': 'ops', 'member': 'dev:user:alice'}, 'POST', '/roles/dev/group/ops', {'members': 'true', 'member': 'dev:user:alice'}, httpx.Response(204)),
    ({'operation': 'remove_role_member', 'kind': 'group', 'identifier': 'ops', 'member': 'dev:user:alice'}, 'DELETE', '/roles/dev/group/ops', {'members': 'true', 'member': 'dev:user:alice'}, httpx.Response(204)),
    *[({'operation': op, 'identifier': 'root', 'policy': '- !variable db-password\n'}, method, '/policies/dev/policy/root', {}, httpx.Response(201, json=documented('policies'))) for op, method in [('load_policy', 'POST'), ('update_policy', 'PATCH'), ('replace_policy', 'PUT')]],
    ({'operation': 'get_public_keys', 'kind': 'user', 'identifier': 'alice@devops'}, 'GET', '/public_keys/dev/user/alice%40devops', {}, httpx.Response(200, text='ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ...')),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,params,response', CASES, ids=[c[0]['operation'] for c in CASES])
async def test_documented_operations(monkeypatch, config, method, path, params, response):
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert len(requests) == 2
    request = requests[1]
    assert request.method == method
    assert request.url.raw_path.split(b'?')[0].decode() == path
    assert dict(request.url.params) == params
    assert result['status'] == 'success' and result['http_status'] == response.status_code
    assert CREDENTIAL['api_key'] not in str(result) and TOKEN not in str(result)
    if config['operation'] == 'set_secret':
        assert request.content == b'supersecret'
        assert request.headers['Content-Type'] == 'application/octet-stream'
        assert result['data'] is None
    elif 'policy' in config:
        assert request.content.decode() == config['policy']
        assert request.headers['Content-Type'] == 'text/plain'
        assert result['data'] == documented('policies')
    elif config['operation'] == 'get_secret':
        assert result['data'] == 'supersecret'
    elif config['operation'] == 'get_identity':
        assert result['data']['username'] == 'admin'
    elif config['operation'] == 'list_resources':
        assert result['next_offset'] == 1
    elif config['operation'] == 'list_kind_resources':
        assert result['next_offset'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_errors_never_claim_success_or_retry_mutations(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text='denied ' + CREDENTIAL['api_key']))
    with pytest.raises(ValueError, match=f'Conjur HTTP {status}: denied \\[redacted\\]'):
        await node({'operation': 'add_role_member', 'kind': 'group', 'identifier': 'ops', 'member': 'dev:user:alice'}).execute({})
    assert len(requests) == 2


@pytest.mark.parametrize('field,value', [('server_url', 'http://conjur.example.com'), ('server_url', 'https://conjur.example.com/path'), ('server_url', 'https://user:password@conjur.example.com'), ('api_key', '<token>'), ('api_key', 'bad\r\nheader'), ('account', 'dev:bad'), ('login', '..')])
def test_manual_credential_validation(field, value):
    with pytest.raises(ValidationError):
        native.ConjurAPIKeyCredential.model_validate({**CREDENTIAL, field: value})


def test_credential_default_and_connection_evidence():
    credential = native.ConjurAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != 'credential_type'})
    assert credential.credential_type == 'conjur_api_key'
    assert native.ConjurNode.connection_evidence.identity_operation == 'get_identity'
    assert native.ConjurNode.parse_config({'config': {'operation': 'get_identity'}, 'credentials': credential.model_dump()}).config.operation == 'get_identity'


@pytest.mark.asyncio
async def test_authentication_failure_stops_before_api_call(monkeypatch):
    requests = []
    def handle(req):
        requests.append(req)
        return httpx.Response(401, text='Invalid credentials')
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(ValueError, match='Conjur HTTP 401: Invalid credentials'):
        await node({'operation': 'get_identity'}).execute({})
    assert len(requests) == 1

"""Exercise GoTo Connect through the discovered node, without provider credentials.

Contract-shaped fixtures pin routes, repeated query keys, wire bodies and response
preservation so conformance fixes cannot silently break an existing action.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import go_to_connect_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.go_to_connect_oauth import OAUTH_PROVIDER

CREDS = {"credential_type": "go_to_connect_oauth", "access_token": "synthetic-access-token", "refresh_token": "synthetic-refresh-token"}
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/go-to-connect/actions.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="connect-test", node_type="automation-go-to-connect",
        node_data={"config": config, "credentials": CREDS})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        assert request.url.host == "api.goto.com"
        assert request.headers["Authorization"] == "Bearer " + CREDS["access_token"]
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FIXTURES)
async def test_go_to_connect_contract_request_and_response(monkeypatch, name):
    fixture = FIXTURES[name]
    def respond(request):
        assert request.method == fixture['method']
        assert request.url.path == fixture['path']
        assert {key: request.url.params.get_list(key) for key in request.url.params} == fixture['query']
        if fixture['body'] is not None:
            assert json.loads(request.content) == fixture['body']
        else:
            assert request.content == b''
        return httpx.Response(fixture['status'], json=fixture['response']) if fixture['status'] != 204 else httpx.Response(204)
    requests = transport(monkeypatch, respond)
    result = await node(fixture['config']).execute({})
    assert result == {'status': 'success', 'operation': name, 'data': fixture['response']}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_go_to_connect_errors_and_redirects(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={'errorCode': 'EXPIRED_TOKEN', 'message': 'Provider rejected token'}, headers={'Location': 'https://other.example/'}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_my_setup'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_go_to_connect_rejects_error_envelope(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'errorCode': 'INVALID_TOKEN', 'message': 'The supplied authentication token is not valid.'}))
    with pytest.raises(ValueError, match='supplied authentication token'):
        await node({'operation': 'get_my_setup'}).execute({})


@pytest.mark.parametrize('operation,patch', [
    ('get_message', {'messageId': '../other'}),
    ('send_message', {'body': {'ownerPhoneNumber': 'not-a-number', 'contactPhoneNumbers': ['+15145557777'], 'body': 'Hi'}}),
    ('send_message', {'body': {'ownerPhoneNumber': '+15145552672', 'contactPhoneNumbers': ['+15145557777'] * 2, 'body': 'Hi'}}),
    ('list_messages', {'pageSize': 101}),
    ('list_messages', {'contactPhoneNumber': ['+15145557777'] * 2}),
    ('get_presence', {'userKey': ['123456123456'] * 2}),
    ('set_my_presence', {'body': {}}),
    ('set_my_presence', {'body': {'userDoNotDisturbExpiration': '2029-11-30T01:17:23Z'}}),
    ('set_my_presence', {'body': {'userStatus': 'invented'}}),
    ('set_my_presence', {'userKey': 'someone-else'}),
])
def test_go_to_connect_invalid_inputs(operation, patch):
    config = {**FIXTURES[operation]['config'], **patch}
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS[operation].model_validate(config)


def test_go_to_connect_oauth_and_evidence_contract():
    assert native.GoToConnectOAuthCredential.model_fields['credential_type'].default == 'go_to_connect_oauth'
    assert native.GoToConnectNode.connection_evidence.operation == 'get_my_setup'
    assert OAUTH_PROVIDER.identity_url == native.BASE + '/users/v1/me'
    assert OAUTH_PROVIDER.name_field == 'items.0.accountKey'
    assert set(native.GO_TO_CONNECT_SCOPES) == set(FIXTURES)
    assert 'users.v1.read' in native.GO_TO_CONNECT_SCOPES.declared_scopes()
    assert native.PresenceBody(userNote='').model_dump(exclude_none=True) == {'userNote': ''}


@pytest.mark.asyncio
async def test_go_to_connect_evidence_displays_account_key(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    async def read_setup(**kwargs):
        assert kwargs['node_type'] == 'automation-go-to-connect'
        assert kwargs['operation'] == 'get_my_setup'
        assert kwargs['arguments'] == {}
        return {'status': 'success', 'data': FIXTURES['get_my_setup']['response']}

    monkeypatch.setattr(run_op, 'run_node_operation', read_setup)
    result = await collect_evidence(node_type='automation-go-to-connect', user_id='test-user', pool=None, credential_data=CREDS)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ['31416']

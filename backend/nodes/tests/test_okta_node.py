"""All 20 operations against unmodified Okta documented responses.

Source URLs are pinned per fixture in fixtures/okta/documented.json.
https://developer.okta.com/docs/api/openapi/okta-management/
https://developer.okta.com/docs/guides/create-an-api-token/main/
No live API requests, sign-ins, or email deliveries.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.okta_node import OktaAPITokenCredential, OktaNode, OktaNodeConfig, OKTA_OPERATIONS

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/okta/documented.json').read_text())
CREDENTIAL = {'credential_type': 'okta_api_token', 'org_url': 'https://example.okta.com', 'api_token': 'okta-test-token'}


def node(config, credential=CREDENTIAL):
    return OktaNode(node_id='okta', node_type='automation-okta', node_data={},
                    config=OktaNodeConfig.model_validate({'config': config, 'credentials': credential}))


def mocked_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_every_documented_operation(operation):
    f = FIXTURES[operation]
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == f['method']
        assert request.url.path == f['path']
        assert request.headers['authorization'] == 'SSWS okta-test-token'
        assert request.headers['accept'] == 'application/json'
        assert request.headers['content-type'] == 'application/json'
        return httpx.Response(f['response_status'], **({'json': f['response']} if f['response'] is not None else {}))
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(handler)):
        result = await node(f['config']).execute({})
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['status_code'] == f['response_status']
    assert result['action'] == operation
    assert result['timing_ms']['api_request'] >= 0
    collection = OKTA_OPERATIONS[operation][2]
    if collection:
        assert result['data'][collection] == f['response']
        assert result['data']['count'] == len(f['response'])
    else:
        assert result['data'] == (f['response'] if f['response'] is not None else {'success': True})
    request, config = calls[0], f['config']
    if operation == 'create_user':
        assert json.loads(request.content) == {'profile': {'firstName': config['first_name'], 'lastName': config['last_name'], 'email': config['email'], 'login': config['login']}}
        assert request.url.params['activate'] == 'false'
    elif operation == 'update_user':
        assert json.loads(request.content) == {'profile': json.loads(config['profile_json'])}
    elif operation == 'create_group':
        assert json.loads(request.content) == {'profile': {'name': config['name'], 'description': config['description']}}
    elif operation == 'assign_user_to_app':
        assert json.loads(request.content) == {'id': config['user_id'], 'scope': 'USER', 'credentials': {'userName': config['username']}}
    else:
        assert not request.content
    if operation in ('activate_user','deactivate_user','unassign_user_from_app'):
        assert request.url.params['sendEmail'] == 'false'


def test_fixtures_cover_exactly_the_catalog():
    assert FIXTURES.keys() == OKTA_OPERATIONS.keys()
    assert all(f['source'].startswith('https://raw.githubusercontent.com/okta/') for f in FIXTURES.values())


@pytest.mark.asyncio
async def test_pagination_keeps_only_cursor_and_preserves_rows():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.params['after'] == 'opaque cursor'
        assert request.url.params['search'] == 'profile.lastName eq "Brock"'
        return httpx.Response(200, json=FIXTURES['list_users']['response'], headers={
            'Link': '<https://attacker.invalid/path?after=next%2Bcursor&limit=100>; rel="next"'})
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(handler)):
        result = await node({'operation':'list_users','after':'opaque cursor','search':'profile.lastName eq "Brock"'}).execute({})
    assert len(calls) == 1
    assert result['data']['next_after'] == 'next+cursor'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['list_users','list_groups','list_apps','list_group_users','list_app_users','list_user_groups'])
async def test_empty_lists_are_valid(operation):
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(200, json=[]))):
        result = await node(FIXTURES[operation]['config']).execute({})
    assert result['status'] == 'success'
    assert result['data']['count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 403, 404, 429, 500])
async def test_errors_never_reflect_secrets_or_follow_redirects(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'errorSummary':'echo okta-test-token'}, headers={'Location':'https://attacker.invalid'})
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(handler)) as factory:
        result = await node({'operation':'list_users'}).execute({})
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert 'okta-test-token' not in str(result)
    assert len(calls) == 1
    assert factory.call_args.kwargs['follow_redirects'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'errorCode':'E0000005'}, [None], [{'profile':{}}], 'login page'])
async def test_malformed_success_cannot_verify_connection(body):
    from nodes.core.connection_evidence import collect_evidence
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(200,json=body))):
        result = await collect_evidence(node_type='automation-okta',credential_data=CREDENTIAL,user_id='test',pool=Mock())
    assert result.reachable is not True


@pytest.mark.asyncio
async def test_connection_evidence_shows_user_logins():
    from nodes.core.connection_evidence import collect_evidence
    f = FIXTURES['list_users']
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(200,json=f['response']))):
        result = await collect_evidence(node_type='automation-okta',credential_data=CREDENTIAL,user_id='test',pool=Mock())
    assert result.reachable is True
    assert result.samples[0].label == f['response'][0]['profile']['login']


@pytest.mark.asyncio
async def test_rejected_connection_is_not_an_empty_list():
    from nodes.core.connection_evidence import collect_evidence
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(401,json={'errorCode':'E0000011'}))):
        result = await collect_evidence(node_type='automation-okta',credential_data=CREDENTIAL,user_id='test',pool=Mock())
    assert result.reachable is False


@pytest.mark.asyncio
@pytest.mark.parametrize('field,op', [('user_id','list_users'),('group_id','list_groups'),('app_id','list_apps')])
async def test_picker_contract(field,op):
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(200,json=FIXTURES[op]['response']))):
        result = await OktaNode.load_field_options(field,CREDENTIAL,{},None,None)
    assert result['options'][0]['value'] == FIXTURES[op]['response'][0]['id']
    assert result['options'][0]['label']


@pytest.mark.asyncio
async def test_invalid_json_and_transport_failure_are_sanitized():
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(lambda r: httpx.Response(200,text='<html>okta-test-token</html>'))):
        result = await node({'operation':'list_users'}).execute({})
    assert result['status'] == 'error'
    assert 'okta-test-token' not in str(result)
    def fail(request):
        raise httpx.ConnectError('echo okta-test-token')
    with patch('nodes.okta_node.guarded_async_client', return_value=mocked_client(fail)):
        result = await node({'operation':'list_users'}).execute({})
    assert result['status'] == 'error'
    assert 'okta-test-token' not in str(result)


@pytest.mark.parametrize('origin', ['http://example.okta.com','https://user:pass@example.okta.com','https://example-admin.okta.com'])
def test_invalid_org_url(origin):
    with pytest.raises(ValidationError):
        OktaAPITokenCredential(**{**CREDENTIAL,'org_url':origin})


def test_org_url_normalizes_pasted_console_path():
    credential = OktaAPITokenCredential(**{**CREDENTIAL,'org_url':'EXAMPLE.okta.com/dashboard'})
    assert credential.org_url == 'https://example.okta.com'


@pytest.mark.asyncio
@pytest.mark.parametrize('profile', ['[]','null','{"broken"','{}'])
async def test_invalid_profile_fails_before_request(profile):
    with patch('nodes.okta_node.guarded_async_client') as request:
        with pytest.raises(ValueError,match='Profile must'):
            await node({'operation':'update_user','user_id':'00u123','profile_json':profile}).execute({})
        request.assert_not_called()


@pytest.mark.asyncio
async def test_user_login_is_encoded_as_one_segment():
    def handler(request):
        assert request.url.raw_path == b'/api/v1/users/isaac%2Fbrock%40example.com'
        return httpx.Response(200,json=FIXTURES['get_user']['response'])
    with patch('nodes.okta_node.guarded_async_client',return_value=mocked_client(handler)):
        result = await node({'operation':'get_user','user_id':'isaac/brock@example.com'}).execute({})
    assert result['status'] == 'success'


@pytest.mark.asyncio
async def test_private_custom_org_is_guarded(monkeypatch):
    monkeypatch.delenv('OUTBOUND_ALLOW_PRIVATE_IPS',raising=False)
    monkeypatch.delenv('HTTP_NODE_ALLOW_PRIVATE_IPS',raising=False)
    with patch('utils.ssrf._resolve_host_addresses',return_value=['127.0.0.1']):
        result = await node({'operation':'list_users'}).execute({})
    assert result['status'] == 'error'

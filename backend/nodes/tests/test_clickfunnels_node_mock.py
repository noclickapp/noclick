"""Exercise every ClickFunnels operation against unaltered provider-authored responses.

Fixture source: https://accounts.myclickfunnels.com/openapi.json, version 2.0.0.
The invoice example has schema-inconsistent nulls and numeric strings; retaining
those values verifies that our parser handles the provider's documented payload.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.clickfunnels_node import ClickFunnelsAPIKeyCredential, ClickFunnelsNode, ClickFunnelsNodeConfig
from nodes.core.connection_evidence import collect_evidence

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/clickfunnels/documented.json').read_text())
CREDENTIAL = {'api_key': 'clickfunnels-test-key', 'workspace_subdomain': 'myworkspace'}
ORIGINAL_CLIENT = httpx.AsyncClient


def node(config, credentials=CREDENTIAL):
    return ClickFunnelsNode(node_id='clickfunnels-test', node_type='automation-clickfunnels', node_data={},
        config=ClickFunnelsNodeConfig(config=config, credentials=credentials),
        sio=None, sid=None, workflow_id='test-workflow', user_id='test-user')


def transport(monkeypatch, callback):
    monkeypatch.setattr('nodes.clickfunnels_node.httpx.AsyncClient',
        lambda *args, **kwargs: ORIGINAL_CLIENT(*args, **kwargs, transport=httpx.MockTransport(callback)))


@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_operation(monkeypatch, operation):
    """Source: official OpenAPI operation examples, copied without changing responses."""
    f = FIXTURES[operation]
    seen = []
    def respond(req):
        seen.append(req)
        assert req.method == f['method']
        host = 'accounts' if operation in {'list_teams', 'list_workspaces'} else 'myworkspace'
        assert req.url.host == f'{host}.myclickfunnels.com'
        assert req.url.path == '/api/v2' + f['path']
        assert req.headers['Authorization'] == 'Bearer clickfunnels-test-key'
        assert req.headers['User-Agent'] == 'NoClick/ClickFunnels'
        assert req.headers['Accept'] == 'application/json'
        if f['request_body'] is not None:
            assert json.loads(req.content) == f['request_body']
        else:
            assert req.content == b''
        assert dict(req.url.params) == ({'per_page': '20'} if operation.startswith('list_') else {})
        return httpx.Response(204) if f['response_status'] == 204 else httpx.Response(f['response_status'], json=f['response'])
    transport(monkeypatch, respond)
    result = await node({'operation': operation, **f['config']}).execute({})
    assert len(seen) == 1
    assert result['status'] == 'success'
    assert result['action'] == operation
    assert result['status_code'] == f['response_status']
    assert result['timing_ms']['total'] >= 0
    if f['result_key']:
        assert result['data'] == {f['result_key']: f['response'], 'count': len(f['response']), 'next_cursor': None, 'next_link': None}
    else:
        assert result['data'] == ({'deleted': True} if f['response_status'] == 204 else f['response'])


async def test_pagination(monkeypatch):
    seen = []
    def respond(req):
        seen.append(req)
        assert req.url.params['after'] == 'after[opaque]+/='
        assert req.url.params['per_page'] == '50'
        return httpx.Response(200, json=[], headers={'Pagination-Next': 'next-opaque', 'Link': '<https://example.test>; rel="next"'})
    transport(monkeypatch, respond)
    r = await node({'operation': 'list_contacts', 'workspace_id': '4', 'after': 'after[opaque]+/=', 'per_page': 50}).execute({})
    assert r['data'] == {'contacts': [], 'count': 0, 'next_cursor': 'next-opaque', 'next_link': '<https://example.test>; rel="next"'}
    assert len(seen) == 1  # Never follow a response link with the user's key.


@pytest.mark.parametrize('config,expected', [
    ({'operation': 'update_contact', 'contact_id': '24359', 'first_name': 'Sol', 'custom_attributes_json': '{"tier":"gold"}'},
     {'contact': {'first_name': 'Sol', 'custom_attributes': {'tier': 'gold'}}}),
    ({'operation': 'update_enrollment', 'enrollment_id': '8', 'suspended': False}, {'courses_enrollment': {'suspended': False}}),
])
async def test_partial_updates_preserve_false_and_omit_unset(monkeypatch, config, expected):
    def respond(req):
        assert json.loads(req.content) == expected
        return httpx.Response(200, json=FIXTURES[config['operation']]['response'])
    transport(monkeypatch, respond)
    r = await node(config).execute({})
    assert r['data'] == FIXTURES[config['operation']]['response']


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_preserved(monkeypatch, status):
    body = {'error': 'API key missing or invalid', 'hint': 'Send the token as Authorization: Bearer <token>.'}
    transport(monkeypatch, lambda req: httpx.Response(status, json=body))
    with pytest.raises(ValueError, match=f'ClickFunnels API {status}') as exc:
        await node({'operation': 'list_teams'}).execute({})
    assert body['error'] in str(exc.value)
    assert body['hint'] in str(exc.value)


@pytest.mark.parametrize('operation,payload', [('list_teams', {}), ('list_teams', ['unexpected']), ('get_contact', [])])
async def test_bad_success_shapes(monkeypatch, operation, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match='invalid resource'):
        await node({'operation': operation, **FIXTURES[operation]['config']}).execute({})


async def test_error_envelope_and_non_json(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={'error': 'API key missing or invalid'}))
    with pytest.raises(ValueError, match='API key missing or invalid'):
        await node({'operation': 'list_teams'}).execute({})
    transport(monkeypatch, lambda req: httpx.Response(200, text='<html>Sign in</html>'))
    with pytest.raises(ValueError, match='non-JSON'):
        await node({'operation': 'list_teams'}).execute({})


@pytest.mark.parametrize('config,error', [
    ({'operation': 'update_contact', 'contact_id': '24359'}, 'at least one field'),
    ({'operation': 'update_contact', 'contact_id': '24359', 'custom_attributes_json': '[]'}, 'JSON object'),
    ({'operation': 'update_contact', 'contact_id': '24359', 'custom_attributes_json': '{'}, 'valid JSON'),
    ({'operation': 'update_contact', 'contact_id': '24359', 'custom_attributes_json': '{"x":3}'}, 'must be strings'),
    ({'operation': 'create_order', **FIXTURES['create_order']['config'], 'line_items_json': '{}'}, 'nonempty JSON array'),
    ({'operation': 'create_order', **FIXTURES['create_order']['config'], 'line_items_json': '[]'}, 'nonempty JSON array'),
    ({'operation': 'create_order', **FIXTURES['create_order']['config'], 'line_items_json': 'no'}, 'valid JSON'),
    ({'operation': 'create_order', **FIXTURES['create_order']['config'], 'line_items_json': '[{"quantity":1}]'}, 'variant_id'),
    ({'operation': 'create_order', **FIXTURES['create_order']['config'], 'line_items_json': '[{"quantity":0,"variant_id":15,"products_price_id":23}]'}, 'quantity'),
    ({'operation': 'create_invoice', **FIXTURES['create_invoice']['config'], 'line_items_json': '[{"quantity":1,"variant_id":123,"products_price_id":456}]'}, 'amount string'),
])
async def test_invalid_writes_make_no_request(monkeypatch, config, error):
    def forbidden(req):
        pytest.fail('Invalid local inputs reached the provider')
    transport(monkeypatch, forbidden)
    with pytest.raises(ValueError, match=error):
        await node(config).execute({})


@pytest.mark.parametrize('slug,expected', [('acme', 'acme'), (' ACME ', 'acme'),
    ('https://acme.myclickfunnels.com/account/workspaces/42', 'acme'), ('acme.myclickfunnels.com', 'acme')])
def test_workspace_normalization(slug, expected):
    assert ClickFunnelsAPIKeyCredential(api_key='test', workspace_subdomain=slug).workspace_subdomain == expected


@pytest.mark.parametrize('slug', ['accounts', 'agents', 'https://example.com', 'https://a.b.myclickfunnels.com',
    'http://acme.myclickfunnels.com', 'https://user:pass@acme.myclickfunnels.com', 'acme:443', 'acme.myclickfunnels.com.evil.test', ''])
def test_invalid_workspace(slug):
    with pytest.raises(ValidationError):
        ClickFunnelsAPIKeyCredential(api_key='test', workspace_subdomain=slug)


@pytest.mark.parametrize('config', [
    {'operation': 'get_contact', 'contact_id': '../teams'}, {'operation': 'get_order', 'order_id': '42?other=1'},
    {'operation': 'list_contacts', 'workspace_id': '4', 'per_page': 0}, {'operation': 'create_contact', 'workspace_id': '4'},
    {'operation': 'create_enrollment', 'course_id': '19', 'contact_id': 0},
    {'operation': 'create_invoice', **{k:v for k,v in FIXTURES['create_invoice']['config'].items() if k != 'paid_at'}},
])
def test_invalid_config(config):
    with pytest.raises(ValidationError):
        node(config)


async def test_missing_credential():
    with pytest.raises(ValueError, match='Connect a ClickFunnels API key'):
        await node({'operation': 'list_teams'}, credentials=None).execute({})


async def test_picker_and_connection_evidence(monkeypatch):
    seen = []
    def respond(req):
        seen.append(req)
        assert req.url.host == 'accounts.myclickfunnels.com'
        assert req.url.path == '/api/v2/teams'
        return httpx.Response(200, json=FIXTURES['list_teams']['response'])
    transport(monkeypatch, respond)
    options = await ClickFunnelsNode.load_field_options('team_id', CREDENTIAL)
    assert options[0] == {'value': '42000', 'label': 'Example Team'}
    assert await ClickFunnelsNode.load_field_options('unknown', CREDENTIAL) == []
    assert await ClickFunnelsNode.load_field_options('team_id', CREDENTIAL, search='no-match') == []
    evidence = await collect_evidence(node_type='automation-clickfunnels', user_id='test', credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert evidence.answers_field == 'team_id'
    assert len(seen) == 3


async def test_rejected_key_has_no_evidence(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(401, json={'error': 'API key missing or invalid'}))
    evidence = await collect_evidence(node_type='automation-clickfunnels', user_id='test', credential_data=CREDENTIAL)
    assert evidence.reachable is False
    assert 'API key missing or invalid' in evidence.error

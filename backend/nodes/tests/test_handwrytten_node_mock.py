"""Exercise the real Handwrytten node with intercepted HTTP requests.

Provider-schema examples cover every route; negative cases protect connect-time
account evidence and prevent accidental retrying or leaking session tokens.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import handwrytten_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'owned-handwrytten-session-token'
EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/handwrytten/v1_examples.json').read_text())['responses']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {'credential_type': 'handwrytten_session_token', 'session_token': TOKEN}


def node(config, creds=None):
    return NodeFactory.create_node(node_id='handwrytten-test', node_type='automation-handwrytten',
        node_data={'config': config, 'credentials': credential() if creds is None else creds})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    # Realistic values from the v1 contract's per-property examples.
    values = {'address_id': 42, 'id': 549494, 'card_id': 3404, 'template_id': 12,
        'name': 'Joe Smith', 'message': 'Dear Frank,\nThank you so much for your interest in our services.\nYours,\nJoe',
        'font_label': 'Chill Charity', 'sender_name': 'Joe Sender', 'sender_address1': '1430 E Indian School Road',
        'sender_city': 'Phoenix', 'sender_state': 'AZ', 'sender_zip': '12345', 'recipient_name': 'Cosmo Spacely',
        'recipient_address1': '123 E Main Street', 'recipient_city': 'Burlington', 'recipient_state': 'ON',
        'recipient_zip': 'L7L 0E9', 'credit_card_id': 34124, 'address1': '1430 E Indian School Rd',
        'city': 'Phoenix', 'zip': '85014', 'type': 'text', 'header_text': 'Sample text for the header'}
    schema = native.HandwryttenFullConfig.model_json_schema()
    shape = next(v for v in schema['$defs'].values() if v.get('properties', {}).get('operation', {}).get('const') == operation)
    config = {'operation': operation, **{key: values[key] for key in shape.get('required', []) if key != 'operation'}}
    if operation.startswith('update_'):
        config['name'] = 'Joe Smith'
    if operation == 'send_card':
        config.update(sender_state='AZ', recipient_state='ON')
    if operation == 'create_custom_card':
        config['header_text'] = values['header_text']
    return config


@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_every_operation_has_exact_route_method_and_body(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    requests = transport(monkeypatch, EXAMPLES[method + ' ' + path])
    cfg = config_for(operation)
    result = await node(cfg).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url) == native.BASE_URL + path
    assert 'authorization' not in request.headers
    assert TOKEN not in str(result)
    if method == 'POST':
        assert json.loads(request.content) == {key: value for key, value in cfg.items() if key != 'operation'} | {'uid': TOKEN}
    else:
        assert request.content == b''


async def test_recipient_evidence_preserves_account_specific_labels(monkeypatch):
    requests = transport(monkeypatch, [{'id': 549494, 'name': 'Joe Smith', 'city': 'Phoenix'}])
    result = await node({'operation': 'list_recipients'}).run({})
    assert result['data'][0]['name'] == 'Joe Smith'
    assert native.HandwryttenNode.connection_evidence.operation == 'list_recipients'
    assert len(requests) == 1


@pytest.mark.parametrize('body', [
    {'status': 'error', 'message': 'Invalid UID'},
    {'error': TOKEN}, {'success': False}, {'httpCode': 401, 'message': 'Unauthorized'},
])
async def test_error_envelopes_do_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_recipients'}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize('response', [
    httpx.Response(401, json={'message': 'Rejected ' + TOKEN}),
    httpx.Response(302, headers={'location': 'https://other.example'}),
    httpx.Response(200, text='<html>login</html>', headers={'content-type': 'text/html'}),
    httpx.Response(200, content=b'{invalid', headers={'content-type': 'application/json'}),
    httpx.Response(200, json='unexpected'),
    httpx.ReadTimeout('timeout ' + TOKEN),
])
async def test_failure_is_redacted_and_not_retried(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError) as exc:
        await node(config_for('send_card')).execute({})
    assert len(requests) == 1 and TOKEN not in str(exc.value)


async def test_nested_token_echo_is_redacted(monkeypatch):
    transport(monkeypatch, {'status': 'ok', 'uid': TOKEN, 'response': {'password': TOKEN, 'description': 'echo ' + TOKEN}})
    result = await node({'operation': 'get_return_address'}).execute({})
    assert TOKEN not in str(result) and 'uid' not in result['data'] and 'password' not in result['data']['response']


@pytest.mark.parametrize('config', [
    {'operation': 'send_card'},
    {'operation': 'delete_recipient'},
    {'operation': 'update_template', 'template_id': 12},
    {'operation': 'create_recipient', 'name': 'Joe Smith', 'address1': '1430 E Indian School Rd', 'city': 'Phoenix', 'zip': '85014', 'country': 'United States', 'country_id': 1},
    {'operation': 'create_custom_card', 'card_id': 243, 'name': 'my custom card design', 'type': 'logo'},
    {'operation': 'list_recipients', 'uid': 'foreign-token'},
])
def test_missing_fields_ambiguous_countries_and_auth_override_are_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize('value', ['', 'https://example.com/token', '<token>', 'has spaces', 'line\nbreak'])
def test_credential_rejects_placeholder_urls_and_controls(value):
    with pytest.raises(ValueError):
        native.HandwryttenSessionToken(session_token=value)


@pytest.mark.parametrize('body', [{}, {'status': 'ok'}, [42], None])
async def test_recipient_evidence_rejects_non_list_or_non_object_rows(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_recipients'}).execute({})

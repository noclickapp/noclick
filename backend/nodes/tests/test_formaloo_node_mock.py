"""Offline request contracts and provider-authored webhook examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import formaloo_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "formaloo_api_token", "api_key": "test-formaloo-key-42", "authorization_token": "test-formaloo-jwt-42"}
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/formaloo/operations.json').read_text())['operations']
EVENTS = json.loads((Path(__file__).parent / 'fixtures/formaloo/events.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="formaloo-test", node_type="automation-formaloo", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, data=None, status=200, errors=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json={"status": status, "errors": errors or {"general_errors": [], "form_errors": {}}, "data": data or {}})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.OPERATIONS))
async def test_each_operation_dispatches_one_documented_endpoint(monkeypatch, operation):
    spec = native.OPERATIONS[operation]
    config = {'operation': operation}
    for key, field in native.CONFIG_MODELS[operation].model_fields.items():
        if field.is_required():
            config[key] = '{"field_tClRSgaU":"Joh Doe"}' if key == 'values_json' else 'example-slug' if key.endswith('_slug') else 'Example title'
    requests = transport(monkeypatch, {'profile': {'username': 'example'}})
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == CONTRACT[operation]['method']
    path = CONTRACT[operation]['path']
    import re
    path = re.sub(r'\{[^}]+\}', 'example-slug', path)
    assert request.url.path == path
    assert request.headers['x-api-key'] == CREDENTIAL['api_key']
    assert request.headers['authorization'] == 'JWT ' + CREDENTIAL['authorization_token']
    if 'values_json' in config:
        assert json.loads(request.content) == json.loads(config['values_json'])
    if operation.startswith('list_') and 'page' in spec.fields:
        assert request.url.params['page'] == '1'
        assert request.url.params['page_size'] == '50'


@pytest.mark.asyncio
async def test_profile_and_error_redaction(monkeypatch):
    transport(monkeypatch, {'profile': {'username': 'jane'}})
    assert (await node({'operation':'get_profile'}).execute({}))['data']['profile']['username'] == 'jane'
    transport(monkeypatch, status=401, errors={'general_errors': [CREDENTIAL['api_key']]})
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_profile'}).execute({})
    assert CREDENTIAL['api_key'] not in str(exc.value)
    assert '401' in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('event', list(EVENTS))
async def test_documented_events_and_exact_header_authentication(monkeypatch, event):
    requests = transport(monkeypatch, {'webhook': {'slug':'FVyTMf7o'}}, status=201)
    config = {'operation':'on_submission_event','form_slug':'contact-form','event_type':event}
    state = await native.FormalooNode._register_external_webhook(webhook_url='https://example.net/webhook/', credential=CREDENTIAL, config=config, node_id='example')
    body = json.loads(requests[0].content)
    assert body['url'] == 'https://example.net/webhook/'
    assert body[native.EVENTS[event]] is True
    assert sum(body[field] for field in native.EVENTS.values()) == 1
    secret = state['signing_secret']
    assert body['secret'] == secret
    verify = native.FormalooNode.verify_webhook_signature
    assert verify(b'{}', {'X-Formaloo-Token':secret}, state)
    assert not verify(b'{}', {}, state)
    assert not verify(b'{}', {'X-Formaloo-Token':'wrong'}, state)
    assert not verify(b'{}', {'X-Formaloo-Token':secret}, {})
    output = await node(config).execute(EVENTS[event]['body'])
    turn = native.FormalooNode.resolve_agent_event(output)
    assert 'Joh Doe' in turn['text'] and 'ZNtjCuScAjt349Rf' in turn['text']
    assert turn['conversation_key'] == 'ZNtjCuScAjt349Rf'
    await native.FormalooNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **state}, node_id='example')
    assert requests[-1].method == 'DELETE'
    assert requests[-1].url.path == '/v3.0/forms/contact-form/webhooks/FVyTMf7o/'


def test_hand_connect_default_and_input_validation():
    assert native.FormalooCredential.model_validate({k:v for k,v in CREDENTIAL.items() if k != 'credential_type'}).credential_type == 'formaloo_api_token'
    for value in ('not-json', '[]', '{}'):
        with pytest.raises(ValidationError):
            native.CONFIG_MODELS['create_submission'](form_slug='example', values_json=value)
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS['get_form'](form_slug='../profile')

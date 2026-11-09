"""Exercise Cvent through discovery, real Pydantic config and mocked HTTP."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from nodes import cvent_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.cvent_oauth import OAUTH_PROVIDER

ID = "04ca6ae2-0dc3-487b-953e-86d6abbdf7d3"
INPUTS = json.loads((Path(__file__).parent / "fixtures/cvent/documented_inputs.json").read_text())
TOKEN = "cvent-synthetic-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, credential=None, **changes):
    config = {"operation": operation, **INPUTS.get(operation, {}).get("config", {}), **changes}
    return NodeFactory.create_node(node_id="cvent-test", node_type="automation-cvent", node_data={
        "config": config, "credentials": credential or {"credential_type": "cvent_oauth", "access_token": TOKEN}})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.CVENT_OPERATIONS)
async def test_all_operations_send_exact_routes_and_whole_json(monkeypatch, operation):
    spec = native.CVENT_OPERATIONS[operation]
    is_delete = spec['method'] == 'DELETE'
    body = {"paging": {"nextToken": "next-page"}, "data": [{"id": ID, "title": "Cvent Connect 2020"}]}
    requests = transport(monkeypatch, lambda req: httpx.Response(204) if is_delete else httpx.Response(200, json=body))
    result = await node(operation).execute({})
    request = requests[0]
    assert len(requests) == 1 and request.method == spec["method"]
    assert request.url.host == "api-platform.cvent.com"
    assert request.url.path == "/ea" + spec["path"].replace("{id}", ID).replace("{attendeeId}", ID)
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if spec.get('body_type'):
        assert json.loads(request.content) == INPUTS[operation]['config']['payload']
    else:
        assert request.content == b''
    assert result['data'] == (None if is_delete else body)
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_manual_client_credentials_exchange_form_basic_and_evidence(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/oauth2/token'):
            assert request.headers['Authorization'] == 'Basic Y2xpZW50OnNlY3JldA=='
            form = parse_qs(request.content.decode())
            assert form['client_id'] == ['client'] and form['grant_type'] == ['client_credentials']
            assert set(form['scope'][0].split()) == set(native.CVENT_SCOPES.declared_scopes())
            return httpx.Response(200, json={'access_token': TOKEN, 'expires_in': 3600})
        assert request.url.path == '/ea/events'
        return httpx.Response(200, json={'data': [{'id': ID, 'title': 'Cvent Connect 2020'}]})
    requests = transport(monkeypatch, handler)
    result = await node('list_events', credential={'credential_type': 'cvent_client_credentials', 'client_id': 'client', 'client_secret': 'secret'}).execute({})
    assert len(requests) == 2 and result['data']['data'][0]['id'] == ID
    assert native.CventNode.connection_evidence.operation == 'list_events'


@pytest.mark.asyncio
async def test_paging_filters_and_expand_query_preserve_provider_token(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={'data': [], 'paging': {'nextToken': 'next'}}))
    result = await node('list_attendees', limit=20, token='cursor+/=', filter="contact.id eq '" + ID + "'", expand=['answers.question','registrationType']).execute({})
    params = requests[0].url.params
    assert params['token'] == 'cursor+/=' and params['limit'] == '20'
    assert params.get_list('expand') == ['answers.question', 'registrationType']
    assert 'event/registration-types:read' in native.CVENT_SCOPES.declared_scopes()
    assert result['data']['paging']['nextToken'] == 'next' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_redirects_and_http_errors_never_report_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={'message': 'Rejected ' + TOKEN}, headers={'Location':'https://example.org'}))
    with pytest.raises((httpx.HTTPStatusError, ValueError)) as error:
        await node('list_events').execute({})
    if status >= 400:
        assert 'Rejected' in str(error.value)
        assert TOKEN not in str(error.value)
    assert len(requests) == 1


def test_oauth_contract_identity_and_required_client_id(monkeypatch):
    monkeypatch.setenv('CVENT_CLIENT_ID','registered-client')
    monkeypatch.setenv('CVENT_CLIENT_SECRET','registered-secret')
    for grant in ({'grant_type':'authorization_code','code':'test-code','redirect_uri':'https://example.com/redirect'}, {'grant_type':'refresh_token','refresh_token':'test-refresh'}):
        request = OAUTH_PROVIDER.token_request(grant)
        assert request['data']['client_id'] == 'registered-client'
        assert request['auth'] is not None
    assert OAUTH_PROVIDER.identity_url.endswith('/users?limit=1')
    assert OAUTH_PROVIDER.name_field == 'data.0.contact.email'


def test_credential_defaults_and_config_validation():
    assert native.CventClientCredential(client_id='client',client_secret='secret').credential_type == 'cvent_client_credentials'
    assert native.CventOAuthCredential(access_token=TOKEN).credential_type == 'cvent_oauth'
    for operation, changes in [('get_event', {'id':'../events'}), ('create_contacts',{'payload':{}}), ('create_contacts',{'payload':'not JSON'}), ('get_attendee',{'expand':'arbitrary'}), ('list_events',{'limit':201})]:
        with pytest.raises(ValueError):
            node(operation, **changes)


@pytest.mark.asyncio
async def test_client_secret_is_redacted_when_token_exchange_is_rejected(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(401, json={'message': 'Denied client-private-secret'}))
    with pytest.raises(httpx.HTTPStatusError) as error:
        await node('list_events', credential={'client_id':'client', 'client_secret':'client-private-secret'}).execute({})
    assert 'Denied' in str(error.value) and 'private-secret' not in str(error.value)
    assert len(requests) == 1


def test_json_payload_uses_a_textarea_and_accepts_pasted_json():
    model = native.CVENT_CONFIGS['create_contacts']
    field = model.model_json_schema()['properties']['payload']
    assert field['type'] == 'string' and field['ui:widget'] == 'textarea'
    config = model(payload='[{"firstName":"Henry"}]')
    assert json.loads(config.payload) == [{'firstName':'Henry'}]

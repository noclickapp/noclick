"""Request/response coverage against Xama's own documented v0.1 shapes."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import xama_hub_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / "fixtures/xama-hub/contract.json").read_text())
AUTH = {"credential_type": native.TYPE, "tenant_id": "my_client_1234", "access_token": "fixture-secret-token"}
PERSON = FIXTURE["contact"]


def node(config):
    return NodeFactory.create_node(node_id="xama-test", node_type="automation-xama-hub",
        node_data={"config": config, "credentials": AUTH})


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "xamahub.xamatech.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        code, body = responses.pop(0)
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)
    original = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


def config_for(operation):
    cfg = {"operation": operation}
    if '{account_id}' in native.OPERATIONS[operation][1]: cfg['account_id'] = 'account-1'
    if '{contact_id}' in native.OPERATIONS[operation][1]: cfg['contact_id'] = 'contact-1'
    if operation == 'get_risk_assessment': cfg['risk_assessment_id'] = 'assessment-1'
    if operation in {'create_contact', 'replace_contact', 'create_account'}: cfg.update(PERSON)
    if operation == 'create_account': cfg.update(name='My Fancy Account Name', account_type='COMPANY')
    if operation in {'patch_account', 'patch_contact'}: cfg['status'] = 'ARCHIVED'
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.OPERATIONS)
async def test_each_operation_uses_one_contract_request(operation, transport):
    requests, responses = transport
    method, template, status = native.OPERATIONS[operation]
    cfg = config_for(operation)
    if operation.startswith('list_'):
        body = {'items': [], 'page': 1, 'page_size': 100, 'result_size': 0}
    elif operation == 'get_client': body = FIXTURE['client']
    else: body = {'id': 'resource-1', 'status': 'IN_PROGRESS'}
    responses.append((status, None if status == 204 else body))
    result = await node(cfg).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == template.format(tenant_id=AUTH['tenant_id'], account_id='account-1', contact_id='contact-1', risk_assessment_id='assessment-1')
    payload = json.loads(request.content) if request.content else None
    if operation == 'create_account':
        assert payload == {'name': cfg['name'], 'type': 'COMPANY', 'primary_contact': PERSON}
    elif operation in {'create_contact', 'replace_contact'}:
        assert payload == {**PERSON, **({'id': 'contact-1'} if operation == 'replace_contact' else {})}
    elif operation in {'patch_account', 'patch_contact'}: assert payload == {'status': 'ARCHIVED'}
    elif operation.startswith('initiate_'): assert payload == {'trigger_lookup': True}
    elif operation == 'create_risk_assessment': assert payload == {'status': 'IN_PROGRESS'}
    else: assert payload is None
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'page': '1', 'page_size': '100'}
        assert result['has_more'] is False and result['page_only'] is True


@pytest.mark.asyncio
async def test_notification_header_and_replacement_id(transport):
    requests, responses = transport
    responses.append((201, {'id': 'contact-1'}))
    cfg = config_for('create_contact');cfg['suppress_notifications'] = True
    await node(cfg).execute({})
    assert requests[0].headers['X-Suppress-Notifications'] == 'true'
    assert 'suppressNotifications' not in requests[0].url.params


@pytest.mark.asyncio
async def test_page_two_and_honest_full_page_without_totals(transport):
    requests, responses = transport
    responses.append((200, {'items': [{'id': 'a'}], 'page': 2, 'page_size': 1, 'result_size': 1}))
    result = await node({'operation': 'list_risk_assessments', 'account_id': 'a', 'page': 2, 'page_size': 1}).execute({})
    assert result['has_more'] is None and result['next_page'] == 3
    assert requests[0].url.params['page'] == '2'
    responses.append((200, {'items': [{'id': 'a'}], 'page': 1, 'total_pages': 2}))
    assert (await node({'operation': 'list_accounts'}).execute({}))['has_more'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 409, 422, 429, 500])
async def test_provider_errors_are_not_success_and_do_not_retry_writes(code, transport):
    requests, responses = transport
    responses.append((code, {'detail': 'Rejected ' + AUTH['access_token']}))
    result = await node(config_for('create_contact')).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert AUTH['access_token'] not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'error': 'bad'}, {'items': None}, {'items': ['not a record']}])
async def test_malformed_pages_fail(body, transport):
    _, responses = transport;responses.append((200, body))
    assert (await node({'operation': 'list_accounts'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'get_account', 'account_id': '../other'},
    {'operation': 'list_accounts', 'page': 0},
    {'operation': 'list_accounts', 'page_size': 101},
    {'operation': 'create_contact', 'account_id': 'a', **PERSON, 'email': 'invalid'},
    {'operation': 'replace_contact', 'account_id': 'a', 'contact_id': 'c'},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises((ValueError, ValidationError)): node(config)


def test_manual_credential_default_and_schema():
    assert native.XamaHubBearerTokenCredential(tenant_id='tenant', access_token='secret').credential_type == native.TYPE
    schema = native.XamaHubConfig.model_json_schema()
    credential = schema['$defs']['XamaHubBearerTokenCredential']
    assert credential['required'] == ['tenant_id', 'access_token']
    assert credential['properties']['access_token']['ui:widget'] == 'password'
    assert len(native.OPERATIONS) == 21

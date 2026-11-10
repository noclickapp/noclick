"""ServiceM8's native factory against provider-published response examples.

The HTTP boundary is replaced, while credential parsing, routing, bodies, errors
and webhook lifecycle hooks run unchanged. No ServiceM8 account is contacted.
"""
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import servicem8_node as sm
from nodes.core.run_op import run_node_operation

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/servicem8/provider_examples.json').read_text())
AUTH = {"credential_type": sm.TYPE, "api_key": "fixture-servicem8-api-key"}
IDENTIFIER = "de305d54-75b4-431b-adb2-eb6b9e546013"
OTHER = "123e4567-ea2f-49a7-8608-589e8dfe228e"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    async def send(request):
        calls.append(request)
        assert request.url.host == 'api.servicem8.com'
        assert request.headers['x-api-key'] == AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        status, body, *headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers[0] if headers else {})
    native = httpx.AsyncClient
    monkeypatch.setattr(sm.httpx, 'AsyncClient', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type='automation-servicem8', operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id='00000000-0000-4000-8000-000000000001')


CASES = [
    ('get_account', {}, 'GET', '/vendor.json'),
    ('list_jobs', {}, 'GET', '/job.json'),
    ('get_job', {'job_uuid': IDENTIFIER}, 'GET', '/job/{uuid}.json'),
    ('create_job', {'status': 'Work Order', 'job_description': 'Repair tap'}, 'POST', '/job.json'),
    ('update_job', {'job_uuid': IDENTIFIER, 'status': 'Completed', 'work_done_description': 'Repaired tap'}, 'POST', '/job/{uuid}.json'),
    ('list_clients', {}, 'GET', '/company.json'),
    ('get_client', {'company_uuid': IDENTIFIER}, 'GET', '/company/{uuid}.json'),
    ('create_client', {'name': 'Example Client'}, 'POST', '/company.json'),
    ('update_client', {'company_uuid': IDENTIFIER, 'name': 'Example Client', 'address': 'New address'}, 'POST', '/company/{uuid}.json'),
    ('list_contacts', {}, 'GET', '/companycontact.json'),
    ('get_contact', {'contact_uuid': IDENTIFIER}, 'GET', '/companycontact/{uuid}.json'),
    ('create_contact', {'company_uuid': IDENTIFIER, 'first': 'Jane', 'email': 'name@example.com'}, 'POST', '/companycontact.json'),
    ('update_contact', {'contact_uuid': IDENTIFIER, 'company_uuid': OTHER, 'mobile': '+61400000000'}, 'POST', '/companycontact/{uuid}.json'),
    ('list_notes', {}, 'GET', '/note.json'),
    ('create_note', {'related_object': 'job', 'related_object_uuid': IDENTIFIER, 'note': 'Parts ordered'}, 'POST', '/note.json'),
    ('list_job_activities', {}, 'GET', '/jobactivity.json'),
    ('create_job_activity', {'job_uuid': IDENTIFIER, 'staff_uuid': OTHER, 'start_date': '2025-01-01 12:00:00', 'end_date': '2025-01-01 13:00:00'}, 'POST', '/jobactivity.json'),
    ('update_job_activity', {'activity_uuid': IDENTIFIER, 'job_uuid': IDENTIFIER, 'staff_uuid': OTHER, 'start_date': '2025-01-01 12:00:00', 'end_date': '2025-01-01 13:00:00'}, 'POST', '/jobactivity/{uuid}.json'),
    ('list_job_payments', {}, 'GET', '/jobpayment.json'),
    ('create_job_payment', {'job_uuid': IDENTIFIER, 'amount': '125.00', 'method': 'Cash'}, 'POST', '/jobpayment.json'),
    ('list_tasks', {}, 'GET', '/task.json'),
    ('create_task', {'name': 'Order parts', 'task_complete': '0'}, 'POST', '/task.json'),
    ('update_task', {'task_uuid': IDENTIFIER, 'name': 'Order parts', 'task_complete': '1'}, 'POST', '/task/{uuid}.json'),
    ('list_staff', {}, 'GET', '/staff.json'),
]


@pytest.mark.parametrize('operation,arguments,method,path', CASES)
@pytest.mark.asyncio
async def test_servicem8_native_operations(transport, operation, arguments, method, path):
    calls, replies = transport
    body = EXAMPLES[method + ' ' + path]['body']
    replies.append((200, body, {'x-record-uuid': IDENTIFIER} if method == 'POST' else {}))
    result = await run(operation, arguments)
    assert result['status'] == 'success'
    assert result['data'] == body
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.path == '/api_1.0' + path.replace('{uuid}', IDENTIFIER)
    if method == 'POST':
        sent = json.loads(request.content)
        assert 'operation' not in sent
        # Route UUIDs must not leak into API bodies under NoClick field names.
        for field in ('contact_uuid', 'activity_uuid', 'task_uuid'):
            assert field not in sent
        assert result['record_uuid'] == IDENTIFIER
        for key, value in arguments.items():
            if key not in ('contact_uuid', 'activity_uuid', 'task_uuid') and not (key in ('job_uuid', 'company_uuid') and '{uuid}' in path):
                assert sent[key] == value
        if 'jobactivity' in path:
            assert sent['activity_was_scheduled'] == '1'
    assert not replies


@pytest.mark.asyncio
async def test_servicem8_filter_is_encoded_once(transport):
    calls, replies = transport
    replies.append((200, []))
    expression = "company_uuid eq '" + IDENTIFIER + "' and active eq 1"
    await run('list_jobs', {'filter': expression})
    assert calls[0].url.params['$filter'] == expression
    assert set(calls[0].url.params) == {'$filter'}


@pytest.mark.parametrize('status,body', [(401, {'errorCode': 401, 'message': 'Authentication failed'}),
    (200, {'errorCode': 1000, 'message': 'An error occurred'}),
    (429, {'message': 'Number of allowed API requests per minute exceeded'})])
@pytest.mark.asyncio
async def test_servicem8_errors_are_not_success(transport, status, body):
    calls, replies = transport
    replies.append((status, body))
    with pytest.raises(ValueError, match=body['message']):
        await sm.ServiceM8Node._request(AUTH, 'GET', '/api_1.0/vendor.json')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_servicem8_dropdowns(transport):
    calls, replies = transport
    rows = EXAMPLES['GET /company.json']['body']
    replies.append((200, rows))
    result = await sm.ServiceM8Node.load_field_options('company_uuid', AUTH)
    assert result == [{'value': rows[0]['uuid'], 'label': rows[0]['name']}]
    assert calls[0].url.params['$filter'] == 'active eq 1'


@pytest.mark.parametrize('operation,arguments', [('get_job', {'job_uuid': '../vendor'}),
    ('update_job', {'job_uuid': IDENTIFIER}), ('create_client', {}),
    ('create_task', {}), ('create_job', {'status': 'Invalid'})])
def test_servicem8_required_contract_fields(operation, arguments):
    with pytest.raises(ValidationError):
        sm.ServiceM8NodeConfig.model_validate({'config': {'operation': operation, **arguments}, 'credentials': AUTH})


def test_servicem8_manual_connect_and_trigger_no_event():
    credential = sm.ServiceM8Credential(api_key=AUTH['api_key'])
    assert credential.credential_type == sm.TYPE
    config = sm.ServiceM8NodeConfig.model_validate({'config': {'operation': 'on_job_changed'}, 'credentials': AUTH})
    node = sm.ServiceM8Node('n', 'automation-servicem8', {}, config=config, sio=Mock())
    assert node.connection_evidence.operation == 'get_account'


@pytest.mark.asyncio
async def test_servicem8_manual_trigger_run_has_no_event():
    config = sm.ServiceM8NodeConfig.model_validate({'config': {'operation': 'on_job_changed'}, 'credentials': AUTH})
    node = sm.ServiceM8Node('n', 'automation-servicem8', {}, config=config, sio=Mock())
    result = await node.execute({'unrelated': 'must not become an event'})
    assert result['status'] == 'no_event'
    assert 'must not become an event' not in str(result)


@pytest.mark.asyncio
async def test_servicem8_webhook_register_deliver_teardown(transport):
    calls, replies = transport
    url = 'https://test.hooks.example.test/test'
    config = {'operation': 'on_job_changed', 'webhook_url': url}
    replies.append((200, {'success': True}))
    registration = await sm.ServiceM8Node._register_external_webhook(webhook_url=url, credential=AUTH, config=config, node_id='node-1')
    config.update(registration)
    assert calls[0].url.path == '/webhook_subscriptions/object'
    form = parse_qs(calls[0].content.decode())
    assert form['object'] == ['job'] and form['callback_url'] == [url]
    assert form['unique_id'] == ['noclick-node-1']
    assert {'uuid', 'status', 'job_description', 'badges', 'generated_job_id'} <= set(form['fields'][0].split(','))
    event = deepcopy(EXAMPLES['job.changed']['body'])
    assert sm.ServiceM8Node.verify_webhook_signature(json.dumps(event).encode(), {}, config)
    assert sm.ServiceM8Node.filter_trigger_payload(event, config)
    assert not sm.ServiceM8Node.filter_trigger_payload({'object': 'company', 'entry': event['entry']}, config)
    output = sm.ServiceM8Node.resolve_trigger_payload(event, config)
    agent = sm.ServiceM8Node.resolve_agent_event(output)
    assert agent['conversation_key'] == event['entry'][0]['uuid']
    for value in ['badges', 'generated_job_id', '2015-01-01', 'get_job', 'update_job', 'Actor and new field values are not included']:
        assert value in agent['text']
    # Deletion discovers the provider UUID and deletes only this node's own subscription.
    rows = [{'uuid': IDENTIFIER, 'type': 'object', 'object': 'job', 'unique_id': 'noclick-node-1', 'callback_url': url},
            {'uuid': OTHER, 'type': 'object', 'object': 'job', 'unique_id': 'another-integration', 'callback_url': url}]
    replies.extend([(200, rows), (200, {'success': True})])
    await sm.ServiceM8Node._unregister_external_webhook(credential=AUTH, config=config, node_id='node-1')
    assert calls[1].url.params['status'] == 'all'
    assert calls[2].method == 'DELETE'
    assert calls[2].url.path == '/webhook_subscriptions/' + IDENTIFIER
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_servicem8_failed_webhook_registration(transport):
    calls, replies = transport
    replies.append((200, {'success': False, 'message': 'Subscription refused'}))
    with pytest.raises(ValueError, match='Subscription refused'):
        await sm.ServiceM8Node._register_external_webhook(webhook_url='https://test.hooks.example.test/test', credential=AUTH, config={}, node_id='n')

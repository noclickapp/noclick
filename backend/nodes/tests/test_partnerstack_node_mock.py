"""Run PartnerStack operations through the native factory with HTTP fixtures."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import partnerstack_node as ps
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/partnerstack/operations.json').read_text())
AUTH = {'credential_type': 'partnerstack_api_keys', 'public_key': 'fixture-public-key', 'secret_key': 'fixture-secret-key'}
USER = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.partnerstack.com'
        assert request.headers['authorization'] == 'Basic Zml4dHVyZS1wdWJsaWMta2V5OmZpeHR1cmUtc2VjcmV0LWtleQ=='
        assert 'fixture-' not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=body) if isinstance(body, bytes) else httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(ps, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type='automation-partnerstack', operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER)


def envelope(data):
    return {'status': 200, 'message': 'success', 'data': data}


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'])
async def test_operation_request_and_response(transport, case):
    requests, replies = transport
    listed = case['operation'].startswith('list_')
    data = {'has_more': True, 'items': [{'key': 'record_123', 'name': 'Test group'}]} if listed else {'key': 'record_123'}
    replies.append((200, envelope(data)))
    output = await run(case['operation'], case['arguments'])
    assert output['status'] == 'success'
    assert output['data'] == data
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case['method']
    if case['path_field']:
        assert request.url.path.endswith('/' + case['arguments'][case['path_field']])
    else:
        assert request.url.path == '/api' + case['path']
    if listed:
        assert request.url.params['limit'] == '10'
        assert output['next_starting_after'] == 'record_123' and output['has_more']
    elif case['method'] in {'POST', 'PATCH'}:
        body = json.loads(request.content)
        assert body == {key: value for key, value in case['arguments'].items() if key != case['path_field']} | ({'notify_by_email': False} if case['operation'] == 'create_partnership' else {})
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_page_and_filters_are_sent_without_automatic_fetch(transport):
    requests, replies = transport
    replies.append((200, envelope({'items': [], 'has_more': False})))
    output = await run('list_customers', {'limit': 250, 'starting_after': 'cus_123', 'partner_key': 'gstest', 'min_created': 1538062487765})
    assert dict(requests[0].url.params) == {'limit': '250', 'starting_after': 'cus_123', 'partner_key': 'gstest', 'min_created': '1538062487765'}
    assert output['items'] == [] and output['next_starting_after'] is None
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_external_customer_key_update_is_not_used_as_the_path(transport):
    requests, replies = transport
    replies.append((200, envelope({'key': 'cus_123', 'customer_key': 'external_new'})))
    await run('update_customer', {'customer_id': 'cus_123', 'customer_key': 'external_new'})
    assert requests[0].url.path == '/api/v2/customers/cus_123'
    assert json.loads(requests[0].content) == {'customer_key': 'external_new'}


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body', [
    (401, {'status': 401, 'message': 'Invalid API keys fixture-secret-key'}),
    (200, {'status': 401, 'message': 'Invalid API keys fixture-secret-key'}),
    (429, {'status': 429, 'message': 'Rate limit exceeded'}),
    (302, {'status': 302, 'message': 'Moved'}),
    (200, b'<html>Not JSON</html>'),
    (200, {'data': {}}),
    (200, envelope({'items': 'bad', 'has_more': False})),
])
async def test_failure_never_claims_success_or_exposes_secrets(transport, code, body):
    requests, replies = transport
    replies.append((code, body))
    result = await run('list_groups')
    assert result['status'] == 'error' and 'fixture-secret-key' not in json.dumps(result)
    if code == 401:
        assert result['error'] == 'Invalid API keys [redacted]'
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('identifier', ['../x', 'a/b', 'x%2Fy', 'https://example.com', '..'])
async def test_invalid_identifiers_do_not_reach_transport(transport, identifier):
    with pytest.raises(ValueError):
        await run('get_customer', {'customer_id': identifier})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('op,args', [
    ('list_customers', {'limit': 251}),
    ('list_customers', {'starting_after': 'a', 'ending_before': 'b'}),
    ('update_customer', {'customer_id': 'cus_123'}),
    ('create_lead', {'external_key': 'lead_123', 'partner_key': 'gstest', 'meta': {}}),
    ('create_transaction', {'amount': 50000000001, 'currency': 'USD', 'customer_key': 'cus_123'}),
    ('create_transaction', {'amount': 100, 'currency': 'USD'}),
    ('create_lead', {'external_key': 'lead_123', 'partner_key': 'gstest', 'status': 'open', 'meta': {'first_name': 'River', 'last_name': 'Tremblay'}}),
    ('record_action', {'type': 'test', 'value': 0, 'target_type': 'customer', 'target_key': 'cus_123'}),
])
async def test_invalid_inputs_do_not_reach_transport(transport, op, args):
    with pytest.raises(ValueError):
        await run(op, args)
    assert transport[0] == []


def test_manual_credential_defaults_and_secret_validation():
    assert ps.PartnerStackAPIKeys.model_validate({k: v for k, v in AUTH.items() if k != 'credential_type'}).credential_type == 'partnerstack_api_keys'
    for key in ['public_key', 'secret_key']:
        for value in ['https://example.com/key', 'Basic key', 'a:b', 'a\nb']:
            with pytest.raises(ValidationError):
                ps.PartnerStackAPIKeys.model_validate({**AUTH, key: value})
    with pytest.raises(ValidationError):
        ps.PartnerStackAPIKeys.model_validate({**AUTH, 'credential_type': 'other_api_key'})


@pytest.mark.asyncio
async def test_account_evidence_uses_groups_read(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, envelope({'items': [{'key': 'gr_123', 'name': 'Resellers'}], 'has_more': False})))
    result = await collect_evidence(node_type='automation-partnerstack', credential_data=AUTH, user_id=USER)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ['Resellers']
    assert transport[0][0].method == 'GET' and transport[0][0].url.path == '/api/v2/groups'


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [("archive_lead", {"lead_id": "lead_123"}), ("archive_deal", {"deal_id": "deal_123"})])
async def test_archive_acknowledgement_without_data(transport, operation, arguments):
    transport[1].append((200, {"status": 200, "message": "Archived"}))
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] is None

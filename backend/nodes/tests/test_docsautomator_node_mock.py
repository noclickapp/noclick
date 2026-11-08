"""Contract-shaped requests without credentials or live provider calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import docsautomator_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'docsautomator-unit-secret-7d92'
CASES = json.loads((Path(__file__).parent / 'fixtures/docsautomator/requests.json').read_text())


def node(config):
    return NodeFactory.create_node(node_id='docsautomator-test', node_type='automation-docsautomator',
        node_data={'config': config, 'credentials': {'credential_type': 'docsautomator_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, status=200, body=None, headers=None):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {}, headers=headers)
    client = httpx.AsyncClient
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: client(transport=httpx.MockTransport(handle), **kw))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_published_operation_request(monkeypatch, case):
    requests = transport(monkeypatch, case.get('status', 200), case.get('response', {'message': 'Success'}))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == case.get('response', {'message': 'Success'})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'api.docsautomator.co'
    assert request.url.path == case['path']
    assert dict(request.url.params) == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN


@pytest.mark.asyncio
async def test_nested_placeholders_are_not_rewritten_and_async_is_accepted(monkeypatch):
    requests = transport(monkeypatch, 202, {'jobId': 'queued-123', 'logId': 'log-123'})
    data = {'customer_name': 'Acme Corp', 'image_options': {'max_width': 'literal placeholder'}, 'line_items_1': [{'quantity': 0, 'children': [{'description': 'Nested'}]}]}
    result = await node({'operation': 'create_document', 'automation_id': 'abc123', 'async_mode': True,
        'data': data, 'recipients': [{'signer': 1, 'email': 'anna@acme.com', 'name': 'Anna Weber'}],
        'existing_pdfs': ['https://example.com/terms.pdf']}).execute({})
    assert result['accepted'] is True and result['data']['jobId'] == 'queued-123'
    body = json.loads(requests[0].content)
    assert body['data'] == data and body['async'] is True
    assert body['recipients'] == [{'signer': 1, 'email': 'anna@acme.com', 'name': 'Anna Weber'}]


@pytest.mark.asyncio
async def test_omitted_false_and_null_update_fields(monkeypatch):
    requests = transport(monkeypatch)
    await node({'operation': 'update_automation', 'automation_id': 'abc123', 'is_active': False,
        'is_preview': False, 'pdf_expiration': None, 'image_options': {'quality': 80, 'max_width': 1000}}).execute({})
    assert json.loads(requests[0].content) == {'isActive': False, 'isPreview': False,
        'pdfExpiration': None, 'imageOptions': {'quality': 80, 'maxWidth': 1000}}
    await node({'operation': 'update_automation', 'automation_id': 'abc123', 'title': 'Updated'}).execute({})
    assert json.loads(requests[1].content) == {'title': 'Updated'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 402, 403, 404, 429, 500])
async def test_rejection_is_not_success_and_secret_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, status, {'error': 'Rejected ' + TOKEN})
    result = await node({'operation': 'list_automations'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_unexpected_success_status(monkeypatch):
    transport(monkeypatch, 200, {'success': False, 'message': 'Rejected'})
    assert (await node({'operation': 'list_automations'}).execute({}))['status'] == 'error'
    transport(monkeypatch, 202, {})
    with pytest.raises(ValueError, match='did not confirm'):
        await node({'operation': 'delete_automation', 'automation_id': 'abc123'}).execute({})


@pytest.mark.asyncio
async def test_path_segments_and_query_are_encoded(monkeypatch):
    requests = transport(monkeypatch, 200, {})
    await node({'operation': 'get_signing_session', 'session_id': 'session/with?reserved#chars'}).execute({})
    assert requests[0].url.raw_path == b'/esign/sessions/session%2Fwith%3Freserved%23chars'
    await node({'operation': 'get_automation', 'automation_id': 'id&other=x'}).execute({})
    assert dict(requests[1].url.params) == {'automationId': 'id&other=x'}


@pytest.mark.asyncio
async def test_account_evidence_uses_only_read_and_returns_labels(monkeypatch):
    requests = transport(monkeypatch, 200, {'automations': [{'_id': 'abc123', 'title': 'Invoice Generator'}]})
    from nodes.core.connection_evidence import _rows_from_operation, _label_from
    result = await node({'operation': 'list_automations'}).execute({})
    assert native.DocsautomatorNode.connection_evidence.operation == 'list_automations'
    assert requests[0].method == 'GET'
    assert [_label_from(row, native.DocsautomatorNode.connection_evidence.label_keys) for row in _rows_from_operation(result)] == ['Invoice Generator']


@pytest.mark.parametrize('config', [
    {'operation': 'create_document', 'automation_id': 'abc123', 'word_template_link': 'https://example.com/a.docx', 'word_template_base64': 'eA=='},
    {'operation': 'resend_signing_invite', 'session_id': 'abc123', 'signer_index': 0},
    {'operation': 'list_signing_sessions', 'limit': 251},
    {'operation': 'create_automation', 'title': 'Test', 'data_source_name': 'unsupported'},
    {'operation': 'send_test_email', 'automation_id': 'abc123', 'recipient': 'not-an-email'},
])
def test_invalid_configuration(config):
    with pytest.raises((ValidationError, ValueError)):
        native.DocsautomatorNode.parse_config({'config': config})


@pytest.mark.asyncio
async def test_failed_job_is_a_successful_status_read(monkeypatch):
    transport(monkeypatch, 200, {'jobId': 'job-123', 'status': 'failed', 'error': 'Template missing'})
    result = await node({'operation': 'get_job_status', 'job_id': 'job-123'}).execute({})
    assert result['status'] == 'success'
    assert result['data']['status'] == 'failed' and result['data']['error'] == 'Template missing'

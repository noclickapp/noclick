"""Exercise native factory parsing and captured provider requests, without live HTTP."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import easy_email_verification_node as node
from nodes.core.binary_output import BinaryOutput
from nodes.core.run_op import run_node_operation
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/easy-email-verification/documented_responses.json').read_text())
AUTH = {"credential_type": "easy_email_verification_api_key", "api_key": "test-server-key"}
JOB = "1ec74e7f-77d4-4d21-ab4b-7256b2d2c943"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(code, content=body, headers={"Content-Type": "text/plain"})
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    instance = NodeFactory.create_node(node_id="eev-test", node_type="automation-easy-email-verification",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": AUTH.copy()})
    return await instance.execute({})


@pytest.mark.parametrize("operation,arguments,method,path,body", [
    ("verify_email", {"email": "john+tag@gmail.com"}, "GET", "/verify", FIXTURE['verify']),
    ("verify_batch", {"emails": ["john@gmail.com"]}, "POST", "/verify", [FIXTURE['verify']]),
    ("upload_bulk_file", {"file_content": "john@gmail.com\n", "filename": "leads.csv"}, "POST", "/bulk/upload", {"status": "accepted", "list_id": JOB, "filename": "leads.csv", "uploaded": 1, "message": "File accepted for processing"}),
    ("list_bulk_jobs", {}, "GET", "/bulk/status", {"status": "ok", "total_lists": 0, "lists": []}),
    ("get_bulk_job", {"job_id": JOB}, "GET", "/bulk/status/" + JOB, {"list_id": JOB, "status": "processing", "progress": 50}),
    ("download_bulk_results", {"job_id": JOB}, "GET", "/bulk/download/" + JOB, b"Email,Result\njohn@gmail.com,invalid\n"),
    ("delete_bulk_job", {"job_id": JOB}, "DELETE", "/bulk/" + JOB, {"status": "deleted", "list_id": JOB, "message": "File permanently removed"}),
    ("get_credits", {}, "GET", "/credits", FIXTURE['credits']),
])
@pytest.mark.asyncio
async def test_all_contract_operations(wire, operation, arguments, method, path, body):
    requests, replies = wire
    replies.append((200, body))
    result = await run(operation, arguments)
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == '/v1' + path
    assert request.url.host == 'api.easyemailverification.com'
    assert request.headers['X-API-Key'] == AUTH['api_key']
    assert AUTH['api_key'] not in str(request.url)
    if operation == 'verify_email':
        assert request.url.params['email'] == 'john+tag@gmail.com'
        assert b'%2B' in request.url.raw_path
    if operation == 'verify_batch':
        assert json.loads(request.content) == {'emails': arguments['emails']}
    if operation == 'upload_bulk_file':
        assert request.headers['Content-Type'].startswith('multipart/form-data; boundary=')
        assert b'name="file"; filename="leads.csv"' in request.content
        assert b'john@gmail.com\n' in request.content
    if operation == 'download_bulk_results':
        assert isinstance(result['file'], BinaryOutput)
        assert result['file'].data == body and result['file'].filename == 'results.csv'
    else:
        assert result['data'] == body


@pytest.mark.asyncio
async def test_unknown_is_preserved(wire):
    body = {**FIXTURE['verify'], 'result': 'unknown', 'reason': 'timeout', 'safe_to_send': False}
    wire[1].append((200, body))
    result = await run('verify_email', {'email': 'john@gmail.com'})
    assert result['data']['result'] == 'unknown' and result['data']['safe_to_send'] is False


@pytest.mark.parametrize('status', [400, 401, 402, 404, 429, 500])
@pytest.mark.asyncio
async def test_provider_rejection_is_not_success_and_no_retries(wire, status):
    wire[1].append((status, {'success': False, 'message': 'Invalid API key'}))
    result = await run('get_credits')
    assert result['status'] == 'error' and result['success'] is False
    assert result['http_status'] == status and result['message'] == 'Invalid API key'
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_application_error_and_malformed_balance_cannot_prove_connection(wire):
    for body in [{'success': False, 'message': 'No key'}, {}, {'success': True}]:
        wire[1].append((200, body))
        with pytest.raises(ValueError):
            await run('get_credits')


@pytest.mark.asyncio
async def test_batch_requires_one_result_per_address(wire):
    wire[1].append((200, []))
    with pytest.raises(ValueError):
        await run('verify_batch', {'emails': ['john@gmail.com']})


@pytest.mark.asyncio
async def test_delete_must_confirm_selected_job(wire):
    wire[1].append((200, {'status': 'deleted', 'list_id': 'different'}))
    with pytest.raises(ValueError):
        await run('delete_bulk_job', {'job_id': JOB})


@pytest.mark.parametrize('bad', ['../other', 'a/b', 'a%2fb', 'x?key=value', 'x\r\n'])
def test_job_cannot_change_route(bad):
    with pytest.raises(ValidationError):
        node.GetBulkJob(job_id=bad)


@pytest.mark.parametrize('bad', ['', 'https://api.example/key', '<token>', 'a\r\nb', 'Bearer key'])
def test_bad_keys_refused(bad):
    with pytest.raises((ValueError, ValidationError)):
        node.EasyEmailVerificationAPIKeyCredential(api_key=bad)


def test_manual_credential_type_defaults_and_batch_bounds():
    assert node.EasyEmailVerificationAPIKeyCredential(api_key='test-key').credential_type == AUTH['credential_type']
    for emails in [[], ['x'] * 51]:
        with pytest.raises(ValidationError):
            node.VerifyBatch(emails=emails)


@pytest.mark.asyncio
async def test_unsaved_manual_credential_can_run_evidence(wire):
    wire[1].append((200, FIXTURE['credits']))
    result = await run_node_operation(node_type="automation-easy-email-verification", operation="get_credits",
        arguments={}, credential_data=AUTH.copy(), user_id="00000000-0000-4000-8000-000000000001")
    assert result['data']['credits_remaining'] == 1250

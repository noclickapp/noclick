"""SelectPdf v2 wire contracts, binary results, async reads and credential evidence."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import selectpdf_node as native
from nodes.core.registry import NodeFactory

KEY = 'd290f1ee-6c54-4b01-90e6-d701748f0851'
JOB = 'd290f1ee-6c54-4b01-90e6-d701748f0852'
PDF = b'%PDF-1.7\nsynthetic unit-test bytes\n%%EOF'
USAGE = json.loads((Path(__file__).parent / 'fixtures/selectpdf/usage.json').read_text())['body']


def node(config, credentials=True):
    return NodeFactory.create_node(node_id='selectpdf-test', node_type='automation-selectpdf',
        node_data={'config': config, **({'credentials': {'api_key': KEY}} if credentials else {})})


def mock(monkeypatch, *, content=None, data=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=content, json=data, headers=headers)
    def factory(**kwargs):
        assert kwargs == {'timeout': 180, 'trust_env': False, 'follow_redirects': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', factory)
    return requests


@pytest.mark.asyncio
async def test_documented_subscription_proves_account_without_conversion(monkeypatch):
    requests = mock(monkeypatch, data=USAGE)
    result = await node({'operation': 'get_usage', 'get_history': True}).execute({})
    assert result['data'] == USAGE
    assert result['items'] == [{'name': 'Entry Level: 340 of 2000 credits used; 1660 available'}]
    assert native.SelectPdfNode.connection_evidence.operation == 'get_usage'
    assert str(requests[0].url) == 'https://selectpdf.com/api2/usage'
    assert json.loads(requests[0].content) == {'key': KEY, 'get_history': True}
    assert requests[0].method == 'POST' and not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,extra,path', [
    ('convert_url', {'url': 'https://selectpdf.com'}, '/api2/convert'),
    ('convert_html', {'html': '<b>test html string</b>', 'base_url': 'https://selectpdf.com'}, '/api2/convert'),
    ('merge_pdfs', {'input_files': [{'url': 'https://selectpdf.com/one.pdf'}, {'url': 'https://selectpdf.com/two.pdf'}]}, '/api2/pdfmerge'),
    ('get_async_job', {'job_id': JOB}, '/api2/asyncjob'),
])
async def test_pdf_result_and_exact_route(monkeypatch, operation, extra, path):
    requests = mock(monkeypatch, content=PDF, headers={'content-type': 'application/pdf'})
    result = await node({'operation': operation, **extra}).execute({})
    assert base64.b64decode(result['pdf_base64']) == PDF
    assert requests[0].url.path == path and requests[0].method == 'POST'
    body = json.loads(requests[0].content)
    assert body['key'] == KEY and 'operation' not in body
    if operation == 'merge_pdfs':
        assert body['input_files'] == [dict(row, file_type=1, idx=i) for i, row in enumerate(extra['input_files'], 1)]
    if operation.startswith('convert_'):
        assert body['async'] is False
        assert ('html' in body) != ('url' in body)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,extra,path', [
    ('start_url_conversion', {'url': 'https://selectpdf.com'}, '/api2/convert'),
    ('start_html_conversion', {'html': '<b>test html string</b>'}, '/api2/convert'),
    ('start_pdf_merge', {'input_files': [{'url': 'https://selectpdf.com/one.pdf'}, {'url': 'https://selectpdf.com/two.pdf'}]}, '/api2/pdfmerge'),
    ('start_pdf_text_extraction', {'url': 'https://selectpdf.com/one.pdf'}, '/api2/pdftotext'),
    ('get_async_job', {'job_id': JOB}, '/api2/asyncjob'),
])
async def test_async_accepted_keeps_job_and_never_resubmits(monkeypatch, operation, extra, path):
    requests = mock(monkeypatch, status=202, headers={'X-SelectPdf-Job-Id': JOB})
    result = await node({'operation': operation, **extra}).execute({})
    assert result == {'status': 'processing', 'http_status': 202, 'job_id': JOB}
    assert len(requests) == 1 and requests[0].url.path == path
    if operation.startswith('start_'):
        assert json.loads(requests[0].content)['async'] is True


@pytest.mark.asyncio
async def test_extract_and_search_are_distinct_actions(monkeypatch):
    requests = mock(monkeypatch, content=b'PDF text', headers={'content-type': 'text/plain'})
    assert (await node({'operation': 'extract_pdf_text', 'url': 'https://selectpdf.com/test.pdf', 'text_layout': 'Reading'}).execute({}))['text'] == 'PDF text'
    assert json.loads(requests[0].content)['action'] == 'Convert'
    requests = mock(monkeypatch, data=[{'page': 1, 'x': 10, 'y': 20, 'w': 30, 'h': 8}])
    assert (await node({'operation': 'search_pdf', 'url': 'https://selectpdf.com/test.pdf', 'search_text': 'pdf'}).execute({}))['data'][0]['page'] == 1
    body = json.loads(requests[0].content)
    assert body['action'] == 'Search' and body['search_text'] == 'pdf'
    assert requests[0].url.path == '/api2/pdftotext'


@pytest.mark.asyncio
@pytest.mark.parametrize('media,value,key', [('text/plain', 'result text', 'text'), ('text/html', '<b>result</b>', 'text'), ('application/json', '[{"page":1}]', 'data')])
async def test_async_job_result_media(monkeypatch, media, value, key):
    mock(monkeypatch, content=value.encode(), headers={'content-type': media})
    result = await node({'operation': 'get_async_job', 'job_id': JOB}).execute({})
    assert result[key] == (json.loads(value) if key == 'data' else value)


@pytest.mark.asyncio
async def test_web_elements_preserves_contract_fields(monkeypatch):
    row = {'selector': 'h1', 'page': 1, 'x': 1, 'y': 2, 'width': 3, 'height': 4, 'text': 'Title', 'attributes': {'id': 'title'}}
    requests = mock(monkeypatch, data=[row])
    assert (await node({'operation': 'get_web_elements', 'job_id': JOB}).execute({}))['data'] == [row]
    assert requests[0].url.path == '/api2/webelements'
    assert json.loads(requests[0].content) == {'key': KEY, 'job_id': JOB}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 429, 499, 500])
async def test_provider_failure_redacts_and_does_not_retry(monkeypatch, status):
    requests = mock(monkeypatch, status=status, content=('License rejected: ' + KEY).encode())
    result = await node({'operation': 'get_usage'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'License rejected: [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,extra,data', [('get_usage', {}, {}), ('get_web_elements', {'job_id': JOB}, {}), ('search_pdf', {'url': 'https://selectpdf.com/t.pdf', 'search_text': 'pdf'}, {})])
async def test_invalid_json_envelopes_rejected(monkeypatch, operation, extra, data):
    mock(monkeypatch, data=data)
    with pytest.raises(ValueError):
        await node({'operation': operation, **extra}).execute({})


@pytest.mark.asyncio
async def test_missing_job_id_and_non_pdf_do_not_claim_success(monkeypatch):
    mock(monkeypatch, status=202)
    with pytest.raises(ValueError, match='without a job ID'):
        await node({'operation': 'start_html_conversion', 'html': '<h1>Hi</h1>'}).execute({})
    mock(monkeypatch, content=b'<html>failed</html>')
    with pytest.raises(ValueError, match='PDF bytes'):
        await node({'operation': 'convert_html', 'html': '<h1>Hi</h1>'}).execute({})


@pytest.mark.asyncio
async def test_missing_key_does_not_call_provider():
    with pytest.raises(ValueError, match='Connect a SelectPdf'):
        await node({'operation': 'get_usage'}, False).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_async_job', 'job_id': '../bad'},
    {'operation': 'convert_url', 'url': 'file:///tmp/a'},
    {'operation': 'convert_url', 'url': 'https://user:password@selectpdf.com'},
    {'operation': 'convert_html', 'html': 'x', 'key': 'overwrite'},
    {'operation': 'extract_pdf_text', 'url': 'https://selectpdf.com/a.pdf', 'start_page': 5, 'end_page': 2},
    {'operation': 'merge_pdfs', 'input_files': [{'url': 'https://selectpdf.com/a.pdf'}]},
])
def test_invalid_inputs(config):
    with pytest.raises(ValidationError):
        native.SelectPdfNodeConfig.model_validate({'config': config})


def test_manual_credential_default_and_password_widget():
    credential = native.SelectPdfAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == 'selectpdf_api_key'
    assert KEY not in repr(credential)
    assert native.SelectPdfAPIKeyCredential.model_fields['api_key'].json_schema_extra['ui:widget'] == 'password'


@pytest.mark.asyncio
async def test_workflow_pdf_becomes_a_downstream_file_url(monkeypatch):
    import utils.resource_store as store
    mock(monkeypatch, content=PDF, headers={'content-type': 'application/pdf'})
    written = []
    async def save(**kwargs):
        written.append(kwargs)
        return {'download_url': 'https://files.example/selectpdf.pdf', 'mime_type': 'application/pdf',
                'name': 'report.pdf', 'size_bytes': len(PDF)}
    monkeypatch.setattr(store, 'create_resource_from_bytes', save)
    instance = node({'operation': 'convert_html', 'html': '<h1>Hi</h1>', 'pdf_name': 'report.pdf'})
    instance.user_id = 'test-user'
    instance.workflow_id = 'test-workflow'
    result = await instance.execute({})
    assert 'pdf_base64' not in result
    assert result['file'] == {'url': 'https://files.example/selectpdf.pdf', 'mime_type': 'application/pdf',
                              'name': 'report.pdf', 'size_bytes': len(PDF)}
    assert written[0]['body'] == PDF and written[0]['filename'] == 'report.pdf'
    assert written[0]['user_id'] == 'test-user' and written[0]['workflow_id'] == 'test-workflow'


@pytest.mark.asyncio
async def test_connect_shows_subscription_and_account_specific_quota(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as runner
    requests = mock(monkeypatch, data=USAGE)
    async def run(**kwargs):
        assert kwargs['operation'] == 'get_usage'
        return await node({'operation': kwargs['operation']}).execute({})
    monkeypatch.setattr(runner, 'run_node_operation', run)
    evidence = await collect_evidence(node_type='automation-selectpdf', user_id='test-user',
                                     credential_data={'credential_type': 'selectpdf_api_key', 'api_key': KEY})
    assert evidence.reachable is True
    assert evidence.samples[0].label == 'Entry Level: 340 of 2000 credits used; 1660 available'
    assert len(requests) == 1 and requests[0].url.path == '/api2/usage'

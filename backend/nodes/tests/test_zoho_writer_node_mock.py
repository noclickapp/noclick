"""Transport and poll behavior using the provider's documented document list."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes.zoho_writer_node import (
    OPS, OP_MODELS, MetadataUpdate, ZohoWriterNode, ZohoWriterOAuthCredential,
    ZohoWriterOnNewOrUpdatedDocumentConfig,
)
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/zoho-writer/list_documents.json').read_text())['body']
TOKEN = 'test-writer-oauth-token'

def node(config):
    return NodeFactory.create_node(node_id='writer-test', node_type='automation-zoho-writer', node_data={
        'config': config, 'credentials': {'access_token': TOKEN, 'credential_type': 'zoho_writer_oauth'}})

def intercept(monkeypatch, response):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=response)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as transport:
            yield transport
    monkeypatch.setattr('nodes.zoho_writer_node.guarded_async_client', client)
    return seen

@pytest.mark.asyncio
async def test_zoho_writer_document_list_preserves_provider_response(monkeypatch):
    seen = intercept(monkeypatch, FIXTURE)
    result = await node({'operation': 'list_documents', 'offset': 2, 'limit': 1}).execute({})
    assert result['data'] == FIXTURE
    assert seen[0].headers['Authorization'] == 'Bearer ' + TOKEN
    assert dict(seen[0].url.params) == {'offset': '2', 'limit': '1', 'sort_order_by': 'descending', 'category': 'all'}

@pytest.mark.asyncio
async def test_zoho_writer_write_encodings(monkeypatch):
    seen = intercept(monkeypatch, {'document_id': FIXTURE['documents'][0]['document_id']})
    await node({'operation': 'create_document', 'text': 'Invoice details for Q1 2026.', 'filename': 'Invoice_2026_001'}).execute({})
    assert seen[0].headers['content-type'].startswith('multipart/form-data; boundary=')
    assert b'Invoice details for Q1 2026.' in seen[0].content
    await node({'operation': 'update_document_metadata', 'document_id': 'doc123', 'operations': {'name': 'New Document Name'}}).execute({})
    assert seen[-1].url.path == '/writer/api/v1/documents/doc123/meta'
    assert json.loads(seen[-1].content) == {'operations': {'name': 'New Document Name'}}
    await node({'operation': 'copy_document', 'document_id': 'doc123', 'version_id': 7}).execute({})
    assert json.loads(seen[-1].content)['version_id'] == 7
    await node({'operation': 'trash_document', 'document_id': 'doc123'}).execute({})
    assert seen[-1].method == 'DELETE'
    assert not seen[-1].content

@pytest.mark.asyncio
async def test_zoho_writer_all_actions_use_declared_routes(monkeypatch):
    seen = intercept(monkeypatch, {})
    for name, (method, path, media, fields) in OPS.items():
        config = {'operation': name}
        for field, model_field in OP_MODELS[name].model_fields.items():
            if model_field.is_required():
                config[field] = {'name': 'New Document Name'} if field == 'operations' else 'doc123' if field.endswith('_id') else 'Invoice'
        await node(config).execute({})
        request = seen[-1]
        assert request.method == method
        assert request.url.path == path.replace('{document_id}', 'doc123').replace('{template_id}', 'doc123')
        assert request.url.host == 'www.zohoapis.com'

@pytest.mark.asyncio
async def test_zoho_writer_poll_baselines_then_emits_new_and_modified(monkeypatch):
    current = node({'operation': 'on_new_or_updated_document'})
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(state)
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    monkeypatch.setattr(current, '_update_node_state', update)
    request = AsyncMock(return_value={'data': copy.deepcopy(FIXTURE)})
    monkeypatch.setattr(current, '_request', request)
    assert (await current.execute({}))['documents'] == []
    assert current.trigger_produced_no_event({})
    assert (await current.execute({}))['documents'] == []
    changed = copy.deepcopy(FIXTURE)
    changed['documents'][0]['modified_time'] = '2018-03-31T13:54:51Z'
    request.return_value = {'data': changed}
    assert (await current.execute({}))['documents'] == changed['documents']
    assert current.trigger_emitted_event({})
    event = current.resolve_agent_event({'documents': changed['documents']})
    assert changed['documents'][0]['document_id'] in event['text']
    assert 'Amelia' in event['text']
    assert current.resolve_agent_event({'documents': []}) is None
    assert (await current.execute({}))['documents'] == []
    added = copy.deepcopy(changed['documents'][0]); added['document_id'] = 'new-document'
    changed['documents'].append(added)
    assert (await current.execute({}))['documents'] == [added]
    assert request.call_args.kwargs['params']['sortby'] == 'modified_time'

@pytest.mark.asyncio
async def test_zoho_writer_poll_refuses_incomplete_scan_and_missing_identity(monkeypatch):
    current = node({'operation': 'on_new_or_updated_document'})
    current._filter_unseen = AsyncMock()
    current._request = AsyncMock(return_value={'data': {'documents': [{}]}})
    with pytest.raises(ValueError, match='identity'): await current.execute({})
    current._request.return_value = {'data': {'documents': FIXTURE['documents'] * 100}}
    with pytest.raises(ValueError, match='2,000'): await current.execute({})
    current._filter_unseen.assert_not_called()

@pytest.mark.asyncio
async def test_zoho_writer_provider_error_is_not_success_and_redacts_token(monkeypatch):
    intercept(monkeypatch, {'error': {'message': 'Invalid token ' + TOKEN}})
    with pytest.raises(ValueError) as error: await node({'operation': 'list_documents'}).execute({})
    assert TOKEN not in str(error.value)
    assert 'Invalid token' in str(error.value)

def test_zoho_writer_manual_credential_and_input_contract():
    credential = ZohoWriterOAuthCredential(access_token=TOKEN)
    assert credential.credential_type == 'zoho_writer_oauth'
    assert not ZohoWriterOAuthCredential.model_fields['credential_type'].is_required()
    for changes in [{}, {'name': 'Invoice', 'lock': True}]:
        with pytest.raises(ValidationError): MetadataUpdate(**changes)
    with pytest.raises(ValueError): node({'operation': 'get_document', 'document_id': '../secret'})
    with pytest.raises(ValueError): node({'operation': 'create_document', 'text': 'Invoice', 'template_id': 'doc123'})
    assert ZohoWriterOnNewOrUpdatedDocumentConfig.model_fields['operation'].json_schema_extra['x-is-trigger']

@pytest.mark.asyncio
async def test_zoho_writer_requests_against_unmodified_provider_contract(monkeypatch):
    """The OAS server omits https://; validate endpoint/body evidence independently.

    Contract fixtures retain their original bytes and hashes. The documented
    origin is checked explicitly rather than repairing that server declaration.
    """
    import hashlib
    import re
    import yaml
    from email.parser import BytesParser
    from email.policy import default
    from jsonschema import Draft7Validator

    fixtures = Path(__file__).parent / 'fixtures/zoho-writer'
    operations = []
    for pin in json.loads((fixtures / 'contract_pins.json').read_text()):
        raw = (fixtures / pin['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pin['sha256']
        contract = yaml.safe_load(raw)
        for path, methods in contract['paths'].items():
            for method, operation in methods.items():
                operations.append((path, method.upper(), operation))
    seen = intercept(monkeypatch, {})
    for name, model in OP_MODELS.items():
        config = {'operation': name}
        for field, declaration in model.model_fields.items():
            if declaration.is_required():
                config[field] = {'name': 'New Document Name'} if field == 'operations' else 'a1b2c3d4e5f6g7h8i9' if field.endswith('_id') else 'Invoice'
        await node(config).execute({})
        request = seen[-1]
        assert str(request.url).startswith('https://www.zohoapis.com/writer/api/v1/')
        exact = [(path, operation) for path, method, operation in operations
            if method == request.method and path == request.url.path]
        matches = exact or [(path, operation) for path, method, operation in operations
            if method == request.method and re.fullmatch(re.sub(r'\{[^}]+\}', '[^/]+', path), request.url.path)]
        assert len(matches) == 1, (name, request.url)
        _, operation = matches[0]
        parameters = {parameter['name']: parameter for parameter in operation.get('parameters', []) if parameter['in'] == 'query'}
        assert set(request.url.params) <= set(parameters)
        for key, value in request.url.params.items():
            schema = parameters[key]['schema']
            value = int(value) if schema.get('type') == 'integer' else value
            Draft7Validator(schema).validate(value)
        if 'requestBody' in operation:
            content = operation['requestBody']['content']
            media = request.headers['content-type'].split(';')[0]
            assert media in content
            if media == 'application/json':
                body = json.loads(request.content)
            else:
                message = BytesParser(policy=default).parsebytes(b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
                body = {part.get_param('name', header='content-disposition'): part.get_content() for part in message.iter_parts()}
            schema = content[media]['schema']
            assert set(body) <= set(schema['properties'])
            Draft7Validator(schema).validate(body)

@pytest.mark.asyncio
async def test_zoho_writer_connection_shows_document_names(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    read = AsyncMock(return_value={'status': 'success', 'data': FIXTURE})
    monkeypatch.setattr('nodes.core.run_op.run_node_operation', read)
    evidence = await collect_evidence(node_type='automation-zoho-writer', user_id='test-user',
        credential_data={'credential_type': 'zoho_writer_oauth', 'access_token': TOKEN})
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ['Presales tips']
    assert read.call_args.kwargs['operation'] == 'list_documents'

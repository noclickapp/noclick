"""Exercise every operation against Templated's verbatim saved Postman examples."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes.templated_node import TemplatedAPIKeyCredential, TemplatedFullConfig

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/templated/postman_examples.json').read_text())
CREDENTIAL = {'credential_type': 'templated_api_key', 'api_key': 'test-templated-key'}


def make_node(config):
    return NodeFactory.create_node(node_id='templated-test', node_type='automation-templated',
        node_data={'config': config, 'credentials': CREDENTIAL})


def example_config(operation, example):
    request = example['request']
    url = request['url']
    raw = url['raw'] if isinstance(url, dict) else url
    config = {'operation': operation}
    if '/template/:' in raw:
        config['template_id'] = 'tmpl_8f7e6d5c4b3a2910'
    elif '/folder/:' in raw:
        config['folder_id'] = 'folder_abc123'
    elif '/render/:' in raw:
        config['render_id'] = 'render_a1b2c3d4e5f6'
    if request.get('body'):
        body = json.loads(request['body']['raw'])
        for key, value in body.items():
            if key in ['name', 'template']:
                value = {'{{templateName}}': 'Social Media Post', '{{folderName}}': 'Marketing Assets',
                    '{{templateId}}': 'tmpl_8f7e6d5c4b3a2910'}.get(value, value)
            elif key == 'ids':
                value = ['upload_abc123']
            elif key == 'fonts':
                value = ['Custom Font']
            config[key] = value
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_saved_postman_responses(operation):
    example = EXAMPLES[operation]
    config = example_config(operation, example)
    expected_body = {k: v for k, v in config.items() if k not in ['operation', 'template_id', 'folder_id', 'render_id']}
    requests = []
    def respond(request):
        requests.append(request)
        declared = example['request']
        raw = declared['url']['raw'] if isinstance(declared['url'], dict) else declared['url']
        expected = raw.replace('{{baseUrl}}', 'https://api.templated.io').split('?')[0]
        for key in ['template_id', 'folder_id', 'render_id']:
            if key in config:
                expected = expected.replace(':folderId', config[key]).replace(':id', config[key])
        assert str(request.url) == expected
        assert request.method == declared['method']
        assert request.headers['authorization'] == 'Bearer test-templated-key'
        assert request.headers['content-type'] == 'application/json'
        if declared.get('body'):
            assert json.loads(request.content) == expected_body
        else:
            assert not request.content
        saved = example['responses'][0]
        return httpx.Response(saved['code'], json=json.loads(saved['body']))
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client',
            side_effect=lambda **kw: async_client(transport=httpx.MockTransport(respond), **kw)):
        result = await make_node(config).execute({})
    assert len(requests) == 1
    assert result == {'status': 'success', 'data': json.loads(example['responses'][0]['body'])}


@pytest.mark.asyncio
async def test_filters_keep_wire_names_and_false():
    def respond(request):
        assert dict(request.url.params) == {'page': '2', 'limit': '10', 'externalId': 'order_12345',
            'includeLayers': 'false', 'includePages': 'true', 'tags': 'social,marketing'}
        return httpx.Response(200, json=json.loads(EXAMPLES['list_templates']['responses'][0]['body']))
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client',
            side_effect=lambda **kw: async_client(transport=httpx.MockTransport(respond), **kw)):
        await make_node({'operation': 'list_templates', 'page': 2, 'limit': 10, 'externalId': 'order_12345',
            'includeLayers': False, 'includePages': True, 'tags': 'social,marketing'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401, 403, 429, 500])
async def test_http_failures_are_not_success(code):
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client', side_effect=lambda **kw:
            async_client(transport=httpx.MockTransport(lambda r: httpx.Response(code, json={'error': 'Rejected'})), **kw)):
        with pytest.raises(ValueError, match=f"Templated HTTP {code}:.*Rejected"):
            await make_node({'operation': 'list_templates'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_template', 'template_id': '../secret'},
    {'operation': 'list_templates', 'page': 0},
    {'operation': 'create_template', 'name': 'A', 'width': 0, 'height': 630},
    {'operation': 'delete_uploads', 'ids': []},
    {'operation': 'delete_fonts', 'fonts': []},
    {'operation': 'list_templates', 'unsupported': True},
])
def test_invalid_configuration(config):
    with pytest.raises(ValidationError):
        TemplatedFullConfig.model_validate({'config': config, 'credentials': CREDENTIAL})


@pytest.mark.parametrize('token', ['Bearer abc', 'https://api.templated.io', 'abc\nxyz'])
def test_invalid_keys(token):
    with pytest.raises(ValidationError):
        TemplatedAPIKeyCredential(api_key=token)


@pytest.mark.asyncio
async def test_connect_evidence_reads_saved_template_names():
    from nodes.core.connection_evidence import collect_evidence
    saved = json.loads(EXAMPLES['list_templates']['responses'][0]['body'])
    def respond(request):
        assert request.method == 'GET'
        assert request.url.path == '/v1/templates'
        return httpx.Response(200, json=saved)
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client', side_effect=lambda **kw:
            async_client(transport=httpx.MockTransport(respond), **kw)):
        evidence = await collect_evidence(node_type='automation-templated', user_id='test-user',
            credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ['Social Media Post', 'Certificate Template']


@pytest.mark.asyncio
async def test_rejected_connection_preserves_provider_message():
    from nodes.core.connection_evidence import collect_evidence
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client', side_effect=lambda **kw:
            async_client(transport=httpx.MockTransport(lambda r:
                httpx.Response(401, json={'error': 'API key rejected'})), **kw)):
        evidence = await collect_evidence(node_type='automation-templated', user_id='test-user',
            credential_data=CREDENTIAL)
    assert evidence.reachable is False
    assert 'API key rejected' in evidence.error


@pytest.mark.asyncio
async def test_empty_account_is_valid_evidence():
    from nodes.core.connection_evidence import collect_evidence
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client', side_effect=lambda **kw:
            async_client(transport=httpx.MockTransport(lambda r:
                httpx.Response(200, json={'data': [], 'pagination': {'page': 1, 'limit': 10, 'total': 0, 'totalPages': 0}})), **kw)):
        evidence = await collect_evidence(node_type='automation-templated', user_id='test-user',
            credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert evidence.samples == []


@pytest.mark.asyncio
async def test_rename_does_not_clear_template_layers():
    def respond(request):
        assert request.method == 'PUT'
        assert json.loads(request.content) == {'name': 'Updated Social Media Post'}
        return httpx.Response(200, json=json.loads(EXAMPLES['update_template']['responses'][0]['body']))
    async_client = httpx.AsyncClient
    with patch('nodes.templated_node.guarded_async_client', side_effect=lambda **kw:
            async_client(transport=httpx.MockTransport(respond), **kw)):
        await make_node({'operation': 'update_template', 'template_id': 'tmpl_8f7e6d5c4b3a2910',
            'name': 'Updated Social Media Post'}).execute({})

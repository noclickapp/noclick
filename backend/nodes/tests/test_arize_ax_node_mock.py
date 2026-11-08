"""Verify the Arize AX factory node against publisher request and response examples.

These tests also cover cursor boundaries, JSON input validation and errors that
must never turn a rejected credential or mutation into a successful result.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import arize_ax_node as provider
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from utils import ssrf

ROOT = Path(__file__).parent / 'fixtures/arize-ax'
CASES = json.loads((ROOT / 'requests.json').read_text())['operations']
RESPONSES = json.loads((ROOT / 'responses.json').read_text())['operations']
AUTH = {'credential_type': 'arize_ax_api_key', 'api_key': 'fixture-arize-key'}


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id='arize-ax-test', node_type='automation-arize-ax',
        node_data={'config': config, 'credentials': credentials})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    def send(request):
        requests.append(request)
        status, data = replies.pop(0)
        return httpx.Response(status, json=data) if data is not None else httpx.Response(status)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(provider, 'guarded_async_client', lambda **kwargs: guarded(**kwargs,
        transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CASES))
async def test_published_operation_request_and_response(transport, operation):
    requests, replies = transport
    case, response = CASES[operation], RESPONSES[operation]
    replies.append((case['status'], response))
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'api.arize.com'
    path = case['path'].format(**{k: quote(str(v), safe='') for k, v in case['config'].items()})
    assert request.url.raw_path.split(b'?')[0] == path.encode()
    assert request.headers['Authorization'] == 'Bearer fixture-arize-key'
    if case['body'] is not None:
        assert json.loads(request.content) == case['body']
    else:
        assert request.content == b''
    assert 'operation' not in request.url.params
    assert 'fixture-arize-key' not in str(result)
    if case['status'] == 204:
        assert result == {'success': True, 'http_status': 204}
    elif operation in provider.LIST_KEYS:
        assert result == {**response, 'data': response[provider.LIST_KEYS[operation]]}
    else:
        assert result == response


@pytest.mark.asyncio
async def test_cursor_and_filters_stay_in_query_without_extra_requests(transport):
    requests, replies = transport
    data = RESPONSES['list_datasets']
    replies.append((200, data))
    out = await node({'operation': 'list_datasets', 'space_id': 'space_12345',
        'space_name': 'my-space', 'name': 'production', 'limit': 100, 'cursor': 'opaque+/='}).execute({})
    assert dict(requests[0].url.params) == {'space_id': 'space_12345', 'space_name': 'my-space',
        'name': 'production', 'limit': '100', 'cursor': 'opaque+/='}
    assert out['pagination'] == data['pagination']
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_version_query_is_distinct_from_delete_examples_version_body(transport):
    requests, replies = transport
    replies.append((200, RESPONSES['insert_dataset_examples']))
    config = {**CASES['insert_dataset_examples']['config'], 'dataset_version_id': 'version_1'}
    await node(config).execute({})
    assert requests[0].url.params['dataset_version_id'] == 'version_1'
    assert 'dataset_version_id' not in json.loads(requests[0].content)
    replies.append((204, None))
    config = CASES['delete_dataset_examples']['config']
    await node(config).execute({})
    assert not requests[1].url.query
    assert json.loads(requests[1].content)['dataset_version_id'] == config['dataset_version_id']


@pytest.mark.asyncio
async def test_account_evidence_is_an_authenticated_space_read(transport):
    requests, replies = transport
    replies.append((200, RESPONSES['list_spaces']))
    result = await node({'operation': 'list_spaces'}).execute({})
    assert result['data'][0]['name'] == 'LLM Evaluation'
    assert requests[0].method == 'GET' and requests[0].url.path == '/v2/spaces'
    assert provider.ArizeAxNode.connection_evidence.operation == 'list_spaces'


@pytest.mark.asyncio
async def test_prompt_description_can_be_cleared_and_omitted_fields_are_not_sent(transport):
    requests, replies = transport
    instance = node({'operation': 'update_prompt', 'prompt_id': 'prompt_001', 'description': None})
    replies.append((200, RESPONSES['update_prompt']))
    await instance.execute({})
    assert json.loads(requests[0].content) == {'description': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_http_failures_preserve_provider_reason_and_redact_key(transport, status):
    requests, replies = transport
    replies.append((status, {'error': 'Rejected fixture-arize-key'}))
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_spaces'}).execute({})
    assert str(status) in str(exc.value)
    assert 'fixture-arize-key' not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'data': []}, {'spaces': {}}, {'error': 'denied'}])
async def test_malformed_or_error_envelope_is_not_account_evidence(transport, body):
    requests, replies = transport
    replies.append((200, body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_spaces'}).execute({})


@pytest.mark.parametrize('operation,changes', [
    ('list_datasets', {'limit': 101}),
    ('list_dataset_examples', {'limit': 501}),
    ('create_dataset', {'examples': '[]'}),
    ('create_dataset', {'examples': '{}'}),
    ('update_dataset_examples', {'examples': '[{"question":"missing id"}]'}),
    ('create_experiment', {'space_id': 'space_1'}),
    ('create_prompt_version', {'messages': '[]'}),
    ('create_prompt_version', {'messages': '[{"role":"invalid"}]'}),
    ('get_prompt', {'version_id': 'version_1', 'label': 'production'}),
    ('get_dataset', {'dataset_id': '..'}),
])
def test_invalid_inputs_fail_before_transport(operation, changes):
    with pytest.raises((ConfigValidationError, ValidationError, ValueError)):
        instance = node({**CASES[operation]['config'], **changes})
        # Factory stores a parse failure until execute on some code paths.
        assert instance.config is not None


def test_credential_has_default_type_and_one_manual_secret():
    credential = provider.ArizeAxApiKey(api_key='fixture-arize-key')
    assert credential.credential_type == 'arize_ax_api_key'
    assert set(provider.ArizeAxApiKey.model_fields) == {'credential_type', 'api_key'}
    with pytest.raises(ValidationError):
        provider.ArizeAxApiKey(api_key='Bearer fixture-arize-key')


@pytest.mark.asyncio
async def test_partial_delete_retains_the_ids_not_deleted(transport):
    requests, replies = transport
    data = {"completed": True, "deleted_example_ids": ["550e8400-e29b-41d4-a716-446655440000"],
        "not_deleted_example_ids": ["6ba7b810-9dad-11d1-80b4-00c04fd430c8"]}
    replies.append((200, data))
    result = await node(CASES['delete_dataset_examples']['config']).execute({})
    assert result == data
    assert 'success' not in result

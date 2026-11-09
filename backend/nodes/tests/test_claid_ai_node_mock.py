"""Provider-documented request examples through the native factory and offline HTTP.

Sources are attached to each fixture. Responses without valid published JSON
are explicitly marked synthetic. No live account or credentials are used.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import claid_ai_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/claid-ai/documented.json').read_text())
TOKEN = 'fixture-claid-key-42'
CREDENTIAL = {'credential_type': 'claid_ai_api_key', 'api_key': TOKEN}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, credentials=CREDENTIAL):
    return NodeFactory.create_node(node_id='claid-fixture', node_type='automation-claid-ai',
        node_data={'config': config, 'credentials': credentials})

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        calls.append(request)
        return replies.pop(0)
    real_client = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return real_client(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls, replies

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CASES))
async def test_claid_ai_documented_operations(transport, operation):
    calls, replies = transport
    case = CASES[operation]
    replies.append(httpx.Response(200, json=case['response']['body']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url == 'https://api.claid.ai' + case['path']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['Accept'] == 'application/json'
    if case['request_body'] is not None:
        expected = json.loads(json.dumps(case["request_body"]))
        if operation == "generate_video":
            # Match DurationEnum from the pinned contract.
            expected["options"]["duration"] = str(expected["options"]["duration"])
        assert json.loads(request.content) == expected
        assert request.headers['Content-Type'] == 'application/json'
    else:
        assert request.content == b''
    assert result['data'] == native._redact(case['response']['body']['data'], TOKEN)
    assert TOKEN not in json.dumps(result)

@pytest.mark.asyncio
async def test_claid_ai_connection_lists_account_storage_names(transport):
    calls, replies = transport
    replies.append(httpx.Response(200, json=CASES['list_storages']['response']['body']))
    result = await node({'operation': 'list_storages'}).execute({})
    assert [row['name'] for row in result['data']] == ['s3-playground', 'designer-uploads']
    assert native.ClaidAiNode.connection_evidence.operation == 'list_storages'
    assert native.ClaidAiNode.connection_evidence.proves == 'account'
    assert all(call.method == 'GET' for call in calls)

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 422, 429, 500])
async def test_claid_ai_rejections_keep_provider_message_and_redact_key(transport, status):
    calls, replies = transport
    replies.append(httpx.Response(status, json={'error_message': 'Not enough permissions. ' + TOKEN, 'error_code': '107'}))
    result = await node({'operation': 'list_storages'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Not enough permissions. [redacted]'}
    assert len(calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'Location': 'https://other.test/'}), httpx.Response(500, text='<html>failure</html>')])
async def test_claid_ai_redirect_or_non_json_error_is_not_followed(transport, response):
    calls, replies = transport
    replies.append(response)
    result = await node({'operation': 'list_storages'}).execute({})
    assert result['status'] == 'error' and len(calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='not JSON'), httpx.Response(200, json=['unexpected'])])
async def test_claid_ai_unreadable_response_is_not_success(transport, response):
    _, replies = transport
    replies.append(response)
    with pytest.raises(ValueError, match='Claid returned'):
        await node({'operation': 'list_storages'}).execute({})

@pytest.mark.asyncio
async def test_claid_ai_nested_cloud_credentials_never_escape(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json={'data': {'parameters': {'credentials': {'access_key': 'cloud-key', 'secret_access_key': 'secret'}}, 'message': TOKEN}}))
    result = await node({'operation': 'get_storage', 'storage_id': 1}).execute({})
    assert result['data']['parameters']['credentials'] == '[redacted]'
    assert result['data']['message'] == '[redacted]'
    assert 'cloud-key' not in json.dumps(result)

@pytest.mark.asyncio
async def test_claid_ai_async_acceptance_and_errors_are_not_completion(transport):
    calls, replies = transport
    replies.append(httpx.Response(200, json=CASES['ai_edit_image']['response']['body']))
    result = await node(CASES['ai_edit_image']['config']).execute({})
    assert result['data']['status'] == 'ACCEPTED' and len(calls) == 1
    payload = {'data': {'id': 1, 'status': 'ERROR', 'errors': [{'error': 'Image unavailable'}]}}
    replies.append(httpx.Response(200, json=payload))
    result = await node({'operation': 'get_ai_edit_result', 'ai_edit_id': 1}).execute({})
    assert result['data'] == payload['data']

@pytest.mark.parametrize('value', ['https://example.com/key', 'Bearer token', 'abc\r\nheader:value', '<token>'])
def test_claid_ai_invalid_key(value):
    with pytest.raises(ValidationError):
        native.ClaidAiAPIKeyCredential(api_key=value)

@pytest.mark.parametrize('config', [
    {'operation': 'ai_edit_image', 'input': 'https://images.test/in.jpg', 'options': {'prompt': 'x'}},
    {'operation': 'ai_edit_image', 'input': 'https://images.test/in.jpg', 'options': {'prompt': 'replace background', 'inference_steps': 100}},
    {'operation': 'edit_image', 'input': 'https://images.test/in.jpg', 'operations': {'undocumented': True}},
    {'operation': 'get_storage', 'storage_id': '../secrets'},
    {'operation': 'create_storage', 'name': 'web', 'type': 'web_folder', 'parameters': {'bucket': 'bucket', 'credentials': {'access_key': 'key', 'secret_access_key': 'secret'}}},
    {'operation': 'generate_video', 'input': 'https://images.test/in.jpg'},
])
def test_claid_ai_invalid_config(config):
    assert native.ClaidAiNode.validate_config({'config': config, 'credentials': CREDENTIAL})['valid'] is False

def test_claid_ai_self_registration_and_manual_key_default():
    assert NODE_REGISTRY['automation-claid-ai'] is native.ClaidAiNode
    assert native.ClaidAiAPIKeyCredential(api_key=TOKEN).credential_type == 'claid_ai_api_key'


@pytest.mark.asyncio
async def test_claid_ai_cloud_secret_in_provider_error_is_redacted(transport):
    _, replies = transport
    replies.append(httpx.Response(422, json={"error_message": "Invalid YourSecretAccessKey for AKIAXXXXXXX"}))
    result = await node(CASES["create_storage"]["config"]).execute({})
    assert result["error"] == "Invalid [redacted] for [redacted]"


def test_claid_ai_credential_validation_does_not_echo_secret():
    with pytest.raises(ValidationError) as failure:
        native.ClaidAiFullConfig.model_validate({"config": {"operation": "list_storages"},
            "credentials": {"credential_type": "wrong", "api_key": TOKEN}})
    assert TOKEN not in str(failure.value)

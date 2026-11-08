"""Exercise Botsonic's public wire contract through the registered node factory."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import botsonic_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


CASES = [
    ({'operation': 'generate_response', 'input_text': 'Hello', 'chat_id': 'chat-1'}, 'POST', '/v1/botsonic/generate', {'input_text': 'Hello', 'chat_id': 'chat-1'}),
    ({'operation': 'list_faqs'}, 'GET', '/v1/business/bot-faq/all', None),
    ({'operation': 'create_faq', 'question': 'Hours?', 'answer': 'Nine to five'}, 'POST', '/v1/business/bot-faq', {'question': 'Hours?', 'answer': 'Nine to five'}),
    ({'operation': 'delete_faq', 'faq_id': 'faq/1'}, 'DELETE', '/v1/business/bot-faq/faq%2F1', None),
    ({'operation': 'list_training_data'}, 'GET', '/v1/business/bot-data/all', None),
    ({'operation': 'list_conversations'}, 'GET', '/v1/business/bot-data/conversations/all', None),
    ({'operation': 'list_conversations_with_source'}, 'GET', '/v1/business/bot-data/conversations/with-source', None),
    ({'operation': 'get_conversation', 'chat_id': 'chat-1'}, 'GET', '/v1/business/bot-data/conversations/chat-1', None),
    ({'operation': 'end_chat', 'chat_id': 'chat-1', 'feedback': 'Thanks'}, 'POST', '/v1/business/bot-data/conversations/chat-1/end-chat', {'status': 'none', 'feedback': 'Thanks'}),
    ({'operation': 'delete_training_data', 'data_id': 'data-1'}, 'DELETE', '/v1/business/bot-data/data-1', None),
    ({'operation': 'upload_urls', 'urls': ['https://example.com']}, 'POST', '/v1/business/bot-data/bulk-upsert-urls', {'urls': ['https://example.com'], 'is_sitemap': False, 'is_crawled': False}),
    ({'operation': 'upload_file', 'id': 'file-1', 'bot_id': 'bot-1', 'file_url': 'https://example.com/file.pdf'}, 'POST', '/v1/business/bot-data/upload-file', {'id': 'file-1', 'bot_id': 'bot-1', 'file_url': 'https://example.com/file.pdf'}),
    ({'operation': 'upload_text', 'id': 'text-1', 'bot_id': 'bot-1', 'text': 'Our hours'}, 'POST', '/v1/business/bot-data/upload-text', {'id': 'text-1', 'bot_id': 'bot-1', 'text': 'Our hours'}),
    ({'operation': 'list_starter_questions'}, 'GET', '/v1/business/bot-starter-questions/all', None),
    ({'operation': 'create_starter_question', 'question': 'Hours?', 'answer': 'Nine'}, 'POST', '/v1/business/bot-starter-questions', {'question': 'Hours?', 'answer': 'Nine', 'order': 0}),
    ({'operation': 'delete_starter_question', 'starter_question_id': 'q-1'}, 'DELETE', '/v1/business/bot-starter-questions/q-1', None),
    ({'operation': 'update_starter_question', 'starter_question_id': 'q-1', 'order': 2}, 'PATCH', '/v1/business/bot-starter-questions/q-1', {'order': 2}),
    ({'operation': 'list_starter_presets'}, 'GET', '/v1/business/bot-starter-presets/all', None),
]


def node(config):
    return NodeFactory.create_node(node_id='botsonic-test', node_type='automation-botsonic', node_data={
        'config': config, 'credentials': {'credential_type': 'botsonic_api_token', 'api_token': 'private-test-token'}})


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES)
async def test_wire_contract(monkeypatch, config, method, path, body):
    seen = []
    response = {'items': [{'id': 'owned-resource', 'question': 'Hours?'}], 'total': 1, 'page': 1, 'size': 50, 'pages': 1}
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    out = await node(config).execute({})
    assert out == {'status': 'success', 'data': response}
    assert len(seen) == 1
    req = seen[0]
    assert req.method == method
    assert req.url.host == 'api.botsonic.ai'
    assert req.url.raw_path.split(b'?')[0].decode() == path
    key = 'token' if config['operation'] == 'generate_response' else 'X-BOT-KEY'
    assert req.headers[key] == 'private-test-token'
    assert 'USER-API-KEY' not in req.headers
    assert (json.loads(req.content) if req.content else None) == body
    assert 'operation' not in dict(req.url.params)


@pytest.mark.asyncio
async def test_provider_rejection_redacts_token(monkeypatch):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text='Invalid private-test-token')), **kw))
    out = await node({'operation': 'list_faqs'}).execute({})
    assert out == {'status': 'error', 'http_status': 401, 'error': 'Invalid [redacted]'}


def test_required_inputs_and_pagination_bounds():
    for config in [{'operation': 'create_faq'}, {'operation': 'list_faqs', 'size': 101}, {'operation': 'list_faqs', 'page': 0}]:
        with pytest.raises(ValidationError):
            native.BotsonicFullConfig.model_validate({'config': config})
    with pytest.raises(ValidationError):
        native.BotsonicCredential(api_token='a\nb')

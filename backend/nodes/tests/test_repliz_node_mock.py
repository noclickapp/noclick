"""Published Repliz examples through the native operation and HTTP seam."""
import base64
import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import repliz_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/repliz/responses.json').read_text())
AUTH = {'credential_type': 'repliz_api_keys', 'access_key': 'fixture-access', 'secret_key': 'fixture-secret'}
@pytest.fixture
def ensure_native_db_pool():
    yield
@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.repliz.com'
        assert request.headers['authorization'] == 'Basic ' + base64.b64encode(b'fixture-access:fixture-secret').decode()
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies
async def run(operation, args=None):
    return await run_node_operation(node_type='automation-repliz', operation=operation, arguments=args or {}, credential_data=deepcopy(AUTH), user_id='00000000-0000-4000-8000-000000000001')
@pytest.mark.asyncio
async def test_repliz_evidence_and_array_encoding(transport):
    requests, replies = transport
    replies.append((200, FIXTURES['list_accounts']))
    assert await run('list_accounts', {'types': ['facebook','instagram']}) == FIXTURES['list_accounts']
    assert requests[0].url.params.get_list('types[]') == ['facebook','instagram']
    assert requests[0].url.params['page'] == '1'
@pytest.mark.asyncio
async def test_repliz_reply_body(transport):
    requests, replies = transport
    replies.append((200, FIXTURES['reply_comment']))
    await run('reply_comment', {'commentId': '69afe793cb043c8192dcc3c7', 'body': {'text': 'Thanks!'}})
    assert requests[0].method == 'POST'
    assert json.loads(requests[0].content)['text'] == 'Thanks!'
@pytest.mark.asyncio
async def test_repliz_rejected_keys(transport):
    _, replies = transport
    replies.append((401, {'message': 'Unauthorized'}))
    with pytest.raises(httpx.HTTPStatusError):
        await run('list_accounts')
@pytest.mark.asyncio
async def test_repliz_poll_documented_comment(monkeypatch, transport):
    _, replies = transport
    body = deepcopy(FIXTURES['list_comments']);body['hasNextPage'] = False
    replies.append((200, body))
    captured = []
    async def unseen(self, items, key):
        captured.extend(key(item) for item in items)
        return items
    monkeypatch.setattr(node.ReplizNode, '_filter_unseen', unseen)
    result = await run('on_new_comment')
    assert captured == [item['_id'] for item in body['docs']]
    assert node.ReplizNode.resolve_agent_event(result)['text'].startswith('Repliz new comments:')
    assert not node.ReplizNode.should_propagate_output({'comments': []}, {'operation':'on_new_comment'})

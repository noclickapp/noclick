"""Synthetic HTTP regressions for SendFox's published personal-token API."""
import json
import httpx
import pytest
from nodes import sendfox_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='sendfox-test', node_type='automation-sendfox', node_data={
        'config': config, 'credentials': {'credential_type': 'sendfox_token', 'access_token': 'synthetic-sendfox-token'}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    return requests

@pytest.mark.asyncio
async def test_sendfox_create_contact_preserves_list_and_tag_distinction(monkeypatch):
    requests = transport(monkeypatch, body={'id': 12, 'email': 'reader@example.com'})
    result = await node({'operation':'create_contact','email':'reader@example.com','lists':[4],'contact_tags':[7]}).execute({})
    assert result['data']['id'] == 12
    request = requests[0]
    assert str(request.url) == 'https://api.sendfox.com/contacts'
    assert request.method == 'POST'
    assert request.headers['Authorization'] == 'Bearer synthetic-sendfox-token'
    assert json.loads(request.content) == {'email':'reader@example.com','lists':[4],'contact_tags':[7]}
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_sendfox_read_preserves_pagination(monkeypatch):
    body={'data':[{'id':12}], 'current_page':1, 'per_page':100, 'total':201}
    requests=transport(monkeypatch, body=body)
    result=await node({'operation':'list_contacts','query':'reader','unsubscribed':False}).execute({})
    assert result['data'] == body
    assert dict(requests[0].url.params) == {'query':'reader','unsubscribed':'false','per_page':'100'}

@pytest.mark.asyncio
async def test_sendfox_membership_delete_has_no_body(monkeypatch):
    requests=transport(monkeypatch, body={'message':'Contact removed'})
    await node({'operation':'remove_contact_from_list','list_id':4,'contact_id':12}).execute({})
    assert requests[0].method == 'DELETE'
    assert requests[0].url.path == '/lists/4/contacts/12'
    assert requests[0].content == b''

@pytest.mark.asyncio
async def test_sendfox_rejection_is_visible_without_token(monkeypatch):
    requests=transport(monkeypatch, status=401, body={'message':'Rejected synthetic-sendfox-token'})
    result=await node({'operation':'get_current_user'}).execute({})
    assert result == {'status':'error','error':'Rejected [redacted]','http_status':401}
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_sendfox_update_refuses_empty_body(monkeypatch):
    requests=transport(monkeypatch, body={})
    with pytest.raises(ValueError, match='at least one field'):
        await node({'operation':'update_contact','id':12}).execute({})
    assert requests == []

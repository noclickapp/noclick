"""Exercise Textline through the real factory with provider-authored examples.

Request expectations are fixed fixtures, independent of the node's routing map.
No Textline account, credentials, or live writes are used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import textline_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/textline/operations.json').read_text())
TOKEN = 'synthetic-textline-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='textline-fixture', node_type='automation-textline',
        node_data={'config':config, 'credentials':{'credential_type':'textline_access_token','access_token':TOKEN}})


def transport(monkeypatch, payload, status=200, *, raw=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload) if raw is None else httpx.Response(status, text=raw)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'])
async def test_published_request_and_response(monkeypatch, case):
    requests = transport(monkeypatch, case['response'])
    output = await node(case['config']).execute({})
    assert output['status'] == 'success' and output['data'] == case['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.scheme == 'https' and request.url.host == 'application.textline.com'
    assert request.url.path == case['path']
    assert request.headers['X-TGP-ACCESS-TOKEN'] == TOKEN
    if case['body'] is None:
        assert request.content == b''
    else:
        assert json.loads(request.content) == case['body']
    expected_params = {key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in case['config'].items() if key not in {'uuid','operation'}} if case['method'] == 'GET' else {}
    assert dict(request.url.params) == expected_params
    assert TOKEN not in str(output)


@pytest.mark.asyncio
async def test_whisper_and_resolve_are_explicit(monkeypatch):
    requests = transport(monkeypatch, {'conversation':{'uuid':'owned'}})
    await node({'operation':'send_message','phone_number':'(222) 222-2222','body':'internal note',
        'internal_whisper':True,'resolve':True,'group_uuid':'department-id'}).execute({})
    assert json.loads(requests[0].content) == {'phone_number':'(222) 222-2222',
        'group_uuid':'department-id','whisper':{'body':'internal note'},'resolve':'1'}


@pytest.mark.asyncio
async def test_update_omits_unsupplied_fields_and_preserves_false(monkeypatch):
    requests = transport(monkeypatch, {'customer':{'uuid':'owned','blocked':False}})
    await node({'operation':'update_customer','uuid':'owned','blocked':False,
        'tags':'foo_bar','tags_handling':'remove','custom_fields':{'field-id':'value'}}).execute({})
    assert json.loads(requests[0].content) == {'customer':{'blocked':False,'tags':'foo_bar',
        'tags_handling':'remove','custom_fields':{'field-id':'value'}}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301,302,400,401,403,404,429,500])
async def test_provider_errors_preserved_and_token_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'errors':{'token':[TOKEN],'name':['Must be present']}}, status)
    output = await node({'operation':'list_departments'}).execute({})
    assert output['status'] == 'error' and output['http_status'] == status
    assert 'Must be present' in str(output) and TOKEN not in str(output) and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_non_json_are_not_success(monkeypatch):
    transport(monkeypatch, {'errors':{'name':['Must be present']}})
    assert (await node({'operation':'list_departments'}).execute({}))['status'] == 'error'
    transport(monkeypatch, None, raw='<html>Login</html>')
    assert (await node({'operation':'get_organization'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_connection_evidence_has_account_departments(monkeypatch):
    transport(monkeypatch, {'departments':[{'uuid':'owned','name':'Customer Service'}]})
    output = await node({'operation':'list_departments'}).execute({})
    assert output['items'] == [{'uuid':'owned','name':'Customer Service'}]
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match='department list'):
        await node({'operation':'list_departments'}).execute({})


def test_credentials_default_for_hand_connect_and_reject_wrong_family():
    credential = native.TextlineAccessTokenCredential(access_token=TOKEN)
    assert credential.credential_type == 'textline_access_token'
    with pytest.raises(ValidationError):
        native.TextlineAccessTokenCredential(credential_type='other_token', access_token=TOKEN)


@pytest.mark.parametrize('value', ['../outside','a/b','a?admin=true','https://example.com'])
def test_resource_ids_cannot_change_routes(value):
    with pytest.raises(ValidationError):
        native.GetCustomer(uuid=value)


def test_empty_contact_update_is_rejected():
    with pytest.raises(ValidationError, match='at least one'):
        native.UpdateCustomer(uuid='owned')

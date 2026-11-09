"""Membership.io request contracts and migration handling; no live credentials."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import membershipio_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/membershipio/requests.json').read_text())
TOKEN = 'synthetic-membershipio-token'


def node(config):
    return NodeFactory.create_node(node_id='membershipio-test', node_type='automation-membershipio',
        node_data={'config':config, 'credentials':{'credential_type':'membershipio_token','access_token':TOKEN}})


def transport(monkeypatch, handler):
    requests = []
    def reply(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_membershipio_request_contract(monkeypatch, operation):
    case = CASES[operation]
    config = dict(case['config'])
    if operation == 'list_audience':
        config.update(page=2, filter_email='member@example.com', filter_is_person=False,
            sort=['name','email'], include=['tags','hubs'])
    response = {'current_page':2,'data':[{'id':12,'name':'Member'}],'next_page_url':'https://app.membership.io/api/v2/audience?page=3'}
    if operation == 'get_profile': response = {'id':12,'name':'Account','email':'owner@example.com'}
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=response))
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == response
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method']
    assert req.url.path == '/api/v2' + case['path'].replace('{audience}','member-hash').replace('{file}','file-hash')
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    if case['method'] != 'GET':
        assert json.loads(req.content) == {k:config[k] for k in case['body_fields'] if k in config}
    else: assert req.content == b''
    if operation == 'list_audience':
        assert req.url.params.get_list('sort') == ['name','email']
        assert req.url.params['filter[is_person]'] == 'false'
        assert req.url.params['filter[email]'] == 'member@example.com'


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,302,307,308])
async def test_membershipio_exact_migration_preserves_write(monkeypatch,status):
    def handler(req):
        if req.url.host == 'app.searchie.io':
            return httpx.Response(status, headers={'location':str(req.url).replace('app.searchie.io','app.membership.io:443')})
        return httpx.Response(200,json=[{'id':1,'name':'member'}])
    requests=transport(monkeypatch,handler)
    await node(CASES['detach_audience_hubs']['config']).execute({})
    assert len(requests)==2
    assert requests[1].method=='DELETE' and requests[1].content==requests[0].content
    assert requests[1].url.host=='app.membership.io'
    assert requests[1].headers['Authorization']=='Bearer '+TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize('target',['https://evil.example/api/v2/me','https://app.membership.io/api/v2/audience','https://app.membership.io.evil.example/api/v2/me'])
async def test_membershipio_refuses_unexpected_redirect(monkeypatch,target):
    requests=transport(monkeypatch,lambda req:httpx.Response(301,headers={'location':target}))
    with pytest.raises(ValueError, match='unexpected redirect'):
        await node({'operation':'get_profile'}).execute({})
    assert len(requests)==1


@pytest.mark.asyncio
async def test_membershipio_migration_preserves_query(monkeypatch):
    def handler(req):
        if req.url.host=='app.searchie.io':
            return httpx.Response(301,headers={'location':str(req.url).replace('app.searchie.io','app.membership.io')})
        return httpx.Response(200,json={'data':[]})
    requests=transport(monkeypatch,handler)
    await node({'operation':'list_audience','page':3,'filter_email':'a@example.com'}).execute({})
    assert requests[0].url.query==requests[1].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[401,403,422,500])
async def test_membershipio_rejection_text_redacts_token(monkeypatch,status):
    transport(monkeypatch,lambda req:httpx.Response(status,json={'message':'Invalid token '+TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_profile'}).execute({})
    assert f'HTTP {status}' in str(exc.value) and 'Invalid token' in str(exc.value)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize('field,value',[('audience','../me'),('file','a/b')])
def test_membershipio_resource_id_validation(field,value):
    op='list_member_tags' if field=='audience' else 'list_selected_file_tags'
    with pytest.raises(ValueError):node({'operation':op,field:value})


def test_membershipio_manual_token_default():
    credential=native.MembershipioTokenCredential(access_token=TOKEN)
    assert credential.credential_type=='membershipio_token'
    assert native.MembershipioTokenCredential.model_fields['credential_type'].default=='membershipio_token'


@pytest.mark.asyncio
async def test_membershipio_create_with_only_email(monkeypatch):
    requests=transport(monkeypatch,lambda req:httpx.Response(201,json={'id':42,'email':'member@example.com'}))
    await node({'operation':'create_audience','email':'member@example.com'}).execute({})
    assert json.loads(requests[0].content)=={'email':'member@example.com'}


@pytest.mark.asyncio
async def test_membershipio_error_envelope(monkeypatch):
    transport(monkeypatch,lambda req:httpx.Response(200,json={'success':False,'errors':{'token':'Invalid token'}}))
    with pytest.raises(ValueError,match='rejected'):
        await node({'operation':'get_profile'}).execute({})

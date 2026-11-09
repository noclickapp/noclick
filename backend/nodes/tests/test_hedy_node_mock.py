"""Wire behavior, replacement semantics, account proof and provider errors.

session.json is the GET /sessions/{sessionId} example from
https://api.hedy.bot/docs, version 1.6.10. Other responses are synthetic.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hedy_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

TOKEN = 'hedy-synthetic-token'


def node(config, **credential):
    return NodeFactory.create_node(node_id='hedy-test', node_type='automation-hedy', node_data={
        'config': config, 'credentials': {'credential_type': 'hedy_api_key', 'api_key': TOKEN, **credential},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
async def test_documented_session_content_is_preserved(monkeypatch):
    body = json.loads((Path(__file__).parent / 'fixtures/hedy/session.json').read_text())
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'get_session', 'session_id': 'sess_123456789'}).run({})
    assert result == body
    assert result['transcript'].startswith('Ada:')
    assert result['user_todos'][0]['completed'] is False
    assert len(requests) == 1 and requests[0].url.path == '/sessions/sess_123456789'
    assert requests[0].headers['authorization'] == 'Bearer ' + TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', [
    ({'operation':'replace_vocabulary','terms':['Hedy','NoClick'],'enabled':False}, 'PUT','/vocabulary',{'terms':['Hedy','NoClick'],'enabled':False}),
    ({'operation':'replace_vocabulary','terms':[]}, 'PUT','/vocabulary',{'terms':[]}),
    ({'operation':'replace_session_summary','session_id':'sess_1','recap':'Complete recap'},'PATCH','/sessions/sess_1/summary',{'recap':'Complete recap'}),
    ({'operation':'replace_session_summary','session_id':'sess_1','meeting_minutes':'Complete details'},'PATCH','/sessions/sess_1/summary',{'meetingMinutes':'Complete details'}),
    ({'operation':'assign_session_topic','session_id':'sess_1','topic_id':'topic_1'},'PATCH','/sessions/sess_1',{'topicId':'topic_1'}),
    ({'operation':'assign_session_topic','session_id':'sess_1'},'PATCH','/sessions/sess_1',{'topicId':None}),
    ({'operation':'update_todo','session_id':'sess_1','todo_id':'todo_1','completed':False},'PATCH','/sessions/sess_1/todos/todo_1',{'completed':False}),
    ({'operation':'update_todo','session_id':'sess_1','todo_id':'todo_1','clear_due_date':True},'PATCH','/sessions/sess_1/todos/todo_1',{'dueDate':''}),
    ({'operation':'update_todo','session_id':'sess_1','todo_id':'todo_1','due_date':'Next Monday'},'PATCH','/sessions/sess_1/todos/todo_1',{'dueDate':'Next Monday'}),
    ({'operation':'create_topic','name':'Weekly Standups','topic_context':'Focus on blockers','dominant_session_type':'business_meetings'},'POST','/topics',{'name':'Weekly Standups','topicContext':'Focus on blockers','dominantSessionType':'business_meetings'}),
    ({'operation':'update_topic','topic_id':'topic_1','clear_topic_context':True,'clear_dominant_session_type':True},'PATCH','/topics/topic_1',{'topicContext':None,'dominantSessionType':None}),
    ({'operation':'delete_topic','topic_id':'topic_1'},'DELETE','/topics/topic_1',None),
    ({'operation':'create_context','title':'Interview','content':'Focus on skills','is_default':False},'POST','/contexts',{'title':'Interview','content':'Focus on skills','isDefault':False}),
    ({'operation':'update_context','context_id':'ctx_1','is_default':False},'PATCH','/contexts/ctx_1',{'isDefault':False}),
    ({'operation':'delete_context','context_id':'ctx_1'},'DELETE','/contexts/ctx_1',None),
])
async def test_exact_write_body_no_extra_requests(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, {'success':True,'data':{'id':'resource'}})
    await node(config).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path) == (method,path)
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize('config,path,query', [
    ({'operation':'get_profile'},'/me',{}),
    ({'operation':'get_vocabulary'},'/vocabulary',{}),
    ({'operation':'list_sessions','limit':10,'after':'sess_previous'},'/sessions',{'limit':'10','after':'sess_previous'}),
    ({'operation':'list_highlights','after':'highlight_previous'},'/highlights',{'limit':'50','after':'highlight_previous'}),
    ({'operation':'get_highlight','highlight_id':'h_1'},'/highlights/h_1',{}),
    ({'operation':'list_todos'},'/todos',{}),
    ({'operation':'list_session_todos','session_id':'s_1'},'/sessions/s_1/todos',{}),
    ({'operation':'list_session_highlights','session_id':'s_1'},'/sessions/s_1/highlights',{}),
    ({'operation':'get_todo','session_id':'s_1','todo_id':'t_1'},'/sessions/s_1/todos/t_1',{}),
    ({'operation':'list_topic_sessions','topic_id':'t_1','limit':5,'start_after':'s_old'},'/topics/t_1/sessions',{'limit':'5','startAfter':'s_old'}),
    ({'operation':'list_topics'},'/topics',{}),
    ({'operation':'get_topic','topic_id':'t_1'},'/topics/t_1',{}),
    ({'operation':'list_contexts'},'/contexts',{}),
    ({'operation':'get_context','context_id':'c_1'},'/contexts/c_1',{}),
])
async def test_reads_region_and_cursor_routing(monkeypatch, config, path, query):
    requests = transport(monkeypatch, {'id':'user1','name':'Jane'})
    await node(config,region='eu').execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == 'GET' and req.url.host == 'eu-api.hedy.bot'
    assert req.url.path == path and dict(req.url.params) == query


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    {'success':True,'data':[],'pagination':{'hasMore':True,'next':'next-session','total':100}},
    {'success':True,'data':{'sessions':[],'topicInfo':{'id':'topic1'},'pagination':{'hasMore':True,'nextCursor':'next-session'}}},
    [],
])
async def test_pagination_envelopes_and_empty_arrays_are_preserved(monkeypatch, body):
    requests = transport(monkeypatch,body)
    result = await node({'operation':'list_sessions'}).run({})
    assert result == ({'data':body} if isinstance(body,list) else body)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[401,403,404,409,429,500,200])
async def test_provider_errors_are_not_success_and_secrets_are_redacted(monkeypatch,status):
    transport(monkeypatch,{'success':False,'error':{'code':'rejected','message':'Rejected '+TOKEN}},status)
    result = await node({'operation':'get_profile'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_identity_requires_account_id(monkeypatch):
    transport(monkeypatch,{'name':'Generic name'})
    with pytest.raises(ValueError,match='account ID'):
        await node({'operation':'get_profile'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('config,data', [
    ({'operation':'get_topic','topic_id':'topic_123xyz'}, {'id':'topic_123xyz','name':'Project Alpha Discussion'}),
    ({'operation':'update_topic','topic_id':'topic_123xyz','name':'Weekly Standups'}, {'id':'topic_123xyz','name':'Weekly Standups'}),
    ({'operation':'get_context','context_id':'ctx_abc123'}, {'id':'ctx_abc123','title':'Sales Call Context','isDefault':True}),
    ({'operation':'update_context','context_id':'ctx_abc123','is_default':False}, {'id':'ctx_abc123','title':'Sales Call Context','isDefault':False}),
    ({'operation':'list_topic_sessions','topic_id':'topic_123xyz'}, {'sessions':[],'topicInfo':{'id':'topic_123xyz'},'pagination':{'count':0,'hasMore':False,'nextCursor':None}}),
])
async def test_documented_standard_wrappers_with_overlapping_spec_alternatives(monkeypatch, config, data):
    # The provider's standard response schema is success/data for these reads
    # and updates, even though its bare-object oneOf branch also accepts it.
    body = {'success':True,'data':data}
    transport(monkeypatch,body)
    assert await node(config).run({}) == body


@pytest.mark.parametrize('config', [
    {'operation':'get_session','session_id':'../other'},
    {'operation':'list_sessions','limit':101},
    {'operation':'replace_vocabulary','terms':['Hedy','hedy']},
    {'operation':'replace_vocabulary','terms':['bad|term']},
    {'operation':'replace_vocabulary','terms':['x']},
    {'operation':'replace_session_summary','session_id':'s_1'},
    {'operation':'replace_session_summary','session_id':'s_1','recap':'   '},
    {'operation':'update_todo','session_id':'s_1','todo_id':'t_1'},
    {'operation':'update_todo','session_id':'s_1','todo_id':'t_1','clear_due_date':True,'due_date':'Monday'},
    {'operation':'update_topic','topic_id':'t_1'},
    {'operation':'update_topic','topic_id':'t_1','topic_context':'Keep','clear_topic_context':True},
    {'operation':'update_context','context_id':'c_1'},
])
def test_invalid_writes_and_resource_paths_fail_before_network(config):
    with pytest.raises(ConfigValidationError):
        node(config)


def test_manual_credential_default_region_and_key_shaping():
    credential = native.HedyAPICredential(api_key='  '+TOKEN+'\n')
    assert credential.credential_type == 'hedy_api_key' and credential.region == 'us'
    assert credential.api_key == TOKEN
    for bad in ['https://example.com','Bearer some-key','é-key','<token>']:
        with pytest.raises(ValidationError):
            native.HedyAPICredential(api_key=bad)

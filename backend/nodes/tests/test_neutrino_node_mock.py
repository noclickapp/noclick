"""Pinned provider examples and outbound wire regressions; no live calls."""
import json
from pathlib import Path
from urllib.parse import parse_qs
import httpx
import pytest
from nodes import neutrino_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

CREDS = {'credential_type': 'neutrino_api_key', 'user_id': 'example-user', 'api_key': 'synthetic-key'}

def node(config):
    return NodeFactory.create_node(node_type='automation-neutrino', node_id='test', node_data={'config': config, 'credentials': CREDS})

def mock_client(monkeypatch, body, status=200):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls

@pytest.mark.asyncio
async def test_neutrino_read_headers_and_boolean(monkeypatch):
    body=json.loads((Path(__file__).parent/'fixtures/neutrino/responses.json').read_text())['get_email_validation']
    calls=mock_client(monkeypatch,body)
    result=await node({'operation':'get_email_validation','email':'tech@neutrinoapi.com','fix_typos':True}).execute({})
    assert result == {'status':'success','data':body}
    assert calls[0].method=='GET'
    assert calls[0].url.path=='/email-validate'
    assert dict(calls[0].url.params)=={'email':'tech@neutrinoapi.com','fix-typos':'true'}
    assert calls[0].headers['user-id']=='example-user'
    assert calls[0].headers['api-key']=='synthetic-key'

@pytest.mark.asyncio
async def test_neutrino_post_form(monkeypatch):
    calls=mock_client(monkeypatch,{'is-bad':False,'bad-words-total':0,'bad-words-list':[],'censored-content':'hello'})
    await node({'operation':'filter_bad_words','content':'hello','censor_character':'*'}).execute({})
    assert calls[0].method=='POST'
    assert calls[0].url.path=='/bad-word-filter'
    assert parse_qs(calls[0].content.decode())=={'content':['hello'],'catalog':['strict'],'censor-character':['*']}

@pytest.mark.asyncio
async def test_neutrino_evidence_is_read_only(monkeypatch):
    calls=mock_client(monkeypatch,{'ip':'8.8.8.8','valid':True})
    await node({'operation':'get_ip_info'}).execute({})
    assert calls[0].url.path=='/ip-info'
    assert native.NeutrinoNode.connection_evidence.proves=='reachability'

@pytest.mark.asyncio
async def test_neutrino_error_envelope(monkeypatch):
    mock_client(monkeypatch,{'api-error': 1,'api-error-msg':'API key is invalid'})
    result=await node({'operation':'get_ip_info'}).execute({})
    assert result['status']=='error'
    assert result['error']=='API key is invalid'

@pytest.mark.asyncio
async def test_neutrino_http_rejection(monkeypatch):
    mock_client(monkeypatch,{'api-error':'denied'},403)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation':'get_ip_info'}).execute({})

@pytest.mark.parametrize('field', ['api_key','user_id'])
def test_neutrino_credential_rejects_controls(field):
    with pytest.raises(ValueError):
        native.NeutrinoAPIKeyCredential.model_validate({**CREDS,field:'bad\r\nheader'})

def test_neutrino_manual_credential_default():
    assert native.NeutrinoAPIKeyCredential(user_id='example-user',api_key='synthetic-key').credential_type=='neutrino_api_key'

@pytest.mark.asyncio
async def test_neutrino_html_returns_file(monkeypatch):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="Some HTML to clean...")), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result=await node({'operation':'clean_html','content':'Some HTML to clean...','output_type':'plain-text'}).execute({})
    assert isinstance(result['file'], native.BinaryOutput)
    assert result['file'].data==b'Some HTML to clean...'

"""Verify Browserbase routes, request bodies, API-key isolation and error handling.
These tests use an in-memory transport and never start a provider browser session.
"""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes.browserbase_tool_node import BrowserbaseToolNode, BrowserbaseToolApiKeyCredential
from pathlib import Path
from jsonschema import Draft4Validator, RefResolver

TOKEN = "bb-unit-test-key"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/browserbase-tool/request_contract.json").read_text())


def node(config):
    data = {"config": config, "credentials": {"credential_type": "browserbase_tool_api_key", "api_key": TOKEN}}
    return BrowserbaseToolNode("test", "automation-browserbase-tool", data, config=BrowserbaseToolNode.parse_config(data))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CONTRACT["cases"], ids=lambda c: c["config"]["operation"])
async def test_each_operation_maps_to_one_provider_request(monkeypatch, case):
    operation = case["config"]["operation"]
    calls = []
    config = case["config"]
    def handler(request):
        calls.append(request)
        assert request.headers['X-BB-API-Key'] == TOKEN
        assert request.url.host == 'api.browserbase.com'
        assert TOKEN not in str(request.url)
        if operation == 'delete_extension':
            return httpx.Response(204)
        body = [] if operation in {'list_projects','list_sessions','get_session_logs'} else {'id':'resource-123'}
        return httpx.Response(201 if operation in {'create_session','create_context'} else 200, json=body)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = await node(config).execute({})
    assert len(calls) == 1
    assert calls[0].method == case['method']
    assert calls[0].url.path == case['path']
    if 'requestBody' in case['contract']:
        schema=case['contract']['requestBody']['content']['application/json']['schema']
        Draft4Validator(schema, resolver=RefResolver.from_schema(CONTRACT)).validate(json.loads(calls[0].content))
    assert result['status'] == 'success'
    if operation == 'release_session':
        assert json.loads(calls[0].content) == {'projectId': config['project_id'], 'status':'REQUEST_RELEASE'}


@pytest.mark.asyncio
async def test_session_settings_and_filter(monkeypatch):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=[] if req.method=='GET' else {'id':'session'})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    await node({'operation':'create_session','project_id':'project','context_id':'context','persist_context':True,'timeout':120,'keep_alive':False,'region':'us-east-1','record_session':False,'log_session':True,'proxies':False}).execute({})
    assert json.loads(calls[0].content)=={'projectId':'project','timeout':120,'keepAlive':False,'region':'us-east-1','proxies':False,'browserSettings':{'recordSession':False,'logSession':True,'context':{'id':'context','persist':True}}}
    await node({'operation':'list_sessions','status':'RUNNING'}).execute({})
    assert dict(calls[1].url.params)=={'status':'RUNNING'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,429,500])
async def test_provider_errors_are_not_success(monkeypatch,status):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(lambda _:httpx.Response(status,json={'message':'provider refused'})),**kw))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation':'list_projects'}).execute({})


def test_manual_credential_and_config_validation():
    assert BrowserbaseToolApiKeyCredential(api_key=TOKEN).credential_type=='browserbase_tool_api_key'
    with pytest.raises(ValidationError):
        BrowserbaseToolApiKeyCredential(api_key=TOKEN,credential_type='unrelated')
    for timeout in [59,21601]:
        with pytest.raises(Exception):
            node({'operation':'create_session','project_id':'project','timeout':timeout})

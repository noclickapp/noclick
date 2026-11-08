"""DataRobot wire regressions use synthetic responses and never a real account."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import datarobot_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/datarobot/requests.json').read_text())
TOKEN = 'synthetic-datarobot-token-42'


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='datarobot-test', node_type='automation-datarobot',
        node_data={'config': config, 'credentials': credentials or {'credential_type':'datarobot_api_token','api_token':TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {'timeout':30,'follow_redirects':False,'trust_env':False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=[row[0] for row in CASES])
async def test_datarobot_wire_contract(monkeypatch, case):
    operation, config, method, path, query, body, status, response_body = case
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json=response_body) if response_body is not None else httpx.Response(status))
    current = node({'operation':operation, **config})
    current.emit = AsyncMock()
    result = await current.execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == '/api/v2' + path
    assert req.url.host == 'app.datarobot.com' and req.url.scheme == 'https'
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert dict(req.url.params) == query
    assert (json.loads(req.content) if req.content else None) == body
    assert result['success'] and result['status_code'] == status
    assert result['data'] == response_body
    if method != 'GET':
        assert result['request_accepted'] and result['readback_verified'] is False
    if status == 202:
        assert result['pending'] and result['completed'] is False
    assert TOKEN not in str(result)
    current.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_datarobot_refusals_keep_status_and_redact_token(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={'message':'Denied ' + TOKEN}))
    result = await node({'operation':'list_projects'}).execute({})
    assert not result['success'] and result['status'] == 'error'
    assert result['status_code'] == status and TOKEN not in str(result)
    assert 'Denied' in result['message'] and len(requests) == 1


@pytest.mark.asyncio
async def test_datarobot_page_links_are_data_never_followed(monkeypatch):
    body = {'data':[{'id':'dep1'}], 'next':'https://evil.example/steal', 'totalCount':2}
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node({'operation':'list_deployments','limit':1,'offset':0}).execute({})
    assert result['data'] == body and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>Sign in</html>'), httpx.Response(200, content=b''), httpx.Response(200, json='unexpected')])
async def test_datarobot_unusable_response_is_not_success(monkeypatch, response):
    transport(monkeypatch, lambda req: response)
    with pytest.raises(ValueError):
        await node({'operation':'list_projects'}).execute({})


@pytest.mark.asyncio
async def test_datarobot_timeout_does_not_retry_a_write(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout('timeout ' + TOKEN, request=req)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match='inspect writes before retrying') as exc:
        await node({'operation':'update_dataset','dataset_id':'d1','name':'New name'}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize('bad', ['https://example.test/key','Bearer abc','a\nb','<token>'])
def test_datarobot_invalid_manual_credential(bad):
    with pytest.raises(ValidationError):
        native.DataRobotAPITokenCredential(api_token=bad)


@pytest.mark.parametrize('bad', ['../private','a/b','a?query','a#fragment','%2f','..'])
def test_datarobot_invalid_resource_id(bad):
    result = native.DataRobotNode.validate_config({'config':{'operation':'get_project','project_id':bad},'credentials':{'api_token':TOKEN}})
    assert not result['valid']


def test_datarobot_manual_type_default_and_evidence():
    credential = native.DataRobotAPITokenCredential(api_token='  '+TOKEN+'  ')
    assert credential.credential_type == 'datarobot_api_token' and credential.api_token == TOKEN
    assert native.DataRobotNode.connection_evidence.operation == 'list_projects'
    assert native.DataRobotNode.validate_config({'config':{'operation':'list_projects'},'credentials':credential.model_dump()})['valid']


@pytest.mark.asyncio
@pytest.mark.parametrize('config,body', [
    ({'operation':'get_project','project_id':'p1'}, {'id':'p1','autopilotMode':None,'catalogId':None,'advancedOptions':{'blueprintThreshold':None}}),
    ({'operation':'get_model','project_id':'p1','model_id':'m1'}, {'id':'m1','featurelistId':None,'lifecycle':{'reason':None,'stage':'active'}}),
    ({'operation':'get_dataset','dataset_id':'d1'}, {'datasetId':'d1','createdBy':None,'timeSeriesProperties':{'isMostlyImputed':None}}),
    ({'operation':'get_deployment','deployment_id':'dep1'}, {'id':'dep1','label':None,'description':None,'accuracyHealth':{'endDate':None}}),
    ({'operation':'get_use_case','use_case_id':'u1'}, {'id':'u1','description':None,'created':{'id':'owner','email':None}}),
])
async def test_datarobot_documented_nullable_fields_are_preserved(monkeypatch, config, body):
    # Synthetic values exercise the nullable fields described by the provider
    # reference; they are not attributed as provider-authored response examples.
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    assert (await node(config).execute({}))['data'] == body

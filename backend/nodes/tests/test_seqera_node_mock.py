"""Offline Seqera contract regressions; no real tokens or accounts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import seqera_node as native
from nodes.core.registry import NodeFactory

ROWS = json.loads((Path(__file__).parent / 'fixtures/seqera/requests.json').read_text())
TOKEN = 'synthetic-seqera-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='seqera-test', node_type='automation-seqera',
        node_data={'config': config, 'credentials': {'credential_type': 'seqera_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, status=200, body=None):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else {'workflowId':'workflow-42'}) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('row', ROWS, ids=lambda r:r['operation'])
async def test_provider_endpoint_and_body(monkeypatch, row):
    seen = transport(monkeypatch)
    result = await node(row['config']).execute({})
    assert result['status'] == 'success'
    request = seen[0]
    assert len(seen) == 1 and request.method == row['method']
    assert request.url.host == 'api.cloud.seqera.io' and request.url.path == row['path']
    assert request.headers['Authorization'] == 'Bearer '+TOKEN
    if row['operation'] in {'create_pipeline','launch_workflow'}:
        assert json.loads(request.content)['launch'] == row['config']['launch']
    elif row['operation'] == 'create_dataset':
        assert json.loads(request.content) == {'name':'test-resource','sourceType':'UPLOADED'}
    elif row['operation'] == 'create_label':
        assert json.loads(request.content) == {'name':'test-resource','resource':False}
    elif row['operation'] == 'cancel_workflow':
        assert json.loads(request.content) == {} and request.url.params['force'] == 'false'
    elif row['operation'] == 'update_pipeline':
        assert json.loads(request.content) == {'name':'test-resource'}
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_scope_pagination_and_search(monkeypatch):
    seen = transport(monkeypatch, body={'workflows': [], 'totalSize': -1, 'hasMore': True})
    result = await node({'operation':'list_workflows','workspace_id':42,'max_results':20,'offset':40,'search':'status:RUNNING after:2026-08-01'}).execute({})
    assert dict(seen[0].url.params) == {'workspaceId':'42','max':'20','offset':'40','search':'status:RUNNING after:2026-08-01'}
    assert result['hasMore'] is True and result['totalSize'] == -1


@pytest.mark.asyncio
async def test_account_identity_and_no_content_ack(monkeypatch):
    transport(monkeypatch, body={'user':{'id':42,'userName':'scientist','email':'scientist@example.test'}})
    assert (await node({'operation':'get_user'}).execute({}))['user']['userName'] == 'scientist'
    transport(monkeypatch, status=204)
    assert (await node({'operation':'delete_pipeline','pipeline_id':123}).execute({}))['acknowledged'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302,400,401,403,404,429,500])
async def test_errors_redact_token_and_never_retry(monkeypatch, status):
    seen = transport(monkeypatch, status=status, body={'message':'rejected '+TOKEN})
    result = await node({'operation':'cancel_workflow','workflow_id':'workflow-42'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(seen) == 1


@pytest.mark.parametrize('config', [
    {'operation':'get_workflow','workflow_id':'../escape'},
    {'operation':'get_pipeline','pipeline_id':0},
    {'operation':'list_pipelines','max_results':101},
    {'operation':'launch_workflow','launch':{'pipeline':'hello'}},
    {'operation':'get_workflow'},
])
def test_reject_invalid_inputs(config):
    with pytest.raises((ValidationError,ValueError)):
        node(config)


def test_manual_credential_default_and_secret_widget():
    cred = native.SeqeraAPITokenCredential(api_token=' '+TOKEN+' ')
    assert cred.credential_type == 'seqera_api_token' and cred.api_token == TOKEN
    assert native.SeqeraAPITokenCredential.model_json_schema()['properties']['api_token']['ui:widget'] == 'password'
    assert len(ROWS) == 22

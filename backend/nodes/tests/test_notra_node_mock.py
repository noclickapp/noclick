"""Offline factory tests for Notra's documented one-request operation boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import notra_node as mod
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/notra/operations.json').read_text())['cases']
AUTH = {'credential_type': 'notra_api_key', 'api_key': 'notra-fixture-secret', 'organization_id': 'notra'}


def make(operation, config=None, credentials=AUTH):
    return NodeFactory.create_node(node_id='notra-test', node_type='automation-notra',
        node_data={'config': {'operation': operation, **(config or {})}, 'credentials': credentials})


@pytest.fixture
def wire(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))

    async def send(request):
        calls.append(request)
        assert request.url.host == 'api.usenotra.com'
        assert request.headers['authorization'] == 'Bearer notra-fixture-secret'
        assert request.headers['x-notra-organization-id'] == 'notra'
        assert AUTH['api_key'] not in str(request.url)
        status, body = replies.pop(0)
        if isinstance(body, bytes): return httpx.Response(status, content=body, headers={'content-type':'text/html'})
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(mod, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,sent,payload', CASES, ids=[c[0] for c in CASES])
async def test_notra_single_contract_request(wire, operation, config, method, path, sent, payload):
    calls, replies = wire
    replies.append((202 if operation == 'generate_post' else 200, payload))
    result = await make(operation, config).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.path == path
    if method == 'GET': assert dict(request.url.params) == sent
    elif method in {'POST','PATCH'}: assert json.loads(request.content) == sent
    else: assert request.content == b''
    assert result['status'] == 'success'
    assert result['operation'] == operation
    assert result['data'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301,400,401,403,404,429,500,502,504])
async def test_notra_errors_redact_and_never_retry(wire, status):
    calls, replies = wire
    replies.append((status, {'error':'Rejected notra-fixture-secret','recovery':'Check key'}))
    with pytest.raises(ValueError) as err:
        await make('create_post', {'title':'Post','contentType':'blog_post'}).execute({})
    assert f'HTTP {status}' in str(err.value)
    assert AUTH['api_key'] not in str(err.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'<html>login</html>', [], {}, {'error':'no'}, {'posts':{}}])
async def test_notra_invalid_response_is_not_connection_success(wire, body):
    wire[1].append((200,body))
    with pytest.raises(ValueError): await make('list_posts').execute({})


@pytest.mark.parametrize('value', ['../posts','a/b','a?b','a#b','https://example.com','bad\nheader'])
def test_notra_rejects_path_and_workspace_injection(value):
    with pytest.raises(ValidationError): mod.NotraAPIKeyCredential(api_key='notra-fixture-secret',organization_id=value)
    with pytest.raises(ValueError): make('get_post', {'post_id':value})


def test_notra_credential_can_be_created_by_hand():
    value = mod.NotraAPIKeyCredential(api_key=' notra-fixture-secret ')
    assert value.credential_type == 'notra_api_key'
    assert value.api_key == 'notra-fixture-secret'
    assert value.organization_id is None
    assert 'notra-fixture-secret' not in repr(value)
    with pytest.raises(ValueError): make('list_posts', credentials={**AUTH,'credential_type':'another_api_key'})


@pytest.mark.parametrize('config', [
    {'operation':'create_post','title':'Post','contentType':'twitter_post','slug':'post'},
    {'operation':'update_post','post_id':'post_123'},
    {'operation':'update_brand_identity','brand_identity_id':'brand_123'},
    {'operation':'update_brand_identity','brand_identity_id':'brand_123','isDefault':False},
    {'operation':'schedule_post','post_id':'post_123','scheduledAt':'2026-10-06'},
    {'operation':'schedule_post','post_id':'post_123','scheduledAt':'2026-10-06T08:00:00Z','timeZone':'invalid/zone'},
])
def test_notra_invalid_writes_fail_before_network(config):
    assert not mod.NotraNode.validate_config({'config':config,'credentials':AUTH})['valid']


@pytest.mark.asyncio
async def test_notra_workspace_read_provides_recognizable_evidence(wire):
    workspaces=[{'id':'org_1','slug':'notra','name':'Notra'}]
    wire[1].append((200,{'currentWorkspace':workspaces[0],'workspaces':workspaces,'authentication':{'type':'apiKey'}}))
    result=await make('list_workspaces').execute({})
    assert _rows_from_operation(result) == workspaces
    assert mod.NotraNode.connection_evidence.operation == 'list_workspaces'

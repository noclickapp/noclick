"""Transport tests against the independently selected published endpoint fixture."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fly_node as fly

CASES = json.loads((Path(__file__).parent / 'fixtures/fly/requests.json').read_text())['cases']
TOKEN = 'fm2_test_token_for_transport'


def node(config):
    data = {'config': config, 'credentials': {'api_token': TOKEN}}
    return fly.FlyNode('fly-test', 'automation-fly', data, config=fly.FlyNode.parse_config(data))


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(fly, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_provider_endpoint_and_auth(monkeypatch, case):
    seen = []
    def handle(request):
        seen.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.machines.dev'
        assert request.url.path == case['path'].format(**case['config'])
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        return httpx.Response(case['status'], json=case['response'], headers={'fly-next-cursor':'next-page'})
    transport(monkeypatch, handle)
    result = await node(case['config']).execute({})
    assert result['http_status'] == case['status'] and len(seen) == 1
    if case['config']['operation'] in {'delete_app', 'create_volume_snapshot'}:
        assert result['status'] == 'accepted' and result['completed'] is False
    if case['config']['operation'] in {'list_apps','list_machines','list_volumes'}:
        assert result['has_more'] and result['next_cursor'] == 'next-page'
    if case['config']['operation'] in {'create_machine','update_machine'}:
        assert json.loads(seen[0].content)['config'] == case['config']['machine_config']
        assert 'machine_config' not in json.loads(seen[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301,401,403,409,429,500])
async def test_errors_no_retry_or_token_leak(monkeypatch, status):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={'error': 'refused ' + TOKEN}, headers={'location':'https://example.org'})
    transport(monkeypatch, handle)
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_current_token'}).execute({})
    assert TOKEN not in str(exc.value) and f'HTTP {status}' in str(exc.value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_pagination_passes_cursor_even_after_empty_page(monkeypatch):
    def handle(request):
        assert request.url.params['cursor'] == 'opaque+cursor=='
        assert request.url.params['limit'] == '1'
        return httpx.Response(200, json=[], headers={'fly-next-cursor':'next'})
    transport(monkeypatch, handle)
    result = await node({'operation':'list_machines','app_name':'my-app','cursor':'opaque+cursor==','limit':1}).execute({})
    assert result['data'] == [] and result['has_more']


def test_manual_credential_default_and_bad_input():
    assert fly.FlyTokenCredential(api_token=TOKEN).credential_type == 'fly_api_token'
    for config in [{'operation':'get_app','app_name':'../other'}, {'operation':'list_apps'}, {'operation':'create_volume','app_name':'app','name':'data','region':'ord','size_gb':0}]:
        with pytest.raises(ValueError): node(config)
    with pytest.raises(ValidationError): fly.FlyTokenCredential(api_token='Bearer secret')


@pytest.mark.asyncio
async def test_snapshot_empty_response_is_async_ack(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200))
    result = await node({'operation':'create_volume_snapshot', 'app_name':'my-app', 'volume_id':'vol_test'}).execute({})
    assert result == {'status':'accepted', 'http_status':200, 'completed':False}

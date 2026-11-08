"""Offline HypeAuditor request/response contract and failure regressions."""
import json
from pathlib import Path
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes import hypeauditor_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/hypeauditor/requests.json').read_text())
CREDENTIAL = {'credential_type': 'hypeauditor_api_token', 'client_id': '360838', 'api_token': 'synthetic-secret-456'}


def node(config):
    return NodeFactory.create_node(node_id='fixture', node_type='automation-hypeauditor',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, reply):
    calls = []
    constructor = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return reply(request)
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return constructor(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', factory)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_each_operation_wire_contract(monkeypatch, operation):
    case = CASES[operation]
    config = case['config']
    deletion = operation in {'delete_media_plan', 'delete_plan_event'}
    payload = {'result': {'plans': [], 'total': 0, 'skipped': [{'reason': 'not found'}]}}
    calls = transport(monkeypatch, lambda request: httpx.Response(204) if deletion else httpx.Response(200, json=payload))
    output = await node(config).execute({})
    assert output['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    path = case['path']
    for field in ('planId', 'eventId', 'creator_id'):
        if '{' + field + '}' in path:
            path = path.replace('{' + field + '}', str(config[field]))
    assert request.url.scheme == 'https' and request.url.host == 'hypeauditor.com'
    assert request.url.path == path
    assert request.headers['X-Auth-Id'] == CREDENTIAL['client_id']
    assert request.headers['X-Auth-Hash'] == CREDENTIAL['api_token']
    query = parse_qs(request.url.query.decode())
    for field, name in case['query'].items():
        if field in config:
            value = config[field]
            expected = value if isinstance(value, list) else [str(value).lower() if isinstance(value, bool) else str(value)]
            assert query[name] == expected
    if case['body_fields']:
        assert json.loads(request.content) == {k: config[k] for k in case['body_fields'] if k in config}
    else:
        assert request.content == b''
    if deletion:
        assert output['deletion_acknowledged']
    else:
        assert output['result'] == payload['result']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(403, {'error': 'Token rejected'}), (200, {'error': 'No API access'}), (200, {'result': None})])
async def test_provider_errors_are_not_success(monkeypatch, status, payload):
    transport(monkeypatch, lambda request: httpx.Response(status, json=payload))
    result = await node({'operation': 'list_media_plans'}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_rejection_text_redacts_secret(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(403, json={'message': 'Rejected ' + CREDENTIAL['api_token']}))
    result = await node({'operation': 'list_media_plans'}).execute({})
    assert 'Rejected' in result['error'] and CREDENTIAL['api_token'] not in str(result)


@pytest.mark.asyncio
async def test_patch_null_and_omission(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={'result': {}}))
    await node({'operation': 'update_media_plan', 'planId': 'abc', 'description': None}).execute({})
    assert json.loads(calls[0].content) == {'description': None}


def test_manual_credential_and_identifier_guards():
    assert native.HypeAuditorAPIToken.model_validate(CREDENTIAL).credential_type == 'hypeauditor_api_token'
    for token in ['https://example.com/token', 'secret\nheader']:
        with pytest.raises(ValidationError):
            native.HypeAuditorAPIToken.model_validate({**CREDENTIAL, 'api_token': token})
    for cls, config in [(native.HypeAuditorAddPlanAccountsConfigAccountsItem, {'social_type': 'instagram'}),
                        (native.HypeAuditorGetLookalikesConfig, {'social_type': 'youtube', 'usernames': ['creator']})]:
        with pytest.raises(ValidationError):
            cls.model_validate(config)


@pytest.mark.asyncio
async def test_comment_default_sent_and_optional_null_omitted(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"result": {}}))
    await node({"operation": "create_plan_event", "planId": "abc", "value": "A comment", "social_type": "instagram", "social_id": "123"}).execute({})
    assert json.loads(calls[0].content)["type"] == "comment"
    await node({"operation": "create_media_plan", "title": None}).execute({})
    assert json.loads(calls[1].content) == {}

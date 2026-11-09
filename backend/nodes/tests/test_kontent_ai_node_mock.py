"""Replay unchanged provider-saved examples, plus transport and input guards."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import kontent_ai_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/kontent-ai/postman_examples.json').read_text())
ENVIRONMENT = '8d20758c-d74c-4f59-ae04-ee928c0816b7'
RESOURCE = '335d17ac-b6ba-4c6a-ae31-23c1193215cb'
CREDENTIAL = {'credential_type': 'kontent_ai_api_key', 'environment_id': ENVIRONMENT, 'api_key': 'synthetic-kontent-key'}


def config_for(operation):
    config = {'operation': operation}
    for var in FIXTURE['operations'][operation]['request']['url'].get('variable', []):
        if var['key'] != 'environment_id':
            config[var['key']] = RESOURCE
    if operation == 'update_item':
        config['name'] = 'My new article'
    if operation == 'create_language':
        config.update(name='German (Germany)', codename='de-DE')
    return config


def node(config, credential=None):
    return NodeFactory.create_node(node_id='kontent-fixture', node_type='automation-kontent-ai',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})


CASES = [(op, example) for op, fixture in FIXTURE['operations'].items() for example in fixture['responses']]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,example', CASES, ids=[op + ':' + str(e['code']) for op, e in CASES])
async def test_saved_postman_examples(monkeypatch, operation, example):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(example['code'], content=(example.get('body') or '').encode(),
            headers=[(h['key'], h['value']) for h in example.get('header', [])])
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    config = config_for(operation)
    if example['code'] >= 400:
        with pytest.raises(ValueError, match=f'HTTP {example["code"]}'):
            await node(config).execute({})
    else:
        result = await node(config).execute({})
        assert result['http_status'] == example['code']
        assert result['data'] == (json.loads(example['body']) if example.get('body') else None)
    assert len(requests) == 1
    request = requests[0]
    published = FIXTURE['operations'][operation]['request']
    expected_url = published['url']['raw'].replace(':environment_id', ENVIRONMENT)
    for key, value in config.items():
        expected_url = expected_url.replace(':' + key, str(value))
    assert str(request.url) == expected_url
    assert request.method == published['method']
    assert request.headers['authorization'] == 'Bearer ' + CREDENTIAL['api_key']
    if operation == 'update_item':
        assert json.loads(request.content) == {'name': config['name']}
    elif operation == 'create_language':
        assert json.loads(request.content) == {'name': 'German (Germany)', 'codename': 'de-DE'}
    elif operation in {'publish_variant', 'unpublish_variant'}:
        assert json.loads(request.content) == {}
    else:
        assert not request.content


@pytest.mark.parametrize('value', ['../../other', 'https://evil.test', RESOURCE + '/items', RESOURCE + '?x=1'])
def test_path_injection_rejected(value):
    with pytest.raises(ValidationError):
        native.KontentAiGetItemConfig(item_identifier=value)
    with pytest.raises(ValidationError):
        native.KontentAiAPIKeyCredential(environment_id=value, api_key='synthetic-key')


def test_manual_credential_defaults_and_secret_shape():
    credential = native.KontentAiAPIKeyCredential(environment_id=ENVIRONMENT, api_key='synthetic-key')
    assert credential.credential_type == 'kontent_ai_api_key'
    for value in ['https://example.test/key', 'Bearer key', 'key\nheader']:
        with pytest.raises(ValidationError):
            native.KontentAiAPIKeyCredential(environment_id=ENVIRONMENT, api_key=value)


@pytest.mark.asyncio
async def test_connection_evidence_names_the_environment(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    example = FIXTURE['operations']['get_environment']['responses'][0]
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(example['code'], content=example['body'],
                headers=[(h['key'], h['value']) for h in example['header']])), **kwargs))

    async def run_operation(**kwargs):
        assert kwargs['operation'] == 'get_environment'
        assert kwargs['credential_data'] == CREDENTIAL
        return await node({'operation': kwargs['operation']}).execute({})

    monkeypatch.setattr('nodes.core.run_op.run_node_operation', run_operation)
    result = await collect_evidence(node_type='automation-kontent-ai', credential_data=CREDENTIAL, user_id='fixture')
    assert result.reachable is True
    assert result.account_label == 'Sample project'


@pytest.mark.asyncio
async def test_continuation_stays_on_fixed_host_and_redacts_echoes(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'items': [], 'pagination': {'next_page': 'https://evil.test/'},
            'note': CREDENTIAL['api_key'], 'api_key': CREDENTIAL['api_key']}, headers={'X-Continuation': 'next-page'})
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    result = await node({'operation': 'list_items', 'continuation_token': 'previous-page'}).execute({})
    assert result['next_continuation_token'] == 'next-page'
    assert requests[0].headers['X-Continuation'] == 'previous-page'
    assert len(requests) == 1 and requests[0].url.host == 'manage.kontent.ai'
    assert CREDENTIAL['api_key'] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'location': 'https://evil.test'}),
    httpx.Response(200, text='<html>Login</html>'), httpx.Response(200, content=b'{', headers={'content-type': 'application/json'}),
    httpx.Response(200, json={'error_code': 1, 'message': 'Not authorized'})])
async def test_non_success_and_malformed_responses_fail(monkeypatch, response):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response), **kwargs))
    with pytest.raises(ValueError):
        await node({'operation': 'get_environment'}).execute({})

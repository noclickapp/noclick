"""Bannerbear V5 contract regressions, offline.

Fixtures retain provider sample objects (only explanatory // comment lines removed).
Each operation records its input and response source at https://developers.bannerbear.com/v5/.
List fixtures wrap the documented resource object in the array the API specifies.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.bannerbear_node import (
    BannerbearNode, BannerbearNodeConfig, BannerbearAPIKeyCredential, ROUTES,
)

CASES = json.loads((Path(__file__).parent / 'fixtures/bannerbear/responses.json').read_text())
TOKEN = 'bannerbear_mock_key'


def make_node(operation, config=None):
    return BannerbearNode(
        node_id='bannerbear-test', node_type='automation-bannerbear', node_data={},
        config=BannerbearNodeConfig.model_validate({
            'config': {'operation': operation, **(config if config is not None else CASES[operation]['config'])},
            'credentials': {'credential_type': 'bannerbear_api_key', 'api_key': TOKEN},
        }),
        sio=Mock(), sid='sid', workflow_id='workflow', user_id='user',
    )


def mocked_client(handler):
    original = httpx.AsyncClient
    return patch('nodes.bannerbear_node.httpx.AsyncClient', side_effect=lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_every_documented_operation(operation):
    case = CASES[operation]
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.bannerbear.com'
        assert request.url.path == '/v5' + case['path'].replace('{uid}', case['config'].get('uid', ''))
        assert request.headers['authorization'] == f'Bearer {TOKEN}'
        if request.method in {'POST', 'PATCH'}:
            expected = case['body'].copy()
            if operation == 'create_batch':
                expected.setdefault('type', 'images')
            assert json.loads(request.content) == expected
            assert request.headers['content-type'] == 'application/json'
            assert not request.url.params
        else:
            assert request.content == b''
            assert dict(request.url.params) == ({'page': '1'} if operation.startswith('list_') else {})
        if case['response'] is None:
            return httpx.Response(case['status_code'])
        return httpx.Response(case['status_code'], json=case['response'])

    with mocked_client(handler):
        result = await make_node(operation).execute({})
    assert len(seen) == 1
    assert result['status'] == 'success'
    assert result['action'] == operation
    assert result['data'] == (case['response'] if case['response'] is not None else {'deleted': True})
    assert result['timing_ms']['api_request'] >= 0


def test_fixture_covers_every_operation_and_has_sources():
    assert CASES.keys() == ROUTES.keys()
    for case in CASES.values():
        assert case['source'].startswith('https://developers.bannerbear.com/v5/#')
        assert case['input_source'].startswith('https://developers.bannerbear.com/v5/#')


@pytest.mark.asyncio
@pytest.mark.parametrize('field,operation', [('image_template','list_image_templates'), ('animation_template','list_animation_templates')])
async def test_dynamic_templates_use_account_data(field, operation):
    def handler(request):
        assert request.url.path == '/v5/' + ('image_templates' if field == 'image_template' else 'animation_templates')
        assert request.url.params['page'] == '2'
        return httpx.Response(200, json=CASES[operation]['response'])
    with mocked_client(handler):
        result = await BannerbearNode.load_field_options(field, {'api_key': TOKEN}, page_token='2', search='logo' if field == 'animation_template' else 'social')
    item = CASES[operation]['response'][0]
    assert result['options'] == [{'value': item['uid'], 'label': item['name']}]


@pytest.mark.asyncio
async def test_empty_workspace_is_a_valid_list():
    with mocked_client(lambda request: httpx.Response(200, json=[])):
        result = await make_node('list_image_templates').execute({})
        options = await BannerbearNode.load_field_options('image_template', {'api_key': TOKEN})
    assert result['status'] == 'success'
    assert result['data'] == []
    assert options['options'] == []
    assert BannerbearNode.connection_evidence.identity_operation == 'get_account'
    assert BannerbearNode.connection_evidence.identity_keys == ('workspace', 'uid')


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [400, 401, 402, 403, 404, 423, 429, 500])
async def test_provider_errors_remain_errors_and_redact_key(code):
    message = f'Provider rejection {TOKEN}'
    with mocked_client(lambda request: httpx.Response(code, json={'message': message})):
        result = await make_node('get_account').execute({})
    assert result['status'] == 'error'
    assert result['status_code'] == code
    assert result['error'] == 'Provider rejection [redacted]'
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_rejected_key_does_not_look_like_empty_picker():
    with mocked_client(lambda request: httpx.Response(401, json={'message': 'Unauthorized'})):
        with pytest.raises(ValueError, match='Unauthorized'):
            await BannerbearNode.load_field_options('image_template', {'api_key': TOKEN})


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>invalid</html>'), httpx.Response(200, json=[])])
async def test_unexpected_account_response_is_an_error(response):
    with mocked_client(lambda request: response):
        result = await make_node('get_account').execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [httpx.ReadTimeout('secret'), httpx.ConnectError('secret')])
async def test_transport_errors_are_safe(error):
    def handler(request):
        raise error
    with mocked_client(handler):
        result = await make_node('get_account').execute({})
    assert result['status'] == 'error'
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('count', [0, 101])
def test_batch_size_is_bounded(count):
    item = CASES['create_batch']['config']['items'][0]
    with pytest.raises(ValidationError, match='between 1 and 100'):
        make_node('create_batch', {'items': [item] * count})


def test_batch_items_require_v5_image_payloads():
    with pytest.raises(ValidationError):
        make_node('create_batch', {'items': [{'template': 'template'}]})
    with pytest.raises(ValidationError):
        make_node('create_image', {'template': 'template', 'modifications': '[]'})


@pytest.mark.asyncio
async def test_json_text_and_native_objects_serialize_identically():
    config = CASES['create_image']['config'].copy()
    config['modifications'] = json.dumps(config['modifications'])
    config['formats'] = json.dumps(config['formats'])
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(202, json=CASES['create_image']['response'])
    with mocked_client(handler):
        await make_node('create_image', config).execute({})
    assert seen == [CASES['create_image']['body']]


@pytest.mark.asyncio
async def test_image_optional_false_and_numeric_fields_survive():
    config = {**CASES['create_image']['config'], 'proxy': False, 'quality': 1, 'dpi': 72, 'version': 2}
    def handler(request):
        body = json.loads(request.content)
        for key in ('proxy', 'quality', 'dpi', 'version'):
            assert body[key] == config[key]
        return httpx.Response(202, json=CASES['create_image']['response'])
    with mocked_client(handler):
        assert (await make_node('create_image', config).execute({}))['status'] == 'success'


def test_uid_cannot_change_path_or_add_query():
    with pytest.raises(ValidationError):
        make_node('get_image', {'uid': '../account?key=value'})


def test_animation_overrides_require_documented_layer_identity():
    with pytest.raises(ValidationError, match="id and type"):
        make_node('create_animation', {
            'template': '6EZ9nQX0lzpWwqAgzB',
            'modifications': {'objects': [{'name': 'title', 'text': 'Now Playing'}]},
        })

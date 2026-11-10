"""Official OpenAPI examples and native factory HTTP-contract regressions."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lambdatest_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/lambdatest/official_examples.json').read_text())
CREDENTIAL = {'credential_type': 'lambdatest_access_key', 'username': 'fixture-user', 'access_key': 'fixture-access-key-987'}
TEST_ID = 'TES100968331562237283314836'
CASES = [
    ('start_screenshot_test', 'POST', '/', EXAMPLES['start_request']),
    ('get_screenshots', 'GET', '/{test_id}', {'test_id': TEST_ID}),
    ('get_screenshot_zip', 'GET', '/{test_id}/zip', {'test_id': TEST_ID}),
    ('stop_screenshot_test', 'PUT', '/stop/{test_id}', {'test_id': TEST_ID}),
    ('list_browsers', 'GET', '/os-browsers', {'os': 'windows 10'}),
    ('list_devices', 'GET', '/devices', {'os': 'ios 12.0'}),
    ('list_resolutions', 'GET', '/resolutions', {}),
    ('list_profiles', 'GET', '/profiles', {}),
    ('list_locations', 'GET', '/locations', {}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None, credential=None):
    return NodeFactory.create_node(node_id='lambdatest-fixture', node_type='automation-lambdatest',
        node_data={'config': {'operation': operation, **(config or {})}, 'credentials': credential or CREDENTIAL})


def transport(monkeypatch, body, status=200, headers=None):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method,path,config', CASES)
async def test_all_nine_official_operations(monkeypatch, operation, method, path, config):
    response = EXAMPLES['responses'][f'{method} {path}']
    calls = transport(monkeypatch, response)
    result = await node(operation, config).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.host == 'api.lambdatest.com'
    assert request.url.path == '/screenshots/v1' + path.format(test_id=TEST_ID)
    assert request.headers['authorization'] == 'Basic ' + base64.b64encode(b'fixture-user:fixture-access-key-987').decode()
    assert dict(request.url.params) == ({'os': config['os']} if 'os' in config else {})
    assert (json.loads(request.content) if request.content else None) == (config if method == 'POST' else None)
    assert CREDENTIAL['access_key'] not in json.dumps(result)
    if operation == 'list_profiles':
        assert result['items'][0]['name'] == 'lambda-login'
        assert result['data']['profiles'][0]['profile_config']['credentials']['password'] == '[redacted]'
    else:
        assert result['data'] == response


@pytest.mark.asyncio
async def test_eu_server_optional_false_zero_and_json_matrix(monkeypatch):
    calls = transport(monkeypatch, {'test_id': TEST_ID})
    config = {'url': 'http://localhost:3000', 'configs': '{"windows 10":{"chrome":["76"]}}',
              'email': False, 'defer_time': 0, 'tunnel': True, 'tunnel_identifier': 'my-tunnel',
              'username': 'site-user', 'password': 'site-password', 'callback_url': 'https://example.com/callback',
              'profile_id': 'lambda-login', 'country_code': 'US'}
    result = await node('start_screenshot_test', config, {**CREDENTIAL, 'region': 'eu'}).execute({})
    assert calls[0].url.host == 'eu-api.lambdatest.com'
    body = json.loads(calls[0].content)
    assert body == {**config, 'configs': {'windows 10': {'chrome': ['76']}}}
    assert result['data']['test_id'] == TEST_ID


@pytest.mark.asyncio
@pytest.mark.parametrize('status,message', [(401, 'Unauthorized'), (403, 'Screenshot API is supported only in our premium plans. Please upgrade.'), (404, 'No active Screenshot test found for this test_id'), (429, 'Too many requests'), (500, 'Server error')])
async def test_provider_rejections_preserve_message_and_never_retry(monkeypatch, status, message):
    calls = transport(monkeypatch, {'message': message}, status)
    result = await node('stop_screenshot_test', {'test_id': TEST_ID}).execute({})
    assert result == {'status': 'error', 'action': 'stop_screenshot_test', 'http_status': status, 'error': message}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_profile_evidence_empty_and_secret_redaction(monkeypatch):
    transport(monkeypatch, {'profiles': []})
    result = await node('list_profiles').execute({})
    assert result['items'] == []
    transport(monkeypatch, {'message': 'Rejected ' + CREDENTIAL['access_key']}, 401)
    result = await node('list_profiles').execute({})
    assert CREDENTIAL['access_key'] not in str(result)
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_non_json_and_array_fail_closed(monkeypatch):
    transport(monkeypatch, ['unexpected'])
    with pytest.raises(ValueError, match='unexpected JSON shape'):
        await node('list_locations').execute({})
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<html>login</html>')), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='non-JSON'):
        await node('list_locations').execute({})


@pytest.mark.asyncio
async def test_network_failure_reports_unknown_write_outcome(monkeypatch):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('fixture timeout', request=request)
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='inspect the dashboard before retrying a write'):
        await node('start_screenshot_test', EXAMPLES['start_request']).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize('test_id', ['..', '../profiles', 'id?x=y', 'id#fragment', 'id with spaces', 'id\\suffix'])
def test_path_input_cannot_change_endpoint(test_id):
    with pytest.raises(ValidationError):
        native.GetScreenshots(test_id=test_id)


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://user:password@example.com', 'not-a-url'])
def test_capture_url_requires_http_without_userinfo(url):
    with pytest.raises(ValidationError):
        native.StartScreenshotTest(url=url, configs={'windows 10': {'chrome': ['76']}})


def test_manual_credential_default_and_connection_evidence():
    credential = native.LambdaTestCredential(username=' fixture-user ', access_key=' fixture-access-key-987 ')
    assert credential.credential_type == 'lambdatest_access_key'
    assert credential.username == 'fixture-user'
    assert credential.access_key == CREDENTIAL['access_key']
    assert native.LambdaTestNode.connection_evidence.operation == 'list_profiles'
    assert not native.LambdaTestCredential.model_fields['credential_type'].is_required()

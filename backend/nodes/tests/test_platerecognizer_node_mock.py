"""Native factory and HTTP boundary checks; examples are copied from the pinned provider schema."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import platerecognizer_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-platerecognizer-token-42"
EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/platerecognizer/provider_examples.json').read_text())['examples']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='plate-test', node_type='automation-platerecognizer',
        node_data={'config': config, 'credentials': {'credential_type': native.TYPE, 'api_token': TOKEN}})


def transport(monkeypatch, status=200, body=None, content=None, content_type='application/json'):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content, headers={'Content-Type': content_type})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        assert kwargs['timeout'] >= 60
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ('recognize_plates', {'upload_url':'https://app.platerecognizer.com/static/demo.jpg','regions':['gb'], 'mmc':False, 'engine_config_json':'{"detection_mode":"vehicle"}'}, 'POST', '/v1/plate-reader/', '/v1/plate-reader/'),
    ('get_statistics', {}, 'GET', '/v1/statistics/', '/v1/statistics/'),
    ('extract_text', {'upload_url':'https://app.platerecognizer.com/static/demo.jpg','type':'trailer_id'}, 'POST', '/v1/ocr/reader/', '/v1/ocr/reader/'),
    ('get_ocr_statistics', {}, 'GET', '/v1/ocr/statistics/', '/v1/ocr/statistics/'),
    ('list_licenses', {'product_type':'snapshot'}, 'GET', '/v1/licenses/snapshot/', None),
    ('get_models', {}, 'GET', '/v1/models/', None),
    ('list_vision_licenses', {}, 'GET', '/v1/vision-alert/licenses/', '/v1/vision-alert/licenses/'),
    ('list_cameras', {'license_id':5}, 'GET', '/v1/vision-alert/5/cameras/', '/v1/vision-alert/{id}/cameras/'),
    ('list_camera_logs', {'license_id':5,'serial':'Q2GV-ABCD-1234'}, 'GET', '/v1/vision-alert/5/cameras/Q2GV-ABCD-1234/logs/', '/v1/vision-alert/{id}/cameras/{serial}/logs/'),
    ('list_license_logs', {'license_id':5}, 'GET', '/v1/vision-alert/5/logs/', '/v1/vision-alert/{id}/logs/'),
    ('get_camera_reference', {'license_id':5,'serial':'Q2GV-ABCD-1234'}, 'GET', '/v1/vision-alert/5/cameras/Q2GV-ABCD-1234/reference/', '/v1/vision-alert/{id}/cameras/{serial}/reference/'),
    ('list_alerts', {'license_id':5}, 'GET', '/v1/vision-alert/5/alerts/', '/v1/vision-alert/{id}/alerts/'),
    ('upload_video', {'upload_url':'https://api-storage.platerecognizer.com/assets/demo.mp4'}, 'POST', '/v1/stream/video-upload/', '/v1/stream/video-upload/'),
    ('list_stream_licenses', {}, 'GET', '/v1/stream/cloud-licenses/', None),
    ('list_recent_events', {}, 'GET', '/v1/zapier/', '/v1/zapier/'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('action,config,method,path,example_path', CASES)
async def test_platerecognizer_documented_requests_and_responses(monkeypatch, action, config, method, path, example_path):
    body = EXAMPLES.get(method + ' ' + str(example_path), {'results':[], 'next':None, 'previous':None})
    requests = transport(monkeypatch, 201 if method == 'POST' else 200, body)
    result = await node({'operation':action, **config}).execute({})
    assert NODE_REGISTRY['automation-platerecognizer'] is native.PlaterecognizerNode
    assert result['status'] == 'success' and result['data'] == body
    assert TOKEN not in str(result)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == 'api.platerecognizer.com'
    assert req.headers['Authorization'] == 'Token ' + TOKEN
    if method == 'POST':
        sent = json.loads(req.content)
        assert sent['upload_url'] == config['upload_url']
        assert 'operation' not in sent and 'engine_config_json' not in sent
        if action == 'recognize_plates':
            assert sent['config'] == {'detection_mode':'vehicle'} and sent['mmc'] is False
        if action == 'extract_text':
            assert sent['type'] == 'trailer_id'


@pytest.mark.asyncio
async def test_platerecognizer_query_filters_and_one_page(monkeypatch):
    body = {'results':[], 'next':'https://api.platerecognizer.com/v1/vision-alert/5/logs/?cursor=cD00ODY%3D', 'previous':None}
    requests = transport(monkeypatch, body=body)
    result = await node({'operation':'list_license_logs','license_id':5,'serial':'camera + one',
        'tag':'site + A','start':'2026-06-29T14:30:00Z','end':'2026-07-01','status':'anomaly',
        'cursor':'cD00ODY=', 'page_size':100}).execute({})
    assert result['data']['next'] == body['next'] and len(requests) == 1
    assert dict(requests[0].url.params) == {'serial':'camera + one','tag':'site + A','start':'2026-06-29T14:30:00Z',
        'end':'2026-07-01','status':'anomaly','cursor':'cD00ODY=','page_size':'100'}
    requests = transport(monkeypatch, body={'results':[]})
    await node({'operation':'list_alerts','license_id':5,'sent':False}).execute({})
    assert requests[0].url.params['sent'] == 'false'


@pytest.mark.asyncio
async def test_platerecognizer_delete_and_binary_download(monkeypatch):
    requests = transport(monkeypatch, status=204, content=b'')
    result = await node({'operation':'delete_camera','license_id':5,'serial':'Q2GV-ABCD-1234'}).execute({})
    assert result['deletion_acknowledged'] is True and requests[0].method == 'DELETE'
    assert not requests[0].content and not requests[0].url.query
    requests = transport(monkeypatch, content=b'[camera]\nname=front', content_type='text/plain')
    result = await node({'operation':'download_stream_config','code':'LIC-ABC123','version':'1.0'}).execute({})
    assert isinstance(result['file'], BinaryOutput)
    assert result['file'].data == b'[camera]\nname=front'
    assert requests[0].url.path == '/v1/stream/download-config/LIC-ABC123/'
    assert requests[0].url.params['version'] == '1.0'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302,401,403,404,429,500])
async def test_platerecognizer_errors_no_retry_and_token_redaction(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={'detail':'Rejected ' + TOKEN})
    result = await node({'operation':'upload_video','upload_url':'https://api-storage.platerecognizer.com/assets/demo.mp4'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1
    assert result['write_outcome_unknown'] == (status >= 500)


@pytest.mark.asyncio
async def test_platerecognizer_unexpected_response_and_path_refusal(monkeypatch):
    transport(monkeypatch, content=b'<html>sign in</html>',content_type='text/html')
    with pytest.raises(ValueError, match='Expected JSON'):
        await node({'operation':'get_statistics'}).execute({})
    requests = transport(monkeypatch, body={})
    with pytest.raises(ValueError, match='single resource'):
        await node({'operation':'download_stream_config','code':'../other'}).execute({})
    assert requests == []


def test_platerecognizer_manual_credential_and_input_validation():
    cred = native.PlaterecognizerApiTokenCredential(api_token=TOKEN)
    assert cred.credential_type == native.TYPE
    assert set(k for k,v in cred.model_fields.items() if v.is_required()) == {'api_token'}
    assert native.PlaterecognizerNode.connection_evidence.operation == 'list_vision_licenses'
    for value in ['', '☃', 'https://example.com/token', 'Token abc', 'abc\r\nInjected: x']:
        with pytest.raises(ValidationError):
            native.PlaterecognizerApiTokenCredential(api_token=value)
    with pytest.raises(ValidationError):
        native.ExtractText(upload_url='file:///etc/passwd',type='vin')
    with pytest.raises(ValidationError):
        native.RecognizePlates(upload_url='https://example.com/a.jpg',timestamp='2026-01-01T00:00:00')


@pytest.mark.asyncio
async def test_platerecognizer_empty_account_license_evidence(monkeypatch):
    requests = transport(monkeypatch, body=[])
    operation = native.PlaterecognizerNode.connection_evidence.operation
    result = await node({'operation':operation}).execute({})
    assert result['status'] == 'success' and result['data'] == []
    assert requests[0].url.path == '/v1/vision-alert/licenses/'
    assert not requests[0].url.query and len(requests) == 1

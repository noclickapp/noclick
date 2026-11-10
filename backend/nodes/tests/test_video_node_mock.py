"""api.video factory, request and signed-delivery regressions.

HTTP stays offline; response/event fixtures are copied from provider-published
OpenAPI examples and the official webhook verification guide.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import video_node as v
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

HTTP_CLIENT = httpx.AsyncClient

FIXTURES = Path(__file__).parent / "fixtures/video"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
REGISTRATION = json.loads((FIXTURES / "registration.json").read_text())["body"]
AUTH = {"api_key": "synthetic-video-key-42", "credential_type": "video_api_key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="video-test", node_type="automation-video", node_data={
        "config": {"operation": operation, **fields}, "credentials": AUTH})


def transport(monkeypatch, replies):
    requests = []
    client = HTTP_CLIENT
    def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return client(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(v.httpx, "AsyncClient", factory)
    return requests


CASES = [
    ("list_videos", {}, "GET /videos"),
    ("get_video", {"videoId": "vi4blUQJFrYWbaG44NChkH11"}, "GET /videos/{videoId}"),
    ("create_video", {"title": "Maths video", "source": "https://www.myvideo.url.com/video.mp4"}, "POST /videos"),
    ("update_video", {"videoId": "vi4blUQJFrYWbaG44NChkH11", "public": False, "tags": []}, "PATCH /videos/{videoId}"),
    ("delete_video", {"videoId": "vi4blUQJFrYWbaG44NChkH11"}, "DELETE /videos/{videoId}"),
    ("get_video_status", {"videoId": "vi4blUQJFrYWbaG44NChkH11"}, "GET /videos/{videoId}/status"),
    ("set_video_thumbnail", {"videoId": "vi4blUQJFrYWbaG44NChkH11", "timecode": "00:00:00.000"}, "PATCH /videos/{videoId}/thumbnail"),
    ("list_live_streams", {}, "GET /live-streams"),
    ("get_live_stream", {"liveStreamId": "li400mYKSgQ6xs7taUeSaEap"}, "GET /live-streams/{liveStreamId}"),
    ("create_live_stream", {"name": "Test live", "public": False}, "POST /live-streams"),
    ("update_live_stream", {"liveStreamId": "li400mYKSgQ6xs7taUeSaEap", "name": "My Live Stream Video"}, "PATCH /live-streams/{liveStreamId}"),
    ("delete_live_stream", {"liveStreamId": "li400mYKSgQ6xs7taUeSaEap"}, "DELETE /live-streams/{liveStreamId}"),
    ("complete_live_stream", {"liveStreamId": "li400mYKSgQ6xs7taUeSaEap"}, "PUT /live-streams/{liveStreamId}/complete"),
    ("list_captions", {"videoId": "vi4blUQJFrYWbaG44NChkH11"}, "GET /videos/{videoId}/captions"),
    ("get_caption", {"videoId": "vi4blUQJFrYWbaG44NChkH11", "language": "en"}, "GET /videos/{videoId}/captions/{language}"),
    ("delete_caption", {"videoId": "vi4blUQJFrYWbaG44NChkH11", "language": "en"}, "DELETE /videos/{videoId}/captions/{language}"),
    ("list_upload_tokens", {}, "GET /upload-tokens"),
    ("create_upload_token", {"ttl": 3600}, "POST /upload-tokens"),
    ("delete_upload_token", {"uploadToken": "to1RTOdg7eR1rB2m4KhF4RJv"}, "DELETE /upload-tokens/{uploadToken}"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,route", CASES)
async def test_operations_with_provider_responses(monkeypatch, operation, config, route):
    example = RESPONSES.get(route)
    requests = transport(monkeypatch, [(example['status'], example['body']) if example else (204, None)])
    result = await node(operation, **config).execute({})
    assert result['status'] == 'success'
    assert result['data'] == (example['body'] if example else {'acknowledged': True})
    request = requests[0]
    assert request.url.host == 'ws.api.video'
    assert request.method == route.split()[0]
    path = route.split()[1]
    for k, value in config.items():
        path = path.replace('{' + k + '}', str(value))
    assert request.url.path == path
    assert request.headers['Authorization'] == 'Basic ' + base64.b64encode((AUTH['api_key'] + ':').encode()).decode()
    if operation == 'update_video':
        assert json.loads(request.content) == {'public': False, 'tags': []}
    if operation == 'create_video':
        assert json.loads(request.content) == config
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'currentPage': '1', 'pageSize': '25'}


@pytest.mark.asyncio
async def test_pagination_filters_and_sandbox(monkeypatch):
    example = RESPONSES['GET /videos']['body']
    requests = transport(monkeypatch, [(200, example)])
    n = node('list_videos', currentPage=2, pageSize=10, sortBy='updatedAt', sortOrder='desc', title='Maths video')
    n.config.credentials.environment = 'sandbox'
    result = await n.execute({})
    assert result['data']['pagination'] == example['pagination']
    assert requests[0].url.host == 'sandbox.api.video'
    assert dict(requests[0].url.params) == {'currentPage':'2','pageSize':'10','sortBy':'updatedAt','sortOrder':'desc','title':'Maths video'}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,event', v.EVENTS.items())
async def test_signed_registration_delivery_and_cleanup(monkeypatch, operation, event):
    requests = transport(monkeypatch, [(201, REGISTRATION), (204, None)])
    state = await v.VideoNode._register_external_webhook(webhook_url='https://example.com/webhooks', credential=AUTH, config={'operation':operation}, node_id='video-test')
    assert json.loads(requests[0].content) == {'events':[event], 'url':'https://example.com/webhooks'}
    payload = EVENTS[event]['body']
    raw = json.dumps(payload).encode()
    signature = hmac.new(state['signing_secret'].encode(), raw, hashlib.sha256).hexdigest()
    headers = {'X-Api-Video-Signature':signature}
    assert v.VideoNode.verify_webhook_signature(raw, headers, state)
    assert not v.VideoNode.verify_webhook_signature(raw+b' ', headers, state)
    assert not v.VideoNode.verify_webhook_signature(raw, {}, state)
    assert not v.VideoNode.verify_webhook_signature(raw, headers, {})
    assert v.VideoNode.filter_trigger_payload(payload, {'operation':operation})
    assert not v.VideoNode.filter_trigger_payload({'type':'other'}, {'operation':operation})
    output = v.VideoNode.resolve_trigger_payload(payload, {'operation':operation})
    turn = v.VideoNode.resolve_agent_event(output)
    assert turn['text'] and turn['conversation_key'] in turn['text'] and payload['emittedAt'] in turn['text']
    assert state['signing_secret'] not in turn['text']
    await v.VideoNode._unregister_external_webhook(credential=AUTH,config=state,node_id='video-test')
    assert requests[-1].method == 'DELETE' and requests[-1].url.path == '/webhooks/' + REGISTRATION['webhookId']


@pytest.mark.asyncio
async def test_registration_retrieves_secret_and_refuses_unsigned_subscription(monkeypatch):
    old = {k:value for k,value in REGISTRATION.items() if k != 'signatureSecret'}
    requests = transport(monkeypatch, [(201,old),(200,REGISTRATION)])
    state = await v.VideoNode._register_external_webhook(webhook_url='https://example.com',credential=AUTH,config={'operation':'on_video_encoding_completed'},node_id='x')
    assert state['signing_secret'] and requests[-1].method == 'GET'
    requests = transport(monkeypatch, [(201,old),(200,old),(204,None)])
    with pytest.raises(ValueError,match='signing secret'):
        await v.VideoNode._register_external_webhook(webhook_url='https://example.com',credential=AUTH,config={'operation':'on_video_encoding_completed'},node_id='x')
    assert requests[-1].method == 'DELETE'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401,403,429,500,302])
async def test_http_failures_are_not_success(monkeypatch, code):
    transport(monkeypatch, [(code,{'title':'Rejected '+AUTH['api_key']})])
    with pytest.raises(ValueError) as error:
        await node('list_videos').execute({})
    assert AUTH['api_key'] not in str(error.value) and str(code) in str(error.value)


@pytest.mark.asyncio
async def test_manual_trigger_does_not_fabricate_event():
    result = await node('on_video_encoding_completed').execute({})
    assert result['status'] == 'no_event'


def test_manual_credential_and_required_fields():
    assert v.VideoAPIKeyCredential(api_key='  synthetic-video-key-42  ').credential_type == 'video_api_key'
    assert v.VideoAPIKeyCredential(api_key='  synthetic-video-key-42  ').api_key == AUTH['api_key']
    for value in ['', 'https://dashboard.api.video']:
        with pytest.raises(ValidationError):
            v.VideoAPIKeyCredential(api_key=value)
    for operation, fields in [('get_video',{'videoId':'../videos'}),('list_videos',{'pageSize':101}),('create_upload_token',{'ttl':-1})]:
        with pytest.raises(ConfigValidationError):
            node(operation, **fields)

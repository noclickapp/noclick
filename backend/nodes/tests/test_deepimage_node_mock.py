"""Real factory and HTTP wire tests; all credentials/responses are synthetic."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import deepimage_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-deepimage-api-key'
IMAGE = 'https://deep-image.ai/api-example2.jpg'
JOB = 'a8784c00-dc6b-11ee-ad50-9ec3ba0205c0'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='deepimage-test', node_type='automation-deepimage',
        node_data={'config': config, 'credentials': {'credential_type': 'deepimage_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, payload, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.headers['X-API-KEY'] == TOKEN
        assert request.url.host == 'deep-image.ai'
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize('action,enhancement', native.ENHANCEMENTS.items())
async def test_enhancement_submits_single_exact_action(monkeypatch, action, enhancement):
    calls = transport(monkeypatch, {'job': JOB, 'status': 'received'})
    output = await node({'operation': action, 'image_url': IMAGE}).execute({})
    assert output['complete'] is False and output['job'] == JOB
    assert len(calls) == 1 and calls[0].method == 'POST'
    assert calls[0].url.path == '/rest_api/process'
    assert json.loads(calls[0].content) == {'url': IMAGE, 'enhancements': [enhancement]}

@pytest.mark.asyncio
@pytest.mark.parametrize('action,path', [('process_image','process'), ('process_image_wait','process_result'), ('upscale_image','process')])
async def test_resize_and_wait_routes(monkeypatch, action, path):
    calls = transport(monkeypatch, {'job': JOB, 'status': 'in_progress'})
    output = await node({'operation':action, 'image_url':IMAGE, 'width':1000, 'quality':0}).execute({})
    assert output['complete'] is False
    assert calls[0].url.path == '/rest_api/' + path
    assert json.loads(calls[0].content) == {'url':IMAGE, 'width':1000, 'quality':0}

@pytest.mark.asyncio
@pytest.mark.parametrize('action,extra,background', [
    ('remove_background',{}, {'remove':'auto'}),
    ('replace_background',{'background_url':IMAGE},{'remove':'auto','replace':IMAGE}),
    ('generate_image',{'description':'happy apple'}, {'generate':{'description':'happy apple'}}),
])
async def test_background_and_generation_bodies(monkeypatch, action, extra, background):
    calls = transport(monkeypatch, {'job':JOB})
    config = {'operation':action, **extra}
    if action != 'generate_image': config['image_url'] = IMAGE
    await node(config).execute({})
    body = json.loads(calls[0].content)
    assert body['background'] == background
    assert ('url' in body) == (action != 'generate_image')

@pytest.mark.asyncio
async def test_account_evidence_excludes_secret_billing_and_webhooks(monkeypatch):
    calls = transport(monkeypatch, {'username':'John Doe','email':'johndoe@gmail.com','credits':3872,
        'api_key':TOKEN,'address':{'tax':'private'}, 'webhooks':{'url':'private'},'unknown':TOKEN})
    result = await node({'operation':'get_account'}).execute({})
    assert result == {'status':'success','data':{'username':'John Doe','email':'johndoe@gmail.com','credits':3872}}
    assert calls[0].method == 'GET' and calls[0].url.path == '/rest_api/me'
    assert not calls[0].content

@pytest.mark.asyncio
async def test_documented_result_fixture_and_delete(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/deepimage/process_result.json').read_text())
    calls = transport(monkeypatch, fixture)
    output = await node({'operation':'get_result','job_hash':JOB}).execute({})
    assert output['complete'] and output['job_status'] == 'complete'
    assert output['result_url'] == fixture['result_url']
    assert len(calls) == 1 and calls[0].url.path == '/rest_api/result/' + JOB
    calls = transport(monkeypatch, {'message':'Images of job xxx has been removed.'})
    output = await node({'operation':'delete_result','job_hash':JOB}).execute({})
    assert output['deletion_acknowledged']
    assert len(calls) == 1 and calls[0].method == 'DELETE'

@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(403,{'message':'Invalid API key'}), (429,{'message':'Too many requests'}),
    (200,{'status':'failed','message':'Provider processing failed'}), (500,{'message':TOKEN})])
async def test_failures_are_errors_and_redact_key(monkeypatch, status, payload):
    transport(monkeypatch, payload, status)
    output = await node({'operation':'get_result','job_hash':JOB}).execute({})
    assert output['status'] == 'error' and TOKEN not in str(output)
    if payload['message'] != TOKEN: assert output['message'] == payload['message']

@pytest.mark.asyncio
@pytest.mark.parametrize('action,payload,extra', [('get_account',{},{}),('get_result',{'status':'complete'},{'job_hash':JOB}),
    ('delete_result',{}, {'job_hash':JOB}),('get_result',{'job':JOB,'status':'unexpected'},{'job_hash':JOB})])
async def test_malformed_success_is_never_confirmed(monkeypatch, action, payload, extra):
    transport(monkeypatch,payload)
    with pytest.raises(ValueError): await node({'operation':action,**extra}).execute({})

@pytest.mark.parametrize('bad', ['https://example.com/key','<token>','bad\nkey'])
def test_key_validation(bad):
    with pytest.raises(ValidationError): native.DeepimageAPIKeyCredential(api_key=bad)

def test_credential_type_has_default_and_unsafe_input_refused():
    assert native.DeepimageAPIKeyCredential(api_key=TOKEN).credential_type == 'deepimage_api_key'
    for cls, kwargs in [(native.GetResult,{'job_hash':'../me'}),
        (native.ReplaceBackground,{'image_url':IMAGE,'background_url':'http://example.com/image.png'}),
        (native.DenoiseImage,{'image_url':'https://user:pass@example.com/image.png'})]:
        with pytest.raises(ValidationError): cls(**kwargs)

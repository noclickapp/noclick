"""Exercise every operation through the real factory, with provider examples."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import apitemplateio_node as api
from nodes.core.run_op import run_node_operation
from utils import ssrf

RESPONSES = json.loads((Path(__file__).parent / 'fixtures/apitemplateio/responses.json').read_text())['responses']
AUTH = {'credential_type': api.CREDENTIAL, 'api_key': 'fixture-api-secret'}
CASES = [
    ('create_pdf', {'template_id': '00377b2b1e0ee394', 'data': '{"invoice_number":"INV38379"}'}, 'POST', {'invoice_number':'INV38379'}),
    ('create_image', {'template_id': '00377b2b1e0ee394', 'data': '{"overrides":[{"name":"text_1","text":"hello world"}]}'}, 'POST', {'overrides':[{'name':'text_1','text':'hello world'}]}),
    ('create_pdf_from_html', {'body':'<h1>hello world</h1>', 'data':'{"name":"Title"}', 'settings':'{"paper_size":"A4"}'}, 'POST', {'body':'<h1>hello world</h1>', 'data':{'name':'Title'}, 'settings':{'paper_size':'A4'}}),
    ('create_pdf_from_url', {'url':'https://en.wikipedia.org/wiki/Sceloporus_malachiticus'}, 'POST', {'url':'https://en.wikipedia.org/wiki/Sceloporus_malachiticus'}),
    ('list_objects', {'offset': 100, 'transaction_type':'PDF'}, 'GET', None),
    ('delete_object', {'transaction_ref':'1618d386-2343-3d234-b9c7-99c82bb9f104'}, 'GET', None),
    ('list_templates', {'group_name':'Invoices'}, 'GET', None),
    ('get_template', {'template_id':'00377b2b1e0ee394'}, 'GET', None),
    ('update_template', {'template_id':'00377b2b1e0ee394', 'body':'<h1>Title</h1>'}, 'POST', {'template_id':'00377b2b1e0ee394','body':'<h1>Title</h1>'}),
    ('merge_pdfs', {'urls':['https://fileserver.com/a1.pdf','https://fileserver.com/b2.pdf'], 'meta':'external-reference'}, 'POST', {'urls':['https://fileserver.com/a1.pdf','https://fileserver.com/b2.pdf'],'expiration':60,'cloud_storage':1,'export_type':'json'}),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(api, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(action, arguments=None, auth=None):
    return await run_node_operation(node_type='automation-apitemplateio', operation=action,
        arguments=arguments or {}, credential_data=deepcopy(auth or AUTH), user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.parametrize('action,arguments,method,body', CASES)
@pytest.mark.asyncio
async def test_documented_requests_and_responses(transport, action, arguments, method, body):
    requests, replies = transport
    replies.append((200, deepcopy(RESPONSES[action])))
    result = await run(action, arguments)
    assert result['status'] == 'success'
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'rest.apitemplate.io'
    assert request.url.path == '/v2/' + action.replace('_','-')
    assert request.headers['X-API-KEY'] == AUTH['api_key']
    assert AUTH['api_key'] not in str(request.url)
    assert AUTH['api_key'] not in json.dumps(result)
    assert (json.loads(request.content) if request.content else None) == body
    if action in {'create_pdf', 'create_pdf_from_html', 'create_pdf_from_url'}:
        assert request.url.params['export_type'] == 'json'
    if action in {'create_pdf', 'create_image', 'get_template'}:
        assert request.url.params['template_id'] == arguments['template_id']
    if action == 'delete_object':
        assert request.url.params['transaction_ref'] == arguments['transaction_ref']
    if action == 'merge_pdfs':
        assert request.url.params['meta'] == 'external-reference'
    if action.startswith('list_'):
        assert request.url.params['offset'] == str(arguments.get('offset',0))
        assert result['items'] == RESPONSES[action]['templates' if action=='list_templates' else 'objects']


@pytest.mark.parametrize('region,host', [('singapore','rest.apitemplate.io'),('australia','rest-au.apitemplate.io'),('europe','rest-de.apitemplate.io'),('us','rest-us.apitemplate.io')])
@pytest.mark.asyncio
async def test_region_and_empty_account_evidence(transport, region, host):
    requests,replies=transport
    replies.append((200, {'status':'success','templates':[]}))
    result=await run('list_templates',auth={**AUTH,'region':region})
    assert result['items']==[]
    assert requests[0].url.host==host
    assert api.APITemplateIONode.connection_evidence.operation=='list_templates'


@pytest.mark.parametrize('code,payload', [(401,{'status':'error','message':'Invalid API key'}),(200,{'status':'error','message':'Template not found'}),(200,[]),(200,{'status':'success'})])
@pytest.mark.asyncio
async def test_rejection_or_incomplete_list_never_succeeds(transport,code,payload):
    _,replies=transport;replies.append((code,payload))
    with pytest.raises(ValueError):
        await run('list_templates')


@pytest.mark.parametrize('action,args', [
    ('create_pdf',{'template_id':'t','data':'[]'}),
    ('create_pdf_from_url',{'url':'file:///etc/passwd'}),
    ('update_template',{'template_id':'t'}),
    ('merge_pdfs',{'urls':['https://a.test/file.pdf']}),
    ('merge_pdfs',{'urls':['https://a.test/file.pdf', 'http://user:password@host/file.pdf']}),
    ('list_templates',{'offset':-1}),
])
def test_invalid_input_rejected_before_http(action,args):
    with pytest.raises(ValueError):
        api.APITemplateIONode.parse_config({'config':{'operation':action,**args},'credentials':AUTH})


def test_manual_credential_type_default_and_key_shaping():
    assert api.APITemplateIOApiKey(api_key=' fixture-api-secret ').model_dump()=={**AUTH,'region':'singapore'}
    with pytest.raises(ValueError):
        api.APITemplateIOApiKey(api_key='https://example.com/key')


@pytest.mark.asyncio
async def test_image_format_and_merge_filter_follow_docs(transport):
    requests, replies = transport
    replies.append((200, RESPONSES['create_image']))
    await run('create_image', {'template_id':'00377b2b1e0ee394','data':'{}','output_image_type':'pngOnly'})
    assert requests[-1].url.params['output_image_type']=='pngOnly'
    replies.append((200, RESPONSES['list_objects']))
    await run('list_objects', {'transaction_type':'MERGE'})
    assert requests[-1].url.params['transaction_type']=='MERGE'


@pytest.mark.asyncio
async def test_provider_rejection_text_and_secret_redaction(transport):
    requests, replies = transport
    replies.append((403, {'status':'error','message':'Invalid API key fixture-api-secret'}))
    with pytest.raises(ValueError, match=r'Invalid API key \[redacted\]'):
        await run('list_templates')
    assert len(requests)==1

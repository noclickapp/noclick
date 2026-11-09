"""Replay Speechmatics' published response examples with synthetic callback credentials.

Assert the wire protocol and the action-specific multipart job configuration.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.speechmatics_node import SpeechmaticsNode, SpeechmaticsCredential, SpeechmaticsConfig

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/speechmatics/responses.json').read_text())
CASES = [
 ('submit_transcription', 'POST', '/jobs', {}),
 ('submit_speaker_transcription', 'POST', '/jobs', {}),
 ('submit_translation', 'POST', '/jobs', {'target_languages':['fr']}),
 ('submit_summarization', 'POST', '/jobs', {}),
 ('list_jobs', 'GET', '/jobs', {}),
 ('get_job', 'GET', '/jobs/a1b2c3d4e5', {}),
 ('delete_job', 'DELETE', '/jobs/a1b2c3d4e5', {'force':True}),
 ('get_transcript', 'GET', '/jobs/a1b2c3d4e5/transcript', {}),
 ('get_text_transcript', 'GET', '/jobs/a1b2c3d4e5/transcript', {}),
 ('get_srt_transcript', 'GET', '/jobs/a1b2c3d4e5/transcript', {}),
 ('get_log', 'GET', '/jobs/a1b2c3d4e5/log', {}),
 ('get_usage', 'GET', '/usage', {'since':'2026-10-01','until':'2026-10-31'}),
]


def make(op, extra):
    config = {'operation':op, **extra}
    if op.startswith('submit_'):config['audio_url']='https://example.org/recording.mp3'
    elif op not in ('list_jobs','get_usage'):config['job_id']='a1b2c3d4e5'
    return NodeFactory.create_node(node_id='speechmatics-test',node_type='automation-speechmatics',node_data={'config':config,'credentials':{'credential_type':'speechmatics_api_key','api_key':'secret-test-key'}})


@pytest.mark.asyncio
@pytest.mark.parametrize('op,method,path,extra', CASES)
async def test_wire_and_examples(monkeypatch,op,method,path,extra):
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method == method
        assert request.url.host == 'eu1.asr.api.speechmatics.com'
        assert request.url.path == '/v2'+path
        assert request.headers['authorization']=='Bearer secret-test-key'
        if method=='POST':
            body=request.content.decode()
            assert 'multipart/form-data' in request.headers['content-type']
            config=json.loads(body.split('\r\n\r\n',1)[1].split('\r\n--',1)[0])
            assert config['fetch_data']=={'url':'https://example.org/recording.mp3'}
            assert config['type']=='transcription'
            assert config['transcription_config']['language']=='en'
            if op=='submit_speaker_transcription':assert config['transcription_config']['diarization']=='speaker'
            if op=='submit_translation':assert config['translation_config']=={'target_languages':['fr']}
            if op=='submit_summarization':assert config['summarization_config']['summary_length']=='brief'
        if op=='list_jobs':assert dict(request.url.params)=={'limit':'25','include_deleted':'false'}
        if op=='delete_job':assert request.url.params['force']=='true'
        if op=='get_usage':assert request.url.params['since']=='2026-10-01'
        key=method+' '+path.replace('a1b2c3d4e5','{jobid}')
        examples=FIXTURES[key]
        text = op in ('get_text_transcript','get_srt_transcript','get_log')
        if text:
            return httpx.Response(200,text=examples.get('text/plain','1\n00:00:00,000 --> 00:00:01,000\nHello\n'))
        return httpx.Response(201 if method=='POST' else 200,json=next(iter(examples.values())))
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:yield c
    monkeypatch.setattr('nodes.speechmatics_node.guarded_async_client',client)
    result=await make(op,extra).execute({})
    assert result['status']=='success',result
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('code',[401,404,423,429,500])
async def test_errors_preserve_rejection(monkeypatch,code):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(code,json={'error':'Permission Denied'}))) as c:yield c
    monkeypatch.setattr('nodes.speechmatics_node.guarded_async_client',client)
    assert await make('list_jobs',{}).execute({})=={'status':'error','http_status':code,'error':'Permission Denied'}


@pytest.mark.parametrize('key',['bad\nkey','Bearer secret'])
def test_bad_key(key):
    with pytest.raises(ValueError):SpeechmaticsCredential(api_key=key)


def test_bad_job_id():
    with pytest.raises(ValueError):SpeechmaticsConfig.model_validate({'config':{'operation':'get_job','job_id':'../usage'}})


def test_speechmatics_fixtures_contain_no_credentials():
    # Use the export scanner so future provider examples cannot reintroduce tokens.
    import importlib.util
    root = Path(__file__).resolve().parents[3]
    scanner_path = root / 'oss/scan_real_secrets.py'
    if not scanner_path.exists():
        scanner_path = root / 'scripts/scan_real_secrets.py'
    spec = importlib.util.spec_from_file_location('speechmatics_secret_scan', scanner_path)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    fixture = Path(__file__).parent / 'fixtures/speechmatics/responses.json'
    assert not scanner.find_secrets(fixture.read_bytes())

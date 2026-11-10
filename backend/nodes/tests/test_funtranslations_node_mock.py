"""Exercise the native factory against published Swagger 2.3 response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import funtranslations_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/funtranslations/translations.json').read_text())['responses']
TOKEN = 'synthetic-funtranslations-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id='translations-test', node_type=native.NODE_TYPE, node_data={
        'config': config,
        'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_key': TOKEN, **credential},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('translator', FIXTURES)
async def test_funtranslations_published_translation_examples(monkeypatch, translator):
    documented = FIXTURES[translator]
    requests = transport(monkeypatch, documented)
    result = await node({'operation': 'translate_' + translator, 'text': documented['contents']['text']}).execute({})
    assert result == {'contents': documented['contents']}
    request, = requests
    assert request.method == 'GET'
    assert str(request.url.copy_with(query=None)) == native.BASE_URL + '/translate/' + translator
    assert dict(request.url.params) == {'text': documented['contents']['text']}
    assert request.headers['X-Funtranslations-Api-Secret'] == TOKEN
    assert request.headers['Accept'] == 'application/json'
    assert request.content == b''


@pytest.mark.asyncio
async def test_funtranslations_connection_uses_subscribed_translator_and_sample(monkeypatch):
    requests = transport(monkeypatch, FIXTURES['morse2english'])
    result = await node({'operation': 'check_connection'}, check_translator='morse2english').execute({})
    assert result['contents'] == FIXTURES['morse2english']['contents']
    assert requests[0].url.path == '/translate/morse2english'
    assert requests[0].url.params['text'] == FIXTURES['morse2english']['contents']['text']
    assert native.FunTranslationsNode.connection_evidence.proves == 'reachability'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429])
async def test_funtranslations_provider_error_envelope_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, {'error': {'code': status, 'message': 'Rejected ' + TOKEN}}, status)
    result = await node({'operation': 'check_connection'}).execute({})
    assert result['status'] == 'error'
    assert result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]'
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'contents': {}}, {'contents': {'translated': [], 'text': 'x', 'translation': 'yoda'}}])
async def test_funtranslations_incomplete_results_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match='FunTranslations response'):
        await node({'operation': 'check_connection'}).execute({})


def test_funtranslations_manual_credential_default_and_input_validation():
    credential = native.FunTranslationsAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    for bad in ['https://example.com/key', 'bad\nkey', 'bad key', '']:
        with pytest.raises(ValidationError):
            native.FunTranslationsAPIKeyCredential(api_key=bad)
    with pytest.raises(ValidationError):
        native.FunTranslationsYodaConfig(text='   ')

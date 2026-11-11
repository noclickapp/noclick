"""Offline GIPHY requests through the native factory; no live keys."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import giphy_node as native
from nodes.core.registry import NodeFactory

KEY = 'synthetic-giphy-key-42'
AUTH = {'credential_type': 'giphy_api_key', 'api_key': KEY}
CASES = [
    ('search_gifs', {'q': 'cat + café', 'lang': 'en', 'limit': 10, 'offset': 20, 'rating': 'g'}, '/gifs/search'),
    ('get_trending_gifs', {}, '/gifs/trending'),
    ('translate_gif', {'s': 'hello'}, '/gifs/translate'),
    ('random_gif', {'tag': 'cat', 'rating': 'pg'}, '/gifs/random'),
    ('get_gif', {'gif_id': 'YsTs5ltWtEhnq'}, '/gifs/YsTs5ltWtEhnq'),
    ('get_gifs', {'ids': 'YsTs5ltWtEhnq,cZ7rmKfFYOvYI'}, '/gifs'),
    ('search_stickers', {'q': 'cat'}, '/stickers/search'),
    ('get_trending_stickers', {'limit': 5, 'offset': 5}, '/stickers/trending'),
    ('translate_sticker', {'s': 'hello'}, '/stickers/translate'),
    ('random_sticker', {}, '/stickers/random'),
]

@pytest.fixture
def ensure_native_db_pool():
    yield

def node(operation, **config):
    return NodeFactory.create_node(node_id='giphy-test', node_type='automation-giphy',
        node_data={'config': {'operation': operation, **config}, 'credentials': AUTH.copy()})

def transport(monkeypatch, body, code=200):
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(code, json=body)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,path', CASES)
async def test_each_operation_one_exact_authenticated_request(monkeypatch, operation, config, path):
    fixture = json.loads((Path(__file__).parent / 'fixtures/giphy/gif.json').read_text())
    rows = operation in {'search_gifs', 'get_trending_gifs', 'get_gifs', 'search_stickers', 'get_trending_stickers'}
    data = [fixture] if rows else fixture
    requests = transport(monkeypatch, {'data': data, 'meta': {'status': 200, 'msg': 'OK'}})
    result = await node(operation, **config).execute({})
    assert result['status'] == 'success' and result['data'] == data
    assert result['identity_verified'] is False and len(requests) == 1
    request = requests[0]
    assert request.method == 'GET' and request.url.host == 'api.giphy.com'
    assert request.url.path == '/v1' + path
    expected = {k: str(v) for k, v in config.items() if k != 'gif_id'}
    if rows and operation != 'get_gifs':
        expected = {'limit': '25', 'offset': '0', **expected}
    assert dict(request.url.params) == {**expected, 'api_key': KEY}
    assert KEY not in json.dumps(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 429, 500])
async def test_http_failures_preserve_provider_message_and_redact_key(monkeypatch, code):
    requests = transport(monkeypatch, {'meta': {'status': code, 'msg': 'Rejected key ' + KEY}}, code)
    result = await node('get_trending_gifs').execute({})
    assert result == {'status': 'error', 'http_status': code, 'error': 'Rejected key [redacted]'}
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_error_envelope_does_not_become_success(monkeypatch):
    transport(monkeypatch, {'data': [], 'meta': {'status': 403, 'msg': 'Forbidden'}})
    assert (await node('get_trending_gifs').execute({}))['status'] == 'error'

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': None}, {'data': {}}, {'data': 'not JSON data'}])
async def test_malformed_list_response_is_not_a_working_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match='unexpected data envelope'):
        await node('get_trending_gifs').execute({})

@pytest.mark.asyncio
async def test_empty_page_and_pagination_are_preserved(monkeypatch):
    body = {'data': [], 'pagination': {'count': 0, 'offset': 25, 'total_count': 25}}
    transport(monkeypatch, body)
    out = await node('get_trending_gifs', offset=25).execute({})
    assert out['data'] == [] and out['pagination'] == body['pagination']

@pytest.mark.asyncio
async def test_transport_exception_never_leaks_query_key(monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError('https://api.giphy.com/?api_key=' + KEY)
    monkeypatch.setattr(httpx.AsyncClient, 'get', fail)
    with pytest.raises(ValueError) as error:
        await node('get_trending_gifs').execute({})
    assert KEY not in str(error.value)

@pytest.mark.parametrize('config', [
    {'operation': 'get_gif', 'gif_id': '../search'},
    {'operation': 'get_gifs', 'ids': 'x&api_key=evil'},
    {'operation': 'search_gifs'},
    {'operation': 'search_gifs', 'q': 'cat', 'api_key': 'override'},
    {'operation': 'get_trending_gifs', 'limit': 1000},
    {'operation': 'get_trending_gifs', 'offset': -1},
    {'operation': 'upload_gif'},
])
def test_invalid_routes_parameters_and_mutations_rejected(config):
    with pytest.raises(ValueError):
        native.GiphyNode.parse_config({'config': config, 'credentials': AUTH})

def test_schema_credentials_and_reachability_declaration():
    assert native.GiphyNode.connection_evidence.proves == 'reachability'
    assert native.GiphyNode.connection_evidence.operation == 'get_trending_gifs'
    assert len(native.ROUTES) == 10
    assert native.GiphyApiKeyCredential.model_json_schema()['title'] == 'GIPHY API Key'
    with pytest.raises(ValueError):
        native.GiphyApiKeyCredential(api_key='https://example.com/key')


# These two responses are copied from GIPHY's own JS SDK tests (gifsResponse
# and gifsResponseNoTags), not fabricated API events. The pinned source is:
# https://github.com/Giphy/giphy-js/blob/ea20a90638b4ff01255582dcf8aab5dcf209f750/packages/fetch-api/src/__tests__/api.test.ts
SDK_RESPONSE = {
    'data': [{'id': 12345, 'tags': [{'text': 'text prop'}, 'regular tag'],
              'is_hidden': 0, 'analytics_response_payload': 'ARP',
              'images': {'fixed_width': {'width': '12', 'height': '14'}}}],
    'pagination': {}, 'meta': {'response_id': 'response id'},
}
SDK_RESPONSE_NO_TAGS = {
    'data': [{'id': 456, 'is_hidden': 0, 'analytics_response_payload': 'ARP'}],
    'pagination': {}, 'meta': {'response_id': 'response id'},
}


@pytest.fixture
def poll_state(monkeypatch):
    state = {}

    async def update(self, mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(native.GiphyNode, '_update_node_state', update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [
    ('on_new_gif', '/v1/gifs/search'), ('on_new_sticker', '/v1/stickers/search'),
])
async def test_recent_search_poll_baselines_emits_once_and_scopes(monkeypatch, poll_state, operation, path):
    responses = iter([SDK_RESPONSE, SDK_RESPONSE_NO_TAGS, SDK_RESPONSE_NO_TAGS,
                      SDK_RESPONSE, SDK_RESPONSE_NO_TAGS])
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(200, json=next(responses))

    original = httpx.AsyncClient
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kwargs:
                        original(transport=httpx.MockTransport(send), **kwargs))

    def trigger(**changes):
        return node(operation, **{'q': 'dogs', 'lang': 'en', 'rating': 'g', 'limit': 20, **changes})

    first = trigger()
    baseline = await first.execute({})
    assert baseline['data'] == [] and baseline['new_count'] == 0
    assert first.trigger_produced_no_event(baseline)
    assert not native.GiphyNode.should_propagate_output(baseline, {'operation': operation})
    assert native.GiphyNode.resolve_agent_event(baseline) is None
    assert poll_state['seen_ids'] == ['12345']

    fresh_node = trigger()
    fresh = await fresh_node.execute({})
    assert fresh['data'] == SDK_RESPONSE_NO_TAGS['data'] and fresh['new_count'] == 1
    assert fresh_node.trigger_emitted_event(fresh)
    assert native.GiphyNode.should_propagate_output(fresh, {'operation': operation})
    event = native.GiphyNode.resolve_agent_event(fresh)
    assert 'GIPHY' in event['text'] and '456' in event['text'] and 'dogs' in event['text']
    assert (await trigger().execute({}))['new_count'] == 0

    # Changing the watched query baselines the new scope instead of replaying it.
    repointed = await trigger(q='cats').execute({})
    assert repointed['new_count'] == 0 and poll_state['seen_ids'] == ['12345']
    assert (await trigger(q='cats').execute({}))['new_count'] == 1
    assert len(requests) == 5
    for request in requests:
        assert request.method == 'GET' and request.url.host == 'api.giphy.com'
        assert request.url.path == path
        assert dict(request.url.params) == {
            'q': 'cats' if request is requests[3] or request is requests[4] else 'dogs',
            'lang': 'en', 'rating': 'g', 'limit': '20', 'sort': 'recent',
            'offset': '0', 'api_key': KEY,
        }


@pytest.mark.asyncio
async def test_poll_errors_do_not_advance_baseline(monkeypatch, poll_state):
    transport(monkeypatch, {'meta': {'status': 429, 'msg': 'Rate limited'}}, 429)
    result = await node('on_new_gif', q='dogs').execute({})
    assert result['status'] == 'error' and poll_state == {}
    assert not native.GiphyNode.should_propagate_output(result, {'operation': 'on_new_gif'})


@pytest.mark.asyncio
async def test_poll_rejects_missing_ids_before_advancing_state(monkeypatch, poll_state):
    transport(monkeypatch, {'data': [{}]})
    with pytest.raises(ValueError, match='valid ID'):
        await node('on_new_gif', q='dogs').execute({})
    assert poll_state == {}


def test_poll_config_and_scope():
    from nodes.core.poll_trigger import poll_scope
    for model in (native.OnNewGif, native.OnNewSticker):
        schema = model.model_json_schema()
        assert schema['properties']['operation']['x-is-trigger'] is True
        assert schema['x-requires-webhook'] is True
    config = {'operation': 'on_new_gif', 'q': 'dogs'}
    scope = poll_scope(native.GiphyNode, config)
    assert scope is not None
    assert poll_scope(native.GiphyNode, {**config, 'schedule': {'frequency': 'minutes', 'interval': 10}}) == scope
    assert poll_scope(native.GiphyNode, {**config, 'q': 'cats'}) != scope
    assert poll_scope(native.GiphyNode, {**config, 'rating': 'g'}) != scope
    for invalid in ({'operation': 'on_new_gif'}, {**config, 'sort': 'relevant'}, {**config, 'offset': 10}):
        with pytest.raises(ValueError):
            native.GiphyNode.parse_config({'config': invalid, 'credentials': AUTH})


@pytest.mark.parametrize('fixture_name', ['gif.json', 'recent-search.json'])
def test_agent_event_has_documented_creator_url_and_id(fixture_name):
    body = json.loads((Path(__file__).parent / 'fixtures/giphy' / fixture_name).read_text())
    gif = body['data'][0] if 'data' in body else body
    event = native.GiphyNode.resolve_agent_event({
        'operation': 'on_new_gif', 'data': [gif], 'query': '@JoeCool4000', 'new_count': 1,
    })
    assert '@' + gif['username'] in event['text']
    assert gif['url'] in event['text'] and gif['id'] in event['text']
    if gif.get('title'):
        assert gif['title'] in event['text']

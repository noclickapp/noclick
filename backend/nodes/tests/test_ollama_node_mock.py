"""Real factory execution against the provider's published response examples."""
import json
from copy import deepcopy
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import ollama_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "ollama-synthetic-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/ollama/published_examples.json").read_text())
CASES = [
    ({"operation": "generate_response", "model": "gemma4", "prompt": "Hello", "options": {"temperature": 0}, "think": False}, "POST", "/api/generate"),
    ({"operation": "generate_chat", "model": "gemma4", "messages": [{"role": "user", "content": "Hello"}]}, "POST", "/api/chat"),
    ({"operation": "generate_embeddings", "model": "embeddinggemma", "input": ["Hello", "World"], "truncate": False}, "POST", "/api/embed"),
    ({"operation": "list_models"}, "GET", "/api/tags"),
    ({"operation": "list_running_models"}, "GET", "/api/ps"),
    ({"operation": "show_model", "model": "gemma4", "verbose": False}, "POST", "/api/show"),
    ({"operation": "create_model", "model": "mario", "from": "gemma4", "system": "You are Mario from Super Mario Bros."}, "POST", "/api/create"),
    ({"operation": "copy_model", "source": "gemma4", "destination": "gemma4-backup"}, "POST", "/api/copy"),
    ({"operation": "pull_model", "model": "gemma4"}, "POST", "/api/pull"),
    ({"operation": "push_model", "model": "my-username/my-model"}, "POST", "/api/push"),
    ({"operation": "delete_model", "model": "gemma4"}, "DELETE", "/api/delete"),
    ({"operation": "get_version"}, "GET", "/api/version"),
    ({"operation": "get_usage", "range": "24h", "scope": "team", "group_by": "model"}, "GET", "/api/usage"),
    ({"operation": "get_balance"}, "GET", "/api/balance"),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="ollama-fixture", node_type="automation-ollama", node_data={
        "config": config, "credentials": ({"credential_type": "ollama_api_key", "api_key": TOKEN, **credentials}
            if config['operation'] in {'get_usage', 'get_balance'} else
            {"credential_type": "ollama_server", "server_url": "https://models.example.com", "api_key": TOKEN, **credentials})})


def transport(monkeypatch, body=None, *, status=200, content=None):
    requests, policies = [], []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)
    def client(**kwargs):
        policies.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, policies


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[c[0]['operation'] for c in CASES])
async def test_published_examples_exact_method_route_and_payload(monkeypatch, config, method, path):
    body = EXAMPLES.get(method+' '+path, {})
    if path == '/api/balance':
        body = {"included": {"balance_usd": 72.5, "allowance_usd": 100, "period": {"from": "2026-09-15T09:30:00Z", "until": "2026-10-15T09:30:00Z"}}, "purchased": {"balance_usd": 25}}
    requests, policies = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == body
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path, req.url.host) == (method, path, 'ollama.com' if config['operation'] in {'get_usage', 'get_balance'} else 'models.example.com')
    assert req.headers['Authorization'] == 'Bearer '+TOKEN
    expected = {k:v for k,v in config.items() if k != 'operation'}
    if config['operation'] in native.STREAMING: expected['stream'] = False
    if method == 'GET': assert dict(req.url.params) == expected
    else: assert json.loads(req.content) == expected
    assert policies == [{'timeout': 300, 'follow_redirects': False, 'trust_env': False}]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['copy_model', 'delete_model'])
async def test_empty_success_acknowledgements(monkeypatch, operation):
    config = next(c[0] for c in CASES if c[0]['operation'] == operation)
    transport(monkeypatch, content=b'')
    assert (await node(config).execute({}))['status'] == 'success'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 500])
async def test_provider_errors_are_not_success_and_redact_key(monkeypatch, status):
    requests, _ = transport(monkeypatch, {'error': 'rejected '+TOKEN}, status=status)
    result = await node({'operation': 'list_models'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and 'rejected' in result['error'] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('generate_response', {'done': False}), ('generate_chat', {'done': False}), ('pull_model', {'status': 'downloading'}), ('list_models', {}), ('list_running_models', {'models': {}})])
async def test_incomplete_and_malformed_successes_are_rejected(monkeypatch, operation, body):
    config = next(c[0] for c in CASES if c[0]['operation'] == operation)
    transport(monkeypatch, body)
    with pytest.raises(ValueError): await node(config).execute({})


@pytest.mark.asyncio
async def test_custom_origin_keeps_token_on_selected_server(monkeypatch):
    requests, _ = transport(monkeypatch, {'status': 'success'})
    await node({'operation': 'pull_model', 'model': 'gemma4'}, server_url='https://models.example.com/api').execute({})
    assert str(requests[0].url) == 'https://models.example.com/api/pull'
    assert requests[0].headers['Authorization'] == 'Bearer '+TOKEN
    for operation in ['get_usage', 'get_balance']:
        with pytest.raises(ValueError, match='API Key connection'):
            native_node = node({'operation': 'list_models'})
            native_node.config.config = native.OllamaUsageConfig() if operation == 'get_usage' else native.OllamaBalanceConfig()
            await native_node.execute({})
    assert len(requests) == 1


@pytest.mark.parametrize('server_url', ['https://user:pass@models.example.com', 'file:///tmp/ollama', ''])
def test_invalid_origins_fail_before_http(server_url):
    with pytest.raises(ValidationError): native.OllamaServerCredential(api_key=TOKEN, server_url=server_url)


def test_manual_connect_defaults_and_secret_shaping():
    credential, errors, _ = shape_credential('ollama_api_key', {'api_key': ' '+TOKEN+' '})
    assert not errors and credential['api_key'] == TOKEN
    assert native.OllamaAPIKeyCredential.model_validate(credential).credential_type == 'ollama_api_key'
    assert native.OllamaNode.connection_evidence.proves == 'reachability'
    for value in ['https://ollama.com/settings/keys', '<token>', 'Bearer secret']:
        with pytest.raises(ValidationError): native.OllamaAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_plain_http_never_receives_bearer_tokens(monkeypatch):
    requests, _ = transport(monkeypatch, {"models": []})
    with pytest.raises(ValueError, match='HTTPS'):
        await node({"operation": "list_models"}, server_url="http://public.example.com").execute({})
    assert not requests
    await node({"operation": "list_models"}, server_url="http://public.example.com", api_key=None).execute({})
    assert 'Authorization' not in requests[0].headers


@pytest.mark.asyncio
async def test_cloud_inference_and_server_only_management(monkeypatch):
    requests, _ = transport(monkeypatch, EXAMPLES['POST /api/generate'])
    n = node({"operation": "generate_response", "model": "gemma4", "prompt": "Hello"})
    n.config.credentials = native.OllamaAPIKeyCredential(api_key=TOKEN)
    assert (await n.execute({}))['status'] == 'success'
    assert str(requests[0].url) == 'https://ollama.com/api/generate'
    n.config.config = native.OllamaDeleteConfig(model='gemma4')
    with pytest.raises(ValueError, match='Ollama Server'): await n.execute({})
    assert len(requests) == 1


def test_server_credential_connects_by_hand():
    credential, errors, _ = shape_credential('ollama_server', {'server_url': 'https://models.example.com/api'})
    assert not errors and credential['server_url'] == 'https://models.example.com'
    parsed = native.OllamaServerCredential.model_validate(credential)
    assert parsed.credential_type == 'ollama_server' and parsed.api_key is None


@pytest.mark.asyncio
async def test_cloud_connection_evidence_requires_authenticated_balance(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/api/balance':
            return httpx.Response(200, json={"included": {}, "purchased": {"balance_usd": 25}})
        return httpx.Response(200, json={"models": [{"name": "gemma4"}, {"name": "other"}]})
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    options = await native.OllamaNode.load_field_options('model', {'credential_type': 'ollama_api_key', 'api_key': TOKEN}, search='gemma')
    assert options == [{"value": "gemma4", "label": "gemma4"}]
    assert [r.url.path for r in requests] == ['/api/balance', '/api/tags']
    requests, _ = transport(monkeypatch, {'error': 'Invalid credentials'}, status=401)
    with pytest.raises(ValueError, match='401: Invalid credentials'):
        await native.OllamaNode.load_field_options('model', {'credential_type': 'ollama_api_key', 'api_key': TOKEN})
    assert [r.url.path for r in requests] == ['/api/balance']


@pytest.mark.asyncio
async def test_server_connection_evidence_lists_models_without_cloud_request(monkeypatch):
    requests, _ = transport(monkeypatch, {'models': [{'name': 'gemma4'}]})
    assert await native.OllamaNode.load_field_options('model', {'credential_type': 'ollama_server', 'server_url': 'https://models.example.com'}) == [{"value": "gemma4", "label": "gemma4"}]
    assert len(requests) == 1 and requests[0].url.path == '/api/tags'
    assert 'Authorization' not in requests[0].headers


def poll_state(monkeypatch, state=None):
    """Exercise the real poll-family mutator with durable state between ticks."""
    state = {} if state is None else state
    async def update(self, mutator, **kwargs):
        updated, result = mutator(deepcopy(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result
    monkeypatch.setattr(native.OllamaNode, '_update_node_state', update)
    return state


@pytest.mark.asyncio
async def test_model_poll_baselines_detects_new_and_updated_versions_and_deduplicates(monkeypatch):
    # The initial delivery is copied from Ollama's published /api/tags example.
    body = deepcopy(EXAMPLES['GET /api/tags'])
    requests, _ = transport(monkeypatch, body)
    state = poll_state(monkeypatch)
    config = {'operation': 'on_new_or_updated_model'}
    first = node(config)
    assert (await first.execute({}))['models'] == []
    assert first.trigger_produced_no_event({})
    assert state['seen_ids'] and state['scope']
    assert (await node(config).execute({}))['new_or_updated_model_count'] == 0

    # Simulate a later version of the documented model without changing its name.
    body['models'][0]['modified_at'] = '2025-10-04T23:34:03.409490317-07:00'
    changed = node(config)
    output = await changed.execute({})
    assert output['models'] == body['models']
    assert output['new_or_updated_model_count'] == 1
    assert changed.trigger_emitted_event(output)
    event = native.OllamaNode.resolve_agent_event(output)
    assert all(value in event['text'] for value in [body['models'][0]['name'], body['models'][0]['digest'],
        body['models'][0]['modified_at'], 'https://models.example.com'])
    assert (await node(config).execute({}))['models'] == []

    # A new name also fires, even when its contents match an existing model.
    body['models'].append({**body['models'][0], 'name': 'gemma4-backup', 'model': 'gemma4-backup'})
    assert [row['name'] for row in (await node(config).execute({}))['models']] == ['gemma4-backup']
    assert all(req.method == 'GET' and req.url.path == '/api/tags' and not req.url.query for req in requests)
    assert native.OllamaNode.resolve_agent_event({'models': [], 'new_or_updated_model_count': 0}) is None


@pytest.mark.asyncio
async def test_model_poll_uses_documented_example_after_empty_baseline(monkeypatch):
    body = EXAMPLES['GET /api/tags']
    requests, _ = transport(monkeypatch, body)
    poll_state(monkeypatch, {'seen_ids': []})
    result = await node({'operation': 'on_new_or_updated_model'}).execute({})
    assert result['models'] == body['models'] and result['new_or_updated_model_count'] == 1
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_model_poll_scope_uses_declared_model_and_ignores_canvas_metadata(monkeypatch):
    transport(monkeypatch, EXAMPLES['GET /api/tags'])
    poll_state(monkeypatch)
    config = {'operation': 'on_new_or_updated_model', 'model': 'another-model'}
    assert (await node(config).execute({}))['models'] == []
    # Repointing quietly baselines the selected model instead of replaying it.
    config['model'] = 'gemma4'
    assert (await node(config).execute({}))['models'] == []
    before = native.OllamaNode.schedule_poll_scope(config)
    assert before == native.OllamaNode.schedule_poll_scope({**config, 'label': 'Renamed', 'goal': 'Watch models'})
    assert before != native.OllamaNode.schedule_poll_scope({**config, 'model': 'gemma4-backup'})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'models': {}}, {'models': [{}]}, {'models': [{'name': 'gemma4'}]},
    {'models': [{'name': 'gemma4', 'modified_at': 'invalid'}]},
    {'models': [{'name': 'gemma4', 'modified_at': '2025-10-04T12:00:00'}]}])
async def test_model_poll_never_advances_state_on_malformed_snapshot(monkeypatch, body):
    transport(monkeypatch, body)
    state = poll_state(monkeypatch)
    with pytest.raises(ValueError):
        await node({'operation': 'on_new_or_updated_model'}).execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_model_poll_requires_server_connection_before_request(monkeypatch):
    requests, _ = transport(monkeypatch, EXAMPLES['GET /api/tags'])
    n = node({'operation': 'on_new_or_updated_model'})
    n.config.credentials = native.OllamaAPIKeyCredential(api_key=TOKEN)
    with pytest.raises(ValueError, match='Ollama Server'):
        await n.execute({})
    assert not requests

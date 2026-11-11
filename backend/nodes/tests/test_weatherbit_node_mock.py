"""Exercise Weatherbit requests and lightning dedup with the provider's documented JSON."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import weatherbit_node as native
from nodes.core.registry import NodeFactory

KEY = "weatherbit-test-key-4242"
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/weatherbit/lightning.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="weatherbit-test", node_type="automation-weatherbit", node_data={
        "config": config, "credentials": {"credential_type": "weatherbit_api_key", "api_key": KEY}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    _, fields, required = native.OPERATIONS[operation]
    values = {'lat': 0, 'lon': 0, 'city': 'Raleigh,NC', 'date': '2024-08-22',
              'start_date': '2024-08-21', 'end_date': '2024-08-22', 'start_day': '08-21', 'end_day': '08-22'}
    required = set(required) | ({'lat', 'lon'} if 'lat' in fields else set()) | ({'city'} if operation == 'geocode' else set())
    return {'operation': operation, **{field: values[field] for field in required}}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.OPERATIONS)
async def test_routes_and_query_key(monkeypatch, operation):
    requests = transport(monkeypatch, FIXTURE)
    cfg = config_for(operation)
    result = await node(cfg).execute({})
    request = requests[0]
    assert request.method == 'GET'
    assert request.url.scheme == 'https' and request.url.host == 'api.weatherbit.io'
    assert request.url.path == '/v2.0' + native.OPERATIONS[operation][0]
    assert dict(request.url.params) == {**{k: str(float(v)) if k in {'lat', 'lon'} else v for k, v in cfg.items() if k != 'operation'}, 'key': KEY}
    assert result['data'] == FIXTURE and KEY not in str(result)


@pytest.mark.asyncio
async def test_optional_query_csv_and_zero_coordinates(monkeypatch):
    requests = transport(monkeypatch, {'data': []})
    await node({'operation': 'get_current_weather', 'lat': 0, 'lon': 0, 'include': ['minutely'], 'units': 'I'}).execute({})
    assert dict(requests[0].url.params) == {'lat': '0.0', 'lon': '0.0', 'include': 'minutely', 'units': 'I', 'key': KEY}


@pytest.mark.asyncio
async def test_no_data_and_rejected_key(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(204))
    assert (await node(config_for('get_alerts')).execute({}))['no_data'] is True
    transport(monkeypatch, lambda r: httpx.Response(403, json={'error': 'Invalid key ' + KEY}))
    with pytest.raises(ValueError, match=r'HTTP 403: Invalid key \[redacted\]'):
        await node({'operation': 'get_subscription_usage'}).execute({})


@pytest.mark.parametrize('change', [{'lat': 91}, {'lon': -181}, {'lat': None}, {'start_date': 'wrong'}, {'end_date': '2024-08-20'}])
def test_invalid_coordinates_and_history_dates(change):
    with pytest.raises(ValidationError):
        native.WeatherbitNodeConfig.model_validate({'config': {**config_for('get_daily_history'), **change}})


@pytest.mark.asyncio
async def test_documented_lightning_baseline_dedup_and_scope(monkeypatch):
    requests = transport(monkeypatch, FIXTURE)
    trigger = node({'operation': 'on_new_lightning', 'lat': 35.7796, 'lon': -78.6382})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result
    monkeypatch.setattr(trigger, '_update_node_state', update)
    assert (await trigger.execute({}))['new_lightning_count'] == 0
    assert trigger.trigger_produced_no_event({})
    # Reuse the second real documented event as an unseen arrival.
    unseen = FIXTURE['lightning'][1]['id']
    state['seen_ids'] = [x for x in state['seen_ids'] if x != str(unseen)]
    result = await trigger.execute({})
    assert [x['id'] for x in result['lightning']] == [unseen]
    assert trigger.trigger_emitted_event(result)
    event = native.WeatherbitNode.resolve_agent_event(result)
    assert str(unseen) in event['text'] and 'UTC' in event['text']
    assert native.WeatherbitNode.should_propagate_output(result, {'operation': 'on_new_lightning'})
    assert (await trigger.execute({}))['new_lightning_count'] == 0
    assert dict(requests[0].url.params) == {'lat': '35.7796', 'lon': '-78.6382', 'search_distance_km': '20', 'search_mins': '45', 'sort': 'time', 'output_type': 'json', 'limit': '1000', 'skip': '0', 'key': KEY}
    trigger._config = native.WeatherbitNodeConfig.model_validate({'config': {'operation': 'on_new_lightning', 'lat': 0, 'lon': 0}, 'credentials': {'api_key': KEY}})
    assert (await trigger.execute({}))['new_lightning_count'] == 0


@pytest.mark.asyncio
async def test_lightning_pagination_refuses_incomplete_overflow(monkeypatch):
    requests = transport(monkeypatch, {'lightning': [FIXTURE['lightning'][0]] * 1000})
    with pytest.raises(ValueError, match='10,000'):
        await node({'operation': 'on_new_lightning', 'lat': 0, 'lon': 0}).execute({})
    assert [int(r.url.params['skip']) for r in requests] == list(range(0, 10000, 1000))

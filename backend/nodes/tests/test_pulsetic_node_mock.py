"""Pulsetic current-OAS contract fixtures, authored but UNRUN."""
import json

import httpx
import pytest

import nodes.pulsetic_node as native

TOKEN = 'fixture-pulsetic-key-42'
START, END = '2026-10-01 00:00:00', '2026-10-02 00:00:00'


def make_node(operation, **fields):
    data = {'config': {'operation': operation, **fields}, 'credentials': {'credential_type': native.FAMILY, 'api_key': TOKEN}}
    return native.PulseticNode('native', 'automation-pulsetic', data, native.PulseticNode.parse_config(data), user_id='actor')


def monitor(id=7):
    return {'id': id, 'name': 'Private monitor', 'status': 'online', 'uptime': '1.0000000', 'checked_at': '2026-10-01T00:00:00Z',
        'url': 'https://private.example.test', 'ip': '192.0.2.1', 'request_headers': [{'value': 'Private'}], 'request_body_raw': 'Private content',
        'response_body': 'Private content', 'response_headers': ['Private'], 'telegram_hash': 'private-capability', 'nodes': [{'ip': 'Private'}], 'response_time': 0.114747}


def transport(monkeypatch, handler):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_raw_key_fixed_origin_monitor_bare_array_page_and_private_projection(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == 'GET' and request.url.host == 'api.pulsetic.com'
        assert request.headers['Authorization'] == TOKEN and not request.headers['Authorization'].startswith('Bearer ')
        assert request.url.path == '/api/public/monitors' and dict(request.url.params) == {'page': '2', 'per_page': '3'}
        return httpx.Response(200, json=[monitor()])
    transport(monkeypatch, respond)
    data = (await make_node('list_monitors', page=2, per_page=3).execute({}))['data']
    assert data['monitors'] == [{'id': 7, 'status': 'online', 'uptime': '1.0000000', 'checked_at': '2026-10-01T00:00:00Z'}]
    assert data['completion'] == 'unknown' and 'total' not in data and 'account_id' not in data and 'principal_id' not in data
    assert 'Private' not in str(data) and 'https://' not in str(data) and len(calls) == 1


@pytest.mark.parametrize('operation,key', [('list_snapshots', 'snapshots'), ('list_checks', 'checks'), ('list_events', 'events')])
@pytest.mark.asyncio
async def test_history_exact_parent_bare_array_query_and_distinct_paging(monkeypatch, operation, key):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path.endswith('/monitors/7'): return httpx.Response(200, json=monitor())
        assert request.url.path == '/api/public/monitors/7/' + key
        params = dict(request.url.params)
        assert params['start_dt'] == START and params['end_dt'] == END
        if operation == 'list_snapshots':
            assert params['page'] == '1' and params['per_page'] == '100'
            rows = [{'monitor_id': 7, 'hour': START, 'total_checks': 4, 'failed_checks': 1, 'uptime': '0.75', 'node': 'Private location', 'time_total_sum': '0.000987'}]
        else:
            assert not {'page', 'per_page', 'limit', 'cursor'} & params.keys()
            rows = [{'monitor_id': 7, 'created_at': START, 'type': 'MonitorOnline', 'response_code': 200, 'is_successful': 1, 'response_body': 'Private content', 'ip': '192.0.2.1', 'response_time': 0.357101}]
        return httpx.Response(200, json=rows)
    transport(monkeypatch, respond)
    data = (await make_node(operation, monitor_id='7', start_dt=START, end_dt=END).execute({}))['data']
    assert data[key][0]['monitor_id'] == 7 and data['completion'] == 'unknown'
    assert 'response_time' not in str(data) and 'Private' not in str(data) and 'time_total_sum' not in str(data)
    assert [call.url.path for call in calls].count('/api/public/monitors/7') == 2


@pytest.mark.asyncio
async def test_stats_exact_window_object_and_downtime_numeric_scalar(monkeypatch):
    def respond(request):
        if request.url.path.endswith('/monitors/7'): return httpx.Response(200, json=monitor())
        if request.url.path.endswith('/stats'):
            assert not request.url.params
            return httpx.Response(200, json={'1day': {'averageResponseTime': 220, 'uptime': '99.95', 'downtime': '00:03:10', 'url': 'https://private.example.test'}, 'secret': 'Private'})
        assert dict(request.url.params) == {'seconds': '3600'}
        return httpx.Response(200, json=190.25)
    transport(monkeypatch, respond)
    stats = (await make_node('get_stats', monitor_id='7').execute({}))['data']
    assert stats == {'monitor_id': 7, 'stats': {'1day': {'averageResponseTime': 220, 'uptime': '99.95', 'downtime': '00:03:10'}}}
    downtime = (await make_node('get_downtime', monitor_id='7').execute({}))['data']
    assert downtime == {'monitor_id': 7, 'downtime_seconds': 190.25, 'requested_seconds': 3600}


@pytest.mark.asyncio
async def test_heartbeat_and_status_metadata_local_caps_no_settings_or_secret_fields(monkeypatch):
    def respond(request):
        assert not request.url.params
        row = {'id': 5, 'name': 'Private heartbeat', 'title': 'Private title', 'created_at': START, 'alert_email': True, 'monitoring_interval': 60,
            'site_key': 'private-capability', 'secret_key': 'private-secret', 'statusPageSubscriptions': [{'email': 'private@example.test'}]}
        return httpx.Response(200, json=[row, dict(row, id=6)] if request.url.path.endswith(('/heartbeats', '/status-page')) else row)
    transport(monkeypatch, respond)
    h = (await make_node('list_heartbeats', limit=1).execute({}))['data']
    assert h['heartbeats'] == [{'id': 5, 'created_at': START}] and h['locally_truncated'] is True
    p = (await make_node('get_status_page', status_page_id='5', include_names=True).execute({}))['data']
    assert p == {'status_page': {'id': 5, 'title': 'Private title'}}
    assert 'secret' not in str(p) and 'Subscriptions' not in str(p)


@pytest.mark.parametrize('case', ['foreign_row', 'changed_parent', 'object_wrapper'])
@pytest.mark.asyncio
async def test_history_parent_and_array_contract_refuse_before_return(monkeypatch, case):
    count = 0
    def respond(request):
        nonlocal count
        if request.url.path.endswith('/monitors/7'):
            count += 1
            return httpx.Response(200, json=monitor(id=8 if case == 'changed_parent' and count > 1 else 7))
        rows = [{'monitor_id': 8 if case == 'foreign_row' else 7, 'created_at': START}]
        return httpx.Response(200, json={'data': rows, 'meta': {'total': 100}} if case == 'object_wrapper' else rows)
    transport(monkeypatch, respond)
    with pytest.raises(native.PulseticError): await make_node('list_checks', monitor_id='7', start_dt=START, end_dt=END).execute({})


@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 422, 429, 503])
@pytest.mark.asyncio
async def test_private_http_errors_redirects_no_follow_no_retries(monkeypatch, status):
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(status, text=TOKEN + ' Private', headers={'location': 'https://foreign.example.test/'}))
    with pytest.raises(native.PulseticError) as error: await make_node('list_monitors').execute({})
    assert error.value.status_code == status and TOKEN not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_reflection_pending_refs_closed_routes_and_raw_actor_change(monkeypatch):
    escaped = json.dumps([dict(monitor(), debug=TOKEN)]).replace('fixture', '\\u0066ixture')
    transport(monkeypatch, lambda request: httpx.Response(200, content=escaped, headers={'content-type': 'application/json'}))
    with pytest.raises(native.PulseticError, match='reflected'): await make_node('list_monitors').execute({})
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, json=[]))
    node = make_node('get_monitor', monitor_id='{{vars.monitor_id}}')
    with pytest.raises(native.PulseticError, match='Resolve'): await node.execute({})
    node = make_node('list_monitors'); node._frame = node._snapshot(); node._binding = None
    for route in ('/me', '/hello', '/rum/sites', '/monitors/7/notification-channels', '/heartbeats/5/ping'):
        with pytest.raises(native.PulseticError, match='Unsupported'): await node._request(route)
    with pytest.raises(native.PulseticError, match='Unsupported'): await node._request('/heartbeats', {'page': 1})
    assert calls == []
    node = make_node('list_monitors')
    async def changed(route, params=None):
        node.user_id = 'other-actor'
        return []
    node._request = changed
    with pytest.raises(native.PulseticError, match='actor'): await node.execute({})


def test_oas_offset_times_and_naive_examples_preserve_distinct_timezone_semantics():
    native.PulseticNode._window('2026-10-01T00:00:00Z', '2026-10-02T01:00:00+01:00')
    native.PulseticNode._window(START, END)
    with pytest.raises(native.PulseticError, match='mix'):
        native.PulseticNode._window(START, '2026-10-02T00:00:00Z')
    with pytest.raises(native.PulseticError, match='31-day'):
        native.PulseticNode._window(START, '2026-12-01 00:00:00')

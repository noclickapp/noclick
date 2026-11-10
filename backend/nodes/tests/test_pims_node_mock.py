"""HTTP-boundary checks using fields and examples in Pims' published v2 contract."""
import base64
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes.pims_node import OPERATIONS, PimsBasicCredential, PimsNode

CREDENTIAL = {"customer_domain": "sandbox", "username": "api-user", "password": "test-password"}
# These field values are copied from EventsEntity in the pinned OpenAPI document.
EVENT = {"id": 2142, "venue_id": 123, "series_id": 263, "label": "Alan Wilson",
         "datetime": "2018-01-11T20:00:00", "created_at": 1262300401, "updated_at": 1516500001}


def node(config):
    data = {"config": config, "credentials": CREDENTIAL}
    return PimsNode("pims-test", "automation-pims", data, config=PimsNode.parse_config(data))


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as c:
            yield c
    monkeypatch.setattr("nodes.pims_node.guarded_async_client", client)


@pytest.mark.parametrize("value", ["https://evil.example", "sandbox.pims.io.evil.example", "x@evil.example", "a/b", "127.0.0.1", "https://sandbox.pims.io:8443"])
def test_pims_domain_rejects_credential_exfiltration(value):
    with pytest.raises(ValueError):
        PimsBasicCredential(**{**CREDENTIAL, "customer_domain": value})


def test_pims_manual_connection_defaults_type_and_normalizes_domain():
    credential = PimsBasicCredential(**{**CREDENTIAL, "customer_domain": "https://sandbox.pims.io"})
    assert credential.credential_type == "pims_basic"
    assert credential.customer_domain == "sandbox"
    assert set(PimsBasicCredential.model_fields) == {"credential_type", "customer_domain", "username", "password"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_pims_operations_one_request(monkeypatch, operation):
    method, route, collection = OPERATIONS[operation]
    config = {"operation": operation}
    for segment in route.split('/'):
        if segment.startswith('{'):
            config[segment[1:-1]] = 2142
    if method in {"POST", "PATCH"}:
        config["label"] = "Alan Wilson"
    if operation == "create_event":
        config.update(datetime="2018-01-11T20:00:00", venue_id=123, input_type_id="DET", contract_type_id="PRO")
    if operation == "create_promotion":
        config.update(type_id="PRE", cost_type_id="PAY")
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == method
        assert request.url.host == "sandbox.pims.io"
        assert request.url.path == "/api/v2" + route.format(**config)
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"api-user:test-password").decode()
        if method == "DELETE":
            return httpx.Response(204)
        body = {"_embedded": {collection: [EVENT]}, "page": 1, "page_count": 1, "total_items": 1} if collection else EVENT
        return httpx.Response(201 if method in {"POST", "PATCH"} else 200, json=body)
    transport(monkeypatch, handle)
    result = await node(config).execute({})
    assert len(calls) == 1
    assert result["data"] == ([EVENT] if collection else {"deleted": True} if method == "DELETE" else EVENT)


@pytest.mark.asyncio
async def test_pims_sends_filters_and_page_without_following_response_links(monkeypatch):
    def handle(request):
        assert request.url.params == httpx.QueryParams({"page": 2, "page_size": 50, "series_id": 263, "from_updated_at": 1516500001})
        return httpx.Response(200, json={"_embedded": {"events": [EVENT]}, "page": 2, "page_count": 2, "total_items": 51})
    transport(monkeypatch, handle)
    out = await node({"operation": "list_events", "page": 2, "page_size": 50, "series_id": 263, "from_updated_at": 1516500001}).execute({})
    assert out["page"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_event", "on_updated_event"])
async def test_pims_poll_baseline_dedup_and_updates(monkeypatch, operation):
    current = dict(EVENT)
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.params['sort'] == ('-created_at' if operation == 'on_new_event' else '-updated_at')
        assert request.url.params['venue_id'] == '123'
        return httpx.Response(200, json={"_embedded": {"events": [current]}, "page_count": 1})
    transport(monkeypatch, handle)
    n = node({"operation": operation, "venue_id": 123})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    n._update_node_state = update
    assert (await n.execute({}))["event_count"] == 0  # arming establishes the baseline
    assert (await n.execute({}))["event_count"] == 0
    if operation == 'on_new_event':
        current['id'] += 1
    else:
        current['updated_at'] += 1
    out = await n.execute({})
    assert out['event_count'] == 1
    assert 'Alan Wilson' in PimsNode.resolve_agent_event(out)['text']
    assert PimsNode.should_propagate_output(out, {'operation': operation})
    assert (await n.execute({}))["event_count"] == 0


@pytest.mark.asyncio
async def test_pims_poll_reads_all_pages_before_marking_seen(monkeypatch):
    def handle(request):
        page = int(request.url.params.get('page', '1'))
        event = {**EVENT, 'id': page}
        return httpx.Response(200, json={'_embedded': {'events': [event]}, 'page_count': 2,
                                      '_links': {'next': {'href': 'https://evil.example'}} if page == 1 else {}})
    transport(monkeypatch, handle)
    n = node({'operation': 'on_new_event'})
    found = []
    async def unseen(items, key):
        found.extend(key(row) for row in items)
        return items
    n._filter_unseen = unseen
    assert (await n.execute({}))['event_count'] == 2
    assert found == ['1', '2']


@pytest.mark.asyncio
async def test_pims_rejection_cannot_expose_password(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, json={'detail': 'Rejected test-password'}))
    with pytest.raises(ValueError, match='HTTP 401: Rejected \\[redacted\\]'):
        await node({'operation': 'list_events'}).execute({})


@pytest.mark.asyncio
async def test_pims_empty_update_is_refused_before_http(monkeypatch):
    transport(monkeypatch, lambda request: pytest.fail('empty write reached HTTP'))
    with pytest.raises(ValueError, match='at least one'):
        await node({'operation': 'update_event', 'event_id': 2142}).execute({})

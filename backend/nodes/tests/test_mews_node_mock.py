"""Exercise the native factory with provider-authored examples and mock HTTP."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import mews_node as mews
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

CASES = json.loads((Path(__file__).parent / 'fixtures/mews/documented_cases.json').read_text())
AUTH = {"credential_type": "mews_tokens", "client_token": "fixture-client-secret", "access_token": "fixture-property-secret"}
ID = "20e00c32-d561-4008-8609-82d8aa525714"


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="mews-test", node_type="automation-mews",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


def mock_http(monkeypatch, handler):
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(mews, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_documented_response_through_factory(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == mews.BASE_URL + case["route"]
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["ClientToken"] == AUTH["client_token"]
        assert body["AccessToken"] == AUTH["access_token"]
        assert body["Client"] == "NoClick 1.0.0"
        return httpx.Response(200, json=case["response"])
    mock_http(monkeypatch, handler)
    result = await node(operation, **case["config"]).execute({})
    assert result["data"] == case["response"]
    assert len(calls) == 1
    if operation.startswith("list_"):
        assert result["next_cursor"] == case["response"].get("Cursor")


def test_guest_updates_omit_unchanged_fields():
    op = mews.UpdateCustomer(customer_id=ID, notes="Replaced notes")
    assert mews._body(op) == {"CustomerId": ID, "Notes": "Replaced notes"}
    assert mews._body(mews.CreateCustomer(last_name="Guest")) == {"LastName": "Guest", "OverwriteExisting": False}


def test_reservation_and_housekeeping_wire_shapes():
    op = mews.CreateReservation(**CASES["create_reservation"]["config"])
    body = mews._body(op)
    assert body["CheckRateApplicability"] is True
    assert body["CheckOverbooking"] is True
    assert body["SendConfirmationEmail"] is False
    assert body["Reservations"][0]["PersonCounts"] == [{"AgeCategoryId": op.age_category_id, "Count": 2}]
    assert mews._body(mews.ConfirmReservation(reservation_id=ID)) == {"ReservationIds": [ID], "SendConfirmationEmail": False}
    assert mews._body(mews.CancelReservation(reservation_id=ID)) == {"ReservationIds": [ID], "PostCancellationFee": False, "SendEmail": False}
    assert mews._body(mews.ProcessReservation(reservation_id=ID)) == {"ReservationId": ID, "CloseBills": False, "AllowOpenBalance": False}
    assert mews._body(mews.UpdateResource(resource_id=ID, state="Clean")) == {"ResourceUpdates": [{"ResourceId": ID, "State": {"Value": "Clean"}}]}


def test_pagination_and_account_filter_mapping():
    body = mews._body(mews.ListReservations(customer_id=ID, cursor=ID, count=17,
        updated_start_utc="2026-01-01T00:00:00Z", updated_end_utc="2026-01-02T00:00:00Z"))
    assert body == {"Limitation": {"Count": 17, "Cursor": ID}, "AccountIds": [ID],
        "UpdatedUtc": {"StartUtc": "2026-01-01T00:00:00Z", "EndUtc": "2026-01-02T00:00:00Z"}}


@pytest.mark.parametrize("operation,config", [
    ("start_reservation", {"reservation_id": "../other"}),
    ("list_customers", {"cursor": "bad"}),
    ("list_customers", {"count": 0}),
    ("list_services", {"updated_start_utc": "2026-01-01T00:00:00Z"}),
    ("create_task", {"name": "Task", "deadline_utc": "2026-01-01"}),
    ("create_customer", {"last_name": "Guest", "email": "bad"}),
    ("update_customer", {"customer_id": ID}),
    ("update_resource", {"resource_id": ID}),
    ("update_resource", {"resource_id": ID, "state": "OutOfOrder"}),
    ("get_configuration", {"url": "https://evil.example"}),
])
def test_invalid_config_rejected(operation, config):
    assert mews.MewsNode.validate_config({"config": {"operation": operation, **config}, "credentials": AUTH})["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 302])
async def test_provider_errors_not_retried_and_secrets_redacted(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"Message": "Rejected " + AUTH["access_token"]})
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError) as error:
        await node("get_configuration").execute({})
    assert "Rejected" in str(error.value)
    assert AUTH["access_token"] not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>bad</html>"), httpx.Response(200, json=[]), httpx.Response(200, json={"Message": "Refused", "RequestId": ID})])
async def test_malformed_or_error_success_envelope(monkeypatch, response):
    mock_http(monkeypatch, lambda _: response)
    with pytest.raises(ValueError):
        await node("get_configuration").execute({})


@pytest.mark.asyncio
async def test_account_connection_evidence(monkeypatch):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=CASES["get_configuration"]["response"]))
    result = await collect_evidence(node_type="automation-mews", user_id=ID, pool=None, credential_data=AUTH)
    assert result.reachable is True
    assert result.account_label == CASES["get_configuration"]["response"]["Enterprise"]["Name"]


def test_manual_credential_default_and_secret_repr():
    credential = mews.MewsTokenCredential(client_token=AUTH["client_token"], access_token=AUTH["access_token"])
    assert credential.credential_type == "mews_tokens"
    assert AUTH["access_token"] not in repr(credential)
    assert AUTH["client_token"] not in repr(credential)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,action,key', [
    ('on_updated_reservation', 'list_reservations', 'Reservations'),
    ('on_updated_customer', 'list_customers', 'Customers'),
    ('on_updated_resource', 'list_resources', 'Resources'),
])
async def test_poll_baselines_and_emits_changed_versions(monkeypatch, operation, action, key):
    from copy import deepcopy
    from datetime import datetime

    case = CASES[action]
    response = deepcopy(case['response'])
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == mews.BASE_URL + case['route']
        start, end = (datetime.fromisoformat(body['UpdatedUtc'][k]) for k in ('StartUtc', 'EndUtc'))
        assert (end - start).total_seconds() == 86400
        assert body['Limitation'] == {'Count': 100}
        if operation == 'on_updated_reservation':
            assert body['ServiceIds'] == [ID]
        return httpx.Response(200, json=response)

    mock_http(monkeypatch, handler)
    instance = node(operation, **({'service_id': ID} if operation == 'on_updated_reservation' else {}))
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    baseline = await instance.execute({})
    assert baseline['records'] == []
    assert instance.trigger_produced_no_event(baseline)
    assert instance.resolve_agent_event(baseline) is None
    assert (await instance.execute({}))['records'] == []
    response[key][0]['UpdatedUtc'] = '2026-11-10T12:00:00Z'
    changed = await instance.execute({})
    assert changed['records'] == [response[key][0]]
    assert instance.trigger_emitted_event(changed)
    turn = instance.resolve_agent_event(changed)
    assert 'Mews:' in turn['text']
    assert response[key][0]['Id'] in turn['text']
    assert '2026-11-10T12:00:00Z' in turn['text']
    assert (await instance.execute({}))['records'] == []
    added = deepcopy(response[key][0])
    added['Id'] = '00000000-0000-4000-8000-000000000123'
    response[key].append(added)
    assert (await instance.execute({}))['records'] == [added]
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_dedup(monkeypatch):
    from copy import deepcopy

    record = CASES['list_customers']['response']['Customers'][0]
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={'Customers': [record] * 100, 'Cursor': ID})
        assert body['Limitation']['Cursor'] == ID
        assert body['UpdatedUtc'] == calls[0]['UpdatedUtc']
        return httpx.Response(200, json={'Customers': [record], 'Cursor': None})

    mock_http(monkeypatch, handler)
    instance = node('on_updated_customer')
    captured = []

    async def filter_unseen(items, id_fn):
        captured.extend(deepcopy(items))
        assert id_fn(items[0]) == record['Id'] + ':' + record['UpdatedUtc']
        return items

    monkeypatch.setattr(instance, '_filter_unseen', filter_unseen)
    await instance.execute({})
    assert len(calls) == 2
    assert len(captured) == 101


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{'Customers': None}, {'Customers': [{}]}])
async def test_poll_invalid_response_does_not_advance_baseline(monkeypatch, response):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=response))
    instance = node('on_updated_customer')

    async def unexpected(*args, **kwargs):
        pytest.fail('Invalid responses must not update poll state')

    monkeypatch.setattr(instance, '_filter_unseen', unexpected)
    with pytest.raises(ValueError):
        await instance.execute({})


def test_poll_scope_tracks_service_and_ignores_canvas_metadata():
    from nodes.core.poll_trigger import poll_scope
    config = {'operation': 'on_updated_reservation', 'service_id': ID}
    scope = poll_scope(mews.MewsNode, config)
    assert scope
    assert poll_scope(mews.MewsNode, {**config, 'label': 'New name'}) == scope
    assert poll_scope(mews.MewsNode, {**config, 'service_id': None}) != scope


def test_poll_schedule_mirrors_are_not_provider_uuids():
    parsed = mews.OnUpdatedReservation(service_id=ID, schedule_id='schedule-mews-test',
                                      webhook_id='webhook-mews-test')
    assert str(parsed.service_id) == ID
    assert parsed.schedule_id == 'schedule-mews-test'
    assert mews.MewsNode._is_schedule_operation('on_updated_reservation')


@pytest.mark.asyncio
@pytest.mark.parametrize('repeated,expected_calls', [(True, 2), (False, 20)])
async def test_incomplete_poll_never_consumes_seen_state(monkeypatch, repeated, expected_calls):
    calls = []
    record = CASES['list_customers']['response']['Customers'][0]

    def handler(request):
        calls.append(request)
        cursor = ID if repeated else f'00000000-0000-4000-8000-{len(calls):012d}'
        return httpx.Response(200, json={'Customers': [record] * 100, 'Cursor': cursor})

    mock_http(monkeypatch, handler)
    instance = node('on_updated_customer')

    async def unexpected(*args, **kwargs):
        pytest.fail('Incomplete pagination must not consume poll state')

    monkeypatch.setattr(instance, '_filter_unseen', unexpected)
    with pytest.raises(ValueError, match='repeated pagination|2,000 records'):
        await instance.execute({})
    assert len(calls) == expected_calls

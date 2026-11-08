"""Real node factory against fixed Humanitix HTTP requests; no live account."""
import httpx
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes import humanitix_node as native
from nodes.core.registry import NodeFactory

KEY = "humanitix-synthetic-key"
EVENT = "5ac598ccd8fe7c0c0f212e2a"
TICKET = "5ac598ccd8fe7c0c0f212e2d"
DATE = "5ac598ccd8fe7c0c0f212e2f"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="humanitix-test", node_type="automation-humanitix",
        node_data={"config": config, "credentials": {"credential_type": "humanitix_api_key", "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,collection", [
    ("list_events", "/v1/events", "events"),
    ("list_orders", "/v1/events/" + EVENT + "/orders", "orders"),
    ("list_tickets", "/v1/events/" + EVENT + "/tickets", "tickets"),
    ("list_tags", "/v1/tags", "tags"),
    ("list_global_events", "/v1/global/events", "events"),
    ("list_global_event_dates", "/v1/global/event-dates", "eventDates"),
])
async def test_lists_one_page_and_exact_pagination(monkeypatch, operation, path, collection):
    body = {collection: [{"_id": EVENT, "name": "Test event"}], "page": 2, "pageSize": 10, "total": 21}
    requests = transport(monkeypatch, body)
    config = {"operation": operation, "page": 2, "pageSize": 10}
    if operation in {"list_orders", "list_tickets"}:
        config["eventId"] = EVENT
    output = await node(config).execute({})
    assert output["data"] == body and output["items"] == body[collection]
    assert output["next_page"] == 3 and len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.path == path
    assert request.url.host == "api.humanitix.com" and request.headers["x-api-key"] == KEY
    assert dict(request.url.params) == {"page": "2", "pageSize": "10"}
    assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,path", [
    ("get_event", {"eventId": EVENT}, "/v1/events/" + EVENT),
    ("get_order", {"eventId": EVENT, "orderId": TICKET}, "/v1/events/" + EVENT + "/orders/" + TICKET),
    ("get_ticket", {"eventId": EVENT, "ticketId": TICKET}, "/v1/events/" + EVENT + "/tickets/" + TICKET),
    ("get_tag", {"tagId": TICKET}, "/v1/tags/" + TICKET),
])
async def test_detail_reads_keep_provider_fields(monkeypatch, operation, extra, path):
    body = {"_id": TICKET, "name": "Guest", "futureField": {"value": 42}}
    requests = transport(monkeypatch, body)
    assert (await node({"operation": operation, **extra}).execute({}))["data"] == body
    assert requests[0].url.path == path and not requests[0].url.params


@pytest.mark.asyncio
async def test_required_checkin_count_date_is_query(monkeypatch):
    body = {"eventId": EVENT, "eventDateId": DATE, "checkedIn": 3, "ticketTypes": []}
    requests = transport(monkeypatch, body)
    output = await node({"operation": "get_event_check_in_count", "eventId": EVENT, "eventDateId": DATE}).execute({})
    assert output["data"] == body
    assert requests[0].url.path == "/v1/events/" + EVENT + "/check-in-count"
    assert dict(requests[0].url.params) == {"eventDateId": DATE}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,suffix", [("check_in_ticket", "check-in"), ("check_out_ticket", "check-out")])
async def test_scan_single_post_without_body(monkeypatch, operation, suffix):
    body = {"scanningMessages": [{"header": "Test scan message", "message": "<p>My custom message</p>"}]}
    requests = transport(monkeypatch, body)
    output = await node({"operation": operation, "eventId": EVENT, "ticketId": TICKET, "overrideLocation": "AU"}).execute({})
    assert output["data"] == body and len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and request.content == b""
    assert request.url.path == "/v1/events/" + EVENT + "/tickets/" + TICKET + "/" + suffix
    assert dict(request.url.params) == {"overrideLocation": "AU"}


@pytest.mark.asyncio
async def test_filters_and_empty_terminal_page(monkeypatch):
    requests = transport(monkeypatch, {"events": [], "page": 1, "pageSize": 100, "total": 0})
    output = await node({"operation": "list_events", "inFutureOnly": False, "since": "2026-01-01T00:00:00Z", "overrideLocation": "NZ"}).execute({})
    assert output["next_page"] is None and output["items"] == []
    assert dict(requests[0].url.params) == {"page": "1", "pageSize": "100", "inFutureOnly": "false", "since": "2026-01-01T00:00:00Z", "overrideLocation": "NZ"}


@pytest.mark.asyncio
async def test_ticket_filters(monkeypatch):
    requests = transport(monkeypatch, {"tickets": [], "page": 1, "pageSize": 100, "total": 0})
    await node({"operation": "list_tickets", "eventId": EVENT, "eventDateId": DATE, "status": "cancelled"}).execute({})
    assert dict(requests[0].url.params) == {"page": "1", "pageSize": "100", "eventDateId": DATE, "status": "cancelled"}


@pytest.mark.asyncio
async def test_global_classification_filters(monkeypatch):
    requests = transport(monkeypatch, {"events": [], "page": 1, "pageSize": 100, "total": 0})
    await node({"operation": "list_global_events", "type": "festivalOrFair", "category": "music", "subcategory": "electronic", "withArtistsOnly": True}).execute({})
    assert dict(requests[0].url.params) == {"page": "1", "pageSize": "100", "type": "festivalOrFair", "category": "music", "subcategory": "electronic", "withArtistsOnly": "true"}


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "eventId": "../tags"},
    {"operation": "get_event_check_in_count", "eventId": EVENT},
    {"operation": "list_events", "page": 0},
    {"operation": "list_events", "pageSize": 101},
    {"operation": "list_events", "since": "yesterday"},
    {"operation": "list_events", "since": "2026-01-01T00:00:00"},
    {"operation": "list_global_events", "subcategory": "electronic"},
    {"operation": "list_tickets", "eventId": EVENT, "status": "unknown"},
    {"operation": "check_in_ticket", "eventId": EVENT, "ticketId": TICKET, "body": {}},
])
def test_invalid_parameters_fail_before_http(config):
    with pytest.raises(ValidationError):
        TypeAdapter(native.HumanitixConfig).validate_python(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_no_retry_or_false_success_for_provider_errors(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + KEY}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "check_in_ticket", "eventId": EVENT, "ticketId": TICKET}).execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_ambiguous_write_does_not_retry(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("timeout"))
    with pytest.raises(ValueError, match="check the ticket before retrying"):
        await node({"operation": "check_in_ticket", "eventId": EVENT, "ticketId": TICKET}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"scanningMessages": "ok"}, {"scanningMessages": [{}]}, {"error": "no"}])
async def test_malformed_scan_never_reports_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "check_out_ticket", "eventId": EVENT, "ticketId": TICKET}).execute({})


@pytest.mark.asyncio
async def test_secret_reflections_removed(monkeypatch):
    transport(monkeypatch, {"_id": EVENT, "nested": [{"key": KEY}]})
    output = await node({"operation": "get_event", "eventId": EVENT}).execute({})
    assert KEY not in str(output)


def test_legacy_api_keys_are_accepted_and_cleaned():
    assert native.HumanitixAPIKeyCredential(api_key=" legacy-key ").api_key == "legacy-key"

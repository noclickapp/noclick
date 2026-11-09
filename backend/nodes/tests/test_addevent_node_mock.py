"""Exercise every AddEvent endpoint with provider-authored example responses."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import addevent_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/addevent/published-examples.json").read_text()
)
AUTH = {"credential_type": "addevent_api_key", "api_key": "fixture-addevent-key"}


def example(name):
    def resolve(value):
        if isinstance(value, dict):
            if "$ref" in value:
                parts = value["$ref"].split("/")
                return resolve(FIXTURE["examples"][parts[3]])
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value

    return resolve(deepcopy(FIXTURE["examples"][name]))


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        calls.append(request)
        assert request.url.host == "api.addevent.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        return (
            httpx.Response(status, json=body)
            if body is not None
            else httpx.Response(status)
        )

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        node,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return calls, replies


async def run(operation, config=None):
    return await run_node_operation(
        node_type="automation-addevent",
        operation=operation,
        arguments=config or {},
        credential_data=AUTH.copy(),
        user_id="00000000-0000-4000-8000-000000000001",
    )


CASES = [
    ("create_event", "POST", "/events", "event-body", "event-min", 201),
    ("search_events", "GET", "/events", None, "event-search", 200),
    ("retrieve_event", "GET", "/events/event1", None, "event-all", 200),
    ("update_event", "PATCH", "/events/event1", "event-body", "event-all", 200),
    ("delete_event", "DELETE", "/events/event1", None, None, 204),
    ("create_calendar", "POST", "/calendars", "calendar-body", "calendar-all", 201),
    ("search_calendars", "GET", "/calendars", None, "calendar-search", 200),
    ("retrieve_calendar", "GET", "/calendars/calendar1", None, "calendar-all", 200),
    (
        "update_calendar",
        "PATCH",
        "/calendars/calendar1",
        "calendar-body",
        "calendar-all",
        200,
    ),
    ("delete_calendar", "DELETE", "/calendars/calendar1", None, None, 204),
    (
        "create_rsvp_attendee",
        "POST",
        "/events/event1/rsvps",
        "rsvp-attendee-body",
        "attendee-all",
        201,
    ),
    ("search_rsvp_attendees", "GET", "/rsvps", None, "attendee-search", 200),
    ("retrieve_rsvp_attendee", "GET", "/rsvps/attendee1", None, "attendee-all", 200),
    (
        "update_rsvp_attendee",
        "PATCH",
        "/rsvps/attendee1",
        "rsvp-attendee-body",
        "attendee-all",
        200,
    ),
    ("delete_rsvp_attendee", "DELETE", "/rsvps/attendee1", None, None, 204),
    (
        "search_calendar_subscribers",
        "GET",
        "/subscribers",
        None,
        "subscriber-search",
        200,
    ),
    (
        "retrieve_calendar_subscriber",
        "GET",
        "/subscribers/subscriber1",
        None,
        "subscriber-all",
        200,
    ),
    (
        "delete_calendar_subscriber",
        "DELETE",
        "/subscribers/subscriber1",
        None,
        None,
        204,
    ),
    ("list_rsvp_forms", "GET", "/events/rsvp-forms", None, "rsvp-forms", 200),
    (
        "list_event_templates",
        "GET",
        "/events/templates",
        None,
        "event-landing-page-templates",
        200,
    ),
    (
        "list_calendar_templates",
        "GET",
        "/calendars/templates",
        None,
        "calendar-landing-page-templates",
        200,
    ),
    ("list_timezones", "GET", "/timezones", None, "timezones", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,path,input_example,response_example,status", CASES
)
async def test_published_contract(
    transport, operation, method, path, input_example, response_example, status
):
    calls, replies = transport
    config = example(input_example) if input_example else {}
    # The provider's calendar example has an undocumented palette_id; the
    # published request schema uses calendar_color instead. Do not send it.
    config.pop("palette_id", None)
    for kind in ["event", "calendar", "attendee", "subscriber"]:
        if f"/{kind}1" in path:
            config[kind + "_id"] = kind + "1"
    body = example(response_example) if response_example else None
    replies.append((status, body))
    result = await run(operation, config)
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.path == "/calevent/v2" + path
    if method in {"POST", "PATCH"}:
        expected = {
            k: v
            for k, v in config.items()
            if k not in {"event_id", "calendar_id", "attendee_id"}
        }
        assert json.loads(request.content) == expected
    elif status == 204:
        assert result["deleted"] is True
    if operation.startswith("search_"):
        assert result["pagination"] == body["pagination"]
        assert result["items"]
    elif operation.startswith("list_"):
        assert result["items"] == body
    elif status != 204:
        assert result["data"] == body


@pytest.mark.asyncio
async def test_query_array_encoding_and_single_page(transport):
    calls, replies = transport
    replies.append((200, example("attendee-search")))
    await run(
        "search_rsvp_attendees",
        {
            "calendar_ids": ["cal1", "cal2"],
            "attending": ["going", "maybe"],
            "page": 2,
            "page_size": 20,
        },
    )
    assert calls[0].url.params["calendar_ids"] == "cal1,cal2"
    assert calls[0].url.params.get_list("attending") == ["going", "maybe"]
    assert calls[0].url.params["page"] == "2"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_are_not_success_and_redact_key(transport, status):
    calls, replies = transport
    replies.append((status, {"error": "Unauthorized " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as err:
        await run("search_calendars")
    assert str(status) in str(err.value)
    assert AUTH["api_key"] not in str(err.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "retrieve_event", "event_id": ".."},
        {"operation": "create_event", "title": "Missing start"},
        {
            "operation": "update_event",
            "event_id": "ev1",
            "location": "Somewhere",
            "location_id": 1,
        },
        {"operation": "update_event", "event_id": "ev1", "organizer_name": "Example"},
        {"operation": "search_events", "page_size": 21},
        {"operation": "search_events", "sort_order": "asc"},
        {"operation": "search_events", "custom_data_key": "incomplete"},
        {"operation": "update_calendar", "calendar_id": "cal1"},
        {
            "operation": "create_rsvp_attendee",
            "event_id": "ev1",
            "email": "emailaddress@addevent.com",
        },
    ],
)
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        node.AddEventNode.parse_config({"config": config, "credentials": AUTH})


def test_manual_credential_default_and_secret_shaping():
    credential = node.AddEventApiKeyCredential(api_key=" fixture-addevent-key ")
    assert credential.credential_type == "addevent_api_key"
    assert credential.api_key == AUTH["api_key"]

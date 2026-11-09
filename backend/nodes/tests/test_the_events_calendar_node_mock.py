"""Offline request, credential, archive and error regressions for TEC v1."""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import the_events_calendar_node as native
from nodes.core.registry import NodeFactory

CREDS = {"credential_type": "the_events_calendar_application_password", "site_url": "https://calendar.example.org/blog", "username": "editor", "application_password": "abcd efgh ijkl mnop qrst uvwx"}
KINDS = [("events", "event", "title"), ("venues", "venue", "venue"), ("organizers", "organizer", "organizer"), ("categories", "category", "name"), ("tags", "tag", "name")]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tec-test", node_type="automation-the-events-calendar", node_data={"config": config, "credentials": CREDS})


def mock_client(monkeypatch, body, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,singular,field", KINDS)
async def test_list_archive_pagination_and_basic_auth(monkeypatch, kind, singular, field):
    row = {"id": 42, field: "Community picnic"}
    requests = mock_client(monkeypatch, {kind: [row], "total": 31, "total_pages": 2})
    result = await node({"operation": "list_" + kind, "page": 2, "search": "picnic + lunch"}).execute({})
    assert result == {"items": [row], "page": 2, "per_page": 20, "total": 31, "total_pages": 2}
    req = requests[0]
    assert req.method == "GET"
    assert req.url.path == "/blog/wp-json/tribe/events/v1/" + kind
    assert dict(req.url.params) == {"page": "2", "per_page": "20", "search": "picnic + lunch"}
    assert req.headers["Authorization"] == "Basic " + base64.b64encode((CREDS["username"] + ":" + CREDS["application_password"]).encode()).decode()
    assert len(requests) == 1
    mock_client(monkeypatch, [row], headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"})
    assert (await node({"operation": "list_" + kind}).execute({}))["items"] == [row]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,singular,field", KINDS)
@pytest.mark.parametrize("action,method", [("get", "GET"), ("update", "POST"), ("delete", "DELETE")])
async def test_resource_routes_methods_and_form_encoding(monkeypatch, kind, singular, field, action, method):
    requests = mock_client(monkeypatch, {"id": 42, field: "Updated title"})
    config = {"operation": action + "_" + singular, "id": 42}
    if action == "update": config[field] = "Updated title"
    assert (await node(config).execute({}))["data"]["id"] == 42
    req = requests[0]
    assert len(requests) == 1 and req.method == method
    assert req.url.path == "/blog/wp-json/tribe/events/v1/" + kind + "/42"
    assert not req.url.query
    if method == "POST":
        assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert parse_qs(req.content.decode()) == {field: ["Updated title"]}
    else:
        assert not req.content


@pytest.mark.asyncio
async def test_update_false_arrays_and_omission(monkeypatch):
    requests = mock_client(monkeypatch, {"id": 42})
    await node({"operation": "update_event", "id": 42, "featured": False, "categories": [12, 34]}).execute({})
    assert parse_qs(requests[0].content.decode()) == {"featured": ["false"], "categories[0]": ["12"], "categories[1]": ["34"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_provider_error_is_preserved_without_retry(monkeypatch, status):
    requests = mock_client(monkeypatch, {"code": "rest_forbidden", "message": "Sorry, you cannot edit this event."}, status)
    with pytest.raises(ValueError, match="Sorry, you cannot edit this event"):
        await node({"operation": "delete_event", "id": 42}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_malformed_archive_rejected(monkeypatch):
    mock_client(monkeypatch, {"events": {"id": 42}})
    with pytest.raises(ValueError, match="invalid archive"):
        await node({"operation": "list_events"}).execute({})


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://example.com?secret=foo", "https://example.com/wp-admin", "https://example.com/../admin", "https://example.com/wp-json/tribe/events/v1", "https://example.com/#fragment"])
def test_invalid_site_refused(url):
    with pytest.raises(ValidationError):
        native.TheEventsCalendarCredential.model_validate({**CREDS, "site_url": url})


def test_manual_credential_default_and_normalization():
    raw = {k: v for k, v in CREDS.items() if k != "credential_type"}
    raw["site_url"] = "https://Calendar.Example.org/blog/"
    parsed = native.TheEventsCalendarCredential.model_validate(raw)
    assert parsed.credential_type == CREDS["credential_type"]
    assert parsed.site_url == CREDS["site_url"]


def test_invalid_ids_and_empty_update():
    for config in [{"operation": "get_event", "id": 0}, {"operation": "get_event", "id": "../venues"}, {"operation": "update_event", "id": 42}]:
        assert node_validation(config)["valid"] is False


def node_validation(config):
    return native.TheEventsCalendarNode.validate_config({"config": config, "credentials": CREDS})


@pytest.mark.asyncio
async def test_query_array_filters_and_false_are_sent(monkeypatch):
    requests = mock_client(monkeypatch, {"events": []})
    await node({"operation": "list_events", "venue": [12, 34], "organizer": [56], "featured": False}).execute({})
    assert dict(requests[0].url.params) == {"page": "1", "per_page": "20", "venue": "12,34", "organizer": "56", "featured": "false"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"id": 99}, []])
async def test_wrong_resource_response_refused(monkeypatch, body):
    mock_client(monkeypatch, body)
    with pytest.raises(ValueError, match="invalid or mismatched resource"):
        await node({"operation": "update_event", "id": 42, "title": "Updated title"}).execute({})


@pytest.mark.asyncio
async def test_provider_published_single_event_example(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/the-events-calendar/event.json").read_text())
    mock_client(monkeypatch, body)
    result = await node({"operation": "get_event", "id": 6}).execute({})
    assert result["data"] == body

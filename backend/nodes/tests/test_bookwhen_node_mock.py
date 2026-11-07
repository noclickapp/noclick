"""Prepared Bookwhen native factory, schema and read-contract regressions.

All tokens and JSON:API responses are synthetic; no provider account is used.
"""
import base64
import json
from pathlib import Path
from urllib.parse import urlencode
import httpx
import pytest
from pydantic import ValidationError
from nodes import bookwhen_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-bookwhen-token-42"
EVENT = "ev-owned-20261006100000"
TICKET = "ti-owned-20261006100000-tk1m"
IDS = {"events": EVENT, "tickets": TICKET, "locations": "owned-location", "attachments": "owned-attachment", "class_passes": "cp-owned-pass"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


def credential(**changes):
    return {"credential_type": native.FAMILY, "api_token": TOKEN, **changes}


def record(kind="events", *, resource_id=None, attributes=None, relationships=None):
    attrs = {"title": "Owned fixture", "details": "private-fixture@example.com", "file_url": "https://secret.example.test/file",
        "built_basket_url": "https://secret.example.test/book", "map_url": "https://secret.example.test/map", "password": TOKEN}
    if kind == "locations": attrs["address_text"] = "Owned fixture"
    if kind == "attachments": attrs.update(file_size_bytes="47070", file_name="fixture.pdf")
    if kind == "class_passes": attrs.update(usage_type="personal", usage_allowance=4, number_available=None)
    rels = {"events": {"tickets": {"data": [{"type": "ticket", "id": TICKET}]}},
        "tickets": {"events": {"data": [{"type": "event", "id": EVENT}]}}}.get(kind, {})
    return {"type": native.KINDS[kind], "id": resource_id or IDS[kind], "attributes": {**attrs, **(attributes or {})},
        "relationships": rels if relationships is None else relationships}


def page(items=None, next_offset=None, *, kind="events", params=None):
    links = {}
    if next_offset is not None:
        links["next"] = native.BASE + "/" + kind + "?" + urlencode({**(params or {}), "page[offset]": next_offset})
    return {"data": [record(kind)] if items is None else items, "links": links}


def node(config, *, creds=None):
    return NodeFactory.create_node(node_id="owned-fixture", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential() if creds is None else creds})


def transport(monkeypatch, reply):
    requests, policies = [], []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        policies.append(kwargs.copy())
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, policies


@pytest.mark.asyncio
async def test_actual_factory_basic_blank_password_public_empty_reachability(monkeypatch):
    requests, policies = transport(monkeypatch, page([]))
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "success" and result["read_completed"] and result["complete"]
    assert result["items"] == [] and result["user_identity_verified"] is False and result["ownership_verified"] is False
    assert "key_accepted" not in result and TOKEN not in str(result)
    assert requests[0].method == "GET" and requests[0].url.host == "api.bookwhen.com"
    assert requests[0].headers["Authorization"] == "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()
    assert dict(requests[0].url.params) == {"page[offset]": "0"} and len(policies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(native.KINDS))
async def test_native_typed_list_and_selected_detail_paths_project_metadata(monkeypatch, kind):
    requests, _ = transport(monkeypatch, page(kind=kind))
    cfg = {"operation": "list_" + kind, **({"event_id": EVENT} if kind == "tickets" else {})}
    result = await node(cfg).run({})
    assert result["status"] == "success" and result["items"][0]["id"] == IDS[kind]
    assert all(private not in str(result) for private in (TOKEN, "private-fixture@example.com", "secret.example.test", "details", "file_url", "built_basket_url", "map_url"))
    assert requests[-1].url.path == "/v2/" + kind
    if kind == "tickets": assert dict(requests[-1].url.params) == {"page[offset]": "0", "event": EVENT}
    field = next(name for name, resource in native.FIELDS.items() if resource == kind)
    transport(monkeypatch, {"data": record(kind)})
    result = await node({"operation": "get_" + field.removesuffix("_id"), field: IDS[kind], **({"event_id": EVENT} if kind == "tickets" else {})}).run({})
    assert result["status"] == "success" and result["item"]["id"] == IDS[kind]


@pytest.mark.asyncio
async def test_documented_filters_exact_spaces_plus_dates_and_provider_offset(monkeypatch):
    filters = {"filter[title]": "Yoga + café", "filter[from]": "20261006", "filter[to]": "20261007", "filter[compact]": "false"}
    requests, _ = transport(monkeypatch, page(next_offset=40, params=filters))
    result = await node({"operation": "list_events", "title": filters["filter[title]"], "from_time": "20261006", "to_time": "20261007", "compact": False}).run({})
    assert result["has_more"] and result["next_offset"] == 40 and result["complete"] is False
    assert dict(requests[0].url.params) == {"page[offset]": "0", **filters}
    assert "%20" in str(requests[0].url) and "%2B" in str(requests[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize("next_link", ["https://evil.example.test/v2/events?page[offset]=20", "https://api.bookwhen.com/v2/tickets?page[offset]=20", "/v2/events?page[offset]=0", "/v2/events?page[offset]=true", "/v2/events?page[offset]=20&filter[title]=other", "/v2/events?page[offset]=20&page[offset]=40", "/v2/events?page[offset]=20&include=leaders", None])
async def test_foreign_changed_stalled_malformed_paging_fails_without_follow(monkeypatch, next_link):
    body = page(); body["links"]["next"] = next_link
    requests, _ = transport(monkeypatch, body)
    result = await node({"operation": "list_events", "title": "owned"}).run({})
    assert result["status"] == "error" and len(requests) == 1 and "items" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": [], "links": {"next": "/v2/events?page[offset]=20"}}, {"data": [record(), record()], "links": {}}, {"data": [record("tickets")], "links": {}}, {"data": [], "errors": [{"detail": TOKEN}], "links": {}}])
async def test_incomplete_empty_next_duplicate_wrong_type_and_error_envelopes(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_events"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_tickets", "get_ticket"])
async def test_selected_event_relation_is_required_for_ticket_reads(monkeypatch, operation):
    foreign = record("tickets", relationships={"events": {"data": [{"type": "event", "id": "ev-other"}]}})
    transport(monkeypatch, {"data": foreign} if operation == "get_ticket" else page([foreign], kind="tickets"))
    result = await node({"operation": operation, "event_id": EVENT, **({"ticket_id": TICKET} if operation == "get_ticket" else {})}).run({})
    assert result["status"] == "error" and "item" not in result and "items" not in result


@pytest.mark.asyncio
async def test_fixed_related_include_graph_and_missing_ref_are_honest(monkeypatch):
    body = {"data": record(), "included": [record("tickets")]}
    requests, _ = transport(monkeypatch, body)
    result = await node({"operation": "get_event", "event_id": EVENT, "include_related": True}).run({})
    assert result["status"] == "success" and result["included_complete"] and result["included"][0]["id"] == TICKET
    assert requests[0].url.params["include"] == "location,attachments,tickets,tickets.class_passes"
    body["included"] = []
    assert (await node({"operation": "get_event", "event_id": EVENT, "include_related": True}).run({}))["included_complete"] is False
    body["included"] = [record("locations")]
    assert (await node({"operation": "get_event", "event_id": EVENT, "include_related": True}).run({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 302, 401, 403, 404, 429, 500])
async def test_non200_redirect_refusal_and_outage_not_completed(monkeypatch, status):
    requests, _ = transport(monkeypatch, lambda request: httpx.Response(status, json={"message": TOKEN}, headers={"Location": "https://evil.example.test/"}))
    result = await node({"operation": "check_connection"}).run({})
    assert result["status"] == "error" and result["http_status"] == status and TOKEN not in str(result) and len(requests) == 1


def test_schema_contract_defaults_hidden_token_parent_and_no_mutations():
    schema = native.BookwhenFullConfig.model_json_schema()
    golden = json.loads((Path(__file__).parent / "fixtures/bookwhen/native.json").read_text())
    mapping = schema["$defs"]["BookwhenCheckConfig"]["properties"]["operation"]["const"]
    assert mapping == "check_connection" and len(golden["operations"]) == 11
    assert schema["$defs"]["BookwhenAPITokenCredential"]["properties"]["api_token"]["ui:widget"] == "password"
    assert schema["$defs"]["BookwhenGetTicketConfig"]["properties"]["ticket_id"]["x-dynamic-options"]["depends_on"] == "event_id"
    assert "password" not in schema["$defs"]["BookwhenAPITokenCredential"]["properties"]
    for cfg in [{"operation": "list_events", "offset": True}, {"operation": "list_events", "from_time": "20260230"}, {"operation": "get_event", "event_id": "../other"}, {"operation": "list_tickets"}, {"operation": "list_events", "page_size": 20}, {"operation": "create_booking"}]:
        with pytest.raises((ValueError, ValidationError)): native.BookwhenNode.parse_config({"config": cfg, "credentials": credential()})
    with pytest.raises(ValidationError) as error: native.BookwhenAPITokenCredential.model_validate(credential(api_token=TOKEN + ":bad"))
    assert TOKEN not in str(error.value)

"""Sevdesk request, pagination, error and manual credential regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sevdesk_node as native
from nodes.core.registry import NodeFactory

TOKEN = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="sevdesk-test", node_type="automation-sevdesk",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN}})


def transport(monkeypatch, body=None, status=200, exception=None):
    requests = []

    def reply(request):
        requests.append(request)
        if exception:
            raise exception
        return httpx.Response(status, json={"objects": []} if body is None else body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_contacts"}, "GET", "/Contact"),
    ({"operation": "get_contact", "contact_id": 1}, "GET", "/Contact/1"),
    ({"operation": "create_contact", "name": "Example GmbH", "category_id": 3}, "POST", "/Contact"),
    ({"operation": "update_contact", "contact_id": 1, "first_name": "John"}, "PUT", "/Contact/1"),
    ({"operation": "delete_contact", "contact_id": 1}, "DELETE", "/Contact/1"),
    ({"operation": "list_parts"}, "GET", "/Part"),
    ({"operation": "get_part", "part_id": 1}, "GET", "/Part/1"),
    ({"operation": "create_part", "name": "Dragonglass", "part_number": "Part-1000", "tax_rate": 19, "unity_id": 1, "stock": 10000}, "POST", "/Part"),
    ({"operation": "update_part", "part_id": 1, "stock": 0}, "PUT", "/Part/1"),
    ({"operation": "list_invoices"}, "GET", "/Invoice"),
    ({"operation": "get_invoice", "invoice_id": 1}, "GET", "/Invoice/1"),
    ({"operation": "list_invoice_positions", "invoice_id": 1}, "GET", "/Invoice/1/getPositions"),
    ({"operation": "list_orders"}, "GET", "/Order"),
    ({"operation": "get_order", "order_id": 1}, "GET", "/Order/1"),
    ({"operation": "list_vouchers"}, "GET", "/Voucher"),
    ({"operation": "get_voucher", "voucher_id": 1}, "GET", "/Voucher/1"),
    ({"operation": "list_check_accounts"}, "GET", "/CheckAccount"),
    ({"operation": "get_check_account", "check_account_id": 1}, "GET", "/CheckAccount/1"),
    ({"operation": "list_tags"}, "GET", "/Tag"),
    ({"operation": "get_tag", "tag_id": 1}, "GET", "/Tag/1"),
    ({"operation": "create_tag", "name": "Paid", "object_id": 1, "object_name": "Invoice"}, "POST", "/Tag/Factory/create"),
    ({"operation": "update_tag", "tag_id": 1, "name": "Paid"}, "PUT", "/Tag/1"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES)
async def test_one_request_per_operation(monkeypatch, config, method, path):
    requests = transport(monkeypatch)
    result = await node(config).execute({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith(native.BASE_URL + path)
    assert request.url.path == "/api/v1" + path
    assert request.headers["Authorization"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    assert request.headers["User-Agent"] == "NoClick Sevdesk integration"
    if method != "GET":
        assert result["readback_verified"] is False
        assert result["write_acknowledged"] is True
    if config["operation"] == "create_part":
        assert json.loads(request.content) == {"name": "Dragonglass", "partNumber": "Part-1000", "taxRate": 19, "unity": {"id": 1, "objectName": "Unity"}, "stock": 10000.0}
    if config["operation"] == "update_part":
        assert json.loads(request.content) == {"stock": 0.0}
    if config["operation"] == "create_contact":
        assert json.loads(request.content) == {"name": "Example GmbH", "category": {"id": 3, "objectName": "Category"}}
    if config["operation"] == "update_contact":
        assert json.loads(request.content) == {"surename": "John"}
    if config["operation"] == "create_tag":
        assert json.loads(request.content) == {"name": "Paid", "object": {"id": 1, "objectName": "Invoice"}}


@pytest.mark.asyncio
async def test_paging_and_contact_filter_pair(monkeypatch):
    requests = transport(monkeypatch, {"objects": [{"id": "2"}, {"id": "3"}], "total": "157"})
    result = await node({"operation": "list_invoices", "limit": 2, "offset": 10,
        "contact_id": 9, "status": 200, "invoice_number": "RE + 1", "start_date": 1700000000}).execute({})
    assert dict(requests[0].url.params) == {"limit": "2", "offset": "10", "contact[id]": "9",
        "contact[objectName]": "Contact", "status": "200", "invoiceNumber": "RE + 1", "startDate": "1700000000"}
    assert result["next_offset"] == 12 and result["has_more"] is True
    transport(monkeypatch)
    result = await node({"operation": "list_contacts"}).execute({})
    assert result["has_more"] is False and result["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 429, 500, 503])
async def test_provider_rejection_and_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_contacts"}).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert TOKEN not in str(result)
    assert "Rejected" in result["message"]
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"objects": {}}, {"objects": [None]}, {"objects": [], "error": "no access"}, []])
async def test_malformed_lists_fail(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_contacts"}).execute({})
    assert not result["success"]


@pytest.mark.asyncio
async def test_write_timeout_unknown_and_never_retried(monkeypatch):
    requests = transport(monkeypatch, exception=httpx.ReadTimeout("private " + TOKEN))
    result = await node({"operation": "update_contact", "contact_id": 1, "name": "Changed"}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified"
    assert TOKEN not in str(result) and len(requests) == 1


def test_manual_credential_default_and_shaping():
    credential = native.SevdeskAPITokenCredential(api_token="  " + TOKEN + "\n")
    assert credential.credential_type == "sevdesk_api_token"
    assert credential.api_token == TOKEN
    assert set(native.SevdeskAPITokenCredential.model_fields) == {"credential_type", "api_token"}


@pytest.mark.parametrize("value", ["https://example.com/token", "<token>", "Bearer abc", "a\nb", "ａｂｃ"])
def test_reject_bad_pasted_token(value):
    with pytest.raises(ValidationError):
        native.SevdeskAPITokenCredential(api_token=value)


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../Invoice"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "list_contacts", "offset": -1},
    {"operation": "list_contacts", "limit": 1001},
    {"operation": "update_contact", "contact_id": 1},
    {"operation": "update_part", "part_id": 1},
    {"operation": "create_contact", "category_id": 3},
    {"operation": "list_invoices", "start_date": 100, "end_date": 90},
    {"operation": "list_contacts", "base_url": "https://evil.test"},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_foreign_credential_family_refused():
    with pytest.raises(ValueError, match="Sevdesk"):
        node({"operation": "list_contacts"}, {"credential_type": "other_api_token", "api_token": TOKEN})


@pytest.mark.asyncio
async def test_provider_documented_part_fields(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/sevdesk/part_creation.json").read_text())
    requests = transport(monkeypatch, {"id": 1, **fixture["body"]}, status=201)
    result = await node(fixture["config"]).execute({})
    assert result["success"]
    assert json.loads(requests[0].content) == fixture["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reachable", [(401, False), (403, False), (500, None)])
async def test_connection_evidence_uses_http_rejection_status(monkeypatch, status, reachable):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"message": "The request was rejected"}, status)

    async def run(**kwargs):
        assert kwargs["operation"] == "list_contacts"
        return await node({"operation": kwargs["operation"]}).execute({})

    monkeypatch.setattr(run_op, "run_node_operation", run)
    result = await collect_evidence(node_type="automation-sevdesk", user_id="fixture",
        credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN})
    assert result.reachable is reachable


# Published response-property examples from Model_InvoiceResponse and
# Model_VoucherResponse, including the provider's differently formatted revisions.
POLL_EXAMPLES = json.loads((Path(__file__).parent / "fixtures/sevdesk/poll_responses.json").read_text())


def poll_state(instance, monkeypatch, initial=None):
    state = {} if initial is None else dict(initial)

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(instance, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["Contact", "Invoice", "Order", "Voucher"])
async def test_poll_routes_config_and_scope(monkeypatch, resource):
    from nodes.core.poll_trigger import poll_scope
    operation = "on_new_or_updated_" + resource.lower()
    config = {"operation": operation, "updated_after": 0}
    instance = node(config)
    requests = transport(monkeypatch)
    poll_state(instance, monkeypatch)
    result = await instance.execute({})
    assert result["objects"] == []
    assert instance.trigger_produced_no_event(result)
    assert requests[0].url.path == "/api/v1/" + resource
    expected = {"limit": "1000", "offset": "0", "updateAfter": "0"}
    if resource == "Contact":
        expected["depth"] = "1"
    assert dict(requests[0].url.params) == expected
    assert poll_scope(native.SevdeskNode, config) == poll_scope(native.SevdeskNode, {**config, "label": "Changed"})
    assert poll_scope(native.SevdeskNode, config) != poll_scope(native.SevdeskNode, {**config, "updated_after": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["Invoice", "Voucher"])
async def test_poll_baseline_new_revision_and_agent_event(monkeypatch, resource):
    body = POLL_EXAMPLES[resource]["body"]
    original = body["objects"][0]
    operation = "on_new_or_updated_" + resource.lower()
    instance = node({"operation": operation})
    state = poll_state(instance, monkeypatch)
    transport(monkeypatch, body)
    assert (await instance.execute({}))["objects"] == []  # Baseline never emits history.
    assert state["seen_ids"]
    assert (await instance.execute({}))["objects"] == []
    # A prior empty baseline sees the documented record as new.
    state["seen_ids"] = []
    result = await instance.execute({})
    assert result["objects"] == [original]
    event = native.SevdeskNode.resolve_agent_event(result)
    assert "id " + original["id"] in event["text"]
    assert original["update"] in event["text"]
    assert resource.lower() in event["text"]
    assert instance.trigger_emitted_event(result)
    assert (await instance.execute({}))["objects"] == []
    # Simulate an older revision of the same ID, then feed the documented current revision.
    state["seen_ids"] = [json.dumps([original["id"], "older revision"])]
    assert (await instance.execute({}))["objects"] == [original]
    assert native.SevdeskNode.resolve_agent_event({"resource": resource, "objects": []}) is None
    # Repointing the declared filter baselines again.
    instance.config.config.updated_after = 1
    assert (await instance.execute({}))["objects"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"objects": [{}]}, 200), ({"error": "rejected"}, 200), ({"objects": []}, 401)])
async def test_poll_failure_does_not_consume_state(monkeypatch, body, status):
    instance = node({"operation": "on_new_or_updated_invoice"})
    state = poll_state(instance, monkeypatch)
    transport(monkeypatch, body, status)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await instance.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_poll_paginates_before_marking_seen(monkeypatch):
    body = POLL_EXAMPLES["Invoice"]["body"]
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"objects": body["objects"] * 1000 if len(requests) == 1 else []})

    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    instance = node({"operation": "on_new_or_updated_invoice"})
    poll_state(instance, monkeypatch, {"seen_ids": []})
    result = await instance.execute({})
    assert [r.url.params["offset"] for r in requests] == ["0", "1000"]
    assert result["objects"] == body["objects"]

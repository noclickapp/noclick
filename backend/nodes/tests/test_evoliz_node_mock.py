"""HTTP-boundary tests; synthetic account keys, published schema examples.

No live account, registration, email delivery or financial write is performed.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import evoliz_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / "fixtures" / "evoliz"
CREDENTIAL = {"credential_type": native.CREDENTIAL, "public_key": "synthetic-public-key", "secret_key": "synthetic-secret-key", "companyid": 2}
CLIENT = {"name": "Synthetic client", "type": "Particulier", "address": {"postcode": "75001", "town": "Paris", "iso2": "FR"}}
DOCUMENT = {"clientid": 9876, "documentdate": "2025-10-10", "term": {"paytermid": 3},
            "items": [{"designation": "Banana Split", "quantity": 12.5, "unit_price": 28.25, "vat_rate": 5.5}]}
EMAIL = {"to": ["recipient@example.com"], "subject": "Here is your Document", "body": "Here is your document"}
CONFIGS = {
    "create_client": CLIENT, "update_client": {"clientid": 9876, "name": "Updated client"},
    "create_article": {k: v for k, v in json.loads((FIXTURES / "article.json").read_text())["body"].items()
                       if k in native.ArticleCreate.model_fields},
    "update_article": {"articleid": 12345, "designation": "Updated article", "unit_price": 36},
    "create_invoice": DOCUMENT, "create_quote": DOCUMENT,
    "update_invoice_template": {"invoiceid": 2476128, "templateid": 25},
    "send_invoice": {"invoiceid": 2476128, **EMAIL}, "send_quote": {"quoteid": 2476128, **EMAIL},
    "create_invoice_payment": {"invoiceid": 2476128, "paydate": "2025-10-10", "label": "Règlement client", "paytypeid": 4, "amount": 537.71},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture(autouse=True)
def clear_cache():
    native._TOKENS.clear()
    native._LOCKS.clear()
    yield
    native._TOKENS.clear()
    native._LOCKS.clear()


def node(config, credential=None):
    return NodeFactory.create_node(node_id="evoliz-test", node_type="automation-evoliz",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, reply=None):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == "/api/login":
            assert json.loads(request.content) == {k: CREDENTIAL[k] for k in ("public_key", "secret_key")}
            return httpx.Response(200, json={"access_token": "synthetic-access-token", "expires_at":
                (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()})
        assert request.headers["authorization"] == "Bearer synthetic-access-token"
        return reply(request) if reply else httpx.Response(200, json={"companyid": 2, "name": "Synthetic Company"})
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.OPERATIONS)
async def test_evoliz_action_wire_contract(monkeypatch, operation):
    method, route, _ = native.OPERATIONS[operation]
    config = {"operation": operation, **copy.deepcopy(CONFIGS.get(operation, {}))}
    for identifier in ("clientid", "articleid", "invoiceid", "quoteid", "paymentid"):
        if "{" + identifier + "}" in route:
            config.setdefault(identifier, 9876)
            route = route.replace("{" + identifier + "}", str(config[identifier]))
    requests = transport(monkeypatch)
    output = await node(config).execute({})
    assert output["operation"] == operation
    assert requests[-1].method == method
    assert requests[-1].url.path == "/api/v1/companies/2" + route
    if method == "GET":
        assert not json.loads(requests[-1].content or b"null")
        if operation.startswith("list_"):
            assert dict(requests[-1].url.params) == {"page": "1", "per_page": "100"}
    else:
        body = json.loads(requests[-1].content)
        assert "operation" not in body
        assert "invoiceid" not in body
        if operation in {"create_invoice", "create_quote"}:
            assert body["items"][0]["unit_price"] == 28.25
            assert body["term"] == {"paytermid": 3}
        if operation.startswith("send_"):
            assert body["to"] == EMAIL["to"]
            assert body["body"] == EMAIL["body"]


@pytest.mark.asyncio
async def test_evoliz_reuses_token_and_keeps_accounts_separate(monkeypatch):
    requests = transport(monkeypatch)
    await node({"operation": "get_company"}).execute({})
    await node({"operation": "list_clients", "page": 2}).execute({})
    assert sum(r.url.path == "/api/login" for r in requests) == 1
    other = native.EvolizAPIKeysCredential(**{**CREDENTIAL, "secret_key": "another-secret-key"})
    assert native._cache_key(other) != native._cache_key(native.EvolizAPIKeysCredential(**CREDENTIAL))
    assert dict(requests[-1].url.params)["page"] == "2"


@pytest.mark.asyncio
async def test_evoliz_rejection_is_redacted_and_write_not_retried(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(429, json={"message": "Limit synthetic-secret-key synthetic-access-token"}))
    with pytest.raises(native.EvolizError, match=r"Limit \[redacted\] \[redacted\]"):
        await node({"operation": "create_client", **CLIENT}).execute({})
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 422, 500])
async def test_evoliz_never_reports_failed_request_as_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"message": "Provider rejected request"}))
    with pytest.raises(native.EvolizError, match="Provider rejected request"):
        await node({"operation": "get_company"}).execute({})
    assert len(requests) == 2


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "clientid": "../invoices"},
    {"operation": "get_client", "clientid": 0},
    {"operation": "create_client", "name": "Missing address"},
    {"operation": "create_invoice", **{**DOCUMENT, "term": {"paytermid": 18}}},
    {"operation": "create_invoice_payment", "invoiceid": 1, "paydate": "2025-10-10", "label": "Credit", "paytypeid": 13, "amount": 10},
    {"operation": "send_invoice", "invoiceid": 1, **{**EMAIL, "to": ["not an email"]}},
])
def test_evoliz_rejects_invalid_inputs(config):
    with pytest.raises(ValueError):
        native.EvolizNode.parse_config({"config": config})


def test_evoliz_credential_is_manual_and_uses_default_type():
    credential = native.EvolizAPIKeysCredential(**{k:v for k,v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == native.CREDENTIAL
    assert native.EvolizAPIKeysCredential.model_fields["companyid"].is_required()
    with pytest.raises(ValidationError):
        native.EvolizAPIKeysCredential(**{**CREDENTIAL, "secret_key": "https://bad.example/key"})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.TRIGGERS)
async def test_evoliz_poll_uses_documented_events_baseline_dedup_pagination_and_agent(monkeypatch, operation):
    event = json.loads((FIXTURES / "event.json").read_text())["body"]
    rows = [event]
    def reply(request):
        assert request.url.params["element_type"] == native.TRIGGERS[operation]
        assert request.url.params["period"] == "custom"
        assert "date_min" in request.url.params and "date_max" in request.url.params
        return httpx.Response(200, json={"data": rows, "meta": {"last_page": 1}})
    transport(monkeypatch, reply)
    instance = node({"operation": operation})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        change, result = mutator(copy.deepcopy(state))
        if change is not None:
            state = change
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    assert (await instance.execute({}))["event_count"] == 0
    assert instance.trigger_produced_no_event({})
    rows.append({**event, "eventid": event["eventid"] + 1})
    output = await instance.execute({})
    assert output["event_count"] == 1
    assert instance.trigger_emitted_event(output)
    text = native.EvolizNode.resolve_agent_event(output)["text"]
    assert str(event["userid"]) in text and str(event["linked_element"]["id"]) in text
    assert str(event["eventid"] + 1) in text
    assert (await instance.execute({}))["event_count"] == 0
    assert poll_scope(native.EvolizNode, {"operation": operation, "lookback_hours": 24}) != poll_scope(native.EvolizNode, {"operation": operation, "lookback_hours": 48})
    assert poll_scope(native.EvolizNode, {"operation": operation, "label": "A"}) == poll_scope(native.EvolizNode, {"operation": operation, "label": "B"})


@pytest.mark.asyncio
async def test_evoliz_poll_pages_before_consuming_and_refuses_incomplete_window(monkeypatch):
    event = json.loads((FIXTURES / "event.json").read_text())["body"]
    pages = []
    def reply(request):
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"data": [{**event, "eventid": page}], "meta": {"last_page": 2}})
    transport(monkeypatch, reply)
    instance = node({"operation": "on_invoice_event"})
    async def unseen(events, id_fn):
        assert [id_fn(e) for e in events] == ["1", "2"]
        return events
    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    assert (await instance.execute({}))["event_count"] == 2
    assert pages == [1, 2]
    transport(monkeypatch, lambda _: httpx.Response(200, json={"data": [event]}))
    with pytest.raises(native.EvolizError, match="pagination is missing"):
        await instance.execute({})


@pytest.mark.asyncio
async def test_evoliz_company_evidence_names_account(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    transport(monkeypatch)
    async def run(**kwargs):
        assert kwargs["operation"] == "get_company"
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-evoliz", user_id="evoliz-test", credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert evidence.account_label == "Synthetic Company"

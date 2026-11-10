"""Qonto request-contract tests; all credentials and resources are synthetic."""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import qonto_node as native
from nodes.core.registry import NodeFactory

ID = "7b7a5ed6-3903-4782-889d-b4f64bd7bef9"
CREDENTIAL = {"credential_type": "qonto_api_key", "login": "pied-piper-7132", "secret_key": "synthetic-qonto-secret"}


def node(config):
    return NodeFactory.create_node(node_id="qonto-test", node_type="automation-qonto",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, body, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_auth_and_identity_evidence(monkeypatch):
    requests = mock(monkeypatch, {"organization": {"id": ID, "name": "Pied Piper", "bank_accounts": []}})
    result = await node({"operation": "get_organization"}).execute({})
    assert result["data"]["organization"]["name"] == "Pied Piper"
    assert requests[0].headers["Authorization"] == "pied-piper-7132:synthetic-qonto-secret"
    assert requests[0].url.host == "thirdparty.qonto.com"
    assert native.QontoNode.connection_evidence.identity_operation == "get_organization"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,id_field,path", [
    ("get_transaction", "transaction_id", "transactions"),
    ("get_beneficiary", "beneficiary_id", "sepa/beneficiaries"),
    ("get_supplier_invoice", "supplier_invoice_id", "supplier_invoices"),
    ("get_client", "client_id", "clients"),
    ("get_product", "product_id", "products"),
    ("get_client_invoice", "client_invoice_id", "client_invoices"),
])
async def test_detail_routes(monkeypatch, operation, id_field, path):
    requests = mock(monkeypatch, {"id": ID})
    result = await node({"operation": operation, id_field: ID}).execute({})
    assert result["status"] == "success"
    assert requests[0].method == "GET" and requests[0].url.path == "/v2/" + path + "/" + ID
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_transaction_filters_and_single_page_continuation(monkeypatch):
    requests = mock(monkeypatch, {"transactions": [], "meta": {"next_page": 3}})
    result = await node({"operation": "list_transactions", "bank_account_id": ID,
        "statuses": ["completed", "pending"], "page": 2, "per_page": 25, "with_attachments": False}).execute({})
    assert requests[0].url.params.get_list("status[]") == ["completed", "pending"]
    assert requests[0].url.params["with_attachments"] == "false"
    assert requests[0].url.params["page"] == "2"
    assert result["next_page"] == 3 and result["has_more"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("config,expected", [
    ({"operation": "list_clients", "name": "Pied + Piper", "email": "a@example.com"}, {"filter[name]": "Pied + Piper", "filter[email]": "a@example.com"}),
    ({"operation": "list_client_invoices", "statuses": ["draft", "unpaid"]}, {"filter[status]": "draft,unpaid", "exclude_imported": "true"}),
    ({"operation": "list_products", "product_type": "service"}, {"filter[type]": "service"}),
    ({"operation": "list_supplier_invoices", "status": "paid"}, {"filter[status]": "paid"}),
])
async def test_documented_filter_serialization(monkeypatch, config, expected):
    requests = mock(monkeypatch, {"meta": {"next_page": None}})
    await node(config).execute({})
    for key, value in expected.items(): assert requests[0].url.params[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body,status,path", [
    ({"operation": "create_client", "kind": "company", "name": "Pied Piper"}, {"kind": "company", "name": "Pied Piper"}, 200, "/v2/clients"),
    ({"operation": "update_client", "client_id": ID, "name": "New Name"}, {"name": "New Name"}, 200, "/v2/clients/" + ID),
    ({"operation": "create_product", "title": "Service", "product_type": "service", "unit_price_value": "150.00", "currency": "EUR", "vat_rate": "0.2"}, {"title": "Service", "type": "service", "unit_price": {"value": "150.00", "currency": "EUR"}, "vat_rate": "0.2"}, 201, "/v2/products"),
    ({"operation": "mark_supplier_invoice_as_paid", "supplier_invoice_id": ID, "payment_date": "2026-01-01"}, {"supplier_invoice": {"payment_date": "2026-01-01"}}, 200, "/v2/supplier_invoices/" + ID + "/mark_as_paid"),
])
async def test_mutations_use_exact_bodies(monkeypatch, config, body, status, path):
    requests = mock(monkeypatch, {"id": ID}, status)
    assert (await node(config).execute({}))["status"] == "success"
    assert json.loads(requests[0].content) == body and requests[0].url.path == path
    assert not requests[0].url.query and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["client", "product"])
async def test_empty_delete_success(monkeypatch, resource):
    requests = mock(monkeypatch, None, 204)
    assert (await node({"operation": "delete_" + resource, resource + "_id": ID}).execute({}))["deleted"]
    assert requests[0].method == "DELETE"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_errors_are_not_success_and_do_not_leak_secret(monkeypatch, status):
    requests = mock(monkeypatch, {"errors": [{"detail": CREDENTIAL["secret_key"] + " rejected"}]}, status)
    result = await node({"operation": "list_clients"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "rejected" in result["error"] and CREDENTIAL["secret_key"] not in str(result)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "client_id": "../evil"},
    {"operation": "create_client", "kind": "individual"},
    {"operation": "update_client", "client_id": ID},
    {"operation": "list_transactions", "page": 101},
    {"operation": "create_product", "title": "x", "product_type": "service", "unit_price_value": "-1", "currency": "EUR", "vat_rate": "0.2"},
])
def test_invalid_configs_refused(config):
    with pytest.raises((ValidationError, ValueError)): node(config)


def test_manual_credential_default_and_header_injection_refused():
    assert native.QontoAPIKeyCredential(login="pied-piper", secret_key="synthetic-secret").credential_type == "qonto_api_key"
    for bad in ["secret\r\nX-Evil: yes", "Bearer abc", "login:secret"]:
        with pytest.raises(ValidationError): native.QontoAPIKeyCredential(login="pied-piper", secret_key=bad)


@pytest.mark.asyncio
async def test_provider_transaction_example(monkeypatch):
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/qonto/transaction.json").read_text())
    mock(monkeypatch, fixture["body"])
    result = await node({"operation": "get_transaction", "transaction_id": ID}).execute({})
    assert result["data"]["transaction"]["amount_cents"] == 5240
    assert result["data"]["transaction"]["id"] == ID


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["labels", "memberships", "beneficiaries", "statements"])
async def test_remaining_list_routes(monkeypatch, resource):
    requests = mock(monkeypatch, {resource: [], "meta": {"next_page": None}})
    result = await node({"operation": "list_" + resource}).execute({})
    path = "sepa/beneficiaries" if resource == "beneficiaries" else resource
    assert requests[0].method == "GET" and requests[0].url.path == "/v2/" + path
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_unmark_does_not_send_a_paid_date_or_retry(monkeypatch):
    requests = mock(monkeypatch, {"id": ID, "status": "to_review", "payment_date": None})
    result = await node({"operation": "unmark_supplier_invoice_as_paid", "supplier_invoice_id": ID}).execute({})
    assert result["status"] == "success" and len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v2/supplier_invoices/" + ID + "/unmark_as_paid"
    assert requests[0].content == b""


def test_qonto_fixture_has_no_embedded_storage_credentials():
    import re
    from pathlib import Path
    from urllib.parse import urlsplit

    fixture_path = Path(__file__).parent / "fixtures/qonto/transaction.json"
    contents = fixture_path.read_bytes()
    assert not re.search(rb"AKIA[0-9A-Z]{16}", contents)
    fixture = json.loads(contents)
    assert fixture["sanitization"]
    for attachment in fixture["body"]["transaction"]["attachments"]:
        url = urlsplit(attachment["url"])
        assert url.scheme == "https" and url.hostname == "example.invalid"
        assert not url.query


def webhook_examples():
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures/qonto/webhooks.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,event_type', list(native.WEBHOOK_TYPES.items()))
async def test_webhook_registration_and_teardown(monkeypatch, operation, event_type):
    # The registration schema is a flat subscription with a one-time secret.
    from nodes.oauth.qonto_oauth import OAUTH_PROVIDER
    secret = 'whsec_VuvcYxzMbryt1UBytq58jtGBxCgbQdzX/c0vj5ZLjUA='
    requests = mock(monkeypatch, {'id': '123e4567-e89b-12d3-a456-426614174000', 'secret': secret}, 201)
    credential = {'credential_type': 'qonto_oauth', 'access_token': 'synthetic-oauth-token'}
    state = await native.QontoNode._register_external_webhook(webhook_url='https://api.partner.com/webhooks/qonto',
        credential=credential, config={'operation': operation}, node_id='test')
    assert json.loads(requests[0].content) == {'callback_url': 'https://api.partner.com/webhooks/qonto', 'types': [event_type]}
    assert requests[0].headers['Authorization'] == 'Bearer synthetic-oauth-token'
    assert state == {'external_webhook_id': '123e4567-e89b-12d3-a456-426614174000', 'signing_secret': secret}
    parsed = native.QontoFullConfig.model_validate({'config': {'operation': operation, **state}, 'credentials': credential})
    assert parsed.config.signing_secret == secret
    assert parsed.config.model_dump()['external_webhook_id'] == state['external_webhook_id']
    requests = mock(monkeypatch, None, 204)
    await native.QontoNode._unregister_external_webhook(credential=credential, config=state, node_id='test')
    assert requests[0].method == 'DELETE'
    assert requests[0].url.path == '/v2/webhook_subscriptions/' + state['external_webhook_id']
    assert OAUTH_PROVIDER.identity_url == native.BASE + '/v2/organization'
    assert OAUTH_PROVIDER.token_auth == 'body' and OAUTH_PROVIDER.rotates_refresh_tokens


@pytest.mark.asyncio
async def test_api_key_cannot_register_webhooks(monkeypatch):
    requests = mock(monkeypatch, {})
    with pytest.raises(ValueError, match='OAuth'):
        await native.QontoNode._register_external_webhook(webhook_url='https://api.partner.com/webhooks/qonto',
            credential=CREDENTIAL, config={'operation': 'on_transaction'}, node_id='test')
    assert not requests


def test_documented_signature_vector_and_tampering():
    # https://docs.qonto.com/guides/webhooks/setup
    body = b'{"test":"data"}'
    header = 't=1704110400,v1=56aff06dc227db80d6568a5070f912c601c31f20451745d257cbc0b5dfa93805'
    verify = native.QontoNode.verify_webhook_signature
    config = {'signing_secret': 'test-secret'}
    assert verify(body, {'X-Qonto-Signature': header}, config)
    assert not verify(body + b' ', {'X-Qonto-Signature': header}, config)
    assert not verify(body, {'X-Qonto-Signature': header}, {'signing_secret': 'different'})
    for bad in ['', 'v1=abc', 't=x,v1=abc', 't=1,t=2,v1=abc', 't=1,v1=☃', 't=1,broken']:
        assert not verify(body, {'X-Qonto-Signature': bad}, config)
    assert not verify(body, {'X-Qonto-Signature': header}, {})


@pytest.mark.parametrize('operation,event_type', list(native.WEBHOOK_TYPES.items()))
def test_documented_events_reach_workflows_and_agents(operation, event_type):
    body = webhook_examples()[event_type]['body']
    cls = native.QontoNode
    config = {'operation': operation}
    assert cls.filter_trigger_payload(body, config)
    output = cls.resolve_trigger_payload(body, config)
    event = cls.resolve_agent_event(output)
    assert body['data']['id'] in event['text']
    assert body['organization_id'] in event['text']
    assert event['conversation_key'].endswith(body['data']['id'])
    if operation == 'on_transaction':
        assert 'ACME Corp' in event['text'] and 'Business lunch' in event['text']
        assert 'get_transaction transaction_id=' in event['text']
    else:
        assert "McDonald's" in event['text'] and 'paid' in event['text']
        assert 'get_client_invoice client_invoice_id=' in event['text']
    other = 'on_client_invoice' if operation == 'on_transaction' else 'on_transaction'
    assert not cls.filter_trigger_payload(body, {'operation': other})
    assert not cls.filter_trigger_payload({'type': event_type, 'data': {}}, config)


@pytest.mark.asyncio
async def test_oauth_action_transport(monkeypatch):
    from nodes.core import oauth_refresh
    async def fresh(**kwargs):
        return kwargs['credential']['access_token']
    monkeypatch.setattr(oauth_refresh, 'ensure_fresh_oauth_token', fresh)
    requests = mock(monkeypatch, {'organization': {'id': ID, 'name': 'Pied Piper'}})
    instance = NodeFactory.create_node(node_id='qonto-test', node_type='automation-qonto',
        node_data={'config': {'operation': 'get_organization'},
            'credentials': {'credential_type': 'qonto_oauth', 'access_token': 'synthetic-oauth-token'}})
    assert (await instance.execute({}))['status'] == 'success'
    assert requests[0].headers['Authorization'] == 'Bearer synthetic-oauth-token'

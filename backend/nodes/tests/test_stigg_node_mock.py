"""Stigg factory, fixed GraphQL documents, parsing and error contracts."""
from datetime import datetime, timezone
import ipaddress
import json
import logging
from types import SimpleNamespace
from uuid import UUID
import httpx
import pytest
from nodes import stigg_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

NODE, FAMILY = native.NODE_TYPE, "stigg_server_api_key"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
CREDS = {"credential_type": FAMILY, "api_key": "server-offline-stigg-fixture-42", "validation_customer_id": "customer-1"}
OPS = {"get_customer", "provision_customer", "update_customer", "list_products", "get_paywall",
    "get_entitlements", "get_entitlement", "list_active_subscriptions", "get_active_subscription"}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], status=None, raw=None, media=None, target=None,
        timeout=False, after_response=None, empty=False, private_dns=False, name="Fixture customer")
    original_dns, original_client = ssrf._resolve_host_addresses, ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert kwargs.get("permit_non_public", False) is False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            assert host == "api.stigg.io"
            return await original_dns("127.0.0.1", port, **kwargs) if state.private_dns else ["93.184.216.34"]
        return await original_dns(host, port, **kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    async def respond(request):
        assert request.method == "POST" and str(request.url) == native.API_URL
        assert request.headers["x-api-key"] == CREDS["api_key"]
        assert CREDS["api_key"] not in str(request.url) + request.content.decode()
        body = json.loads(request.content)
        operation, variables = body["operationName"], body["variables"]
        assert set(body) == {"operationName", "query", "variables"}
        assert body["query"] in {document for _, document, _ in native._DOCUMENTS.values()}
        assert request.headers["x-graphql-operation-name"] == operation
        assert all("environmentId" not in value for value in variables.values())
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private " + CREDS["api_key"], request=request)
        customer = {"refId": "customer-1", "name": state.name, "createdAt": UPDATED.isoformat(),
            "email": "private@example.invalid", "additionalMetaData": {"private": "private"}, "billingId": "private"}
        product = {"refId": "product-1", "displayName": "Fixture product", "additionalMetaData": "private"}
        entitlement = {"customerId": "customer-1", "resourceId": None, "isGranted": False,
            "hasUnlimitedUsage": False, "hasSoftLimit": False, "currentUsage": 0, "usageLimit": 0,
            "requestedUsage": 0, "feature": {"refId": "feature-1", "displayName": "Fixture feature",
                "featureType": "BOOLEAN", "meterType": None}, "private": "private"}
        subscription = {"subscriptionId": "subscription-1", "status": "ACTIVE",
            "customer": {"customerId": "customer-1", "email": "private@example.invalid"}, "resource": None,
            "plan": {"refId": "plan-1", "displayName": "Fixture plan", "product": product},
            "billingLinkUrl": "private", "totalPrice": {"private": "private"}}
        if operation == "GetCustomerById":
            assert variables == {"input": {"customerId": "customer-1"}}
            raw = {"getCustomerByRefId": customer}
        elif operation == "ProvisionCustomer":
            assert variables == {"input": {"refId": "customer-1", "name": "Fixture customer", "subscriptionParams": None}}
            raw = {"provisionCustomer": {"customer": customer, "subscription": None, "subscriptionDecisionStrategy": "NONE"}}
        elif operation == "UpdateCustomer":
            assert variables == {"input": {"refId": "customer-1", "name": "Updated customer"}}
            state.name = "Updated customer"
            raw = {"updateCustomer": {**customer, "name": state.name}}
        elif operation == "GetProducts":
            assert variables == {}
            raw = {"products": {"edges": [] if state.empty else [{"node": product}]}}
        elif operation == "GetPaywall":
            assert variables == {"input": {"productId": "product-1", "customerId": "customer-1"}}
            raw = {"paywall": {"plans": [] if state.empty else [{"refId": "plan-1", "displayName": "Fixture plan",
                "product": product, "versionNumber": 0, "hiddenFromWidgets": False,
                "compatibleAddons": [{"refId": "addon-1", "displayName": "Fixture add-on", "hiddenFromWidgets": False}],
                "prices": "private"}], "customer": {"email": "private@example.invalid"}, "configuration": "private"}}
        elif operation == "GetEntitlements":
            assert variables == {"query": {"customerId": "customer-1"}}
            raw = {"entitlements": [] if state.empty else [entitlement]}
        elif operation == "GetEntitlement":
            assert variables == {"query": {"customerId": "customer-1", "featureId": "feature-1", "options": {"requestedUsage": 0.0}}}
            raw = {"entitlement": entitlement}
        elif operation == "GetActiveSubscriptionsList":
            assert variables == {"input": {"customerId": "customer-1"}}
            raw = {"getActiveSubscriptions": [] if state.empty else [subscription]}
        elif operation == "GetSubscription":
            assert variables == {"input": {"subscriptionId": "subscription-1"}}
            raw = {"getSubscription": subscription}
        else:
            raise AssertionError("Unexpected native GraphQL document")
        content = json.dumps({"data": raw}).encode()
        headers, status = {"content-type": "application/json"}, 200
        if state.target is None or state.target == operation:
            if state.raw is not None: content = state.raw
            if state.media: headers["content-type"] = state.media
            if state.status: status = state.status
            if state.after_response: state.after_response()
        return httpx.Response(status, content=content, headers=headers, request=request)
    def guarded(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 20.0}
        return original_client(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", guarded)
    return state

async def run(op, args=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {}, user_id=USER,
        credential_data=kwargs.pop("credential_data", CREDS), **kwargs)

CASES = [
    ("get_customer", {}, "GetCustomerById"),
    ("provision_customer", {"customer_id": "customer-1", "name": "Fixture customer"}, "ProvisionCustomer"),
    ("update_customer", {"customer_id": "customer-1", "name": "Updated customer"}, "UpdateCustomer"),
    ("list_products", {}, "GetProducts"),
    ("get_paywall", {"product_id": "product-1", "customer_id": "customer-1"}, "GetPaywall"),
    ("get_entitlements", {"customer_id": "customer-1"}, "GetEntitlements"),
    ("get_entitlement", {"customer_id": "customer-1", "feature_id": "feature-1", "requested_usage": 0.0}, "GetEntitlement"),
    ("list_active_subscriptions", {"customer_id": "customer-1"}, "GetActiveSubscriptionsList"),
    ("get_active_subscription", {"customer_id": "customer-1", "subscription_id": "subscription-1"}, "GetSubscription"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,document", CASES)
async def test_actual_factory_dispatches_only_fixed_native_documents(provider, operation, arguments, document):
    assert NODE_REGISTRY[NODE] is native.StiggNode
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] is not None
    assert document in [json.loads(request.content)["operationName"] for request in provider.requests]
    assert "private" not in json.dumps(result) and CREDS["api_key"] not in json.dumps(result)
    if operation in {"provision_customer", "update_customer"}:
        assert result["data"]["readback_verified"] is True
    if operation == "get_entitlement":
        assert result["data"]["isGranted"] is False and result["data"]["currentUsage"] == 0
    if operation == "get_paywall":
        assert result["data"]["items"][0]["hiddenFromWidgets"] is False
        assert result["data"]["items"][0]["versionNumber"] == 0

def test_actual_catalog_factory_and_native_schema_scope():
    from coder.workflow.operation_catalog import get_operations_for_node_type
    operations = get_operations_for_node_type(NODE)
    assert {operation.name for operation in operations} == OPS
    assert not any(operation.is_trigger for operation in operations)
    instance = NodeFactory.create_node(node_id="fixture", node_type=NODE,
        node_data={"config": {"operation": "get_customer"}, "credentials": CREDS},
        sio=None, sid=None, workflow_id=None, user_id=USER, conversation_id=None, organization_id=ORG)
    assert isinstance(instance.config, native.StiggNodeConfig)
    assert native.StiggNode.get_config_schema()["$defs"]["StiggServerCredential"]["properties"]["credential_type"]["const"] == FAMILY

@pytest.mark.asyncio
async def test_actual_manual_connect_and_recognizable_customer_evidence(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.account_label == "Fixture customer"
    assert json.loads(provider.requests[-1].content)["operationName"] == "GetCustomerById"
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is True and evidence.account_label == "Fixture customer"

@pytest.mark.parametrize("change", [{"api_key": "client-publishable"}, {"api_key": "server-your-key"},
    {"api_key": "server-<key>"}, {"api_key": "Bearer server-pasted"}, {"api_key": "server-bad\r\nheader"},
    {"api_key": "https://foreign.invalid"}, {"validation_customer_id": "../foreign"}, {"credential_type": "foreign"}])
def test_strict_native_credential_shape(change):
    with pytest.raises(ValueError): native._credential({**CREDS, **change})

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 202, 204, 401, 403, 404, 429, 500])
async def test_fixed_http_errors_no_retry_redirect_secret_echo(provider, status, caplog):
    provider.status = status
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as failure: await run("get_customer")
    assert CREDS["api_key"] not in str(failure.value) + caplog.text
    assert len(provider.requests) == 1

@pytest.mark.asyncio
async def test_http200_partial_errors_null_data_media_token_and_private_dns(provider):
    for raw, media in [(b'{"data":{"getCustomerByRefId":{"refId":"customer-1"}},"errors":[{"message":"private"}]}', "application/json"),
        (b'{"data":null}', "application/json"), (b'{"data":{},"data":{}}', "application/json"),
        (b"NaN", "application/json"), (b"{}", "text/html"), (b"x" * (native.MAX_BYTES + 1), "application/json"),
        (json.dumps({"data": {}, "key": CREDS["api_key"]}).encode(), "application/json")]:
        provider.raw, provider.media = raw, media
        with pytest.raises(ValueError): await run("get_customer")
    provider.raw, provider.media, provider.private_dns = None, None, True
    provider.requests.clear()
    with pytest.raises(ValueError): await run("get_customer")
    assert provider.requests == []

@pytest.mark.asyncio
async def test_empty_bounds_scope_and_parent_guards(provider):
    provider.empty = True
    assert (await run("list_products"))["data"]["items"] == []
    assert (await run("get_entitlements", {"customer_id": "customer-1"}))["data"]["items"] == []
    provider.requests.clear()
    with pytest.raises(ValueError): await run("get_active_subscription", {"customer_id": "customer-1", "subscription_id": "subscription-1"})
    assert [json.loads(r.content)["operationName"] for r in provider.requests] == ["GetCustomerById", "GetActiveSubscriptionsList"]
    provider.requests.clear()
    with pytest.raises(ValueError): await native.StiggNode.load_field_options("feature_id", CREDS, {})
    with pytest.raises(ValueError): await native.StiggNode.load_field_options("product_id", CREDS, page_token="foreign")
    assert provider.requests == []
    provider.empty, provider.target = False, "GetEntitlement"
    foreign = {"customerId": "foreign", "resourceId": None, "isGranted": False, "feature": {"refId": "feature-1"}}
    provider.raw = json.dumps({"data": {"entitlement": foreign}}).encode()
    with pytest.raises(ValueError): await run("get_entitlement", {"customer_id": "customer-1", "feature_id": "feature-1", "requested_usage": 0.0})
    provider.target, provider.raw = "GetProducts", json.dumps({"data": {"products": {"edges": [{"node": {"refId": "p"}}] * 21}}}).encode()
    with pytest.raises(ValueError): await run("list_products")

@pytest.mark.asyncio
@pytest.mark.parametrize("subscription", ["missing", {"subscriptionId": "unexpected"}])
async def test_provision_requires_explicit_null_subscription_response(provider, subscription):
    payload = {"customer": {"refId": "customer-1", "name": "Fixture customer"}}
    if subscription != "missing":
        payload["subscription"] = subscription
    provider.target = "ProvisionCustomer"
    provider.raw = json.dumps({"data": {"provisionCustomer": payload}}).encode()
    with pytest.raises(ValueError):
        await run("provision_customer", {"customer_id": "customer-1", "name": "Fixture customer"})
    assert len(provider.requests) == 1

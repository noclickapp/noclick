"""Stigg environment-scoped customer, catalog and entitlement workflows.

Fixed vendor GraphQL documents return bounded, minimal metadata. Customer writes
explicitly omit billing and skip subscription provisioning; they never grant access.
"""
from contextvars import ContextVar
import json
import logging
import math
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictFloat, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-stigg"
FAMILIES = {"stigg_server_api_key"}
API_URL = "https://api.stigg.io/graphql"
MAX_BYTES = 2_097_152
Code = Annotated[StrictStr, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Name = Annotated[StrictStr, Field(min_length=1, max_length=200)]


def _dynamic(name, *parents):
    value = {"field_name": name, "allow_custom": True, "searchable": True}
    if parents:
        value["depends_on"] = list(parents)
    return {"x-dynamic-options": value}


class StiggServerCredential(BaseModel):
    model_config = ConfigDict(title="Stigg Environment", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "api_key",
            "x-credential-url": "https://docs.stigg.io/documentation/managing-your-account/environments/api-keys",
            "x-credential-instructions": "Use an issued server- secret key for one Stigg environment. Full and scoped server keys are supported; client publishable keys are excluded. Supply an existing customer ID for the read-only connection check."})
    credential_type: Literal["stigg_server_api_key"] = Field("stigg_server_api_key", json_schema_extra={"ui:hidden": True})
    api_key: StrictStr = Field(..., min_length=8, max_length=4096, repr=False, title="Server API Key",
        description="Existing server- full or scoped secret key. Permissions and environment are set by Stigg; no key is minted or rotated.",
        json_schema_extra={"ui:widget": "password"})
    validation_customer_id: Code = Field(..., title="Existing Customer ID",
        description="One existing customer in this key's environment, used for a protected metadata read on connect. This does not prove an account or environment name.")

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        suffix = value.removeprefix("server-")
        if not value.startswith("server-") or not suffix or is_placeholder(value) or is_placeholder(suffix) or is_url_shaped(value) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use an issued server- secret API key without a header prefix or whitespace")
        return value


def _credential(raw):
    if isinstance(raw, StiggServerCredential):
        return raw
    if not isinstance(raw, dict) or raw.get("credential_type") not in (None, *FAMILIES):
        raise ValueError("Connect Stigg server API credentials")
    return StiggServerCredential.model_validate(raw)


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def clean(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use metadata text without control characters")
        if isinstance(value, str) and not value.strip():
            raise ValueError("Use nonblank metadata text")
        return value


class GetCustomer(_Config):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: Optional[Code] = Field(None, description="Omit to read the existing validation customer in the credential.")


class ProvisionCustomer(_Config):
    operation: Literal["provision_customer"] = Field("provision_customer", json_schema_extra={"ui:hidden": True})
    customer_id: Code = Field(..., description="Customer reference ID. Stigg provisioning can return an existing customer; this is not an exclusive create.")
    name: Name = Field(..., title="Customer Name", description="Ordinary customer metadata write. No email, billing, coupon, subscription or access-grant fields are sent.")


class UpdateCustomer(_Config):
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: Code
    name: Name = Field(..., title="Customer Name", description="Update only the customer's name. Other customer metadata and billing fields are not sent.")


class ListProducts(_Config):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})


class GetPaywall(_Config):
    operation: Literal["get_paywall"] = Field("get_paywall", json_schema_extra={"ui:hidden": True})
    product_id: Optional[Code] = Field(None, json_schema_extra=_dynamic("product_id"),
        description="Optional product from the SDK's bounded first-20 product catalog. No country pricing, checkout or customer portal is requested.")
    customer_id: Optional[Code] = None


class _CustomerScope(_Config):
    customer_id: Code
    resource_id: Optional[Code] = Field(None, description="Optional resource within this customer; passed to the exact entitlement/subscription input.")


class GetEntitlements(_CustomerScope):
    operation: Literal["get_entitlements"] = Field("get_entitlements", json_schema_extra={"ui:hidden": True})


class GetEntitlement(_CustomerScope):
    operation: Literal["get_entitlement"] = Field("get_entitlement", json_schema_extra={"ui:hidden": True})
    feature_id: Code = Field(..., json_schema_extra=_dynamic("feature_id", "customer_id"))
    requested_usage: Optional[StrictFloat] = Field(None, ge=0, le=1e12, allow_inf_nan=False,
        description="Optional amount to check. This does not report, reserve or consume usage.")


class ListActiveSubscriptions(_CustomerScope):
    operation: Literal["list_active_subscriptions"] = Field("list_active_subscriptions", json_schema_extra={"ui:hidden": True})


class GetActiveSubscription(_CustomerScope):
    operation: Literal["get_active_subscription"] = Field("get_active_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: Code = Field(..., json_schema_extra=_dynamic("subscription_id", "customer_id"),
        description="Selected subscription must first appear in the bounded active subscriptions for this customer/resource.")


StiggConfig = Annotated[Union[GetCustomer, ProvisionCustomer, UpdateCustomer, ListProducts,
    GetPaywall, GetEntitlements, GetEntitlement, ListActiveSubscriptions, GetActiveSubscription],
    Field(discriminator="operation")]


class StiggNodeConfig(NodeConfig[StiggConfig, StiggServerCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    credentials: Optional[StiggServerCredential] = None


_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("stigg_private_request", default=False)



class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "utils.ssrf"):
    logging.getLogger(_logger).addFilter(_PrivateRequestLogFilter())


class _AuthRefused(ValueError):
    pass


_CUSTOMER_FIELDS = "refId name createdAt updatedAt"
_SUBSCRIPTION_FIELDS = """subscriptionId status startDate endDate cancellationDate effectiveEndDate currentBillingPeriodEnd
customer { customerId } resource { resourceId }
plan { refId displayName product { refId displayName } }"""
_ENTITLEMENT_FIELDS = """isGranted accessDeniedReason customerId resourceId usageLimit hasUnlimitedUsage hasSoftLimit
currentUsage requestedUsage entitlementUpdatedAt usageUpdatedAt validUntil
feature { refId displayName featureType meterType }"""
# Selections are a minimal subset of the official @stigg/api-client-js 6.24.0
# operation/fragments. Neither the document nor endpoint is caller-controlled.
_DOCUMENTS = {
    "get_customer": ("GetCustomerById", "query GetCustomerById($input: GetCustomerByRefIdInput!) { getCustomerByRefId(input: $input) { " + _CUSTOMER_FIELDS + " } }", "getCustomerByRefId"),
    "provision_customer": ("ProvisionCustomer", "mutation ProvisionCustomer($input: ProvisionCustomerInput!) { provisionCustomer(input: $input) { customer { " + _CUSTOMER_FIELDS + " } subscription { subscriptionId } subscriptionDecisionStrategy } }", "provisionCustomer"),
    "update_customer": ("UpdateCustomer", "mutation UpdateCustomer($input: UpdateCustomerInput!) { updateCustomer: updateOneCustomer(input: $input) { " + _CUSTOMER_FIELDS + " } }", "updateCustomer"),
    "list_products": ("GetProducts", "query GetProducts { products(paging: {first: 20}) { edges { node { refId displayName } } } }", "products"),
    "get_paywall": ("GetPaywall", """query GetPaywall($input: GetPaywallInput!) { paywall(input: $input) {
plans { refId displayName versionNumber hiddenFromWidgets product { refId displayName }
compatibleAddons { refId displayName hiddenFromWidgets } } } }""", "paywall"),
    "get_entitlements": ("GetEntitlements", "query GetEntitlements($query: FetchEntitlementsQuery!) { entitlements: cachedEntitlements(query: $query) { " + _ENTITLEMENT_FIELDS + " } }", "entitlements"),
    "get_entitlement": ("GetEntitlement", "query GetEntitlement($query: FetchEntitlementQuery!) { entitlement(query: $query) { " + _ENTITLEMENT_FIELDS + " } }", "entitlement"),
    "list_active_subscriptions": ("GetActiveSubscriptionsList", "query GetActiveSubscriptionsList($input: GetActiveSubscriptionsInput!) { getActiveSubscriptions(input: $input) { " + _SUBSCRIPTION_FIELDS + " } }", "getActiveSubscriptions"),
    "get_active_subscription": ("GetSubscription", "query GetSubscription($input: GetSubscriptionInput!) { getSubscription(input: $input) { " + _SUBSCRIPTION_FIELDS + " } }", "getSubscription"),
}


def _unique(pairs):
    raw = {}
    for key, value in pairs:
        if key in raw:
            raise ValueError("Stigg returned duplicate JSON properties")
        raw[key] = value
    return raw


def _nonfinite(_value):
    raise ValueError("Stigg returned non-finite JSON")


def _contains_key(raw, api_key):
    pending = [raw]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and api_key in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


class _Session:
    def __init__(self, credential):
        self.credential = credential

    async def query(self, operation, variables):
        if operation not in _DOCUMENTS or not isinstance(variables, dict) or set(variables) - {"input", "query"}:
            raise ValueError("Unsupported Stigg GraphQL operation")
        for value in variables.values():
            if not isinstance(value, dict) or "environmentId" in value:
                raise ValueError("Stigg environment is determined exclusively by the supplied server key")
        operation_name, document, root = _DOCUMENTS[operation]
        body = {"operationName": operation_name, "query": document, "variables": variables}
        if len(json.dumps(body, allow_nan=False).encode()) > 16384:
            raise ValueError("Stigg request exceeds the bounded metadata limit")
        private = _PRIVATE_REQUEST.set(True)
        try:
            async with guarded_async_client( follow_redirects=False, trust_env=False, timeout=20.0) as client:
                async with client.stream("POST", API_URL, json=body, headers={
                    "X-API-Key": self.credential.api_key, "X-GraphQL-Operation-Name": operation_name,
                    "Accept": "application/json", "Content-Type": "application/json"}) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused("Stigg server key or permission was rejected (HTTP " + str(response.status_code) + ")")
                    if response.status_code == 429:
                        raise ValueError("Stigg rate limit reached; retry later")
                    if response.status_code != 200:
                        raise ValueError("Stigg request failed with HTTP " + str(response.status_code))
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Stigg returned an unsupported metadata format")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError("Stigg response exceeds the bounded metadata limit")
                    try:
                        raw = json.loads(data, object_pairs_hook=_unique, parse_constant=_nonfinite)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("Stigg returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Stigg public HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(private)
        if _contains_key(raw, self.credential.api_key):
            raise ValueError("Stigg returned credential material")
        if not isinstance(raw, dict) or ("errors" in raw and raw["errors"] not in (None, [])) or raw.get("error") is not None:
            raise ValueError("Stigg returned GraphQL errors; no partial result was accepted")
        if not isinstance(raw.get("data"), dict) or root not in raw["data"]:
            raise ValueError("Stigg returned an incomplete GraphQL result")
        return raw["data"][root]


def _text(value, maximum=1000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Stigg returned invalid text metadata")
    return value


def _identifier(value):
    value = _text(value, 200)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        raise ValueError("Stigg returned an invalid reference identifier")
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Stigg returned invalid record metadata")
    return value


def _array(value, *, limit=100):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("Stigg returned an invalid bounded collection")
    return value


def _scalar_fields(raw, names):
    result = {}
    for name in names:
        if name not in raw:
            continue
        value = raw[name]
        result[name] = None if value is None else _text(value)
    return result


def _customer(raw, expected):
    raw = _object(raw)
    if _identifier(raw.get("refId")) != expected:
        raise ValueError("Stigg returned a different customer")
    return {"refId": expected, **_scalar_fields(raw, ("name", "createdAt", "updatedAt"))}


def _product(raw):
    raw = _object(raw)
    return {"refId": _identifier(raw.get("refId")), **_scalar_fields(raw, ("displayName",))}


def _entitlement(raw, customer_id, resource_id, feature_id=None):
    raw = _object(raw)
    if raw.get("customerId") != customer_id or raw.get("resourceId") != resource_id:
        raise ValueError("Stigg returned entitlement metadata outside the selected customer/resource")
    feature = _object(raw.get("feature"))
    identifier = _identifier(feature.get("refId"))
    if feature_id is not None and identifier != feature_id:
        raise ValueError("Stigg returned a different feature")
    result = {"customerId": customer_id, "resourceId": resource_id,
        "feature": {"refId": identifier, **_scalar_fields(feature, ("displayName", "featureType", "meterType"))},
        **_scalar_fields(raw, ("accessDeniedReason", "entitlementUpdatedAt", "usageUpdatedAt", "validUntil"))}
    for name in ("isGranted", "hasUnlimitedUsage", "hasSoftLimit"):
        if name not in raw or raw[name] is None and name != "isGranted":
            result[name] = None
        elif type(raw[name]) is bool:
            result[name] = raw[name]
        else:
            raise ValueError("Stigg returned invalid entitlement boolean metadata")
    if result["isGranted"] is None:
        raise ValueError("Stigg did not return an entitlement verdict")
    for name in ("usageLimit", "currentUsage", "requestedUsage"):
        if name not in raw:
            continue
        value = raw[name]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("Stigg returned invalid entitlement usage metadata")
        result[name] = value
    return result


def _subscription(raw, customer_id, resource_id=None):
    raw = _object(raw)
    if _object(raw.get("customer")).get("customerId") != customer_id:
        raise ValueError("Stigg returned a subscription outside the selected customer")
    resource = raw.get("resource")
    actual_resource = None if resource is None else _identifier(_object(resource).get("resourceId"))
    if resource_id is not None and actual_resource != resource_id:
        raise ValueError("Stigg returned a subscription outside the selected resource")
    plan = _object(raw.get("plan"))
    return {"subscriptionId": _identifier(raw.get("subscriptionId")), "customerId": customer_id,
        "resourceId": actual_resource, **_scalar_fields(raw, ("status", "startDate", "endDate", "cancellationDate", "effectiveEndDate", "currentBillingPeriodEnd")),
        "plan": {**_product(plan), "product": _product(plan.get("product"))}}


def _distinct(rows, key):
    if len({row[key] for row in rows}) != len(rows):
        raise ValueError("Stigg returned duplicate record identifiers")
    return rows


class StiggNode(WorkflowNode):
    integration_type = "automation-stigg"
    connection_evidence = ConnectionEvidence(noun="customer metadata", identity_operation="get_customer", identity_keys=("name", "refId"))

    @classmethod
    def get_config_model(cls):
        return StiggNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"product_id", "feature_id", "subscription_id"}:
            raise ValueError("Unsupported Stigg picker")
        if page_token is not None:
            raise ValueError("This bounded Stigg SDK read does not expose a continuation cursor")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in search)):
            raise ValueError("Use a bounded metadata search")
        context = context or {}
        if not isinstance(context, dict):
            raise ValueError("Use a valid Stigg picker context")
        if field_name == "product_id":
            config = ListProducts()
        else:
            # Validate the required parent before making provider requests.
            parent = _CustomerScope.model_validate({key: context.get(key) for key in ("customer_id", "resource_id")})
            config = (GetEntitlements if field_name == "feature_id" else ListActiveSubscriptions)(**parent.model_dump())
        result = await cls._execute(_Session(_credential(credential_data)), config)
        options = []
        for row in result["items"]:
            item = row["feature"] if field_name == "feature_id" else row
            key = "subscriptionId" if field_name == "subscription_id" else "refId"
            label = item.get("displayName") or (item.get("plan") or {}).get("displayName") or item[key]
            options.append({"value": item[key], "label": label})
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not isinstance(self.config, StiggNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect Stigg server API credentials")
        result = await self._execute(_Session(self.config.credentials), self.config.config)
        return {"status": "success", "data": result}

    @staticmethod
    async def _customer(session, customer_id):
        raw = await session.query("get_customer", {"input": {"customerId": customer_id}})
        return _customer(raw, customer_id)

    @classmethod
    async def _execute(cls, session, config):
        op = config.operation
        if op == "get_customer":
            return await cls._customer(session, config.customer_id or session.credential.validation_customer_id)
        if op == "provision_customer":
            raw = _object(await session.query(op, {"input": {"refId": config.customer_id, "name": config.name, "subscriptionParams": None}}))
            _customer(raw.get("customer"), config.customer_id)
            if "subscription" not in raw:
                raise ValueError("Stigg returned incomplete subscription-skipping confirmation")
            if raw.get("subscription") is not None:
                raise ValueError("Stigg reported an unexpected subscription; provisioning outcome requires review")
            # Provisioning is idempotent for an existing customer; it does not
            # imply the supplied name overwrote an existing name.
            readback = await cls._customer(session, config.customer_id)
            return {"customer": readback, "accepted": True, "readback_verified": True,
                "subscription_provisioned": False, "effect": "customer_provision_without_subscription"}
        if op == "update_customer":
            await cls._customer(session, config.customer_id)
            _customer(await session.query(op, {"input": {"refId": config.customer_id, "name": config.name}}), config.customer_id)
            readback = await cls._customer(session, config.customer_id)
            if readback.get("name") != config.name:
                raise ValueError("Stigg customer name readback did not match the requested update")
            return {"customer": readback, "accepted": True, "readback_verified": True, "effect": "customer_name_update"}
        if op == "list_products":
            raw = _object(await session.query(op, {}))
            rows = [_product(_object(edge).get("node")) for edge in _array(raw.get("edges"), limit=20)]
            return {"items": _distinct(rows, "refId"), "returned_count": len(rows), "limit": 20,
                "catalog_complete": None, "continuation_available": False,
                "note": "Official SDK selects first 20 products; no completeness or cursor is inferred"}
        if op == "get_paywall":
            input_value = {}
            if config.product_id is not None:
                products = await cls._execute(session, ListProducts())
                if not any(row["refId"] == config.product_id for row in products["items"]):
                    raise ValueError("The selected product is not in the bounded product catalog")
                input_value["productId"] = config.product_id
            if config.customer_id is not None:
                await cls._customer(session, config.customer_id)
                input_value["customerId"] = config.customer_id
            raw = _object(await session.query(op, {"input": input_value}))
            plans = []
            for value in _array(raw.get("plans")):
                value = _object(value)
                plan = {**_product(value), "product": _product(value.get("product"))}
                if config.product_id is not None and plan["product"]["refId"] != config.product_id:
                    raise ValueError("Stigg returned a plan outside the selected product")
                for name in ("versionNumber", "hiddenFromWidgets"):
                    if name not in value:
                        continue
                    item = value[name]
                    if item is not None and (type(item) is not bool if name == "hiddenFromWidgets" else type(item) not in (int, float) or not math.isfinite(item) or item < 0):
                        raise ValueError("Stigg returned invalid paywall metadata")
                    plan[name] = item
                addons = []
                for addon in _array(value.get("compatibleAddons")):
                    addon = _object(addon)
                    item = _product(addon)
                    if "hiddenFromWidgets" in addon:
                        if addon["hiddenFromWidgets"] is not None and type(addon["hiddenFromWidgets"]) is not bool:
                            raise ValueError("Stigg returned invalid add-on metadata")
                        item["hiddenFromWidgets"] = addon["hiddenFromWidgets"]
                    addons.append(item)
                plan["compatibleAddons"] = _distinct(addons, "refId")
                plans.append(plan)
            return {"items": _distinct(plans, "refId"), "returned_count": len(plans), "product_id": config.product_id,
                "customer_id": config.customer_id, "effect": "paywall_metadata_read"}
        # These reads require an existing customer before entitlement/subscription work.
        await cls._customer(session, config.customer_id)
        scope = {"customerId": config.customer_id}
        if config.resource_id is not None:
            scope["resourceId"] = config.resource_id
        if op == "get_entitlements":
            raw = await session.query(op, {"query": scope})
            rows = [_entitlement(row, config.customer_id, config.resource_id) for row in _array(raw)]
            _distinct([{"refId": row["feature"]["refId"]} for row in rows], "refId")
            return {"items": rows, "returned_count": len(rows), "customer_id": config.customer_id, "resource_id": config.resource_id}
        if op == "get_entitlement":
            query = {**scope, "featureId": config.feature_id}
            if config.requested_usage is not None:
                query["options"] = {"requestedUsage": config.requested_usage}
            raw = await session.query(op, {"query": query})
            return _entitlement(raw, config.customer_id, config.resource_id, config.feature_id)
        if op in {"list_active_subscriptions", "get_active_subscription"}:
            raw = await session.query("list_active_subscriptions", {"input": scope})
            rows = [_subscription(row, config.customer_id, config.resource_id) for row in _array(raw)]
            _distinct(rows, "subscriptionId")
            if op == "list_active_subscriptions":
                return {"items": rows, "returned_count": len(rows), "customer_id": config.customer_id,
                    "resource_id": config.resource_id, "continuation_available": False}
            if not any(row["subscriptionId"] == config.subscription_id for row in rows):
                raise ValueError("The selected subscription is not in this customer's bounded active subscriptions")
            selected = _subscription(await session.query(op, {"input": {"subscriptionId": config.subscription_id}}), config.customer_id, config.resource_id)
            if selected["subscriptionId"] != config.subscription_id:
                raise ValueError("Stigg returned a different subscription")
            return selected
        raise ValueError("Unsupported Stigg operation")

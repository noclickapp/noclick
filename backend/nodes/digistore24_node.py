"""Digistore24 API v1: one published /api/call operation per action.

Contract: https://www.digistore24.com/api/docs/openapi.yaml
Lists return one page; callers choose the next page number. Writes are not retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://www.digistore24.com/api/call"


class Digistore24APIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Digistore24 API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.digistore24.com/hc/en-us/articles/23658595845009-Create-API-key",
            "x-credential-instructions": "Paste your Digistore24 API key from Settings > Account access > API keys. The key needs permission for the operations you use. NoClick sends it in the X-DS-API-KEY header only to www.digistore24.com. Connecting reads the API key owner's user information; this does not prove write permissions.",
        })
    credential_type: Literal["digistore24_api_key"] = Field("digistore24_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class Digistore24GetUserInfoConfig(_Input):
    """Get current user information."""
    operation: Literal['get_user_info'] = Field('get_user_info', json_schema_extra={"ui:hidden": True})

class Digistore24ListProductsConfig(_Input):
    """List products."""
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    sort_by: Literal['name', 'group'] = Field('name', description='Sort products by name or product group')
    merchant_id: int | None = Field(None, description='Read the products of another account. Only permitted for API keys with cross-account read access (classes `network` and `network_ai`). Defaults to the account owning the API key.\n', ge=1)

class Digistore24GetProductConfig(_Input):
    """Get product details."""
    operation: Literal['get_product'] = Field('get_product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='Numeric ID of the product to retrieve', ge=1)

class Digistore24ListBuyersConfig(_Input):
    """List buyers."""
    operation: Literal['list_buyers'] = Field('list_buyers', json_schema_extra={"ui:hidden": True})
    page_no: int = Field(1, description='Page number for pagination (starts at 1)', ge=1)
    page_size: int = Field(100, description='Number of buyers per page', ge=1, le=1000)

class Digistore24GetBuyerConfig(_Input):
    """Get buyer details."""
    operation: Literal['get_buyer'] = Field('get_buyer', json_schema_extra={"ui:hidden": True})
    buyer_id: int = Field(..., description='ID of the buyer to retrieve', ge=1)

class Digistore24UpdateBuyerConfig(_Input):
    """Update a buyer."""
    operation: Literal['update_buyer'] = Field('update_buyer', json_schema_extra={"ui:hidden": True})
    buyer_id: int = Field(..., description='The buyer ID, as returned by e.g. getPurchase', ge=1)
    email: str | None = Field(None, description="Buyer's email address", max_length=4096)
    first_name: str | None = Field(None, description="Buyer's first name", max_length=4096)
    last_name: str | None = Field(None, description="Buyer's last name", max_length=4096)
    salutation: Literal['', 'M', 'F'] | None = Field(None, description="Buyer's salutation (empty, M or F)")
    title: str | None = Field(None, description="Buyer's title", max_length=4096)
    company: str | None = Field(None, description="Buyer's company name", max_length=4096)
    street_name: str | None = Field(None, description='Street name', max_length=4096)
    street_number: str | None = Field(None, description='Street number', max_length=4096)
    phone_number: str | None = Field(None, description='Phone number (can be overwritten with an empty string)', max_length=4096)
    city: str | None = Field(None, description='City', max_length=4096)
    zipcode: str | None = Field(None, description='ZIP/Postal code', max_length=4096)
    state: str | None = Field(None, description='State/Province', max_length=4096)
    country: str | None = Field(None, description='Two-digit ISO country code (e.g., DE or AT)', max_length=4096)

    @model_validator(mode="after")
    def has_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "buyer_id"}):
            raise ValueError("Provide at least one buyer field to update")
        return self

class Digistore24ListPurchasesConfig(_Input):
    """List purchases."""
    operation: Literal['list_purchases'] = Field('list_purchases', json_schema_extra={"ui:hidden": True})
    from_time: str = Field('-24h', alias="from", description='Start time for purchase list (e.g. "2014-02-28 23:11:24", "now", "-3d", "start")', max_length=4096)
    to: str = Field('now', description='End time for purchase list', max_length=4096)
    sort_by: Literal['date', 'earning', 'amount'] = Field('date', description='Sort criteria')
    sort_order: Literal['asc', 'desc'] = Field('asc', description='Sort order')
    load_transactions: StrictBool = Field(False, description='Include transaction list for each purchase')
    page_no: int = Field(1, description='Page number (starts at 1)', ge=1)
    page_size: int = Field(500, description='Number of items per page', ge=1, le=1000)
    merchant_id: int | None = Field(None, description='List the purchases of another account. Only permitted for API keys with cross-account read access (class `network`). Defaults to the account owning the API key.\n', ge=1)

class Digistore24GetPurchaseConfig(_Input):
    """Get purchase details."""
    operation: Literal['get_purchase'] = Field('get_purchase', json_schema_extra={"ui:hidden": True})
    purchase_id: str = Field(..., description='Single Digistore24 order ID or comma-separated list of order IDs', max_length=4096, min_length=1)

class Digistore24StopRebillingConfig(_Input):
    """Stop rebilling for a purchase."""
    operation: Literal['stop_rebilling'] = Field('stop_rebilling', json_schema_extra={"ui:hidden": True})
    purchase_id: str = Field(..., description='The Digistore24 order ID', max_length=4096, min_length=1)
    force: StrictBool = Field(False, description='If possible, a rebilling is canceled immediately. If a minimum duration is specified, this will be adhered to by default (for force=false),\nmeaning that it will be canceled at the end of the minimum duration. If force=true, it will be canceled immediately.\n')
    ignore_refund_possibility: StrictBool = Field(False, description='If false (default), the purchase is cancelled effective immediately if a refund is possible.\nIf true, the cancellation becomes effective at the end of the regular cancellation period.\nThe parameter is ignored if force=true.\n')

class Digistore24StartRebillingConfig(_Input):
    """Start rebilling."""
    operation: Literal['start_rebilling'] = Field('start_rebilling', json_schema_extra={"ui:hidden": True})
    purchase_id: str = Field(..., description='The Digistore24 order ID', max_length=4096, min_length=1)

class Digistore24ListTransactionsConfig(_Input):
    """List transactions (payments, returns, chargebacks)."""
    operation: Literal['list_transactions'] = Field('list_transactions', json_schema_extra={"ui:hidden": True})
    from_time: str = Field('-24h', alias="from", description='Point of time to filter transaction creation date from. Examples:\n- "2014-02-28 23:11:24"\n- "2021-10-08T07:20:11-05:00" (ISO 8601)\n- "now" for current time\n- "-3d" for 3 days ago\n- "start" for first available date\n', max_length=4096)
    to: str = Field('now', description='Point of time to filter transaction creation date to', max_length=4096)
    sort_by: Literal['date', 'earning', 'amount'] = Field('date', description='Field to sort results by')
    sort_order: Literal['asc', 'desc'] = Field('asc', description='Sort direction')
    page_no: int = Field(1, description='Page number (starts at 1)', ge=1)
    page_size: int = Field(500, description='Number of entries per page', ge=1, le=1000)

class Digistore24ListVouchersConfig(_Input):
    """List voucher codes."""
    operation: Literal['list_vouchers'] = Field('list_vouchers', json_schema_extra={"ui:hidden": True})

class Digistore24GetVoucherConfig(_Input):
    """Get voucher details."""
    operation: Literal['get_voucher'] = Field('get_voucher', json_schema_extra={"ui:hidden": True})
    code: str = Field(..., description='The voucher code that the buyer enters on the order form', max_length=4096, min_length=1)

class Digistore24CreateVoucherConfig(_Input):
    """Create a discount voucher."""
    operation: Literal['create_voucher'] = Field('create_voucher', json_schema_extra={"ui:hidden": True})
    code: str = Field(..., description='The voucher code', max_length=4096, min_length=1)
    product_ids: str = Field('all', description='Comma-separated list of product IDs this voucher applies to', max_length=4096)
    valid_from: str | None = Field(None, description='Point in time from when the code becomes valid (e.g. 2017-12-31 12:00:00)', max_length=4096)
    expires_at: str | None = Field(None, description='Point in time when the code becomes invalid', max_length=4096)
    first_rate: float | None = Field(None, description='Discount percentage on first payment (subscriptions/installments) or single payment', ge=0, allow_inf_nan=False, le=100)
    other_rates: float | None = Field(None, description='Discount percentage on follow-up payments (subscriptions/installments)', ge=0, allow_inf_nan=False, le=100)
    first_amount: float | None = Field(None, description='Fixed discount amount on first/single payment', ge=0, allow_inf_nan=False)
    other_amounts: float | None = Field(None, description='Fixed discount amount on follow-up payments', ge=0, allow_inf_nan=False)
    currency: str | None = Field(None, description='Currency code for the fixed discount amounts', max_length=4096)
    is_count_limited: StrictBool = Field(False, description='Whether the number of uses is limited')
    count_left: int = Field(1, description='Number of remaining uses if is_count_limited is true', ge=0)
    upgrade_policy: Literal['valid', 'other_only', 'not_valid'] = Field('valid', description='How the code is used for upgrades:\n* valid - voucher fully usable\n* other_only - only discount on follow-up installments\n* not_valid - voucher not usable\n')

class Digistore24DeleteVoucherConfig(_Input):
    """Delete a voucher."""
    operation: Literal['delete_voucher'] = Field('delete_voucher', json_schema_extra={"ui:hidden": True})
    code: str = Field(..., description='The voucher code or voucher ID to delete', max_length=4096, min_length=1)


# Registration contract: /api/docs/paths/ipnSetup.yaml and ipnDelete.yaml.
# Event fields/signatures: https://dev.digistore24.com/hc/en-us/articles/32480561422353-Events
ORDER_EVENTS = {
    "on_payment": ("payment", "Payment received"),
    "on_refund": ("refund", "Payment refunded"),
    "on_chargeback": ("chargeback", "Payment charged back"),
    "on_payment_missed": ("payment_missed", "Recurring payment missed"),
    "on_rebill_cancelled": ("rebill_cancelled", "Subscription rebilling cancelled"),
    "on_rebill_resumed": ("rebill_resumed", "Subscription rebilling resumed"),
    "last_paid_day": ("last_paid_day", "Paid period ended"),
}


class Digistore24OnOrderEventConfig(WebhookTriggerConfigBase):
    """Start a workflow or agent when the selected order event arrives."""

    operation: Literal["on_order_event"] = Field("on_order_event", title="On Order Event", json_schema_extra={
        "const": "on_order_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Order Event",
    })
    event_type: Literal[*ORDER_EVENTS] = Field("on_payment", title="Order event")
    product_ids: str = Field("all", title="Products", max_length=4096,
        description='Use "all" or comma-separated product IDs.')
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Digistore24 automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

    @field_validator("product_ids")
    @classmethod
    def valid_products(cls, value):
        value = value.strip()
        if value != "all" and not all(part.isascii() and part.isdigit() and int(part) > 0 for part in value.split(",")):
            raise ValueError('Use "all" or positive product IDs separated by commas without spaces')
        return value


Digistore24Config = Annotated[Union[
    Digistore24OnOrderEventConfig,
    Digistore24GetUserInfoConfig,
    Digistore24ListProductsConfig,
    Digistore24GetProductConfig,
    Digistore24ListBuyersConfig,
    Digistore24GetBuyerConfig,
    Digistore24UpdateBuyerConfig,
    Digistore24ListPurchasesConfig,
    Digistore24GetPurchaseConfig,
    Digistore24StopRebillingConfig,
    Digistore24StartRebillingConfig,
    Digistore24ListTransactionsConfig,
    Digistore24ListVouchersConfig,
    Digistore24GetVoucherConfig,
    Digistore24CreateVoucherConfig,
    Digistore24DeleteVoucherConfig
], Field(discriminator="operation")]


class Digistore24FullConfig(NodeConfig[Digistore24Config, Digistore24APIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed routes, query fields and body fields from the pinned provider contract.
ROUTES = {'get_user_info': ('GET', 'getUserInfo', [], []),
 'list_products': ('GET', 'listProducts', ['sort_by', 'merchant_id'], []),
 'get_product': ('GET', 'getProduct', ['product_id'], []),
 'list_buyers': ('GET', 'listBuyers', ['page_no', 'page_size'], []),
 'get_buyer': ('GET', 'getBuyer', ['buyer_id'], []),
 'update_buyer': ('PUT',
                  'updateBuyer',
                  ['buyer_id'],
                  ['email',
                   'first_name',
                   'last_name',
                   'salutation',
                   'title',
                   'company',
                   'street_name',
                   'street_number',
                   'phone_number',
                   'city',
                   'zipcode',
                   'state',
                   'country']),
 'list_purchases': ('GET',
                    'listPurchases',
                    ['from',
                     'to',
                     'sort_by',
                     'sort_order',
                     'load_transactions',
                     'page_no',
                     'page_size',
                     'merchant_id'],
                    []),
 'get_purchase': ('GET', 'getPurchase', ['purchase_id'], []),
 'stop_rebilling': ('POST', 'stopRebilling', ['purchase_id', 'force', 'ignore_refund_possibility'], []),
 'start_rebilling': ('POST', 'startRebilling', ['purchase_id'], []),
 'list_transactions': ('GET',
                       'listTransactions',
                       ['from', 'to', 'sort_by', 'sort_order', 'page_no', 'page_size'],
                       []),
 'list_vouchers': ('GET', 'listVouchers', [], []),
 'get_voucher': ('GET', 'getVoucher', ['code'], []),
 'create_voucher': ('POST',
                    'createVoucher',
                    [],
                    ['code',
                     'product_ids',
                     'valid_from',
                     'expires_at',
                     'first_rate',
                     'other_rates',
                     'first_amount',
                     'other_amounts',
                     'currency',
                     'is_count_limited',
                     'count_left',
                     'upgrade_policy']),
 'delete_voucher': ('DELETE', 'deleteVoucher', ['code'], [])}


class Digistore24Node(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-digistore24"
    connection_evidence = ConnectionEvidence(
        noun="account", identity_operation="get_user_info", label_keys=("user_name", "user_id"),
    )
    edit_examples = ["List my recent purchases", "Update a buyer's contact details", "Create a discount voucher"]

    @classmethod
    def get_config_model(cls):
        return Digistore24FullConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "on_payment"),
                "product_ids": (config or {}).get("product_ids", "all")}

    @classmethod
    async def _ipn_request(cls, credential, method, function, **kwargs):
        key = Digistore24APIKeyCredential.model_validate(credential or {}).api_key
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + "/" + function,
                headers={"X-DS-API-KEY": key, "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        # The IPN contract declares HTTP 200 with no response content.
        if not response.content:
            return
        data = response.json()
        if not isinstance(data, dict) or data.get("result") == "error" or data.get("status") == "error":
            raise ValueError("Digistore24 rejected the IPN registration request")

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = Digistore24OnOrderEventConfig.model_validate(config or {})
        # The provider deletes registrations by domain_id. Use the unique minted
        # webhook URL so identical canvas node IDs in different workflows cannot collide.
        domain_id = "noclick-" + hashlib.sha256(webhook_url.encode()).hexdigest()[:32]
        secret = secrets.token_hex(30)  # 60 chars, below the documented 63-char limit.
        await cls._ipn_request(credential, "POST", "ipnSetup", json={
            "ipn_url": webhook_url, "name": "NoClick order events", "product_ids": op.product_ids,
            "domain_id": domain_id, "categories": "orders", "transactions": ORDER_EVENTS[op.event_type][0],
            "timing": "delayed", "sha_passphrase": secret,
        })
        return {"external_webhook_id": domain_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        domain_id = (config or {}).get("external_webhook_id")
        if not domain_id:
            raise ValueError("Digistore24 IPN domain ID is missing")
        await cls._ipn_request(credential, "DELETE", "ipnDelete", params={"domain_id": str(domain_id)})

    @staticmethod
    def _ipn_parameters(body, headers):
        # IPN is a form POST; JSON is also accepted for documented fixture replay.
        content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        if content_type.split(";")[0].strip() == "application/json":
            data = json.loads(body)
            if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
                raise ValueError("IPN fields must be strings")
            return data
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError("Duplicate IPN fields")
        return dict(pairs)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        try:
            params = cls._ipn_parameters(body, headers)
        except (ValueError, UnicodeError):
            return False
        signature = params.get("sha_sign", "")
        # Provider's current ipn_receiver.php: case-sensitive SORT_STRING, omit
        # sha_sign / SHASIGN and empty values; append passphrase after each pair.
        message = "".join(f"{k}={params[k]}{secret}" for k in sorted(params)
                          if k not in {"sha_sign", "SHASIGN"} and params[k] != "")
        expected = hashlib.sha512(message.encode("utf-8")).hexdigest().upper()
        return len(signature) == 128 and hmac.compare_digest(signature, expected)

    @classmethod
    def handle_webhook_handshake(cls, body, headers, config=None):
        try:
            params = cls._ipn_parameters(body, headers)
        except (ValueError, UnicodeError):
            return None
        if params.get("event") == "connection_test" and cls.verify_webhook_signature(body, headers, config):
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("OK")
        return None

    @classmethod
    def webhook_ack_response(cls):
        return {"content": "OK", "media_type": "text/plain"}

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("event") == (config or {}).get("event_type", "on_payment")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # Never forward the signature, lifecycle metadata or arbitrary run inputs.
        return {"status": "success", "operation": "on_order_event",
                "data": {k: v for k, v in payload.items() if k not in {"sha_sign", "SHASIGN", "_webhook"}}}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_order_event":
            return super().resolve_agent_event(output)
        event = output.get("data") or {}
        if event.get("event") not in ORDER_EVENTS:
            return None
        label = ORDER_EVENTS[event["event"]][1]
        text = (f"Digistore24: {label}. Buyer: {event.get('email') or 'not supplied'} "
                f"(buyer ID {event.get('buyer_id') or 'not supplied'}). "
                f"Product: {event.get('product_name') or 'not supplied'} "
                f"(ID {event.get('product_id') or 'not supplied'}). "
                f"Order ID: {event.get('order_id') or 'not supplied'}. "
                f"Transaction ID: {event.get('transaction_id') or 'not supplied'}. "
                f"Amount: {event.get('transaction_amount') or 'not supplied'} "
                f"{event.get('transaction_currency') or ''}. Mode: {event.get('api_mode') or 'not supplied'}.")
        return {"text": text[:4000], "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Digistore24 API key")
        op = self.config.config
        if isinstance(op, Digistore24OnOrderEventConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload")
            if not isinstance(payload, dict) or not self.filter_trigger_payload(payload, op.model_dump()):
                return {"status": "success", "operation": op.operation, "data": {}}
            return self.resolve_trigger_payload(payload, op.model_dump())
        key = self.config.credentials.api_key
        method, function, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        params = {name: values[name] for name in query_fields if name in values}
        body = {name: values[name] for name in body_fields if name in values}
        kwargs = {"params": params, "headers": {"X-DS-API-KEY": key, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + "/" + function, **kwargs)
            try:
                payload = response.json()
            except ValueError:
                return self._failure(op.operation, method, response.status_code, "Digistore24 returned a non-JSON response")
            # Failures commonly arrive on HTTP 200. The published result flag is authoritative.
            if isinstance(payload, dict) and (payload.get("result") == "error" or payload.get("status") == "error"):
                message = payload.get("message")
                message = message.replace(key, "[redacted]") if isinstance(message, str) else "Digistore24 rejected this request"
                return {"status": "error", "success": False, "operation": op.operation,
                        "http_status": response.status_code, "code": payload.get("code"), "error": message}
            if not 200 <= response.status_code < 300:
                return self._failure(op.operation, method, response.status_code, "Digistore24 rejected this request")
            if not isinstance(payload, (dict, list)):
                return self._failure(op.operation, method, response.status_code, "Digistore24 returned an unexpected JSON shape")
            # Preserve provider pagination without flattening records.
            data = payload.get("data", payload) if isinstance(payload, dict) and payload.get("result") == "success" else payload
            if op.operation == "get_user_info":
                account = data.get("data", data) if isinstance(data, dict) else None
                if not isinstance(account, dict) or not isinstance(account.get("user_name"), str) or not account["user_name"].strip() or type(account.get("user_id")) is not int or account["user_id"] < 1:
                    return self._failure(op.operation, method, response.status_code, "Digistore24 account identity was not present in the response")
            return {"status": "success", "success": True, "operation": op.operation,
                    "http_status": response.status_code, "data": self._redact(data, key),
                    "write_acknowledged": method != "GET", "readback_verified": False}
        except httpx.HTTPError:
            return self._failure(op.operation, method, None, "Digistore24 request did not complete; inspect writes before retrying")

    @staticmethod
    def _failure(operation, method, status, message):
        return {"status": "error" if method == "GET" or status is not None and 400 <= status < 500 else "unknown",
                "success": False, "operation": operation, "http_status": status, "error": message,
                "write_outcome": "unverified" if method != "GET" else None}

    @classmethod
    def _redact(cls, value, key):
        if isinstance(value, str):
            return value.replace(key, "[redacted]")
        if isinstance(value, list):
            return [cls._redact(item, key) for item in value]
        if isinstance(value, dict):
            return {cls._redact(k, key): cls._redact(v, key) for k, v in value.items()}
        return value

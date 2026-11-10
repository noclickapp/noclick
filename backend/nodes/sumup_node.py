"""SumUp payments, customer sync and reconciliation using a pasted API key.

Reference: https://developer.sumup.com/api
Contract: sumup/sumup-developer OpenAPI 1.0.0, commit
240a391e1c6c2b1d55d3803b0a22ba09958ef877. Each operation is one API call.
Checkout callbacks are supported through return_url; no webhook trigger is
registered here. Creating a checkout does not itself charge a customer.
"""

import time
from datetime import date
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


class SumUpAPIKeyCredential(BaseModel):
    credential_type: Literal["sumup_api_key"] = Field(
        "sumup_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", description="API key from your SumUp Dashboard.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="API Key",
        json_schema_extra={
            "x-credential-url": "https://me.sumup.com/settings/api-keys",
            "x-credential-instructions": "Create an API key in SumUp Dashboard → Settings → API keys, then paste it here. Use a sandbox merchant's key to test without real payments.",
        },
    )


def _operation(name: str, label: str, category: str):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": category, "x-is-trigger": False,
    })


class SumUpMerchantConfig(BaseModel):
    merchant_code: str = Field(..., title="Merchant", min_length=1, description="Merchant account receiving the payment or owning the records.", json_schema_extra={
        "x-dynamic-options": {"field_name": "merchant_code", "allow_custom": True,
                              "searchable": True, "placeholder": "Select a merchant account"},
    })


class SumUpCreateCheckoutConfig(SumUpMerchantConfig):
    operation: Literal["create_checkout"] = _operation("create_checkout", "Create Checkout", "Checkouts")
    checkout_reference: str = Field(..., title="Checkout Reference", min_length=1, max_length=64, description="Your order or payment attempt reference.")
    amount: float = Field(..., title="Amount", gt=0, description="Amount in major currency units, for example 10.10 EUR.")
    currency: str = Field(..., title="Currency", min_length=3, max_length=3, description="Three-letter ISO currency code, for example EUR.")
    description: Optional[str] = Field(None, title="Description")
    customer_id: Optional[str] = Field(None, title="Customer ID")
    purpose: Literal["CHECKOUT", "SETUP_RECURRING_PAYMENT"] = Field("CHECKOUT", title="Purpose")
    hosted_checkout: bool = Field(True, title="Hosted Checkout", description="Request a hosted payment URL where the customer can complete payment.")
    return_url: Optional[str] = Field(None, title="Callback URL", description="Backend URL receiving checkout processing notifications; retrieve the checkout to verify its current status.")
    redirect_url: Optional[str] = Field(None, title="Redirect URL", description="Where to send the payer after redirect or 3DS completion.")
    valid_until: Optional[str] = Field(None, title="Valid Until", description="Optional expiry timestamp in ISO 8601 format.")


class SumUpListCheckoutsConfig(BaseModel):
    operation: Literal["list_checkouts"] = _operation("list_checkouts", "List Checkouts", "Checkouts")
    checkout_reference: Optional[str] = Field(None, title="Checkout Reference", description="Filter by your merchant-defined reference.")


class SumUpCheckoutIDConfig(BaseModel):
    checkout_id: str = Field(..., title="Checkout ID", min_length=1, description="SumUp-generated checkout ID.")


class SumUpGetCheckoutConfig(SumUpCheckoutIDConfig):
    operation: Literal["get_checkout"] = _operation("get_checkout", "Get Checkout", "Checkouts")


class SumUpUpdateCheckoutConfig(SumUpCheckoutIDConfig):
    operation: Literal["update_checkout"] = _operation("update_checkout", "Update Checkout", "Checkouts")
    amount: Optional[float] = Field(None, title="Amount", gt=0)
    currency: Optional[str] = Field(None, title="Currency", min_length=3, max_length=3)
    description: Optional[str] = Field(None, title="Description")
    checkout_reference: Optional[str] = Field(None, title="Checkout Reference", max_length=64)
    valid_until: Optional[str] = Field(None, title="Valid Until", description="Expiry timestamp in ISO 8601 format.")
    customer_id: Optional[str] = Field(None, title="Customer ID")


class SumUpDeactivateCheckoutConfig(SumUpCheckoutIDConfig):
    operation: Literal["deactivate_checkout"] = _operation("deactivate_checkout", "Deactivate Checkout", "Checkouts")


class SumUpCustomerDetailsConfig(BaseModel):
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    email: Optional[str] = Field(None, title="Email")
    phone: Optional[str] = Field(None, title="Phone")
    birth_date: Optional[date] = Field(None, title="Birth Date")
    tax_id: Optional[str] = Field(None, title="Tax ID", max_length=255)


class SumUpCustomerIDConfig(BaseModel):
    customer_id: str = Field(..., title="Customer ID", min_length=1, description="Customer ID supplied by your integration when the customer was created.")


class SumUpCreateCustomerConfig(SumUpCustomerIDConfig, SumUpCustomerDetailsConfig):
    operation: Literal["create_customer"] = _operation("create_customer", "Create Customer", "Customers")


class SumUpGetCustomerConfig(SumUpCustomerIDConfig):
    operation: Literal["get_customer"] = _operation("get_customer", "Get Customer", "Customers")


class SumUpUpdateCustomerConfig(SumUpCustomerIDConfig, SumUpCustomerDetailsConfig):
    operation: Literal["update_customer"] = _operation("update_customer", "Update Customer", "Customers")


class SumUpListPaymentInstrumentsConfig(SumUpCustomerIDConfig):
    operation: Literal["list_payment_instruments"] = _operation("list_payment_instruments", "List Payment Instruments", "Customers")


class SumUpDeactivatePaymentInstrumentConfig(SumUpCustomerIDConfig):
    operation: Literal["deactivate_payment_instrument"] = _operation("deactivate_payment_instrument", "Deactivate Payment Instrument", "Customers")
    token: str = Field(..., title="Payment Instrument Token", min_length=1, description="Saved card token from List Payment Instruments.")


class SumUpRefundTransactionConfig(SumUpMerchantConfig):
    operation: Literal["refund_transaction"] = _operation("refund_transaction", "Refund Transaction", "Transactions")
    transaction_id: str = Field(..., title="Transaction ID", min_length=1)
    amount: Optional[float] = Field(None, title="Refund Amount", gt=0, description="Major currency units. Leave blank to request a full refund.")


class SumUpGetTransactionConfig(SumUpMerchantConfig):
    operation: Literal["get_transaction"] = _operation("get_transaction", "Get Transaction", "Transactions")
    transaction_id: str = Field(..., title="Transaction ID", min_length=1, description="SumUp transaction ID (sent as the id query parameter).")


class SumUpListTransactionsConfig(SumUpMerchantConfig):
    operation: Literal["list_transactions"] = _operation("list_transactions", "List Transactions", "Transactions")
    limit: int = Field(10, title="Limit", ge=1, description="Records per page; response includes pagination links.")
    order: Literal["ascending", "descending"] = Field("ascending", title="Order")
    transaction_code: Optional[str] = Field(None, title="Transaction Code")
    changes_since: Optional[str] = Field(None, title="Changes Since", description="Sync records modified at or after this ISO 8601 timestamp.")
    oldest_time: Optional[str] = Field(None, title="Oldest Time", description="Inclusive creation timestamp in ISO 8601 format.")
    newest_time: Optional[str] = Field(None, title="Newest Time", description="Exclusive creation timestamp in ISO 8601 format.")
    oldest_ref: Optional[str] = Field(None, title="Oldest Reference", description="Copy the reference from a returned pagination link.")
    newest_ref: Optional[str] = Field(None, title="Newest Reference", description="Copy the reference from a returned pagination link.")
    users: Optional[str] = Field(None, title="User Emails", description="Comma-separated user email filters.")
    statuses: Optional[str] = Field(None, title="Statuses", description="Comma-separated: SUCCESSFUL, CANCELLED, FAILED, REFUNDED, CHARGE_BACK.")
    payment_types: Optional[str] = Field(None, title="Payment Types", description="Comma-separated payment types, for example ECOM, POS.")
    entry_modes: Optional[str] = Field(None, title="Entry Modes", description="Comma-separated entry modes, for example CUSTOMER_ENTRY, CHIP.")
    types: Optional[str] = Field(None, title="Transaction Types", description="Comma-separated: PAYMENT, REFUND, CHARGE_BACK.")


class SumUpListPayoutsConfig(SumUpMerchantConfig):
    operation: Literal["list_payouts"] = _operation("list_payouts", "List Payouts", "Reconciliation")
    start_date: date = Field(..., title="Start Date", description="Inclusive payout period start.")
    end_date: date = Field(..., title="End Date", description="Inclusive payout period end.")
    limit: int = Field(10, title="Limit", ge=1, le=9999)
    order: Literal["asc", "desc"] = Field("asc", title="Order")

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class SumUpGetReceiptConfig(SumUpMerchantConfig):
    operation: Literal["get_receipt"] = _operation("get_receipt", "Get Receipt", "Reconciliation")
    transaction_id: str = Field(..., title="Transaction ID", min_length=1)
    tx_event_id: Optional[int] = Field(None, title="Transaction Event ID")


class SumUpListMembershipsConfig(BaseModel):
    operation: Literal["list_memberships"] = _operation("list_memberships", "List Memberships", "Merchant Accounts")
    offset: int = Field(0, title="Offset", ge=0)
    limit: int = Field(10, title="Limit", ge=1, le=25)


class SumUpGetMerchantConfig(SumUpMerchantConfig):
    operation: Literal["get_merchant"] = _operation("get_merchant", "Get Merchant", "Merchant Accounts")


class SumUpGetPaymentMethodsConfig(SumUpMerchantConfig):
    operation: Literal["get_payment_methods"] = _operation("get_payment_methods", "Get Payment Methods", "Checkouts")
    amount: Optional[float] = Field(None, title="Amount", gt=0)
    currency: Optional[str] = Field(None, title="Currency", min_length=3, max_length=3)

    @model_validator(mode="after")
    def currency_for_amount(self):
        if self.amount is not None and self.currency is None:
            raise ValueError("Currency is required when filtering by amount")
        return self


SumUpConfig = Annotated[Union[
    SumUpCreateCheckoutConfig, SumUpListCheckoutsConfig, SumUpGetCheckoutConfig,
    SumUpUpdateCheckoutConfig, SumUpDeactivateCheckoutConfig,
    SumUpCreateCustomerConfig, SumUpGetCustomerConfig, SumUpUpdateCustomerConfig,
    SumUpListPaymentInstrumentsConfig, SumUpDeactivatePaymentInstrumentConfig,
    SumUpRefundTransactionConfig, SumUpGetTransactionConfig, SumUpListTransactionsConfig,
    SumUpListPayoutsConfig, SumUpGetReceiptConfig, SumUpListMembershipsConfig,
    SumUpGetMerchantConfig, SumUpGetPaymentMethodsConfig,
], Field(discriminator="operation")]


class SumUpNodeConfig(NodeConfig[SumUpConfig, SumUpAPIKeyCredential]):
    pass


# Route templates never accept arbitrary URLs. Every user-supplied path segment
# is escaped before interpolation, including opaque saved-payment tokens.
_ROUTES = {
    "create_checkout": ("POST", "/v0.1/checkouts"),
    "list_checkouts": ("GET", "/v0.1/checkouts"),
    "get_checkout": ("GET", "/v0.1/checkouts/{checkout_id}"),
    "update_checkout": ("PATCH", "/v0.1/checkouts/{checkout_id}"),
    "deactivate_checkout": ("DELETE", "/v0.1/checkouts/{checkout_id}"),
    "create_customer": ("POST", "/v0.1/customers"),
    "get_customer": ("GET", "/v0.1/customers/{customer_id}"),
    "update_customer": ("PUT", "/v0.1/customers/{customer_id}"),
    "list_payment_instruments": ("GET", "/v0.1/customers/{customer_id}/payment-instruments"),
    "deactivate_payment_instrument": ("DELETE", "/v0.1/customers/{customer_id}/payment-instruments/{token}"),
    "refund_transaction": ("POST", "/v1.0/merchants/{merchant_code}/payments/{transaction_id}/refunds"),
    "get_transaction": ("GET", "/v2.1/merchants/{merchant_code}/transactions"),
    "list_transactions": ("GET", "/v2.1/merchants/{merchant_code}/transactions/history"),
    "list_payouts": ("GET", "/v1.0/merchants/{merchant_code}/payouts"),
    "get_receipt": ("GET", "/v1.1/receipts/{transaction_id}"),
    "list_memberships": ("GET", "/v0.1/memberships"),
    "get_merchant": ("GET", "/v1/merchants/{merchant_code}"),
    "get_payment_methods": ("GET", "/v0.1/merchants/{merchant_code}/payment-methods"),
}
_PERSONAL_FIELDS = {"first_name", "last_name", "email", "phone", "birth_date", "tax_id"}
_ARRAY_FILTERS = {"users", "statuses", "payment_types", "entry_modes", "types"}


async def _sumup_request(api_key: str, method: str, path: str, action: str,
                         params=None, body=None) -> dict[str, Any]:
    start = time.perf_counter()
    result: dict[str, Any] = {"action": action}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            kwargs = {"params": params} if params else {}
            if body is not None:
                kwargs["json"] = body
            response = await client.request(method, "https://api.sumup.com" + path,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"}, **kwargs)
        result["status_code"] = response.status_code
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection text for credential connection,
            # while removing an echoed secret from errors and avoiding raw HTML.
            message = f"SumUp API request failed (HTTP {response.status_code})"
            try:
                error = response.json()
                if isinstance(error, dict):
                    for key in ("detail", "message", "error_description", "error", "title"):
                        if isinstance(error.get(key), str) and error[key]:
                            message = error[key].replace(api_key, "[redacted]")
                            break
            except ValueError:
                pass
            result.update(status="error", error=message)
        elif response.status_code == 204:
            result.update(status="success", data={"success": True})
        else:
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Unexpected JSON response")
            # A 200 error envelope cannot count as successful account evidence.
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False or data.get("status") in ("error", "failed")):
                result.update(status="error", error="SumUp returned an error response")
            else:
                result.update(status="success", data=data)
    except httpx.TimeoutException:
        result.update(status="error", error="SumUp request timed out")
    except httpx.RequestError:
        result.update(status="error", error="Could not reach the SumUp API")
    except ValueError:
        result.update(status="error", error="SumUp returned an invalid JSON response")
    result["timing_ms"] = {"api_request": round((time.perf_counter() - start) * 1000, 2)}
    return result


class SumUpNode(WorkflowNode):
    integration_type = "automation-sumup"
    credential_provider_labels = {"sumup": "Sumup Account"}
    connection_evidence = ConnectionEvidence(field="merchant_code", noun="merchant accounts")
    edit_examples = [
        "Create a hosted payment checkout for an order",
        "Sync customer details with SumUp",
        "Retrieve transactions changed since yesterday",
        "Refund a customer payment and reconcile payouts",
    ]

    @classmethod
    def get_config_model(cls):
        return SumUpNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "merchant_code" or not credential_data or not credential_data.get("api_key"):
            return {"options": []}
        offset = int(page_token or 0)
        result = await _sumup_request(credential_data["api_key"], "GET", "/v0.1/memberships", "list_memberships",
                                      params={"offset": offset, "limit": 25})
        if result["status"] != "success":
            code = result.get("status_code")
            suffix = f" (HTTP {code})" if code else ""
            raise ValueError(result["error"] + suffix)
        data = result["data"]
        if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("total_count"), int):
            raise ValueError("SumUp returned an invalid memberships response")
        options = []
        for item in data["items"]:
            resource = item.get("resource") if isinstance(item, dict) else None
            if not isinstance(resource, dict) or not resource.get("id") or not resource.get("name"):
                raise ValueError("SumUp returned an invalid membership resource")
            if resource.get("type") == "merchant":
                options.append({"value": resource["id"], "label": resource["name"]})
        if search:
            options = [o for o in options if search.casefold() in o["label"].casefold()]
        next_offset = offset + len(data["items"])
        return {"options": options, "next_page_token": str(next_offset) if data["items"] and next_offset < data["total_count"] else None}

    async def execute(self, inputs):
        start = time.perf_counter()
        if not isinstance(self.config, SumUpNodeConfig):
            raise ValueError("SumUp configuration is required")
        if not self.config.credentials:
            raise ValueError("Connect a SumUp API key in the credentials tab")
        config = self.config.config
        action = config.operation
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        method, template = _ROUTES[action]
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        path_fields = {name for name in values if "{" + name + "}" in template}
        values = {k: v for k, v in values.items() if k not in path_fields}
        params, body = None, None
        if action == "create_checkout":
            # merchant_code belongs in the request body for checkout creation.
            values["hosted_checkout"] = {"enabled": values["hosted_checkout"]}
            body = values
        elif action in ("create_customer", "update_customer"):
            details = {k: v for k, v in values.items() if k in _PERSONAL_FIELDS}
            body = {"personal_details": details}
            if action == "create_customer":
                body["customer_id"] = config.customer_id
        elif action in ("update_checkout", "refund_transaction"):
            body = values
        elif method == "GET":
            if action == "get_transaction":
                values["id"] = values.pop("transaction_id")
            elif action == "get_receipt":
                values["mid"] = values.pop("merchant_code")
            elif action == "list_payouts":
                values["format"] = "json"
            params = []
            for key, value in values.items():
                if key in _ARRAY_FILTERS:
                    params.extend((key + "[]", entry.strip()) for entry in value.split(",") if entry.strip())
                else:
                    params.append((key, value))
        result = await _sumup_request(self.config.credentials.api_key, method, path, action, params=params, body=body)
        # Wrap list responses with descriptive keys for the workflow table view.
        collection = {"list_checkouts": "checkouts", "list_payment_instruments": "payment_instruments",
                      "list_payouts": "payouts"}.get(action)
        if result["status"] == "success" and collection and isinstance(result["data"], list):
            result["data"] = {collection: result["data"]}
        result["timing_ms"]["total"] = round((time.perf_counter() - start) * 1000, 2)
        return result

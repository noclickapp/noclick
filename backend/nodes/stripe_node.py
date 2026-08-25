"""
Stripe REST API automation node.

Provides Stripe operations in workflows via direct REST API calls (httpx),
mirroring the other REST nodes (GitHub / Airtable): typed discriminated-union
operation configs, a ``Union`` multi-auth credential, ``NodeConfig`` binding, and
a dispatch in ``execute()``.

Coverage strategy — Stripe exposes 600+ endpoints, so this node ships ~110 typed
convenience operations across every major product area, driven by a declarative
``_OPERATIONS`` table, PLUS a generic ``custom_request`` operation that reaches
any remaining endpoint. Every write op also accepts an ``extra_params`` object so
Stripe's long tail of per-resource optional parameters is always reachable.

Auth: API key (secret ``sk_`` or restricted ``rk_``) or Connect OAuth — both used
as ``Authorization: Bearer <token>``. An optional ``Stripe-Account`` header targets
a connected account.

API reference: https://docs.stripe.com/api
"""

import hashlib
import hmac
import logging
import re
import time
import uuid
from typing import (
    Annotated,
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.stripe import STRIPE_SCOPES

logger = logging.getLogger(__name__)

STRIPE_HOST = "https://api.stripe.com"
STRIPE_API_BASE = f"{STRIPE_HOST}/v1"


# ============================================================================
# Helpers — auth, form-encoding, webhook registration
# ============================================================================


def _stripe_token_from_credential(credential: Dict[str, Any]) -> Optional[str]:
    """Extract a bearer token from a decrypted Stripe credential (key or OAuth)."""
    cred = credential or {}
    return cred.get("api_key") or cred.get("access_token")


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _flatten_form(value: Any, prefix: str, out: List[Tuple[str, str]]) -> None:
    """Flatten a nested dict/list into Stripe's bracket-notation form pairs.

    e.g. {"metadata": {"k": "v"}, "items": [{"price": "p"}]} ->
         metadata[k]=v, items[0][price]=p
    """
    if value is None:
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            _flatten_form(sub, child, out)
    elif isinstance(value, (list, tuple)):
        for idx, sub in enumerate(value):
            child = f"{prefix}[{idx}]"
            _flatten_form(sub, child, out)
    else:
        out.append((prefix, _stringify(value)))


def _to_form(data: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Convert a params dict into Stripe's form-encoded key/value pairs."""
    pairs: List[Tuple[str, str]] = []
    if not data:
        return pairs
    for key, value in data.items():
        if value is None:
            continue
        _flatten_form(value, str(key), pairs)
    return pairs


async def register_stripe_webhook(
    token: str,
    url: str,
    enabled_events: List[str],
    stripe_account: Optional[str] = None,
) -> Tuple[str, str]:
    """Create a Stripe webhook_endpoint; return (endpoint_id, signing_secret)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    # content= (not data=) — httpx's urlencoded data= path can yield a sync byte
    # stream that an AsyncClient rejects on some interpreter/httpx combos.
    body_str = urlencode(_to_form({"url": url, "enabled_events": enabled_events or ["*"]}))
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{STRIPE_API_BASE}/webhook_endpoints", headers=headers, content=body_str
        )
        if response.status_code >= 400:
            err = (response.json() or {}).get("error", {})
            raise ValueError(err.get("message") or response.text)
        body = response.json()
        return body["id"], body.get("secret", "")


async def unregister_stripe_webhook(
    token: str, endpoint_id: str, stripe_account: Optional[str] = None
) -> None:
    """Delete a Stripe webhook_endpoint. A missing endpoint (404) is treated as done."""
    headers = {"Authorization": f"Bearer {token}"}
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{STRIPE_API_BASE}/webhook_endpoints/{endpoint_id}", headers=headers
        )
        if response.status_code not in (200, 404):
            response.raise_for_status()


# ============================================================================
# Credential Schemas (Union — OAuth shown first in UI)
# ============================================================================


class StripeOAuthCredential(BaseModel):
    """Connect OAuth credential for Stripe ("Connect with Stripe").

    Tokens are obtained via the OAuth flow, not entered manually. Stripe Connect
    access tokens do not expire, so refresh_token/expires_at are optional.

    Register a Connect app at:
    https://dashboard.stripe.com/settings/connect/onboarding-options/oauth
    """

    credential_type: Literal["stripe_oauth"] = Field(
        "stripe_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    stripe_user_id: Optional[str] = Field(None, title="Connected Account ID")
    stripe_publishable_key: Optional[str] = Field(None, title="Publishable Key")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    scope: Optional[str] = Field(None, title="Scope")
    livemode: Optional[bool] = Field(None, title="Live Mode")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "stripe",
            "x-oauth-scopes": ["read_write"],
        }
    )


class StripeApiKeyCredential(BaseModel):
    """API key authentication for the Stripe API.

    Accepts a secret key (``sk_live_…`` / ``sk_test_…``) or a restricted key
    (``rk_…``). Restricted keys are drop-in identical to secret keys.

    Get your API keys at: https://dashboard.stripe.com/apikeys
    """

    credential_type: Literal["stripe_api_key"] = Field(
        "stripe_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Stripe secret (sk_) or restricted (rk_) API key",
        json_schema_extra={"ui:widget": "password"},
    )
    stripe_account: Optional[str] = Field(
        None,
        title="Connected Account ID (optional)",
        description="acct_… to act on behalf of a connected account (Connect)",
    )
    stripe_version: Optional[str] = Field(
        None,
        title="API Version (optional)",
        description="Pin a Stripe API version (e.g. 2024-06-20) for stable behavior. Defaults to your account's version.",
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://dashboard.stripe.com/apikeys"}
    )


# OAuth first so the UI surfaces "Connect with Stripe" above the key form.
StripeCredential = Union[StripeOAuthCredential, StripeApiKeyCredential]


# ============================================================================
# Field factories (keep ~110 operation configs DRY)
# ============================================================================


def _opf(value: str, display: str, category: str, is_trigger: bool = False, creates: Optional[str] = None):
    """Operation discriminator field. ``creates`` names the resource type this
    op mints (e.g. ``stripe_customer``); the new ID is read from ``data.id``."""
    extra: Dict[str, Any] = {
        "ui:hidden": True,
        "x-display-name": display,
        "x-category": category,
        "x-is-trigger": is_trigger,
    }
    if creates:
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = creates
        extra["x-resource-id-path"] = "data.id"
    return Field(
        default=value,
        title=display,
        json_schema_extra=extra,
    )


def _extra():
    return Field(
        None,
        title="Additional Parameters",
        description="Any other Stripe API parameters (key/value); merged into the request.",
    )


def _meta():
    return Field(None, title="Metadata", description="Set of key-value string pairs.")


def _limit():
    return Field(None, title="Limit", description="Max objects to return (1-100).", ge=1, le=100)


def _start():
    return Field(None, title="Starting After", description="Pagination cursor (object ID).")


def _end():
    return Field(None, title="Ending Before", description="Pagination cursor (object ID).")


def _dyn(field_name: str, label: str):
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": f"Select a {label}...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": f"Or paste a {label} ID",
        },
        "x-resource-type": f"stripe_{field_name.removesuffix('_id')}",
    }


def _id(title: str, *, dyn: Optional[str] = None, required: bool = True):
    extra = _dyn(dyn, title.lower()) if dyn else {}
    if required:
        return Field(..., title=title, json_schema_extra=extra)
    return Field(None, title=title, json_schema_extra=extra)


# ============================================================================
# Operation configs — grouped by product area
# ============================================================================


# ---- Customers -------------------------------------------------------------
class StripeCreateCustomerConfig(BaseModel):
    operation: Literal["create_customer"] = _opf("create_customer", "Create Customer", "Customers", creates="stripe_customer")
    email: Optional[str] = Field(None, title="Email")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    phone: Optional[str] = Field(None, title="Phone")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveCustomerConfig(BaseModel):
    operation: Literal["retrieve_customer"] = _opf("retrieve_customer", "Retrieve Customer", "Customers")
    customer_id: str = _id("Customer", dyn="customer_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateCustomerConfig(BaseModel):
    operation: Literal["update_customer"] = _opf("update_customer", "Update Customer", "Customers")
    customer_id: str = _id("Customer", dyn="customer_id")
    email: Optional[str] = Field(None, title="Email")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    phone: Optional[str] = Field(None, title="Phone")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteCustomerConfig(BaseModel):
    operation: Literal["delete_customer"] = _opf("delete_customer", "Delete Customer", "Customers")
    customer_id: str = _id("Customer", dyn="customer_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListCustomersConfig(BaseModel):
    operation: Literal["list_customers"] = _opf("list_customers", "List Customers", "Customers")
    email: Optional[str] = Field(None, title="Email Filter")
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    ending_before: Optional[str] = _end()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchCustomersConfig(BaseModel):
    operation: Literal["search_customers"] = _opf("search_customers", "Search Customers", "Customers")
    query: str = Field(..., title="Query", description="Stripe search query, e.g. email:'a@b.com'")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Payment Intents -------------------------------------------------------
class StripeCreatePaymentIntentConfig(BaseModel):
    operation: Literal["create_payment_intent"] = _opf("create_payment_intent", "Create Payment Intent", "Payments")
    amount: int = Field(..., title="Amount", description="Amount in the smallest currency unit (e.g. cents).")
    currency: str = Field(..., title="Currency", description="Three-letter ISO code, e.g. usd.")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    payment_method: Optional[str] = Field(None, title="Payment Method")
    description: Optional[str] = Field(None, title="Description")
    confirm: Optional[bool] = Field(None, title="Confirm Immediately")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePaymentIntentConfig(BaseModel):
    operation: Literal["retrieve_payment_intent"] = _opf("retrieve_payment_intent", "Retrieve Payment Intent", "Payments")
    payment_intent_id: str = _id("Payment Intent")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePaymentIntentConfig(BaseModel):
    operation: Literal["update_payment_intent"] = _opf("update_payment_intent", "Update Payment Intent", "Payments")
    payment_intent_id: str = _id("Payment Intent")
    amount: Optional[int] = Field(None, title="Amount")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPaymentIntentsConfig(BaseModel):
    operation: Literal["list_payment_intents"] = _opf("list_payment_intents", "List Payment Intents", "Payments")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    ending_before: Optional[str] = _end()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCapturePaymentIntentConfig(BaseModel):
    operation: Literal["capture_payment_intent"] = _opf("capture_payment_intent", "Capture Payment Intent", "Payments")
    payment_intent_id: str = _id("Payment Intent")
    amount_to_capture: Optional[int] = Field(None, title="Amount to Capture")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeConfirmPaymentIntentConfig(BaseModel):
    operation: Literal["confirm_payment_intent"] = _opf("confirm_payment_intent", "Confirm Payment Intent", "Payments")
    payment_intent_id: str = _id("Payment Intent")
    payment_method: Optional[str] = Field(None, title="Payment Method")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelPaymentIntentConfig(BaseModel):
    operation: Literal["cancel_payment_intent"] = _opf("cancel_payment_intent", "Cancel Payment Intent", "Payments")
    payment_intent_id: str = _id("Payment Intent")
    cancellation_reason: Optional[str] = Field(None, title="Cancellation Reason")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchPaymentIntentsConfig(BaseModel):
    operation: Literal["search_payment_intents"] = _opf("search_payment_intents", "Search Payment Intents", "Payments")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Charges ---------------------------------------------------------------
class StripeCreateChargeConfig(BaseModel):
    operation: Literal["create_charge"] = _opf("create_charge", "Create Charge", "Charges")
    amount: int = Field(..., title="Amount")
    currency: str = Field(..., title="Currency")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    source: Optional[str] = Field(None, title="Source")
    description: Optional[str] = Field(None, title="Description")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveChargeConfig(BaseModel):
    operation: Literal["retrieve_charge"] = _opf("retrieve_charge", "Retrieve Charge", "Charges")
    charge_id: str = _id("Charge")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateChargeConfig(BaseModel):
    operation: Literal["update_charge"] = _opf("update_charge", "Update Charge", "Charges")
    charge_id: str = _id("Charge")
    description: Optional[str] = Field(None, title="Description")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListChargesConfig(BaseModel):
    operation: Literal["list_charges"] = _opf("list_charges", "List Charges", "Charges")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    ending_before: Optional[str] = _end()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCaptureChargeConfig(BaseModel):
    operation: Literal["capture_charge"] = _opf("capture_charge", "Capture Charge", "Charges")
    charge_id: str = _id("Charge")
    amount: Optional[int] = Field(None, title="Amount")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchChargesConfig(BaseModel):
    operation: Literal["search_charges"] = _opf("search_charges", "Search Charges", "Charges")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Payment Methods -------------------------------------------------------
class StripeCreatePaymentMethodConfig(BaseModel):
    operation: Literal["create_payment_method"] = _opf("create_payment_method", "Create Payment Method", "Payment Methods")
    type: str = Field(..., title="Type", description="e.g. card, us_bank_account.")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePaymentMethodConfig(BaseModel):
    operation: Literal["retrieve_payment_method"] = _opf("retrieve_payment_method", "Retrieve Payment Method", "Payment Methods")
    payment_method_id: str = _id("Payment Method")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePaymentMethodConfig(BaseModel):
    operation: Literal["update_payment_method"] = _opf("update_payment_method", "Update Payment Method", "Payment Methods")
    payment_method_id: str = _id("Payment Method")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPaymentMethodsConfig(BaseModel):
    operation: Literal["list_payment_methods"] = _opf("list_payment_methods", "List Payment Methods", "Payment Methods")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    type: Optional[str] = Field(None, title="Type")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeAttachPaymentMethodConfig(BaseModel):
    operation: Literal["attach_payment_method"] = _opf("attach_payment_method", "Attach Payment Method", "Payment Methods")
    payment_method_id: str = _id("Payment Method")
    customer: str = Field(..., title="Customer", json_schema_extra=_dyn("customer", "customer"))
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDetachPaymentMethodConfig(BaseModel):
    operation: Literal["detach_payment_method"] = _opf("detach_payment_method", "Detach Payment Method", "Payment Methods")
    payment_method_id: str = _id("Payment Method")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Setup Intents ---------------------------------------------------------
class StripeCreateSetupIntentConfig(BaseModel):
    operation: Literal["create_setup_intent"] = _opf("create_setup_intent", "Create Setup Intent", "Setup Intents")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    payment_method: Optional[str] = Field(None, title="Payment Method")
    confirm: Optional[bool] = Field(None, title="Confirm Immediately")
    usage: Optional[Literal["on_session", "off_session"]] = Field(None, title="Usage")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveSetupIntentConfig(BaseModel):
    operation: Literal["retrieve_setup_intent"] = _opf("retrieve_setup_intent", "Retrieve Setup Intent", "Setup Intents")
    setup_intent_id: str = _id("Setup Intent")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateSetupIntentConfig(BaseModel):
    operation: Literal["update_setup_intent"] = _opf("update_setup_intent", "Update Setup Intent", "Setup Intents")
    setup_intent_id: str = _id("Setup Intent")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListSetupIntentsConfig(BaseModel):
    operation: Literal["list_setup_intents"] = _opf("list_setup_intents", "List Setup Intents", "Setup Intents")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeConfirmSetupIntentConfig(BaseModel):
    operation: Literal["confirm_setup_intent"] = _opf("confirm_setup_intent", "Confirm Setup Intent", "Setup Intents")
    setup_intent_id: str = _id("Setup Intent")
    payment_method: Optional[str] = Field(None, title="Payment Method")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelSetupIntentConfig(BaseModel):
    operation: Literal["cancel_setup_intent"] = _opf("cancel_setup_intent", "Cancel Setup Intent", "Setup Intents")
    setup_intent_id: str = _id("Setup Intent")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Refunds ---------------------------------------------------------------
class StripeCreateRefundConfig(BaseModel):
    operation: Literal["create_refund"] = _opf("create_refund", "Create Refund", "Refunds")
    charge: Optional[str] = Field(None, title="Charge")
    payment_intent: Optional[str] = Field(None, title="Payment Intent")
    amount: Optional[int] = Field(None, title="Amount")
    reason: Optional[Literal["duplicate", "fraudulent", "requested_by_customer"]] = Field(None, title="Reason")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveRefundConfig(BaseModel):
    operation: Literal["retrieve_refund"] = _opf("retrieve_refund", "Retrieve Refund", "Refunds")
    refund_id: str = _id("Refund")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateRefundConfig(BaseModel):
    operation: Literal["update_refund"] = _opf("update_refund", "Update Refund", "Refunds")
    refund_id: str = _id("Refund")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListRefundsConfig(BaseModel):
    operation: Literal["list_refunds"] = _opf("list_refunds", "List Refunds", "Refunds")
    charge: Optional[str] = Field(None, title="Charge")
    payment_intent: Optional[str] = Field(None, title="Payment Intent")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelRefundConfig(BaseModel):
    operation: Literal["cancel_refund"] = _opf("cancel_refund", "Cancel Refund", "Refunds")
    refund_id: str = _id("Refund")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Disputes --------------------------------------------------------------
class StripeRetrieveDisputeConfig(BaseModel):
    operation: Literal["retrieve_dispute"] = _opf("retrieve_dispute", "Retrieve Dispute", "Disputes")
    dispute_id: str = _id("Dispute")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateDisputeConfig(BaseModel):
    operation: Literal["update_dispute"] = _opf("update_dispute", "Update Dispute", "Disputes")
    dispute_id: str = _id("Dispute")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListDisputesConfig(BaseModel):
    operation: Literal["list_disputes"] = _opf("list_disputes", "List Disputes", "Disputes")
    charge: Optional[str] = Field(None, title="Charge")
    payment_intent: Optional[str] = Field(None, title="Payment Intent")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCloseDisputeConfig(BaseModel):
    operation: Literal["close_dispute"] = _opf("close_dispute", "Close Dispute", "Disputes")
    dispute_id: str = _id("Dispute")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Balance ---------------------------------------------------------------
class StripeRetrieveBalanceConfig(BaseModel):
    operation: Literal["retrieve_balance"] = _opf("retrieve_balance", "Retrieve Balance", "Balance")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveBalanceTransactionConfig(BaseModel):
    operation: Literal["retrieve_balance_transaction"] = _opf("retrieve_balance_transaction", "Retrieve Balance Transaction", "Balance")
    balance_transaction_id: str = _id("Balance Transaction")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListBalanceTransactionsConfig(BaseModel):
    operation: Literal["list_balance_transactions"] = _opf("list_balance_transactions", "List Balance Transactions", "Balance")
    type: Optional[str] = Field(None, title="Type")
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Checkout --------------------------------------------------------------
class StripeCreateCheckoutSessionConfig(BaseModel):
    operation: Literal["create_checkout_session"] = _opf("create_checkout_session", "Create Checkout Session", "Checkout")
    mode: Optional[Literal["payment", "subscription", "setup"]] = Field(None, title="Mode")
    success_url: Optional[str] = Field(None, title="Success URL")
    cancel_url: Optional[str] = Field(None, title="Cancel URL")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    line_items: Optional[List[Dict[str, Any]]] = Field(None, title="Line Items", description="List of {price, quantity}.")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveCheckoutSessionConfig(BaseModel):
    operation: Literal["retrieve_checkout_session"] = _opf("retrieve_checkout_session", "Retrieve Checkout Session", "Checkout")
    session_id: str = _id("Checkout Session")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListCheckoutSessionsConfig(BaseModel):
    operation: Literal["list_checkout_sessions"] = _opf("list_checkout_sessions", "List Checkout Sessions", "Checkout")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeExpireCheckoutSessionConfig(BaseModel):
    operation: Literal["expire_checkout_session"] = _opf("expire_checkout_session", "Expire Checkout Session", "Checkout")
    session_id: str = _id("Checkout Session")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListCheckoutLineItemsConfig(BaseModel):
    operation: Literal["list_checkout_line_items"] = _opf("list_checkout_line_items", "List Checkout Line Items", "Checkout")
    session_id: str = _id("Checkout Session")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Payment Links ---------------------------------------------------------
class StripeCreatePaymentLinkConfig(BaseModel):
    operation: Literal["create_payment_link"] = _opf("create_payment_link", "Create Payment Link", "Payment Links")
    line_items: List[Dict[str, Any]] = Field(..., title="Line Items", description="List of {price, quantity}.")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePaymentLinkConfig(BaseModel):
    operation: Literal["retrieve_payment_link"] = _opf("retrieve_payment_link", "Retrieve Payment Link", "Payment Links")
    payment_link_id: str = _id("Payment Link")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePaymentLinkConfig(BaseModel):
    operation: Literal["update_payment_link"] = _opf("update_payment_link", "Update Payment Link", "Payment Links")
    payment_link_id: str = _id("Payment Link")
    active: Optional[bool] = Field(None, title="Active")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPaymentLinksConfig(BaseModel):
    operation: Literal["list_payment_links"] = _opf("list_payment_links", "List Payment Links", "Payment Links")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPaymentLinkLineItemsConfig(BaseModel):
    operation: Literal["list_payment_link_line_items"] = _opf("list_payment_link_line_items", "List Payment Link Line Items", "Payment Links")
    payment_link_id: str = _id("Payment Link")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Products --------------------------------------------------------------
class StripeCreateProductConfig(BaseModel):
    operation: Literal["create_product"] = _opf("create_product", "Create Product", "Products", creates="stripe_product")
    name: str = Field(..., title="Name")
    description: Optional[str] = Field(None, title="Description")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveProductConfig(BaseModel):
    operation: Literal["retrieve_product"] = _opf("retrieve_product", "Retrieve Product", "Products")
    product_id: str = _id("Product", dyn="product_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateProductConfig(BaseModel):
    operation: Literal["update_product"] = _opf("update_product", "Update Product", "Products")
    product_id: str = _id("Product", dyn="product_id")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteProductConfig(BaseModel):
    operation: Literal["delete_product"] = _opf("delete_product", "Delete Product", "Products")
    product_id: str = _id("Product", dyn="product_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListProductsConfig(BaseModel):
    operation: Literal["list_products"] = _opf("list_products", "List Products", "Products")
    active: Optional[bool] = Field(None, title="Active")
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchProductsConfig(BaseModel):
    operation: Literal["search_products"] = _opf("search_products", "Search Products", "Products")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Prices ----------------------------------------------------------------
class StripeCreatePriceConfig(BaseModel):
    operation: Literal["create_price"] = _opf("create_price", "Create Price", "Prices", creates="stripe_price")
    product: Optional[str] = Field(None, title="Product", json_schema_extra=_dyn("product", "product"))
    unit_amount: Optional[int] = Field(None, title="Unit Amount")
    currency: str = Field(..., title="Currency")
    recurring: Optional[Dict[str, Any]] = Field(None, title="Recurring", description="e.g. {interval: month}.")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePriceConfig(BaseModel):
    operation: Literal["retrieve_price"] = _opf("retrieve_price", "Retrieve Price", "Prices")
    price_id: str = _id("Price", dyn="price_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePriceConfig(BaseModel):
    operation: Literal["update_price"] = _opf("update_price", "Update Price", "Prices")
    price_id: str = _id("Price", dyn="price_id")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPricesConfig(BaseModel):
    operation: Literal["list_prices"] = _opf("list_prices", "List Prices", "Prices")
    product: Optional[str] = Field(None, title="Product", json_schema_extra=_dyn("product", "product"))
    active: Optional[bool] = Field(None, title="Active")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchPricesConfig(BaseModel):
    operation: Literal["search_prices"] = _opf("search_prices", "Search Prices", "Prices")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Subscriptions ---------------------------------------------------------
class StripeCreateSubscriptionConfig(BaseModel):
    operation: Literal["create_subscription"] = _opf("create_subscription", "Create Subscription", "Subscriptions", creates="stripe_subscription")
    customer: str = Field(..., title="Customer", json_schema_extra=_dyn("customer", "customer"))
    items: List[Dict[str, Any]] = Field(..., title="Items", description="List of {price, quantity}.")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveSubscriptionConfig(BaseModel):
    operation: Literal["retrieve_subscription"] = _opf("retrieve_subscription", "Retrieve Subscription", "Subscriptions")
    subscription_id: str = _id("Subscription", dyn="subscription_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateSubscriptionConfig(BaseModel):
    operation: Literal["update_subscription"] = _opf("update_subscription", "Update Subscription", "Subscriptions")
    subscription_id: str = _id("Subscription", dyn="subscription_id")
    cancel_at_period_end: Optional[bool] = Field(None, title="Cancel at Period End")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelSubscriptionConfig(BaseModel):
    operation: Literal["cancel_subscription"] = _opf("cancel_subscription", "Cancel Subscription", "Subscriptions")
    subscription_id: str = _id("Subscription", dyn="subscription_id")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListSubscriptionsConfig(BaseModel):
    operation: Literal["list_subscriptions"] = _opf("list_subscriptions", "List Subscriptions", "Subscriptions")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    status: Optional[str] = Field(None, title="Status")
    price: Optional[str] = Field(None, title="Price")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeResumeSubscriptionConfig(BaseModel):
    operation: Literal["resume_subscription"] = _opf("resume_subscription", "Resume Subscription", "Subscriptions")
    subscription_id: str = _id("Subscription", dyn="subscription_id")
    billing_cycle_anchor: Optional[str] = Field(None, title="Billing Cycle Anchor")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchSubscriptionsConfig(BaseModel):
    operation: Literal["search_subscriptions"] = _opf("search_subscriptions", "Search Subscriptions", "Subscriptions")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Subscription Items ----------------------------------------------------
class StripeCreateSubscriptionItemConfig(BaseModel):
    operation: Literal["create_subscription_item"] = _opf("create_subscription_item", "Create Subscription Item", "Subscription Items")
    subscription: str = Field(..., title="Subscription", json_schema_extra=_dyn("subscription", "subscription"))
    price: Optional[str] = Field(None, title="Price")
    quantity: Optional[int] = Field(None, title="Quantity")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveSubscriptionItemConfig(BaseModel):
    operation: Literal["retrieve_subscription_item"] = _opf("retrieve_subscription_item", "Retrieve Subscription Item", "Subscription Items")
    subscription_item_id: str = _id("Subscription Item")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateSubscriptionItemConfig(BaseModel):
    operation: Literal["update_subscription_item"] = _opf("update_subscription_item", "Update Subscription Item", "Subscription Items")
    subscription_item_id: str = _id("Subscription Item")
    price: Optional[str] = Field(None, title="Price")
    quantity: Optional[int] = Field(None, title="Quantity")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteSubscriptionItemConfig(BaseModel):
    operation: Literal["delete_subscription_item"] = _opf("delete_subscription_item", "Delete Subscription Item", "Subscription Items")
    subscription_item_id: str = _id("Subscription Item")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListSubscriptionItemsConfig(BaseModel):
    operation: Literal["list_subscription_items"] = _opf("list_subscription_items", "List Subscription Items", "Subscription Items")
    subscription: str = Field(..., title="Subscription", json_schema_extra=_dyn("subscription", "subscription"))
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Invoices --------------------------------------------------------------
class StripeCreateInvoiceConfig(BaseModel):
    operation: Literal["create_invoice"] = _opf("create_invoice", "Create Invoice", "Invoices")
    customer: str = Field(..., title="Customer", json_schema_extra=_dyn("customer", "customer"))
    subscription: Optional[str] = Field(None, title="Subscription")
    auto_advance: Optional[bool] = Field(None, title="Auto Advance")
    collection_method: Optional[Literal["charge_automatically", "send_invoice"]] = Field(None, title="Collection Method")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveInvoiceConfig(BaseModel):
    operation: Literal["retrieve_invoice"] = _opf("retrieve_invoice", "Retrieve Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateInvoiceConfig(BaseModel):
    operation: Literal["update_invoice"] = _opf("update_invoice", "Update Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteInvoiceConfig(BaseModel):
    operation: Literal["delete_invoice"] = _opf("delete_invoice", "Delete Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListInvoicesConfig(BaseModel):
    operation: Literal["list_invoices"] = _opf("list_invoices", "List Invoices", "Invoices")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    subscription: Optional[str] = Field(None, title="Subscription")
    status: Optional[str] = Field(None, title="Status")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeFinalizeInvoiceConfig(BaseModel):
    operation: Literal["finalize_invoice"] = _opf("finalize_invoice", "Finalize Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    auto_advance: Optional[bool] = Field(None, title="Auto Advance")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripePayInvoiceConfig(BaseModel):
    operation: Literal["pay_invoice"] = _opf("pay_invoice", "Pay Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSendInvoiceConfig(BaseModel):
    operation: Literal["send_invoice"] = _opf("send_invoice", "Send Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeVoidInvoiceConfig(BaseModel):
    operation: Literal["void_invoice"] = _opf("void_invoice", "Void Invoice", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeMarkUncollectibleInvoiceConfig(BaseModel):
    operation: Literal["mark_uncollectible_invoice"] = _opf("mark_uncollectible_invoice", "Mark Invoice Uncollectible", "Invoices")
    invoice_id: str = _id("Invoice")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeSearchInvoicesConfig(BaseModel):
    operation: Literal["search_invoices"] = _opf("search_invoices", "Search Invoices", "Invoices")
    query: str = Field(..., title="Query")
    limit: Optional[int] = _limit()
    page: Optional[str] = Field(None, title="Page Cursor")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Invoice Items ---------------------------------------------------------
class StripeCreateInvoiceItemConfig(BaseModel):
    operation: Literal["create_invoice_item"] = _opf("create_invoice_item", "Create Invoice Item", "Invoice Items")
    customer: str = Field(..., title="Customer", json_schema_extra=_dyn("customer", "customer"))
    amount: Optional[int] = Field(None, title="Amount")
    currency: Optional[str] = Field(None, title="Currency")
    description: Optional[str] = Field(None, title="Description")
    invoice: Optional[str] = Field(None, title="Invoice")
    price: Optional[str] = Field(None, title="Price")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveInvoiceItemConfig(BaseModel):
    operation: Literal["retrieve_invoice_item"] = _opf("retrieve_invoice_item", "Retrieve Invoice Item", "Invoice Items")
    invoice_item_id: str = _id("Invoice Item")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateInvoiceItemConfig(BaseModel):
    operation: Literal["update_invoice_item"] = _opf("update_invoice_item", "Update Invoice Item", "Invoice Items")
    invoice_item_id: str = _id("Invoice Item")
    amount: Optional[int] = Field(None, title="Amount")
    description: Optional[str] = Field(None, title="Description")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteInvoiceItemConfig(BaseModel):
    operation: Literal["delete_invoice_item"] = _opf("delete_invoice_item", "Delete Invoice Item", "Invoice Items")
    invoice_item_id: str = _id("Invoice Item")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListInvoiceItemsConfig(BaseModel):
    operation: Literal["list_invoice_items"] = _opf("list_invoice_items", "List Invoice Items", "Invoice Items")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    invoice: Optional[str] = Field(None, title="Invoice")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Credit Notes ----------------------------------------------------------
class StripeCreateCreditNoteConfig(BaseModel):
    operation: Literal["create_credit_note"] = _opf("create_credit_note", "Create Credit Note", "Credit Notes")
    invoice: str = Field(..., title="Invoice")
    amount: Optional[int] = Field(None, title="Amount")
    memo: Optional[str] = Field(None, title="Memo")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveCreditNoteConfig(BaseModel):
    operation: Literal["retrieve_credit_note"] = _opf("retrieve_credit_note", "Retrieve Credit Note", "Credit Notes")
    credit_note_id: str = _id("Credit Note")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateCreditNoteConfig(BaseModel):
    operation: Literal["update_credit_note"] = _opf("update_credit_note", "Update Credit Note", "Credit Notes")
    credit_note_id: str = _id("Credit Note")
    memo: Optional[str] = Field(None, title="Memo")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListCreditNotesConfig(BaseModel):
    operation: Literal["list_credit_notes"] = _opf("list_credit_notes", "List Credit Notes", "Credit Notes")
    invoice: Optional[str] = Field(None, title="Invoice")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeVoidCreditNoteConfig(BaseModel):
    operation: Literal["void_credit_note"] = _opf("void_credit_note", "Void Credit Note", "Credit Notes")
    credit_note_id: str = _id("Credit Note")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Coupons ---------------------------------------------------------------
class StripeCreateCouponConfig(BaseModel):
    operation: Literal["create_coupon"] = _opf("create_coupon", "Create Coupon", "Coupons")
    duration: Literal["forever", "once", "repeating"] = Field(..., title="Duration")
    percent_off: Optional[float] = Field(None, title="Percent Off")
    amount_off: Optional[int] = Field(None, title="Amount Off")
    currency: Optional[str] = Field(None, title="Currency")
    name: Optional[str] = Field(None, title="Name")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveCouponConfig(BaseModel):
    operation: Literal["retrieve_coupon"] = _opf("retrieve_coupon", "Retrieve Coupon", "Coupons")
    coupon_id: str = _id("Coupon")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateCouponConfig(BaseModel):
    operation: Literal["update_coupon"] = _opf("update_coupon", "Update Coupon", "Coupons")
    coupon_id: str = _id("Coupon")
    name: Optional[str] = Field(None, title="Name")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteCouponConfig(BaseModel):
    operation: Literal["delete_coupon"] = _opf("delete_coupon", "Delete Coupon", "Coupons")
    coupon_id: str = _id("Coupon")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListCouponsConfig(BaseModel):
    operation: Literal["list_coupons"] = _opf("list_coupons", "List Coupons", "Coupons")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Promotion Codes -------------------------------------------------------
class StripeCreatePromotionCodeConfig(BaseModel):
    operation: Literal["create_promotion_code"] = _opf("create_promotion_code", "Create Promotion Code", "Promotion Codes")
    coupon: str = Field(..., title="Coupon")
    code: Optional[str] = Field(None, title="Code")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePromotionCodeConfig(BaseModel):
    operation: Literal["retrieve_promotion_code"] = _opf("retrieve_promotion_code", "Retrieve Promotion Code", "Promotion Codes")
    promotion_code_id: str = _id("Promotion Code")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePromotionCodeConfig(BaseModel):
    operation: Literal["update_promotion_code"] = _opf("update_promotion_code", "Update Promotion Code", "Promotion Codes")
    promotion_code_id: str = _id("Promotion Code")
    active: Optional[bool] = Field(None, title="Active")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPromotionCodesConfig(BaseModel):
    operation: Literal["list_promotion_codes"] = _opf("list_promotion_codes", "List Promotion Codes", "Promotion Codes")
    coupon: Optional[str] = Field(None, title="Coupon")
    code: Optional[str] = Field(None, title="Code")
    active: Optional[bool] = Field(None, title="Active")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Quotes ----------------------------------------------------------------
class StripeCreateQuoteConfig(BaseModel):
    operation: Literal["create_quote"] = _opf("create_quote", "Create Quote", "Quotes")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    line_items: Optional[List[Dict[str, Any]]] = Field(None, title="Line Items")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveQuoteConfig(BaseModel):
    operation: Literal["retrieve_quote"] = _opf("retrieve_quote", "Retrieve Quote", "Quotes")
    quote_id: str = _id("Quote")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateQuoteConfig(BaseModel):
    operation: Literal["update_quote"] = _opf("update_quote", "Update Quote", "Quotes")
    quote_id: str = _id("Quote")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListQuotesConfig(BaseModel):
    operation: Literal["list_quotes"] = _opf("list_quotes", "List Quotes", "Quotes")
    customer: Optional[str] = Field(None, title="Customer", json_schema_extra=_dyn("customer", "customer"))
    status: Optional[str] = Field(None, title="Status")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeFinalizeQuoteConfig(BaseModel):
    operation: Literal["finalize_quote"] = _opf("finalize_quote", "Finalize Quote", "Quotes")
    quote_id: str = _id("Quote")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeAcceptQuoteConfig(BaseModel):
    operation: Literal["accept_quote"] = _opf("accept_quote", "Accept Quote", "Quotes")
    quote_id: str = _id("Quote")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelQuoteConfig(BaseModel):
    operation: Literal["cancel_quote"] = _opf("cancel_quote", "Cancel Quote", "Quotes")
    quote_id: str = _id("Quote")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Tax Rates -------------------------------------------------------------
class StripeCreateTaxRateConfig(BaseModel):
    operation: Literal["create_tax_rate"] = _opf("create_tax_rate", "Create Tax Rate", "Tax Rates")
    display_name: str = Field(..., title="Display Name")
    percentage: float = Field(..., title="Percentage")
    inclusive: bool = Field(..., title="Inclusive")
    jurisdiction: Optional[str] = Field(None, title="Jurisdiction")
    active: Optional[bool] = Field(None, title="Active")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveTaxRateConfig(BaseModel):
    operation: Literal["retrieve_tax_rate"] = _opf("retrieve_tax_rate", "Retrieve Tax Rate", "Tax Rates")
    tax_rate_id: str = _id("Tax Rate")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateTaxRateConfig(BaseModel):
    operation: Literal["update_tax_rate"] = _opf("update_tax_rate", "Update Tax Rate", "Tax Rates")
    tax_rate_id: str = _id("Tax Rate")
    active: Optional[bool] = Field(None, title="Active")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListTaxRatesConfig(BaseModel):
    operation: Literal["list_tax_rates"] = _opf("list_tax_rates", "List Tax Rates", "Tax Rates")
    active: Optional[bool] = Field(None, title="Active")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Billing Portal --------------------------------------------------------
class StripeCreateBillingPortalSessionConfig(BaseModel):
    operation: Literal["create_billing_portal_session"] = _opf("create_billing_portal_session", "Create Billing Portal Session", "Billing Portal")
    customer: str = Field(..., title="Customer", json_schema_extra=_dyn("customer", "customer"))
    return_url: Optional[str] = Field(None, title="Return URL")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Connect: Accounts -----------------------------------------------------
class StripeCreateAccountConfig(BaseModel):
    operation: Literal["create_account"] = _opf("create_account", "Create Account", "Connect")
    type: Optional[Literal["standard", "express", "custom"]] = Field(None, title="Type")
    country: Optional[str] = Field(None, title="Country")
    email: Optional[str] = Field(None, title="Email")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveAccountConfig(BaseModel):
    operation: Literal["retrieve_account"] = _opf("retrieve_account", "Retrieve Account", "Connect")
    account_id: str = _id("Account")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateAccountConfig(BaseModel):
    operation: Literal["update_account"] = _opf("update_account", "Update Account", "Connect")
    account_id: str = _id("Account")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteAccountConfig(BaseModel):
    operation: Literal["delete_account"] = _opf("delete_account", "Delete Account", "Connect")
    account_id: str = _id("Account")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListAccountsConfig(BaseModel):
    operation: Literal["list_accounts"] = _opf("list_accounts", "List Accounts", "Connect")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRejectAccountConfig(BaseModel):
    operation: Literal["reject_account"] = _opf("reject_account", "Reject Account", "Connect")
    account_id: str = _id("Account")
    reason: str = Field(..., title="Reason", description="e.g. fraud, terms_of_service, other.")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCreateAccountLinkConfig(BaseModel):
    operation: Literal["create_account_link"] = _opf("create_account_link", "Create Account Link", "Connect")
    account: str = Field(..., title="Account")
    refresh_url: Optional[str] = Field(None, title="Refresh URL")
    return_url: Optional[str] = Field(None, title="Return URL")
    type: Optional[str] = Field(None, title="Type", description="e.g. account_onboarding.")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCreateLoginLinkConfig(BaseModel):
    operation: Literal["create_login_link"] = _opf("create_login_link", "Create Login Link", "Connect")
    account_id: str = _id("Account")
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Connect: Transfers / Payouts / Top-ups / Fees -------------------------
class StripeCreateTransferConfig(BaseModel):
    operation: Literal["create_transfer"] = _opf("create_transfer", "Create Transfer", "Connect")
    amount: int = Field(..., title="Amount")
    currency: str = Field(..., title="Currency")
    destination: str = Field(..., title="Destination Account")
    transfer_group: Optional[str] = Field(None, title="Transfer Group")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveTransferConfig(BaseModel):
    operation: Literal["retrieve_transfer"] = _opf("retrieve_transfer", "Retrieve Transfer", "Connect")
    transfer_id: str = _id("Transfer")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateTransferConfig(BaseModel):
    operation: Literal["update_transfer"] = _opf("update_transfer", "Update Transfer", "Connect")
    transfer_id: str = _id("Transfer")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListTransfersConfig(BaseModel):
    operation: Literal["list_transfers"] = _opf("list_transfers", "List Transfers", "Connect")
    destination: Optional[str] = Field(None, title="Destination")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCreatePayoutConfig(BaseModel):
    operation: Literal["create_payout"] = _opf("create_payout", "Create Payout", "Connect")
    amount: int = Field(..., title="Amount")
    currency: str = Field(..., title="Currency")
    method: Optional[Literal["standard", "instant"]] = Field(None, title="Method")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrievePayoutConfig(BaseModel):
    operation: Literal["retrieve_payout"] = _opf("retrieve_payout", "Retrieve Payout", "Connect")
    payout_id: str = _id("Payout")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdatePayoutConfig(BaseModel):
    operation: Literal["update_payout"] = _opf("update_payout", "Update Payout", "Connect")
    payout_id: str = _id("Payout")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListPayoutsConfig(BaseModel):
    operation: Literal["list_payouts"] = _opf("list_payouts", "List Payouts", "Connect")
    status: Optional[str] = Field(None, title="Status")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelPayoutConfig(BaseModel):
    operation: Literal["cancel_payout"] = _opf("cancel_payout", "Cancel Payout", "Connect")
    payout_id: str = _id("Payout")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeReversePayoutConfig(BaseModel):
    operation: Literal["reverse_payout"] = _opf("reverse_payout", "Reverse Payout", "Connect")
    payout_id: str = _id("Payout")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCreateTopupConfig(BaseModel):
    operation: Literal["create_topup"] = _opf("create_topup", "Create Top-up", "Connect")
    amount: int = Field(..., title="Amount")
    currency: str = Field(..., title="Currency")
    description: Optional[str] = Field(None, title="Description")
    statement_descriptor: Optional[str] = Field(None, title="Statement Descriptor")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveTopupConfig(BaseModel):
    operation: Literal["retrieve_topup"] = _opf("retrieve_topup", "Retrieve Top-up", "Connect")
    topup_id: str = _id("Top-up")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListTopupsConfig(BaseModel):
    operation: Literal["list_topups"] = _opf("list_topups", "List Top-ups", "Connect")
    status: Optional[str] = Field(None, title="Status")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCancelTopupConfig(BaseModel):
    operation: Literal["cancel_topup"] = _opf("cancel_topup", "Cancel Top-up", "Connect")
    topup_id: str = _id("Top-up")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveApplicationFeeConfig(BaseModel):
    operation: Literal["retrieve_application_fee"] = _opf("retrieve_application_fee", "Retrieve Application Fee", "Connect")
    fee_id: str = _id("Application Fee")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListApplicationFeesConfig(BaseModel):
    operation: Literal["list_application_fees"] = _opf("list_application_fees", "List Application Fees", "Connect")
    charge: Optional[str] = Field(None, title="Charge")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Events ----------------------------------------------------------------
class StripeRetrieveEventConfig(BaseModel):
    operation: Literal["retrieve_event"] = _opf("retrieve_event", "Retrieve Event", "Events")
    event_id: str = _id("Event")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListEventsConfig(BaseModel):
    operation: Literal["list_events"] = _opf("list_events", "List Events", "Events")
    type: Optional[str] = Field(None, title="Type", description="Event type filter, e.g. invoice.paid.")
    limit: Optional[int] = _limit()
    starting_after: Optional[str] = _start()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Webhook Endpoints -----------------------------------------------------
class StripeCreateWebhookEndpointConfig(BaseModel):
    operation: Literal["create_webhook_endpoint"] = _opf("create_webhook_endpoint", "Create Webhook Endpoint", "Webhooks")
    url: str = Field(..., title="URL")
    enabled_events: List[str] = Field(..., title="Enabled Events", description="Event types, or ['*'] for all.")
    description: Optional[str] = Field(None, title="Description")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveWebhookEndpointConfig(BaseModel):
    operation: Literal["retrieve_webhook_endpoint"] = _opf("retrieve_webhook_endpoint", "Retrieve Webhook Endpoint", "Webhooks")
    webhook_endpoint_id: str = _id("Webhook Endpoint")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateWebhookEndpointConfig(BaseModel):
    operation: Literal["update_webhook_endpoint"] = _opf("update_webhook_endpoint", "Update Webhook Endpoint", "Webhooks")
    webhook_endpoint_id: str = _id("Webhook Endpoint")
    url: Optional[str] = Field(None, title="URL")
    enabled_events: Optional[List[str]] = Field(None, title="Enabled Events")
    disabled: Optional[bool] = Field(None, title="Disabled")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeDeleteWebhookEndpointConfig(BaseModel):
    operation: Literal["delete_webhook_endpoint"] = _opf("delete_webhook_endpoint", "Delete Webhook Endpoint", "Webhooks")
    webhook_endpoint_id: str = _id("Webhook Endpoint")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListWebhookEndpointsConfig(BaseModel):
    operation: Literal["list_webhook_endpoints"] = _opf("list_webhook_endpoints", "List Webhook Endpoints", "Webhooks")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Files / File Links ----------------------------------------------------
class StripeRetrieveFileConfig(BaseModel):
    operation: Literal["retrieve_file"] = _opf("retrieve_file", "Retrieve File", "Files")
    file_id: str = _id("File")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListFilesConfig(BaseModel):
    operation: Literal["list_files"] = _opf("list_files", "List Files", "Files")
    purpose: Optional[str] = Field(None, title="Purpose")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeCreateFileLinkConfig(BaseModel):
    operation: Literal["create_file_link"] = _opf("create_file_link", "Create File Link", "Files")
    file: str = Field(..., title="File")
    expires_at: Optional[int] = Field(None, title="Expires At (unix)")
    metadata: Optional[Dict[str, str]] = _meta()
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeRetrieveFileLinkConfig(BaseModel):
    operation: Literal["retrieve_file_link"] = _opf("retrieve_file_link", "Retrieve File Link", "Files")
    file_link_id: str = _id("File Link")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeUpdateFileLinkConfig(BaseModel):
    operation: Literal["update_file_link"] = _opf("update_file_link", "Update File Link", "Files")
    file_link_id: str = _id("File Link")
    extra_params: Optional[Dict[str, Any]] = _extra()


class StripeListFileLinksConfig(BaseModel):
    operation: Literal["list_file_links"] = _opf("list_file_links", "List File Links", "Files")
    file: Optional[str] = Field(None, title="File")
    limit: Optional[int] = _limit()
    extra_params: Optional[Dict[str, Any]] = _extra()


# ---- Generic Custom Request (reaches any endpoint) -------------------------
class StripeCustomRequestConfig(BaseModel):
    operation: Literal["custom_request"] = _opf("custom_request", "Custom API Request", "Advanced")
    http_method: Literal["GET", "POST", "DELETE"] = Field("GET", title="HTTP Method")
    path: str = Field(
        ...,
        title="Path",
        description="Stripe API path, e.g. /charges or /issuing/cards (the /v1 prefix is optional). Use a /v2/... path for the newer JSON-encoded v2 API.",
    )
    params: Optional[Dict[str, Any]] = Field(
        None, title="Parameters", description="Body params (POST/DELETE) or query params (GET)."
    )
    stripe_account: Optional[str] = Field(None, title="Stripe-Account (acct_…)")
    idempotency_key: Optional[str] = Field(None, title="Idempotency Key")
    stripe_version: Optional[str] = Field(None, title="Stripe-Version (optional)")


# ---- Trigger ---------------------------------------------------------------
def _stripe_trigger_field(value: str, display: str, keywords: Optional[List[str]] = None):
    """Hidden ``operation`` discriminator Field for a per-event Stripe trigger."""
    extra: Dict[str, Any] = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(default=value, title=display, json_schema_extra=extra)


class _StripeEventTriggerBase(WebhookTriggerConfigBase):
    """Shared fields for Stripe per-event triggers. Each trigger op is a separate
    operation; the Stripe event it listens for is resolved via ``_TRIGGER_EVENTS``.
    Hidden webhook lifecycle fields are inherited from WebhookTriggerConfigBase."""

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class StripeOnEventConfig(_StripeEventTriggerBase):
    """Trigger: fires on any Stripe event matching a custom allowlist (escape hatch
    for the long tail of event types not in the decomposed list)."""

    operation: Literal["on_event"] = _stripe_trigger_field(
        "on_event", "On Custom Event", keywords=["custom", "any", "all", "advanced"]
    )
    event_types: Optional[str] = Field(
        None,
        title="Event Types",
        description="Comma-separated Stripe event types to listen for (e.g. radar.early_fraud_warning.created). Leave empty for all events.",
    )


# Decomposed per-event triggers — one operation per Stripe event type, mirroring
# the other nodes' trigger decomposition. (class_name, operation, display, event_type)
_TRIGGER_SPECS: List[Tuple[str, str, str, str]] = [
    # Payments
    ("StripeOnPaymentSucceededConfig", "on_payment_intent_succeeded", "On Payment Succeeded", "payment_intent.succeeded"),
    ("StripeOnPaymentFailedConfig", "on_payment_intent_payment_failed", "On Payment Failed", "payment_intent.payment_failed"),
    ("StripeOnPaymentIntentCreatedConfig", "on_payment_intent_created", "On Payment Intent Created", "payment_intent.created"),
    ("StripeOnPaymentIntentCanceledConfig", "on_payment_intent_canceled", "On Payment Intent Canceled", "payment_intent.canceled"),
    ("StripeOnPaymentProcessingConfig", "on_payment_intent_processing", "On Payment Processing", "payment_intent.processing"),
    ("StripeOnPaymentRequiresActionConfig", "on_payment_intent_requires_action", "On Payment Requires Action", "payment_intent.requires_action"),
    # Charges
    ("StripeOnChargeSucceededConfig", "on_charge_succeeded", "On Charge Succeeded", "charge.succeeded"),
    ("StripeOnChargeFailedConfig", "on_charge_failed", "On Charge Failed", "charge.failed"),
    ("StripeOnChargeRefundedConfig", "on_charge_refunded", "On Charge Refunded", "charge.refunded"),
    ("StripeOnChargeCapturedConfig", "on_charge_captured", "On Charge Captured", "charge.captured"),
    ("StripeOnChargeUpdatedConfig", "on_charge_updated", "On Charge Updated", "charge.updated"),
    # Disputes
    ("StripeOnDisputeCreatedConfig", "on_charge_dispute_created", "On Dispute Created", "charge.dispute.created"),
    ("StripeOnDisputeUpdatedConfig", "on_charge_dispute_updated", "On Dispute Updated", "charge.dispute.updated"),
    ("StripeOnDisputeClosedConfig", "on_charge_dispute_closed", "On Dispute Closed", "charge.dispute.closed"),
    ("StripeOnDisputeFundsWithdrawnConfig", "on_charge_dispute_funds_withdrawn", "On Dispute Funds Withdrawn", "charge.dispute.funds_withdrawn"),
    # Refunds
    ("StripeOnRefundUpdatedConfig", "on_charge_refund_updated", "On Refund Updated", "charge.refund.updated"),
    # Checkout
    ("StripeOnCheckoutCompletedConfig", "on_checkout_session_completed", "On Checkout Completed", "checkout.session.completed"),
    ("StripeOnCheckoutExpiredConfig", "on_checkout_session_expired", "On Checkout Expired", "checkout.session.expired"),
    ("StripeOnCheckoutAsyncSucceededConfig", "on_checkout_session_async_payment_succeeded", "On Checkout Async Payment Succeeded", "checkout.session.async_payment_succeeded"),
    ("StripeOnCheckoutAsyncFailedConfig", "on_checkout_session_async_payment_failed", "On Checkout Async Payment Failed", "checkout.session.async_payment_failed"),
    # Customers
    ("StripeOnCustomerCreatedConfig", "on_customer_created", "On Customer Created", "customer.created"),
    ("StripeOnCustomerUpdatedConfig", "on_customer_updated", "On Customer Updated", "customer.updated"),
    ("StripeOnCustomerDeletedConfig", "on_customer_deleted", "On Customer Deleted", "customer.deleted"),
    # Subscriptions
    ("StripeOnSubscriptionCreatedConfig", "on_customer_subscription_created", "On Subscription Created", "customer.subscription.created"),
    ("StripeOnSubscriptionUpdatedConfig", "on_customer_subscription_updated", "On Subscription Updated", "customer.subscription.updated"),
    ("StripeOnSubscriptionDeletedConfig", "on_customer_subscription_deleted", "On Subscription Canceled", "customer.subscription.deleted"),
    ("StripeOnSubscriptionTrialEndingConfig", "on_customer_subscription_trial_will_end", "On Trial Will End", "customer.subscription.trial_will_end"),
    ("StripeOnSubscriptionPausedConfig", "on_customer_subscription_paused", "On Subscription Paused", "customer.subscription.paused"),
    ("StripeOnSubscriptionResumedConfig", "on_customer_subscription_resumed", "On Subscription Resumed", "customer.subscription.resumed"),
    # Invoices
    ("StripeOnInvoiceCreatedConfig", "on_invoice_created", "On Invoice Created", "invoice.created"),
    ("StripeOnInvoiceFinalizedConfig", "on_invoice_finalized", "On Invoice Finalized", "invoice.finalized"),
    ("StripeOnInvoicePaidConfig", "on_invoice_paid", "On Invoice Paid", "invoice.paid"),
    ("StripeOnInvoicePaymentSucceededConfig", "on_invoice_payment_succeeded", "On Invoice Payment Succeeded", "invoice.payment_succeeded"),
    ("StripeOnInvoicePaymentFailedConfig", "on_invoice_payment_failed", "On Invoice Payment Failed", "invoice.payment_failed"),
    ("StripeOnInvoicePaymentActionRequiredConfig", "on_invoice_payment_action_required", "On Invoice Payment Action Required", "invoice.payment_action_required"),
    ("StripeOnInvoiceUpcomingConfig", "on_invoice_upcoming", "On Upcoming Invoice", "invoice.upcoming"),
    ("StripeOnInvoiceUncollectibleConfig", "on_invoice_marked_uncollectible", "On Invoice Uncollectible", "invoice.marked_uncollectible"),
    ("StripeOnInvoiceVoidedConfig", "on_invoice_voided", "On Invoice Voided", "invoice.voided"),
    # Products / Prices
    ("StripeOnProductCreatedConfig", "on_product_created", "On Product Created", "product.created"),
    ("StripeOnProductUpdatedConfig", "on_product_updated", "On Product Updated", "product.updated"),
    ("StripeOnProductDeletedConfig", "on_product_deleted", "On Product Deleted", "product.deleted"),
    ("StripeOnPriceCreatedConfig", "on_price_created", "On Price Created", "price.created"),
    ("StripeOnPriceUpdatedConfig", "on_price_updated", "On Price Updated", "price.updated"),
    # Payouts
    ("StripeOnPayoutCreatedConfig", "on_payout_created", "On Payout Created", "payout.created"),
    ("StripeOnPayoutPaidConfig", "on_payout_paid", "On Payout Paid", "payout.paid"),
    ("StripeOnPayoutFailedConfig", "on_payout_failed", "On Payout Failed", "payout.failed"),
    # Payment Methods / Setup Intents
    ("StripeOnPaymentMethodAttachedConfig", "on_payment_method_attached", "On Payment Method Attached", "payment_method.attached"),
    ("StripeOnPaymentMethodDetachedConfig", "on_payment_method_detached", "On Payment Method Detached", "payment_method.detached"),
    ("StripeOnSetupIntentSucceededConfig", "on_setup_intent_succeeded", "On Setup Intent Succeeded", "setup_intent.succeeded"),
    ("StripeOnSetupIntentFailedConfig", "on_setup_intent_setup_failed", "On Setup Intent Failed", "setup_intent.setup_failed"),
    # Connect
    ("StripeOnAccountUpdatedConfig", "on_account_updated", "On Connected Account Updated", "account.updated"),
    ("StripeOnAccountDeauthorizedConfig", "on_account_application_deauthorized", "On Account Deauthorized", "account.application.deauthorized"),
    # Radar / Quotes
    ("StripeOnReviewOpenedConfig", "on_review_opened", "On Radar Review Opened", "review.opened"),
    ("StripeOnReviewClosedConfig", "on_review_closed", "On Radar Review Closed", "review.closed"),
    ("StripeOnQuoteAcceptedConfig", "on_quote_accepted", "On Quote Accepted", "quote.accepted"),
]


def _make_trigger_model(class_name: str, op: str, display: str, event_type: str):
    fields = {
        "operation": (
            Literal[op],
            _stripe_trigger_field(op, display, keywords=[event_type, event_type.replace(".", " ")]),
        )
    }
    return create_model(class_name, __base__=_StripeEventTriggerBase, **fields)


_TRIGGER_MODELS: List[Any] = []
_TRIGGER_EVENTS: Dict[str, str] = {}  # operation -> Stripe event type
for _cn, _op, _disp, _evt in _TRIGGER_SPECS:
    _TRIGGER_MODELS.append(_make_trigger_model(_cn, _op, _disp, _evt))
    _TRIGGER_EVENTS[_op] = _evt
# All trigger operations (decomposed per-event + the generic custom-event op).
_TRIGGER_OPERATIONS = set(_TRIGGER_EVENTS) | {"on_event"}


# ============================================================================
# Discriminated union + node config
# ============================================================================

# ============================================================================
# Extended operations — full long-tail coverage of every Stripe product suite.
# Generated from a spec table so each endpoint is a first-class typed operation
# routed through the same dispatch. Operation names are globally unique
# (suite-namespaced where needed). Each op also accepts ``extra_params`` for the
# resource's optional fields; list ops add limit/starting_after.
#   (class_name, operation, display_name, category, http_method, path_template)
# ============================================================================

_EXTENDED_SPECS: List[Tuple[str, str, str, str, str, str]] = [
    # ---- Subscription Schedules ----
    ("StripeCreateSubscriptionScheduleConfig", "create_subscription_schedule", "Create Subscription Schedule", "Subscription Schedules", "POST", "/subscription_schedules"),
    ("StripeListSubscriptionSchedulesConfig", "list_subscription_schedules", "List Subscription Schedules", "Subscription Schedules", "GET", "/subscription_schedules"),
    ("StripeRetrieveSubscriptionScheduleConfig", "retrieve_subscription_schedule", "Retrieve Subscription Schedule", "Subscription Schedules", "GET", "/subscription_schedules/{schedule_id}"),
    ("StripeUpdateSubscriptionScheduleConfig", "update_subscription_schedule", "Update Subscription Schedule", "Subscription Schedules", "POST", "/subscription_schedules/{schedule_id}"),
    ("StripeCancelSubscriptionScheduleConfig", "cancel_subscription_schedule", "Cancel Subscription Schedule", "Subscription Schedules", "POST", "/subscription_schedules/{schedule_id}/cancel"),
    ("StripeReleaseSubscriptionScheduleConfig", "release_subscription_schedule", "Release Subscription Schedule", "Subscription Schedules", "POST", "/subscription_schedules/{schedule_id}/release"),
    # ---- Shipping Rates ----
    ("StripeCreateShippingRateConfig", "create_shipping_rate", "Create Shipping Rate", "Shipping Rates", "POST", "/shipping_rates"),
    ("StripeRetrieveShippingRateConfig", "retrieve_shipping_rate", "Retrieve Shipping Rate", "Shipping Rates", "GET", "/shipping_rates/{rate_id}"),
    ("StripeUpdateShippingRateConfig", "update_shipping_rate", "Update Shipping Rate", "Shipping Rates", "POST", "/shipping_rates/{rate_id}"),
    ("StripeListShippingRatesConfig", "list_shipping_rates", "List Shipping Rates", "Shipping Rates", "GET", "/shipping_rates"),
    # ---- Tax Codes ----
    ("StripeRetrieveTaxCodeConfig", "retrieve_tax_code", "Retrieve Tax Code", "Tax", "GET", "/tax_codes/{tax_code_id}"),
    ("StripeListTaxCodesConfig", "list_tax_codes", "List Tax Codes", "Tax", "GET", "/tax_codes"),
    # ---- Tax IDs (account) ----
    ("StripeCreateTaxIdConfig", "create_tax_id", "Create Tax ID", "Tax", "POST", "/tax_ids"),
    ("StripeRetrieveTaxIdConfig", "retrieve_tax_id", "Retrieve Tax ID", "Tax", "GET", "/tax_ids/{tax_id}"),
    ("StripeListTaxIdsConfig", "list_tax_ids", "List Tax IDs", "Tax", "GET", "/tax_ids"),
    ("StripeDeleteTaxIdConfig", "delete_tax_id", "Delete Tax ID", "Tax", "DELETE", "/tax_ids/{tax_id}"),
    # ---- Tax IDs (customer) ----
    ("StripeCreateCustomerTaxIdConfig", "create_customer_tax_id", "Create Customer Tax ID", "Customers", "POST", "/customers/{customer_id}/tax_ids"),
    ("StripeRetrieveCustomerTaxIdConfig", "retrieve_customer_tax_id", "Retrieve Customer Tax ID", "Customers", "GET", "/customers/{customer_id}/tax_ids/{tax_id}"),
    ("StripeListCustomerTaxIdsConfig", "list_customer_tax_ids", "List Customer Tax IDs", "Customers", "GET", "/customers/{customer_id}/tax_ids"),
    ("StripeDeleteCustomerTaxIdConfig", "delete_customer_tax_id", "Delete Customer Tax ID", "Customers", "DELETE", "/customers/{customer_id}/tax_ids/{tax_id}"),
    # ---- Customer Balance Transactions ----
    ("StripeCreateCustomerBalanceTxnConfig", "create_customer_balance_transaction", "Create Customer Balance Transaction", "Customers", "POST", "/customers/{customer_id}/balance_transactions"),
    ("StripeRetrieveCustomerBalanceTxnConfig", "retrieve_customer_balance_transaction", "Retrieve Customer Balance Transaction", "Customers", "GET", "/customers/{customer_id}/balance_transactions/{transaction_id}"),
    ("StripeUpdateCustomerBalanceTxnConfig", "update_customer_balance_transaction", "Update Customer Balance Transaction", "Customers", "POST", "/customers/{customer_id}/balance_transactions/{transaction_id}"),
    ("StripeListCustomerBalanceTxnsConfig", "list_customer_balance_transactions", "List Customer Balance Transactions", "Customers", "GET", "/customers/{customer_id}/balance_transactions"),
    # ---- Customer Cash Balance ----
    ("StripeRetrieveCustomerCashBalanceConfig", "retrieve_customer_cash_balance", "Retrieve Customer Cash Balance", "Customers", "GET", "/customers/{customer_id}/cash_balance"),
    ("StripeUpdateCustomerCashBalanceConfig", "update_customer_cash_balance", "Update Customer Cash Balance", "Customers", "POST", "/customers/{customer_id}/cash_balance"),
    ("StripeRetrieveCustomerCashBalanceTxnConfig", "retrieve_customer_cash_balance_transaction", "Retrieve Cash Balance Transaction", "Customers", "GET", "/customers/{customer_id}/cash_balance_transactions/{transaction_id}"),
    ("StripeListCustomerCashBalanceTxnsConfig", "list_customer_cash_balance_transactions", "List Cash Balance Transactions", "Customers", "GET", "/customers/{customer_id}/cash_balance_transactions"),
    # ---- Customer Sessions ----
    ("StripeCreateCustomerSessionConfig", "create_customer_session", "Create Customer Session", "Customers", "POST", "/customer_sessions"),
    # ---- Payment Method Domains ----
    ("StripeCreatePaymentMethodDomainConfig", "create_payment_method_domain", "Create Payment Method Domain", "Payment Methods", "POST", "/payment_method_domains"),
    ("StripeRetrievePaymentMethodDomainConfig", "retrieve_payment_method_domain", "Retrieve Payment Method Domain", "Payment Methods", "GET", "/payment_method_domains/{domain_id}"),
    ("StripeUpdatePaymentMethodDomainConfig", "update_payment_method_domain", "Update Payment Method Domain", "Payment Methods", "POST", "/payment_method_domains/{domain_id}"),
    ("StripeListPaymentMethodDomainsConfig", "list_payment_method_domains", "List Payment Method Domains", "Payment Methods", "GET", "/payment_method_domains"),
    ("StripeValidatePaymentMethodDomainConfig", "validate_payment_method_domain", "Validate Payment Method Domain", "Payment Methods", "POST", "/payment_method_domains/{domain_id}/validate"),
    # ---- Payment Method Configurations ----
    ("StripeCreatePaymentMethodConfigConfig", "create_payment_method_configuration", "Create Payment Method Configuration", "Payment Methods", "POST", "/payment_method_configurations"),
    ("StripeRetrievePaymentMethodConfigConfig", "retrieve_payment_method_configuration", "Retrieve Payment Method Configuration", "Payment Methods", "GET", "/payment_method_configurations/{configuration_id}"),
    ("StripeUpdatePaymentMethodConfigConfig", "update_payment_method_configuration", "Update Payment Method Configuration", "Payment Methods", "POST", "/payment_method_configurations/{configuration_id}"),
    ("StripeListPaymentMethodConfigsConfig", "list_payment_method_configurations", "List Payment Method Configurations", "Payment Methods", "GET", "/payment_method_configurations"),
    # ---- Confirmation Tokens / Setup Attempts / Mandates / Tokens / Sources ----
    ("StripeRetrieveConfirmationTokenConfig", "retrieve_confirmation_token", "Retrieve Confirmation Token", "Payments", "GET", "/confirmation_tokens/{confirmation_token_id}"),
    ("StripeListSetupAttemptsConfig", "list_setup_attempts", "List Setup Attempts", "Payments", "GET", "/setup_attempts"),
    ("StripeRetrieveMandateConfig", "retrieve_mandate", "Retrieve Mandate", "Payments", "GET", "/mandates/{mandate_id}"),
    ("StripeCreateTokenConfig", "create_token", "Create Token", "Payments", "POST", "/tokens"),
    ("StripeRetrieveTokenConfig", "retrieve_token", "Retrieve Token", "Payments", "GET", "/tokens/{token_id}"),
    ("StripeCreateSourceConfig", "create_source", "Create Source", "Payments", "POST", "/sources"),
    ("StripeRetrieveSourceConfig", "retrieve_source", "Retrieve Source", "Payments", "GET", "/sources/{source_id}"),
    ("StripeUpdateSourceConfig", "update_source", "Update Source", "Payments", "POST", "/sources/{source_id}"),
    ("StripeAttachSourceConfig", "attach_source", "Attach Source to Customer", "Payments", "POST", "/customers/{customer_id}/sources"),
    ("StripeDetachSourceConfig", "detach_source", "Detach Source from Customer", "Payments", "DELETE", "/customers/{customer_id}/sources/{source_id}"),
    # ---- Billing Meters ----
    ("StripeCreateMeterConfig", "create_meter", "Create Meter", "Billing Meters", "POST", "/billing/meters"),
    ("StripeRetrieveMeterConfig", "retrieve_meter", "Retrieve Meter", "Billing Meters", "GET", "/billing/meters/{meter_id}"),
    ("StripeUpdateMeterConfig", "update_meter", "Update Meter", "Billing Meters", "POST", "/billing/meters/{meter_id}"),
    ("StripeListMetersConfig", "list_meters", "List Meters", "Billing Meters", "GET", "/billing/meters"),
    ("StripeDeactivateMeterConfig", "deactivate_meter", "Deactivate Meter", "Billing Meters", "POST", "/billing/meters/{meter_id}/deactivate"),
    ("StripeReactivateMeterConfig", "reactivate_meter", "Reactivate Meter", "Billing Meters", "POST", "/billing/meters/{meter_id}/reactivate"),
    ("StripeListMeterEventSummariesConfig", "list_meter_event_summaries", "List Meter Event Summaries", "Billing Meters", "GET", "/billing/meters/{meter_id}/event_summaries"),
    ("StripeCreateMeterEventConfig", "create_meter_event", "Create Meter Event", "Billing Meters", "POST", "/billing/meter_events"),
    ("StripeCreateMeterEventAdjustmentConfig", "create_meter_event_adjustment", "Create Meter Event Adjustment", "Billing Meters", "POST", "/billing/meter_event_adjustments"),
    # ---- Billing Credit Grants ----
    ("StripeCreateCreditGrantConfig", "create_credit_grant", "Create Credit Grant", "Billing Credit", "POST", "/billing/credit_grants"),
    ("StripeRetrieveCreditGrantConfig", "retrieve_credit_grant", "Retrieve Credit Grant", "Billing Credit", "GET", "/billing/credit_grants/{grant_id}"),
    ("StripeUpdateCreditGrantConfig", "update_credit_grant", "Update Credit Grant", "Billing Credit", "POST", "/billing/credit_grants/{grant_id}"),
    ("StripeListCreditGrantsConfig", "list_credit_grants", "List Credit Grants", "Billing Credit", "GET", "/billing/credit_grants"),
    ("StripeVoidCreditGrantConfig", "void_credit_grant", "Void Credit Grant", "Billing Credit", "POST", "/billing/credit_grants/{grant_id}/void"),
    ("StripeExpireCreditGrantConfig", "expire_credit_grant", "Expire Credit Grant", "Billing Credit", "POST", "/billing/credit_grants/{grant_id}/expire"),
    ("StripeRetrieveCreditBalanceSummaryConfig", "retrieve_credit_balance_summary", "Retrieve Credit Balance Summary", "Billing Credit", "GET", "/billing/credit_balance_summary"),
    ("StripeRetrieveCreditBalanceTxnConfig", "retrieve_credit_balance_transaction", "Retrieve Credit Balance Transaction", "Billing Credit", "GET", "/billing/credit_balance_transactions/{transaction_id}"),
    ("StripeListCreditBalanceTxnsConfig", "list_credit_balance_transactions", "List Credit Balance Transactions", "Billing Credit", "GET", "/billing/credit_balance_transactions"),
    # ---- Billing Alerts ----
    ("StripeCreateAlertConfig", "create_alert", "Create Billing Alert", "Billing Alerts", "POST", "/billing/alerts"),
    ("StripeRetrieveAlertConfig", "retrieve_alert", "Retrieve Billing Alert", "Billing Alerts", "GET", "/billing/alerts/{alert_id}"),
    ("StripeListAlertsConfig", "list_alerts", "List Billing Alerts", "Billing Alerts", "GET", "/billing/alerts"),
    ("StripeActivateAlertConfig", "activate_alert", "Activate Billing Alert", "Billing Alerts", "POST", "/billing/alerts/{alert_id}/activate"),
    ("StripeDeactivateAlertConfig", "deactivate_alert", "Deactivate Billing Alert", "Billing Alerts", "POST", "/billing/alerts/{alert_id}/deactivate"),
    ("StripeArchiveAlertConfig", "archive_alert", "Archive Billing Alert", "Billing Alerts", "POST", "/billing/alerts/{alert_id}/archive"),
    # ---- Subscription Items usage ----
    ("StripeListUsageRecordSummariesConfig", "list_usage_record_summaries", "List Usage Record Summaries", "Subscription Items", "GET", "/subscription_items/{subscription_item_id}/usage_record_summaries"),
    ("StripeCreateUsageRecordConfig", "create_usage_record", "Create Usage Record", "Subscription Items", "POST", "/subscription_items/{subscription_item_id}/usage_records"),
    # ---- Invoices (special / lines) ----
    ("StripeCreatePreviewInvoiceConfig", "create_preview_invoice", "Create Preview Invoice", "Invoices", "POST", "/invoices/create_preview"),
    ("StripeListInvoiceLinesConfig", "list_invoice_lines", "List Invoice Lines", "Invoices", "GET", "/invoices/{invoice_id}/lines"),
    ("StripeUpdateInvoiceLineConfig", "update_invoice_line", "Update Invoice Line", "Invoices", "POST", "/invoices/{invoice_id}/lines/{line_item_id}"),
    ("StripeUpdateInvoiceLinesConfig", "update_invoice_lines", "Bulk Update Invoice Lines", "Invoices", "POST", "/invoices/{invoice_id}/update_lines"),
    ("StripeAddInvoiceLinesConfig", "add_invoice_lines", "Add Invoice Lines", "Invoices", "POST", "/invoices/{invoice_id}/add_lines"),
    ("StripeRemoveInvoiceLinesConfig", "remove_invoice_lines", "Remove Invoice Lines", "Invoices", "POST", "/invoices/{invoice_id}/remove_lines"),
    # ---- Quotes (special) ----
    ("StripeListQuoteLineItemsConfig", "list_quote_line_items", "List Quote Line Items", "Quotes", "GET", "/quotes/{quote_id}/line_items"),
    ("StripeListQuoteComputedLineItemsConfig", "list_quote_computed_upfront_line_items", "List Quote Computed Upfront Line Items", "Quotes", "GET", "/quotes/{quote_id}/computed_upfront_line_items"),
    # ---- Credit Notes (special) ----
    ("StripeListCreditNoteLinesConfig", "list_credit_note_lines", "List Credit Note Lines", "Credit Notes", "GET", "/credit_notes/{credit_note_id}/lines"),
    ("StripePreviewCreditNoteConfig", "preview_credit_note", "Preview Credit Note", "Credit Notes", "GET", "/credit_notes/preview"),
    ("StripePreviewCreditNoteLinesConfig", "preview_credit_note_lines", "Preview Credit Note Lines", "Credit Notes", "GET", "/credit_notes/preview/lines"),
    # ---- Customer Portal Configurations ----
    ("StripeCreatePortalConfigConfig", "create_portal_configuration", "Create Portal Configuration", "Billing Portal", "POST", "/billing_portal/configurations"),
    ("StripeRetrievePortalConfigConfig", "retrieve_portal_configuration", "Retrieve Portal Configuration", "Billing Portal", "GET", "/billing_portal/configurations/{configuration_id}"),
    ("StripeUpdatePortalConfigConfig", "update_portal_configuration", "Update Portal Configuration", "Billing Portal", "POST", "/billing_portal/configurations/{configuration_id}"),
    ("StripeListPortalConfigsConfig", "list_portal_configurations", "List Portal Configurations", "Billing Portal", "GET", "/billing_portal/configurations"),
    # ---- Connect: Persons ----
    ("StripeCreatePersonConfig", "create_person", "Create Person", "Connect", "POST", "/accounts/{account_id}/persons"),
    ("StripeRetrievePersonConfig", "retrieve_person", "Retrieve Person", "Connect", "GET", "/accounts/{account_id}/persons/{person_id}"),
    ("StripeUpdatePersonConfig", "update_person", "Update Person", "Connect", "POST", "/accounts/{account_id}/persons/{person_id}"),
    ("StripeDeletePersonConfig", "delete_person", "Delete Person", "Connect", "DELETE", "/accounts/{account_id}/persons/{person_id}"),
    ("StripeListPersonsConfig", "list_persons", "List Persons", "Connect", "GET", "/accounts/{account_id}/persons"),
    # ---- Connect: Capabilities ----
    ("StripeRetrieveCapabilityConfig", "retrieve_capability", "Retrieve Capability", "Connect", "GET", "/accounts/{account_id}/capabilities/{capability_id}"),
    ("StripeUpdateCapabilityConfig", "update_capability", "Update Capability", "Connect", "POST", "/accounts/{account_id}/capabilities/{capability_id}"),
    ("StripeListCapabilitiesConfig", "list_capabilities", "List Capabilities", "Connect", "GET", "/accounts/{account_id}/capabilities"),
    # ---- Connect: External Accounts ----
    ("StripeCreateExternalAccountConfig", "create_external_account", "Create External Account", "Connect", "POST", "/accounts/{account_id}/external_accounts"),
    ("StripeRetrieveExternalAccountConfig", "retrieve_external_account", "Retrieve External Account", "Connect", "GET", "/accounts/{account_id}/external_accounts/{external_account_id}"),
    ("StripeUpdateExternalAccountConfig", "update_external_account", "Update External Account", "Connect", "POST", "/accounts/{account_id}/external_accounts/{external_account_id}"),
    ("StripeDeleteExternalAccountConfig", "delete_external_account", "Delete External Account", "Connect", "DELETE", "/accounts/{account_id}/external_accounts/{external_account_id}"),
    ("StripeListExternalAccountsConfig", "list_external_accounts", "List External Accounts", "Connect", "GET", "/accounts/{account_id}/external_accounts"),
    # ---- Connect: Account Sessions / Country Specs ----
    ("StripeCreateAccountSessionConfig", "create_account_session", "Create Account Session", "Connect", "POST", "/account_sessions"),
    ("StripeRetrieveCountrySpecConfig", "retrieve_country_spec", "Retrieve Country Spec", "Connect", "GET", "/country_specs/{country_code}"),
    ("StripeListCountrySpecsConfig", "list_country_specs", "List Country Specs", "Connect", "GET", "/country_specs"),
    # ---- Connect: Application Fee Refunds ----
    ("StripeCreateAppFeeRefundConfig", "create_application_fee_refund", "Create Application Fee Refund", "Connect", "POST", "/application_fees/{fee_id}/refunds"),
    ("StripeRetrieveAppFeeRefundConfig", "retrieve_application_fee_refund", "Retrieve Application Fee Refund", "Connect", "GET", "/application_fees/{fee_id}/refunds/{refund_id}"),
    ("StripeUpdateAppFeeRefundConfig", "update_application_fee_refund", "Update Application Fee Refund", "Connect", "POST", "/application_fees/{fee_id}/refunds/{refund_id}"),
    ("StripeListAppFeeRefundsConfig", "list_application_fee_refunds", "List Application Fee Refunds", "Connect", "GET", "/application_fees/{fee_id}/refunds"),
    # ---- Connect: Transfer Reversals ----
    ("StripeCreateTransferReversalConfig", "create_transfer_reversal", "Create Transfer Reversal", "Connect", "POST", "/transfers/{transfer_id}/reversals"),
    ("StripeRetrieveTransferReversalConfig", "retrieve_transfer_reversal", "Retrieve Transfer Reversal", "Connect", "GET", "/transfers/{transfer_id}/reversals/{reversal_id}"),
    ("StripeUpdateTransferReversalConfig", "update_transfer_reversal", "Update Transfer Reversal", "Connect", "POST", "/transfers/{transfer_id}/reversals/{reversal_id}"),
    ("StripeListTransferReversalsConfig", "list_transfer_reversals", "List Transfer Reversals", "Connect", "GET", "/transfers/{transfer_id}/reversals"),
    # ---- Apps Secrets ----
    ("StripeSetSecretConfig", "set_secret", "Set Secret", "Apps", "POST", "/apps/secrets"),
    ("StripeFindSecretConfig", "find_secret", "Find Secret", "Apps", "GET", "/apps/secrets/find"),
    ("StripeDeleteSecretConfig", "delete_secret", "Delete Secret", "Apps", "POST", "/apps/secrets/delete"),
    ("StripeListSecretsConfig", "list_secrets", "List Secrets", "Apps", "GET", "/apps/secrets"),
    # ---- Radar ----
    ("StripeCreateValueListConfig", "create_value_list", "Create Value List", "Radar", "POST", "/radar/value_lists"),
    ("StripeRetrieveValueListConfig", "retrieve_value_list", "Retrieve Value List", "Radar", "GET", "/radar/value_lists/{value_list_id}"),
    ("StripeUpdateValueListConfig", "update_value_list", "Update Value List", "Radar", "POST", "/radar/value_lists/{value_list_id}"),
    ("StripeDeleteValueListConfig", "delete_value_list", "Delete Value List", "Radar", "DELETE", "/radar/value_lists/{value_list_id}"),
    ("StripeListValueListsConfig", "list_value_lists", "List Value Lists", "Radar", "GET", "/radar/value_lists"),
    ("StripeCreateValueListItemConfig", "create_value_list_item", "Create Value List Item", "Radar", "POST", "/radar/value_list_items"),
    ("StripeRetrieveValueListItemConfig", "retrieve_value_list_item", "Retrieve Value List Item", "Radar", "GET", "/radar/value_list_items/{item_id}"),
    ("StripeDeleteValueListItemConfig", "delete_value_list_item", "Delete Value List Item", "Radar", "DELETE", "/radar/value_list_items/{item_id}"),
    ("StripeListValueListItemsConfig", "list_value_list_items", "List Value List Items", "Radar", "GET", "/radar/value_list_items"),
    ("StripeRetrieveEarlyFraudWarningConfig", "retrieve_early_fraud_warning", "Retrieve Early Fraud Warning", "Radar", "GET", "/radar/early_fraud_warnings/{warning_id}"),
    ("StripeListEarlyFraudWarningsConfig", "list_early_fraud_warnings", "List Early Fraud Warnings", "Radar", "GET", "/radar/early_fraud_warnings"),
    ("StripeRetrieveReviewConfig", "retrieve_review", "Retrieve Review", "Radar", "GET", "/reviews/{review_id}"),
    ("StripeListReviewsConfig", "list_reviews", "List Reviews", "Radar", "GET", "/reviews"),
    ("StripeApproveReviewConfig", "approve_review", "Approve Review", "Radar", "POST", "/reviews/{review_id}/approve"),
    # ---- Reporting / Sigma ----
    ("StripeCreateReportRunConfig", "create_report_run", "Create Report Run", "Reporting", "POST", "/reporting/report_runs"),
    ("StripeRetrieveReportRunConfig", "retrieve_report_run", "Retrieve Report Run", "Reporting", "GET", "/reporting/report_runs/{report_run_id}"),
    ("StripeListReportRunsConfig", "list_report_runs", "List Report Runs", "Reporting", "GET", "/reporting/report_runs"),
    ("StripeRetrieveReportTypeConfig", "retrieve_report_type", "Retrieve Report Type", "Reporting", "GET", "/reporting/report_types/{report_type_id}"),
    ("StripeListReportTypesConfig", "list_report_types", "List Report Types", "Reporting", "GET", "/reporting/report_types"),
    ("StripeRetrieveScheduledQueryRunConfig", "retrieve_scheduled_query_run", "Retrieve Scheduled Query Run", "Reporting", "GET", "/sigma/scheduled_query_runs/{scheduled_query_run_id}"),
    ("StripeListScheduledQueryRunsConfig", "list_scheduled_query_runs", "List Scheduled Query Runs", "Reporting", "GET", "/sigma/scheduled_query_runs"),
    # ---- Issuing ----
    ("StripeRetrieveIssuingAuthorizationConfig", "retrieve_issuing_authorization", "Retrieve Issuing Authorization", "Issuing", "GET", "/issuing/authorizations/{authorization_id}"),
    ("StripeUpdateIssuingAuthorizationConfig", "update_issuing_authorization", "Update Issuing Authorization", "Issuing", "POST", "/issuing/authorizations/{authorization_id}"),
    ("StripeListIssuingAuthorizationsConfig", "list_issuing_authorizations", "List Issuing Authorizations", "Issuing", "GET", "/issuing/authorizations"),
    ("StripeApproveIssuingAuthorizationConfig", "approve_issuing_authorization", "Approve Issuing Authorization", "Issuing", "POST", "/issuing/authorizations/{authorization_id}/approve"),
    ("StripeDeclineIssuingAuthorizationConfig", "decline_issuing_authorization", "Decline Issuing Authorization", "Issuing", "POST", "/issuing/authorizations/{authorization_id}/decline"),
    ("StripeCreateIssuingCardholderConfig", "create_issuing_cardholder", "Create Issuing Cardholder", "Issuing", "POST", "/issuing/cardholders"),
    ("StripeRetrieveIssuingCardholderConfig", "retrieve_issuing_cardholder", "Retrieve Issuing Cardholder", "Issuing", "GET", "/issuing/cardholders/{cardholder_id}"),
    ("StripeUpdateIssuingCardholderConfig", "update_issuing_cardholder", "Update Issuing Cardholder", "Issuing", "POST", "/issuing/cardholders/{cardholder_id}"),
    ("StripeListIssuingCardholdersConfig", "list_issuing_cardholders", "List Issuing Cardholders", "Issuing", "GET", "/issuing/cardholders"),
    ("StripeCreateIssuingCardConfig", "create_issuing_card", "Create Issuing Card", "Issuing", "POST", "/issuing/cards"),
    ("StripeRetrieveIssuingCardConfig", "retrieve_issuing_card", "Retrieve Issuing Card", "Issuing", "GET", "/issuing/cards/{card_id}"),
    ("StripeUpdateIssuingCardConfig", "update_issuing_card", "Update Issuing Card", "Issuing", "POST", "/issuing/cards/{card_id}"),
    ("StripeListIssuingCardsConfig", "list_issuing_cards", "List Issuing Cards", "Issuing", "GET", "/issuing/cards"),
    ("StripeCreateIssuingDisputeConfig", "create_issuing_dispute", "Create Issuing Dispute", "Issuing", "POST", "/issuing/disputes"),
    ("StripeRetrieveIssuingDisputeConfig", "retrieve_issuing_dispute", "Retrieve Issuing Dispute", "Issuing", "GET", "/issuing/disputes/{dispute_id}"),
    ("StripeUpdateIssuingDisputeConfig", "update_issuing_dispute", "Update Issuing Dispute", "Issuing", "POST", "/issuing/disputes/{dispute_id}"),
    ("StripeListIssuingDisputesConfig", "list_issuing_disputes", "List Issuing Disputes", "Issuing", "GET", "/issuing/disputes"),
    ("StripeSubmitIssuingDisputeConfig", "submit_issuing_dispute", "Submit Issuing Dispute", "Issuing", "POST", "/issuing/disputes/{dispute_id}/submit"),
    ("StripeRetrieveIssuingTransactionConfig", "retrieve_issuing_transaction", "Retrieve Issuing Transaction", "Issuing", "GET", "/issuing/transactions/{transaction_id}"),
    ("StripeUpdateIssuingTransactionConfig", "update_issuing_transaction", "Update Issuing Transaction", "Issuing", "POST", "/issuing/transactions/{transaction_id}"),
    ("StripeListIssuingTransactionsConfig", "list_issuing_transactions", "List Issuing Transactions", "Issuing", "GET", "/issuing/transactions"),
    ("StripeCreateIssuingPersoDesignConfig", "create_issuing_personalization_design", "Create Personalization Design", "Issuing", "POST", "/issuing/personalization_designs"),
    ("StripeRetrieveIssuingPersoDesignConfig", "retrieve_issuing_personalization_design", "Retrieve Personalization Design", "Issuing", "GET", "/issuing/personalization_designs/{personalization_design_id}"),
    ("StripeUpdateIssuingPersoDesignConfig", "update_issuing_personalization_design", "Update Personalization Design", "Issuing", "POST", "/issuing/personalization_designs/{personalization_design_id}"),
    ("StripeListIssuingPersoDesignsConfig", "list_issuing_personalization_designs", "List Personalization Designs", "Issuing", "GET", "/issuing/personalization_designs"),
    ("StripeRetrieveIssuingPhysicalBundleConfig", "retrieve_issuing_physical_bundle", "Retrieve Physical Bundle", "Issuing", "GET", "/issuing/physical_bundles/{physical_bundle_id}"),
    ("StripeListIssuingPhysicalBundlesConfig", "list_issuing_physical_bundles", "List Physical Bundles", "Issuing", "GET", "/issuing/physical_bundles"),
    ("StripeRetrieveIssuingTokenConfig", "retrieve_issuing_token", "Retrieve Issuing Token", "Issuing", "GET", "/issuing/tokens/{token_id}"),
    ("StripeUpdateIssuingTokenConfig", "update_issuing_token", "Update Issuing Token", "Issuing", "POST", "/issuing/tokens/{token_id}"),
    ("StripeListIssuingTokensConfig", "list_issuing_tokens", "List Issuing Tokens", "Issuing", "GET", "/issuing/tokens"),
    ("StripeCreateIssuingFundingInstructionsConfig", "create_issuing_funding_instructions", "Create Issuing Funding Instructions", "Issuing", "POST", "/issuing/funding_instructions"),
    ("StripeListIssuingFundingInstructionsConfig", "list_issuing_funding_instructions", "List Issuing Funding Instructions", "Issuing", "GET", "/issuing/funding_instructions"),
    # ---- Treasury ----
    ("StripeCreateTreasuryFinancialAccountConfig", "create_treasury_financial_account", "Create Financial Account", "Treasury", "POST", "/treasury/financial_accounts"),
    ("StripeRetrieveTreasuryFinancialAccountConfig", "retrieve_treasury_financial_account", "Retrieve Financial Account", "Treasury", "GET", "/treasury/financial_accounts/{financial_account_id}"),
    ("StripeUpdateTreasuryFinancialAccountConfig", "update_treasury_financial_account", "Update Financial Account", "Treasury", "POST", "/treasury/financial_accounts/{financial_account_id}"),
    ("StripeListTreasuryFinancialAccountsConfig", "list_treasury_financial_accounts", "List Financial Accounts", "Treasury", "GET", "/treasury/financial_accounts"),
    ("StripeRetrieveTreasuryFAFeaturesConfig", "retrieve_treasury_financial_account_features", "Retrieve Financial Account Features", "Treasury", "GET", "/treasury/financial_accounts/{financial_account_id}/features"),
    ("StripeUpdateTreasuryFAFeaturesConfig", "update_treasury_financial_account_features", "Update Financial Account Features", "Treasury", "POST", "/treasury/financial_accounts/{financial_account_id}/features"),
    ("StripeRetrieveTreasuryTransactionConfig", "retrieve_treasury_transaction", "Retrieve Treasury Transaction", "Treasury", "GET", "/treasury/transactions/{transaction_id}"),
    ("StripeListTreasuryTransactionsConfig", "list_treasury_transactions", "List Treasury Transactions", "Treasury", "GET", "/treasury/transactions"),
    ("StripeRetrieveTreasuryTxnEntryConfig", "retrieve_treasury_transaction_entry", "Retrieve Transaction Entry", "Treasury", "GET", "/treasury/transaction_entries/{transaction_entry_id}"),
    ("StripeListTreasuryTxnEntriesConfig", "list_treasury_transaction_entries", "List Transaction Entries", "Treasury", "GET", "/treasury/transaction_entries"),
    ("StripeCreateTreasuryOutboundTransferConfig", "create_treasury_outbound_transfer", "Create Outbound Transfer", "Treasury", "POST", "/treasury/outbound_transfers"),
    ("StripeRetrieveTreasuryOutboundTransferConfig", "retrieve_treasury_outbound_transfer", "Retrieve Outbound Transfer", "Treasury", "GET", "/treasury/outbound_transfers/{outbound_transfer_id}"),
    ("StripeListTreasuryOutboundTransfersConfig", "list_treasury_outbound_transfers", "List Outbound Transfers", "Treasury", "GET", "/treasury/outbound_transfers"),
    ("StripeCancelTreasuryOutboundTransferConfig", "cancel_treasury_outbound_transfer", "Cancel Outbound Transfer", "Treasury", "POST", "/treasury/outbound_transfers/{outbound_transfer_id}/cancel"),
    ("StripeCreateTreasuryOutboundPaymentConfig", "create_treasury_outbound_payment", "Create Outbound Payment", "Treasury", "POST", "/treasury/outbound_payments"),
    ("StripeRetrieveTreasuryOutboundPaymentConfig", "retrieve_treasury_outbound_payment", "Retrieve Outbound Payment", "Treasury", "GET", "/treasury/outbound_payments/{outbound_payment_id}"),
    ("StripeListTreasuryOutboundPaymentsConfig", "list_treasury_outbound_payments", "List Outbound Payments", "Treasury", "GET", "/treasury/outbound_payments"),
    ("StripeCancelTreasuryOutboundPaymentConfig", "cancel_treasury_outbound_payment", "Cancel Outbound Payment", "Treasury", "POST", "/treasury/outbound_payments/{outbound_payment_id}/cancel"),
    ("StripeCreateTreasuryInboundTransferConfig", "create_treasury_inbound_transfer", "Create Inbound Transfer", "Treasury", "POST", "/treasury/inbound_transfers"),
    ("StripeRetrieveTreasuryInboundTransferConfig", "retrieve_treasury_inbound_transfer", "Retrieve Inbound Transfer", "Treasury", "GET", "/treasury/inbound_transfers/{inbound_transfer_id}"),
    ("StripeListTreasuryInboundTransfersConfig", "list_treasury_inbound_transfers", "List Inbound Transfers", "Treasury", "GET", "/treasury/inbound_transfers"),
    ("StripeCancelTreasuryInboundTransferConfig", "cancel_treasury_inbound_transfer", "Cancel Inbound Transfer", "Treasury", "POST", "/treasury/inbound_transfers/{inbound_transfer_id}/cancel"),
    ("StripeRetrieveTreasuryReceivedCreditConfig", "retrieve_treasury_received_credit", "Retrieve Received Credit", "Treasury", "GET", "/treasury/received_credits/{received_credit_id}"),
    ("StripeListTreasuryReceivedCreditsConfig", "list_treasury_received_credits", "List Received Credits", "Treasury", "GET", "/treasury/received_credits"),
    ("StripeRetrieveTreasuryReceivedDebitConfig", "retrieve_treasury_received_debit", "Retrieve Received Debit", "Treasury", "GET", "/treasury/received_debits/{received_debit_id}"),
    ("StripeListTreasuryReceivedDebitsConfig", "list_treasury_received_debits", "List Received Debits", "Treasury", "GET", "/treasury/received_debits"),
    ("StripeCreateTreasuryCreditReversalConfig", "create_treasury_credit_reversal", "Create Credit Reversal", "Treasury", "POST", "/treasury/credit_reversals"),
    ("StripeRetrieveTreasuryCreditReversalConfig", "retrieve_treasury_credit_reversal", "Retrieve Credit Reversal", "Treasury", "GET", "/treasury/credit_reversals/{credit_reversal_id}"),
    ("StripeListTreasuryCreditReversalsConfig", "list_treasury_credit_reversals", "List Credit Reversals", "Treasury", "GET", "/treasury/credit_reversals"),
    ("StripeCreateTreasuryDebitReversalConfig", "create_treasury_debit_reversal", "Create Debit Reversal", "Treasury", "POST", "/treasury/debit_reversals"),
    ("StripeRetrieveTreasuryDebitReversalConfig", "retrieve_treasury_debit_reversal", "Retrieve Debit Reversal", "Treasury", "GET", "/treasury/debit_reversals/{debit_reversal_id}"),
    ("StripeListTreasuryDebitReversalsConfig", "list_treasury_debit_reversals", "List Debit Reversals", "Treasury", "GET", "/treasury/debit_reversals"),
    # ---- Terminal ----
    ("StripeCreateTerminalConnectionTokenConfig", "create_terminal_connection_token", "Create Connection Token", "Terminal", "POST", "/terminal/connection_tokens"),
    ("StripeCreateTerminalLocationConfig", "create_terminal_location", "Create Terminal Location", "Terminal", "POST", "/terminal/locations"),
    ("StripeRetrieveTerminalLocationConfig", "retrieve_terminal_location", "Retrieve Terminal Location", "Terminal", "GET", "/terminal/locations/{location_id}"),
    ("StripeUpdateTerminalLocationConfig", "update_terminal_location", "Update Terminal Location", "Terminal", "POST", "/terminal/locations/{location_id}"),
    ("StripeDeleteTerminalLocationConfig", "delete_terminal_location", "Delete Terminal Location", "Terminal", "DELETE", "/terminal/locations/{location_id}"),
    ("StripeListTerminalLocationsConfig", "list_terminal_locations", "List Terminal Locations", "Terminal", "GET", "/terminal/locations"),
    ("StripeCreateTerminalReaderConfig", "create_terminal_reader", "Create Terminal Reader", "Terminal", "POST", "/terminal/readers"),
    ("StripeRetrieveTerminalReaderConfig", "retrieve_terminal_reader", "Retrieve Terminal Reader", "Terminal", "GET", "/terminal/readers/{reader_id}"),
    ("StripeUpdateTerminalReaderConfig", "update_terminal_reader", "Update Terminal Reader", "Terminal", "POST", "/terminal/readers/{reader_id}"),
    ("StripeDeleteTerminalReaderConfig", "delete_terminal_reader", "Delete Terminal Reader", "Terminal", "DELETE", "/terminal/readers/{reader_id}"),
    ("StripeListTerminalReadersConfig", "list_terminal_readers", "List Terminal Readers", "Terminal", "GET", "/terminal/readers"),
    ("StripeProcessPIReaderConfig", "process_payment_intent_terminal_reader", "Reader: Process Payment Intent", "Terminal", "POST", "/terminal/readers/{reader_id}/process_payment_intent"),
    ("StripeProcessSIReaderConfig", "process_setup_intent_terminal_reader", "Reader: Process Setup Intent", "Terminal", "POST", "/terminal/readers/{reader_id}/process_setup_intent"),
    ("StripeCancelActionReaderConfig", "cancel_action_terminal_reader", "Reader: Cancel Action", "Terminal", "POST", "/terminal/readers/{reader_id}/cancel_action"),
    ("StripeRefundPaymentReaderConfig", "refund_payment_terminal_reader", "Reader: Refund Payment", "Terminal", "POST", "/terminal/readers/{reader_id}/refund_payment"),
    ("StripeCollectInputsReaderConfig", "collect_inputs_terminal_reader", "Reader: Collect Inputs", "Terminal", "POST", "/terminal/readers/{reader_id}/collect_inputs"),
    ("StripeCreateTerminalConfigurationConfig", "create_terminal_configuration", "Create Terminal Configuration", "Terminal", "POST", "/terminal/configurations"),
    ("StripeRetrieveTerminalConfigurationConfig", "retrieve_terminal_configuration", "Retrieve Terminal Configuration", "Terminal", "GET", "/terminal/configurations/{configuration_id}"),
    ("StripeUpdateTerminalConfigurationConfig", "update_terminal_configuration", "Update Terminal Configuration", "Terminal", "POST", "/terminal/configurations/{configuration_id}"),
    ("StripeDeleteTerminalConfigurationConfig", "delete_terminal_configuration", "Delete Terminal Configuration", "Terminal", "DELETE", "/terminal/configurations/{configuration_id}"),
    ("StripeListTerminalConfigurationsConfig", "list_terminal_configurations", "List Terminal Configurations", "Terminal", "GET", "/terminal/configurations"),
    # ---- Tax (calculations / transactions / registrations / settings) ----
    ("StripeCreateTaxCalculationConfig", "create_tax_calculation", "Create Tax Calculation", "Tax", "POST", "/tax/calculations"),
    ("StripeRetrieveTaxCalculationConfig", "retrieve_tax_calculation", "Retrieve Tax Calculation", "Tax", "GET", "/tax/calculations/{calculation_id}"),
    ("StripeListTaxCalcLineItemsConfig", "list_tax_calculation_line_items", "List Tax Calculation Line Items", "Tax", "GET", "/tax/calculations/{calculation_id}/line_items"),
    ("StripeCreateTaxTxnFromCalcConfig", "create_tax_transaction_from_calculation", "Create Tax Transaction from Calculation", "Tax", "POST", "/tax/transactions/create_from_calculation"),
    ("StripeCreateTaxTxnReversalConfig", "create_tax_transaction_reversal", "Create Tax Transaction Reversal", "Tax", "POST", "/tax/transactions/create_reversal"),
    ("StripeRetrieveTaxTransactionConfig", "retrieve_tax_transaction", "Retrieve Tax Transaction", "Tax", "GET", "/tax/transactions/{transaction_id}"),
    ("StripeListTaxTxnLineItemsConfig", "list_tax_transaction_line_items", "List Tax Transaction Line Items", "Tax", "GET", "/tax/transactions/{transaction_id}/line_items"),
    ("StripeCreateTaxRegistrationConfig", "create_tax_registration", "Create Tax Registration", "Tax", "POST", "/tax/registrations"),
    ("StripeRetrieveTaxRegistrationConfig", "retrieve_tax_registration", "Retrieve Tax Registration", "Tax", "GET", "/tax/registrations/{registration_id}"),
    ("StripeUpdateTaxRegistrationConfig", "update_tax_registration", "Update Tax Registration", "Tax", "POST", "/tax/registrations/{registration_id}"),
    ("StripeListTaxRegistrationsConfig", "list_tax_registrations", "List Tax Registrations", "Tax", "GET", "/tax/registrations"),
    ("StripeRetrieveTaxSettingsConfig", "retrieve_tax_settings", "Retrieve Tax Settings", "Tax", "GET", "/tax/settings"),
    ("StripeUpdateTaxSettingsConfig", "update_tax_settings", "Update Tax Settings", "Tax", "POST", "/tax/settings"),
    # ---- Identity ----
    ("StripeCreateVerificationSessionConfig", "create_verification_session", "Create Verification Session", "Identity", "POST", "/identity/verification_sessions"),
    ("StripeRetrieveVerificationSessionConfig", "retrieve_verification_session", "Retrieve Verification Session", "Identity", "GET", "/identity/verification_sessions/{session_id}"),
    ("StripeUpdateVerificationSessionConfig", "update_verification_session", "Update Verification Session", "Identity", "POST", "/identity/verification_sessions/{session_id}"),
    ("StripeListVerificationSessionsConfig", "list_verification_sessions", "List Verification Sessions", "Identity", "GET", "/identity/verification_sessions"),
    ("StripeCancelVerificationSessionConfig", "cancel_verification_session", "Cancel Verification Session", "Identity", "POST", "/identity/verification_sessions/{session_id}/cancel"),
    ("StripeRedactVerificationSessionConfig", "redact_verification_session", "Redact Verification Session", "Identity", "POST", "/identity/verification_sessions/{session_id}/redact"),
    ("StripeRetrieveVerificationReportConfig", "retrieve_verification_report", "Retrieve Verification Report", "Identity", "GET", "/identity/verification_reports/{report_id}"),
    ("StripeListVerificationReportsConfig", "list_verification_reports", "List Verification Reports", "Identity", "GET", "/identity/verification_reports"),
    # ---- Financial Connections ----
    ("StripeCreateFinConnSessionConfig", "create_financial_connections_session", "Create Financial Connections Session", "Financial Connections", "POST", "/financial_connections/sessions"),
    ("StripeRetrieveFinConnSessionConfig", "retrieve_financial_connections_session", "Retrieve Financial Connections Session", "Financial Connections", "GET", "/financial_connections/sessions/{session_id}"),
    ("StripeRetrieveFinConnAccountConfig", "retrieve_financial_connections_account", "Retrieve Financial Connections Account", "Financial Connections", "GET", "/financial_connections/accounts/{account_id}"),
    ("StripeListFinConnAccountsConfig", "list_financial_connections_accounts", "List Financial Connections Accounts", "Financial Connections", "GET", "/financial_connections/accounts"),
    ("StripeDisconnectFinConnAccountConfig", "disconnect_financial_connections_account", "Disconnect Account", "Financial Connections", "POST", "/financial_connections/accounts/{account_id}/disconnect"),
    ("StripeRefreshFinConnAccountConfig", "refresh_financial_connections_account", "Refresh Account", "Financial Connections", "POST", "/financial_connections/accounts/{account_id}/refresh"),
    ("StripeSubscribeFinConnAccountConfig", "subscribe_financial_connections_account", "Subscribe Account", "Financial Connections", "POST", "/financial_connections/accounts/{account_id}/subscribe"),
    ("StripeUnsubscribeFinConnAccountConfig", "unsubscribe_financial_connections_account", "Unsubscribe Account", "Financial Connections", "POST", "/financial_connections/accounts/{account_id}/unsubscribe"),
    ("StripeListFinConnAccountOwnersConfig", "list_financial_connections_account_owners", "List Account Owners", "Financial Connections", "GET", "/financial_connections/accounts/{account_id}/owners"),
    ("StripeRetrieveFinConnTransactionConfig", "retrieve_financial_connections_transaction", "Retrieve Financial Connections Transaction", "Financial Connections", "GET", "/financial_connections/transactions/{transaction_id}"),
    ("StripeListFinConnTransactionsConfig", "list_financial_connections_transactions", "List Financial Connections Transactions", "Financial Connections", "GET", "/financial_connections/transactions"),
    # ---- Entitlements ----
    ("StripeCreateEntitlementsFeatureConfig", "create_entitlements_feature", "Create Feature", "Entitlements", "POST", "/entitlements/features"),
    ("StripeRetrieveEntitlementsFeatureConfig", "retrieve_entitlements_feature", "Retrieve Feature", "Entitlements", "GET", "/entitlements/features/{feature_id}"),
    ("StripeUpdateEntitlementsFeatureConfig", "update_entitlements_feature", "Update Feature", "Entitlements", "POST", "/entitlements/features/{feature_id}"),
    ("StripeListEntitlementsFeaturesConfig", "list_entitlements_features", "List Features", "Entitlements", "GET", "/entitlements/features"),
    ("StripeRetrieveActiveEntitlementConfig", "retrieve_active_entitlement", "Retrieve Active Entitlement", "Entitlements", "GET", "/entitlements/active_entitlements/{active_entitlement_id}"),
    ("StripeListActiveEntitlementsConfig", "list_active_entitlements", "List Active Entitlements", "Entitlements", "GET", "/entitlements/active_entitlements"),
    # ---- Climate ----
    ("StripeCreateClimateOrderConfig", "create_climate_order", "Create Climate Order", "Climate", "POST", "/climate/orders"),
    ("StripeRetrieveClimateOrderConfig", "retrieve_climate_order", "Retrieve Climate Order", "Climate", "GET", "/climate/orders/{order_id}"),
    ("StripeUpdateClimateOrderConfig", "update_climate_order", "Update Climate Order", "Climate", "POST", "/climate/orders/{order_id}"),
    ("StripeListClimateOrdersConfig", "list_climate_orders", "List Climate Orders", "Climate", "GET", "/climate/orders"),
    ("StripeCancelClimateOrderConfig", "cancel_climate_order", "Cancel Climate Order", "Climate", "POST", "/climate/orders/{order_id}/cancel"),
    ("StripeRetrieveClimateProductConfig", "retrieve_climate_product", "Retrieve Climate Product", "Climate", "GET", "/climate/products/{product_id}"),
    ("StripeListClimateProductsConfig", "list_climate_products", "List Climate Products", "Climate", "GET", "/climate/products"),
    ("StripeRetrieveClimateSupplierConfig", "retrieve_climate_supplier", "Retrieve Climate Supplier", "Climate", "GET", "/climate/suppliers/{supplier_id}"),
    ("StripeListClimateSuppliersConfig", "list_climate_suppliers", "List Climate Suppliers", "Climate", "GET", "/climate/suppliers"),
    # ---- Forwarding ----
    ("StripeCreateForwardingRequestConfig", "create_forwarding_request", "Create Forwarding Request", "Forwarding", "POST", "/forwarding/requests"),
    ("StripeRetrieveForwardingRequestConfig", "retrieve_forwarding_request", "Retrieve Forwarding Request", "Forwarding", "GET", "/forwarding/requests/{request_id}"),
    ("StripeListForwardingRequestsConfig", "list_forwarding_requests", "List Forwarding Requests", "Forwarding", "GET", "/forwarding/requests"),
    # ---- Test Helpers: Test Clocks ----
    ("StripeCreateTestClockConfig", "create_test_clock", "Create Test Clock", "Test Helpers", "POST", "/test_helpers/test_clocks"),
    ("StripeRetrieveTestClockConfig", "retrieve_test_clock", "Retrieve Test Clock", "Test Helpers", "GET", "/test_helpers/test_clocks/{test_clock_id}"),
    ("StripeDeleteTestClockConfig", "delete_test_clock", "Delete Test Clock", "Test Helpers", "DELETE", "/test_helpers/test_clocks/{test_clock_id}"),
    ("StripeListTestClocksConfig", "list_test_clocks", "List Test Clocks", "Test Helpers", "GET", "/test_helpers/test_clocks"),
    ("StripeAdvanceTestClockConfig", "advance_test_clock", "Advance Test Clock", "Test Helpers", "POST", "/test_helpers/test_clocks/{test_clock_id}/advance"),
]


def _titleize(field: str) -> str:
    base = field[:-3] if field.endswith("_id") else field
    return base.replace("_", " ").title() or field


def _make_extended_model(class_name, op, display, category, method, path):
    fields: Dict[str, Any] = {"operation": (Literal[op], _opf(op, display, category))}
    for placeholder in re.findall(r"{(\w+)}", path):
        fields[placeholder] = (str, Field(..., title=_titleize(placeholder)))
    if op.startswith("list_"):
        fields["limit"] = (Optional[int], _limit())
        fields["starting_after"] = (Optional[str], _start())
    # Every extended op accepts arbitrary Stripe params (body for writes, query
    # filters for reads) so the resource's full parameter set stays reachable.
    fields["extra_params"] = (Optional[Dict[str, Any]], _extra())
    return create_model(class_name, **fields)


_EXTENDED_MODELS: List[Any] = []
_EXTENDED_OPERATIONS: Dict[str, Tuple[str, str]] = {}
for _cn, _op, _disp, _cat, _method, _path in _EXTENDED_SPECS:
    _EXTENDED_MODELS.append(_make_extended_model(_cn, _op, _disp, _cat, _method, _path))
    _EXTENDED_OPERATIONS[_op] = (_method, _path)


_EXPLICIT_MEMBERS = [
        # Customers
        StripeCreateCustomerConfig,
        StripeRetrieveCustomerConfig,
        StripeUpdateCustomerConfig,
        StripeDeleteCustomerConfig,
        StripeListCustomersConfig,
        StripeSearchCustomersConfig,
        # Payment Intents
        StripeCreatePaymentIntentConfig,
        StripeRetrievePaymentIntentConfig,
        StripeUpdatePaymentIntentConfig,
        StripeListPaymentIntentsConfig,
        StripeCapturePaymentIntentConfig,
        StripeConfirmPaymentIntentConfig,
        StripeCancelPaymentIntentConfig,
        StripeSearchPaymentIntentsConfig,
        # Charges
        StripeCreateChargeConfig,
        StripeRetrieveChargeConfig,
        StripeUpdateChargeConfig,
        StripeListChargesConfig,
        StripeCaptureChargeConfig,
        StripeSearchChargesConfig,
        # Payment Methods
        StripeCreatePaymentMethodConfig,
        StripeRetrievePaymentMethodConfig,
        StripeUpdatePaymentMethodConfig,
        StripeListPaymentMethodsConfig,
        StripeAttachPaymentMethodConfig,
        StripeDetachPaymentMethodConfig,
        # Setup Intents
        StripeCreateSetupIntentConfig,
        StripeRetrieveSetupIntentConfig,
        StripeUpdateSetupIntentConfig,
        StripeListSetupIntentsConfig,
        StripeConfirmSetupIntentConfig,
        StripeCancelSetupIntentConfig,
        # Refunds
        StripeCreateRefundConfig,
        StripeRetrieveRefundConfig,
        StripeUpdateRefundConfig,
        StripeListRefundsConfig,
        StripeCancelRefundConfig,
        # Disputes
        StripeRetrieveDisputeConfig,
        StripeUpdateDisputeConfig,
        StripeListDisputesConfig,
        StripeCloseDisputeConfig,
        # Balance
        StripeRetrieveBalanceConfig,
        StripeRetrieveBalanceTransactionConfig,
        StripeListBalanceTransactionsConfig,
        # Checkout
        StripeCreateCheckoutSessionConfig,
        StripeRetrieveCheckoutSessionConfig,
        StripeListCheckoutSessionsConfig,
        StripeExpireCheckoutSessionConfig,
        StripeListCheckoutLineItemsConfig,
        # Payment Links
        StripeCreatePaymentLinkConfig,
        StripeRetrievePaymentLinkConfig,
        StripeUpdatePaymentLinkConfig,
        StripeListPaymentLinksConfig,
        StripeListPaymentLinkLineItemsConfig,
        # Products
        StripeCreateProductConfig,
        StripeRetrieveProductConfig,
        StripeUpdateProductConfig,
        StripeDeleteProductConfig,
        StripeListProductsConfig,
        StripeSearchProductsConfig,
        # Prices
        StripeCreatePriceConfig,
        StripeRetrievePriceConfig,
        StripeUpdatePriceConfig,
        StripeListPricesConfig,
        StripeSearchPricesConfig,
        # Subscriptions
        StripeCreateSubscriptionConfig,
        StripeRetrieveSubscriptionConfig,
        StripeUpdateSubscriptionConfig,
        StripeCancelSubscriptionConfig,
        StripeListSubscriptionsConfig,
        StripeResumeSubscriptionConfig,
        StripeSearchSubscriptionsConfig,
        # Subscription Items
        StripeCreateSubscriptionItemConfig,
        StripeRetrieveSubscriptionItemConfig,
        StripeUpdateSubscriptionItemConfig,
        StripeDeleteSubscriptionItemConfig,
        StripeListSubscriptionItemsConfig,
        # Invoices
        StripeCreateInvoiceConfig,
        StripeRetrieveInvoiceConfig,
        StripeUpdateInvoiceConfig,
        StripeDeleteInvoiceConfig,
        StripeListInvoicesConfig,
        StripeFinalizeInvoiceConfig,
        StripePayInvoiceConfig,
        StripeSendInvoiceConfig,
        StripeVoidInvoiceConfig,
        StripeMarkUncollectibleInvoiceConfig,
        StripeSearchInvoicesConfig,
        # Invoice Items
        StripeCreateInvoiceItemConfig,
        StripeRetrieveInvoiceItemConfig,
        StripeUpdateInvoiceItemConfig,
        StripeDeleteInvoiceItemConfig,
        StripeListInvoiceItemsConfig,
        # Credit Notes
        StripeCreateCreditNoteConfig,
        StripeRetrieveCreditNoteConfig,
        StripeUpdateCreditNoteConfig,
        StripeListCreditNotesConfig,
        StripeVoidCreditNoteConfig,
        # Coupons
        StripeCreateCouponConfig,
        StripeRetrieveCouponConfig,
        StripeUpdateCouponConfig,
        StripeDeleteCouponConfig,
        StripeListCouponsConfig,
        # Promotion Codes
        StripeCreatePromotionCodeConfig,
        StripeRetrievePromotionCodeConfig,
        StripeUpdatePromotionCodeConfig,
        StripeListPromotionCodesConfig,
        # Quotes
        StripeCreateQuoteConfig,
        StripeRetrieveQuoteConfig,
        StripeUpdateQuoteConfig,
        StripeListQuotesConfig,
        StripeFinalizeQuoteConfig,
        StripeAcceptQuoteConfig,
        StripeCancelQuoteConfig,
        # Tax Rates
        StripeCreateTaxRateConfig,
        StripeRetrieveTaxRateConfig,
        StripeUpdateTaxRateConfig,
        StripeListTaxRatesConfig,
        # Billing Portal
        StripeCreateBillingPortalSessionConfig,
        # Connect
        StripeCreateAccountConfig,
        StripeRetrieveAccountConfig,
        StripeUpdateAccountConfig,
        StripeDeleteAccountConfig,
        StripeListAccountsConfig,
        StripeRejectAccountConfig,
        StripeCreateAccountLinkConfig,
        StripeCreateLoginLinkConfig,
        StripeCreateTransferConfig,
        StripeRetrieveTransferConfig,
        StripeUpdateTransferConfig,
        StripeListTransfersConfig,
        StripeCreatePayoutConfig,
        StripeRetrievePayoutConfig,
        StripeUpdatePayoutConfig,
        StripeListPayoutsConfig,
        StripeCancelPayoutConfig,
        StripeReversePayoutConfig,
        StripeCreateTopupConfig,
        StripeRetrieveTopupConfig,
        StripeListTopupsConfig,
        StripeCancelTopupConfig,
        StripeRetrieveApplicationFeeConfig,
        StripeListApplicationFeesConfig,
        # Events
        StripeRetrieveEventConfig,
        StripeListEventsConfig,
        # Webhook Endpoints
        StripeCreateWebhookEndpointConfig,
        StripeRetrieveWebhookEndpointConfig,
        StripeUpdateWebhookEndpointConfig,
        StripeDeleteWebhookEndpointConfig,
        StripeListWebhookEndpointsConfig,
        # Files
        StripeRetrieveFileConfig,
        StripeListFilesConfig,
        StripeCreateFileLinkConfig,
        StripeRetrieveFileLinkConfig,
        StripeUpdateFileLinkConfig,
        StripeListFileLinksConfig,
        # Advanced
        StripeCustomRequestConfig,
        # Triggers
        StripeOnEventConfig,
]

StripeConfig = Annotated[
    Union[tuple(_EXPLICIT_MEMBERS + _EXTENDED_MODELS + _TRIGGER_MODELS)],
    Discriminator("operation"),
]


class StripeNodeConfig(NodeConfig[StripeConfig, StripeCredential]):
    """Full configuration for the Stripe node (config + credentials)."""

    pass


# ============================================================================
# Operation routing table: operation -> (HTTP method, path template)
# Path placeholders ({customer_id}, …) are filled from the config; remaining
# fields become the request body (POST/DELETE) or query string (GET).
# ============================================================================

_OPERATIONS: Dict[str, Tuple[str, str]] = {
    # Customers
    "create_customer": ("POST", "/customers"),
    "retrieve_customer": ("GET", "/customers/{customer_id}"),
    "update_customer": ("POST", "/customers/{customer_id}"),
    "delete_customer": ("DELETE", "/customers/{customer_id}"),
    "list_customers": ("GET", "/customers"),
    "search_customers": ("GET", "/customers/search"),
    # Payment Intents
    "create_payment_intent": ("POST", "/payment_intents"),
    "retrieve_payment_intent": ("GET", "/payment_intents/{payment_intent_id}"),
    "update_payment_intent": ("POST", "/payment_intents/{payment_intent_id}"),
    "list_payment_intents": ("GET", "/payment_intents"),
    "capture_payment_intent": ("POST", "/payment_intents/{payment_intent_id}/capture"),
    "confirm_payment_intent": ("POST", "/payment_intents/{payment_intent_id}/confirm"),
    "cancel_payment_intent": ("POST", "/payment_intents/{payment_intent_id}/cancel"),
    "search_payment_intents": ("GET", "/payment_intents/search"),
    # Charges
    "create_charge": ("POST", "/charges"),
    "retrieve_charge": ("GET", "/charges/{charge_id}"),
    "update_charge": ("POST", "/charges/{charge_id}"),
    "list_charges": ("GET", "/charges"),
    "capture_charge": ("POST", "/charges/{charge_id}/capture"),
    "search_charges": ("GET", "/charges/search"),
    # Payment Methods
    "create_payment_method": ("POST", "/payment_methods"),
    "retrieve_payment_method": ("GET", "/payment_methods/{payment_method_id}"),
    "update_payment_method": ("POST", "/payment_methods/{payment_method_id}"),
    "list_payment_methods": ("GET", "/payment_methods"),
    "attach_payment_method": ("POST", "/payment_methods/{payment_method_id}/attach"),
    "detach_payment_method": ("POST", "/payment_methods/{payment_method_id}/detach"),
    # Setup Intents
    "create_setup_intent": ("POST", "/setup_intents"),
    "retrieve_setup_intent": ("GET", "/setup_intents/{setup_intent_id}"),
    "update_setup_intent": ("POST", "/setup_intents/{setup_intent_id}"),
    "list_setup_intents": ("GET", "/setup_intents"),
    "confirm_setup_intent": ("POST", "/setup_intents/{setup_intent_id}/confirm"),
    "cancel_setup_intent": ("POST", "/setup_intents/{setup_intent_id}/cancel"),
    # Refunds
    "create_refund": ("POST", "/refunds"),
    "retrieve_refund": ("GET", "/refunds/{refund_id}"),
    "update_refund": ("POST", "/refunds/{refund_id}"),
    "list_refunds": ("GET", "/refunds"),
    "cancel_refund": ("POST", "/refunds/{refund_id}/cancel"),
    # Disputes
    "retrieve_dispute": ("GET", "/disputes/{dispute_id}"),
    "update_dispute": ("POST", "/disputes/{dispute_id}"),
    "list_disputes": ("GET", "/disputes"),
    "close_dispute": ("POST", "/disputes/{dispute_id}/close"),
    # Balance
    "retrieve_balance": ("GET", "/balance"),
    "retrieve_balance_transaction": ("GET", "/balance_transactions/{balance_transaction_id}"),
    "list_balance_transactions": ("GET", "/balance_transactions"),
    # Checkout
    "create_checkout_session": ("POST", "/checkout/sessions"),
    "retrieve_checkout_session": ("GET", "/checkout/sessions/{session_id}"),
    "list_checkout_sessions": ("GET", "/checkout/sessions"),
    "expire_checkout_session": ("POST", "/checkout/sessions/{session_id}/expire"),
    "list_checkout_line_items": ("GET", "/checkout/sessions/{session_id}/line_items"),
    # Payment Links
    "create_payment_link": ("POST", "/payment_links"),
    "retrieve_payment_link": ("GET", "/payment_links/{payment_link_id}"),
    "update_payment_link": ("POST", "/payment_links/{payment_link_id}"),
    "list_payment_links": ("GET", "/payment_links"),
    "list_payment_link_line_items": ("GET", "/payment_links/{payment_link_id}/line_items"),
    # Products
    "create_product": ("POST", "/products"),
    "retrieve_product": ("GET", "/products/{product_id}"),
    "update_product": ("POST", "/products/{product_id}"),
    "delete_product": ("DELETE", "/products/{product_id}"),
    "list_products": ("GET", "/products"),
    "search_products": ("GET", "/products/search"),
    # Prices
    "create_price": ("POST", "/prices"),
    "retrieve_price": ("GET", "/prices/{price_id}"),
    "update_price": ("POST", "/prices/{price_id}"),
    "list_prices": ("GET", "/prices"),
    "search_prices": ("GET", "/prices/search"),
    # Subscriptions
    "create_subscription": ("POST", "/subscriptions"),
    "retrieve_subscription": ("GET", "/subscriptions/{subscription_id}"),
    "update_subscription": ("POST", "/subscriptions/{subscription_id}"),
    "cancel_subscription": ("DELETE", "/subscriptions/{subscription_id}"),
    "list_subscriptions": ("GET", "/subscriptions"),
    "resume_subscription": ("POST", "/subscriptions/{subscription_id}/resume"),
    "search_subscriptions": ("GET", "/subscriptions/search"),
    # Subscription Items
    "create_subscription_item": ("POST", "/subscription_items"),
    "retrieve_subscription_item": ("GET", "/subscription_items/{subscription_item_id}"),
    "update_subscription_item": ("POST", "/subscription_items/{subscription_item_id}"),
    "delete_subscription_item": ("DELETE", "/subscription_items/{subscription_item_id}"),
    "list_subscription_items": ("GET", "/subscription_items"),
    # Invoices
    "create_invoice": ("POST", "/invoices"),
    "retrieve_invoice": ("GET", "/invoices/{invoice_id}"),
    "update_invoice": ("POST", "/invoices/{invoice_id}"),
    "delete_invoice": ("DELETE", "/invoices/{invoice_id}"),
    "list_invoices": ("GET", "/invoices"),
    "finalize_invoice": ("POST", "/invoices/{invoice_id}/finalize"),
    "pay_invoice": ("POST", "/invoices/{invoice_id}/pay"),
    "send_invoice": ("POST", "/invoices/{invoice_id}/send"),
    "void_invoice": ("POST", "/invoices/{invoice_id}/void"),
    "mark_uncollectible_invoice": ("POST", "/invoices/{invoice_id}/mark_uncollectible"),
    "search_invoices": ("GET", "/invoices/search"),
    # Invoice Items
    "create_invoice_item": ("POST", "/invoiceitems"),
    "retrieve_invoice_item": ("GET", "/invoiceitems/{invoice_item_id}"),
    "update_invoice_item": ("POST", "/invoiceitems/{invoice_item_id}"),
    "delete_invoice_item": ("DELETE", "/invoiceitems/{invoice_item_id}"),
    "list_invoice_items": ("GET", "/invoiceitems"),
    # Credit Notes
    "create_credit_note": ("POST", "/credit_notes"),
    "retrieve_credit_note": ("GET", "/credit_notes/{credit_note_id}"),
    "update_credit_note": ("POST", "/credit_notes/{credit_note_id}"),
    "list_credit_notes": ("GET", "/credit_notes"),
    "void_credit_note": ("POST", "/credit_notes/{credit_note_id}/void"),
    # Coupons
    "create_coupon": ("POST", "/coupons"),
    "retrieve_coupon": ("GET", "/coupons/{coupon_id}"),
    "update_coupon": ("POST", "/coupons/{coupon_id}"),
    "delete_coupon": ("DELETE", "/coupons/{coupon_id}"),
    "list_coupons": ("GET", "/coupons"),
    # Promotion Codes
    "create_promotion_code": ("POST", "/promotion_codes"),
    "retrieve_promotion_code": ("GET", "/promotion_codes/{promotion_code_id}"),
    "update_promotion_code": ("POST", "/promotion_codes/{promotion_code_id}"),
    "list_promotion_codes": ("GET", "/promotion_codes"),
    # Quotes
    "create_quote": ("POST", "/quotes"),
    "retrieve_quote": ("GET", "/quotes/{quote_id}"),
    "update_quote": ("POST", "/quotes/{quote_id}"),
    "list_quotes": ("GET", "/quotes"),
    "finalize_quote": ("POST", "/quotes/{quote_id}/finalize"),
    "accept_quote": ("POST", "/quotes/{quote_id}/accept"),
    "cancel_quote": ("POST", "/quotes/{quote_id}/cancel"),
    # Tax Rates
    "create_tax_rate": ("POST", "/tax_rates"),
    "retrieve_tax_rate": ("GET", "/tax_rates/{tax_rate_id}"),
    "update_tax_rate": ("POST", "/tax_rates/{tax_rate_id}"),
    "list_tax_rates": ("GET", "/tax_rates"),
    # Billing Portal
    "create_billing_portal_session": ("POST", "/billing_portal/sessions"),
    # Connect
    "create_account": ("POST", "/accounts"),
    "retrieve_account": ("GET", "/accounts/{account_id}"),
    "update_account": ("POST", "/accounts/{account_id}"),
    "delete_account": ("DELETE", "/accounts/{account_id}"),
    "list_accounts": ("GET", "/accounts"),
    "reject_account": ("POST", "/accounts/{account_id}/reject"),
    "create_account_link": ("POST", "/account_links"),
    "create_login_link": ("POST", "/accounts/{account_id}/login_links"),
    "create_transfer": ("POST", "/transfers"),
    "retrieve_transfer": ("GET", "/transfers/{transfer_id}"),
    "update_transfer": ("POST", "/transfers/{transfer_id}"),
    "list_transfers": ("GET", "/transfers"),
    "create_payout": ("POST", "/payouts"),
    "retrieve_payout": ("GET", "/payouts/{payout_id}"),
    "update_payout": ("POST", "/payouts/{payout_id}"),
    "list_payouts": ("GET", "/payouts"),
    "cancel_payout": ("POST", "/payouts/{payout_id}/cancel"),
    "reverse_payout": ("POST", "/payouts/{payout_id}/reverse"),
    "create_topup": ("POST", "/topups"),
    "retrieve_topup": ("GET", "/topups/{topup_id}"),
    "list_topups": ("GET", "/topups"),
    "cancel_topup": ("POST", "/topups/{topup_id}/cancel"),
    "retrieve_application_fee": ("GET", "/application_fees/{fee_id}"),
    "list_application_fees": ("GET", "/application_fees"),
    # Events
    "retrieve_event": ("GET", "/events/{event_id}"),
    "list_events": ("GET", "/events"),
    # Webhook Endpoints
    "create_webhook_endpoint": ("POST", "/webhook_endpoints"),
    "retrieve_webhook_endpoint": ("GET", "/webhook_endpoints/{webhook_endpoint_id}"),
    "update_webhook_endpoint": ("POST", "/webhook_endpoints/{webhook_endpoint_id}"),
    "delete_webhook_endpoint": ("DELETE", "/webhook_endpoints/{webhook_endpoint_id}"),
    "list_webhook_endpoints": ("GET", "/webhook_endpoints"),
    # Files
    "retrieve_file": ("GET", "/files/{file_id}"),
    "list_files": ("GET", "/files"),
    "create_file_link": ("POST", "/file_links"),
    "retrieve_file_link": ("GET", "/file_links/{file_link_id}"),
    "update_file_link": ("POST", "/file_links/{file_link_id}"),
    "list_file_links": ("GET", "/file_links"),
}
_OPERATIONS.update(_EXTENDED_OPERATIONS)

_PATH_PLACEHOLDER_RE = re.compile(r"{(\w+)}")
_PATH_FIELDS: Dict[str, List[str]] = {
    op: _PATH_PLACEHOLDER_RE.findall(tmpl) for op, (_m, tmpl) in _OPERATIONS.items()
}

# Dynamic-dropdown field name -> (list endpoint, label key candidates)
_DYNAMIC_RESOURCES: Dict[str, Tuple[str, List[str]]] = {
    "customer": ("/customers", ["email", "name"]),
    "customer_id": ("/customers", ["email", "name"]),
    "product": ("/products", ["name"]),
    "product_id": ("/products", ["name"]),
    "price": ("/prices", ["nickname"]),
    "price_id": ("/prices", ["nickname"]),
    "subscription": ("/subscriptions", []),
    "subscription_id": ("/subscriptions", []),
}


# ============================================================================
# Node implementation
# ============================================================================


class StripeNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Stripe automation node — executes Stripe operations via the REST API."""

    edit_examples = [
        "Create a customer and a $20 one-time payment link",
        "List all active subscriptions for a customer",
        "Refund the most recent charge for an order",
        "Create a product and a recurring monthly price for it",
        "Finalize and send a draft invoice",
        "Trigger a workflow whenever a payment_intent.succeeded event fires",
    ]

    scope_registry = STRIPE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="customer_id",
        noun="customers",
    )

    @classmethod
    def get_config_model(cls):
        return StripeNodeConfig

    # ----- token resolution -------------------------------------------------

    def _token(self, credentials: StripeCredential) -> str:
        if isinstance(credentials, StripeOAuthCredential):
            return credentials.access_token
        return credentials.api_key

    def _stripe_account(self, credentials: StripeCredential) -> Optional[str]:
        if isinstance(credentials, StripeApiKeyCredential):
            return credentials.stripe_account
        return None

    def _stripe_version(self, credentials: StripeCredential) -> Optional[str]:
        return getattr(credentials, "stripe_version", None)

    async def _ensure_fresh_token(self, credentials: StripeCredential) -> str:
        """Stripe API keys and Connect OAuth access tokens don't expire, so this
        simply returns the bearer token. ``freshen_credential`` covers the load
        path for symmetry with other OAuth nodes."""
        return self._token(credentials)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """No-op for Stripe (non-expiring, non-rotating tokens)."""
        return credential_data

    # ----- HTTP -------------------------------------------------------------

    async def _make_request(
        self,
        method: str,
        path: str,
        credentials: StripeCredential,
        *,
        body: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        action: str = "request",
        stripe_account: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        stripe_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated Stripe API request with timing + form-encoding."""
        total_start = time.time()
        token = await self._ensure_fresh_token(credentials)

        headers = {"Authorization": f"Bearer {token}"}
        acct = stripe_account or self._stripe_account(credentials)
        if acct:
            headers["Stripe-Account"] = acct
        version = stripe_version or self._stripe_version(credentials)
        if version:
            headers["Stripe-Version"] = version
        if method in ("POST", "DELETE"):
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())

        # The /v2 namespace is JSON-encoded against the bare host; /v1 (the
        # classic API) is form/bracket-encoded under /v1. The form body is
        # encoded here and sent via ``content=`` (not httpx ``data=``, whose
        # urlencoded path can yield a sync byte stream that an AsyncClient
        # rejects on some interpreter/httpx combinations).
        is_v2 = path.startswith("/v2/") or path == "/v2"
        request_kwargs: Dict[str, Any] = {"timeout": 30.0}
        if is_v2:
            url = f"{STRIPE_HOST}{path}"
            request_kwargs["params"] = query or None
            if body:
                request_kwargs["json"] = body
        else:
            url = f"{STRIPE_API_BASE}{path}"
            request_kwargs["params"] = _to_form(query) if query else None
            if body:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                request_kwargs["content"] = urlencode(_to_form(body))

        async with httpx.AsyncClient() as client:
            api_start = time.time()
            logger.info(f"[StripeNode] 🔌 {method} {path}")
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                **request_kwargs,
            )
            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[StripeNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            payload = response.json() if response.content else None

            if response.status_code >= 400:
                err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "stripe",
                    "action": action,
                    "status": "error",
                    "error": err.get("message", response.text),
                    "error_code": err.get("code"),
                    "error_type": err.get("type"),
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {"api_request": round(api_time, 1), "total": round(total_time, 1)},
                }
                logger.error(f"[StripeNode] API error: {output['error']}")
                await self.emit(output)
                return output

            total_time = (time.time() - total_start) * 1000
            output: Dict[str, Any] = {
                "type": "stripe",
                "action": action,
                "status": "success",
                "data": payload,
                "status_code": response.status_code,
                "timestamp": time.time(),
                "timing_ms": {"api_request": round(api_time, 1), "total": round(total_time, 1)},
            }
            # Surface list pagination cursors at the top level for convenience.
            if isinstance(payload, dict) and payload.get("object") == "list":
                output["has_more"] = payload.get("has_more", False)
                items = payload.get("data") or []
                if items and isinstance(items[-1], dict) and items[-1].get("id"):
                    output["last_id"] = items[-1]["id"]
            await self.emit(output)
            return output

    # ----- execute ----------------------------------------------------------

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[StripeNode] Executing node {self.node_id}")
        node_config = self.config
        if not node_config or not isinstance(node_config, StripeNodeConfig):
            raise ValueError("StripeNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials
        op = config.operation

        # Trigger nodes only emit a descriptive payload on manual run.
        if op in _TRIGGER_OPERATIONS:
            return await self._on_event_manual(config)

        if not credentials:
            raise ValueError(
                "[StripeNode] Credentials are required. Add a Stripe API key or "
                "connect your account in the node's credentials tab."
            )

        if op == "custom_request":
            return await self._custom_request(config, credentials)

        spec = _OPERATIONS.get(op)
        if not spec:
            raise ValueError(f"[StripeNode] Unknown operation: {op}")

        method, path_template = spec
        data = config.model_dump(exclude_none=True)
        data.pop("operation", None)
        extra = data.pop("extra_params", None) or {}

        path = path_template
        for field in _PATH_FIELDS[op]:
            value = data.pop(field, None)
            if value is None or value == "":
                raise ValueError(f"[StripeNode] '{field}' is required for {op}")
            path = path.replace("{" + field + "}", quote(str(value), safe=""))

        # extra_params override/extend typed fields.
        for key, value in extra.items():
            data[key] = value

        if method == "GET":
            return await self._make_request(method, path, credentials, query=data, action=op)
        return await self._make_request(method, path, credentials, body=data, action=op)

    async def _custom_request(self, config: StripeCustomRequestConfig, credentials) -> Dict[str, Any]:
        method = config.http_method.upper()
        path = config.path.strip()
        if path.startswith("/v1/"):
            path = path[3:]
        elif path.startswith("v1/"):
            path = "/" + path[3:]
        if not path.startswith("/"):
            path = "/" + path
        params = config.params or {}
        if method == "GET":
            return await self._make_request(
                method, path, credentials, query=params, action="custom_request",
                stripe_account=config.stripe_account, idempotency_key=config.idempotency_key,
                stripe_version=config.stripe_version,
            )
        return await self._make_request(
            method, path, credentials, body=params, action="custom_request",
            stripe_account=config.stripe_account, idempotency_key=config.idempotency_key,
            stripe_version=config.stripe_version,
        )

    # ----- dynamic dropdowns ------------------------------------------------

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List a Stripe resource to populate an ID dropdown."""
        resource = _DYNAMIC_RESOURCES.get(field_name)
        if not resource:
            return {"options": [], "next_page_token": None}
        token = _stripe_token_from_credential(credential_data or {})
        if not token:
            return {"options": [], "next_page_token": None}

        endpoint, label_keys = resource
        params: List[Tuple[str, str]] = [("limit", "100")]
        if page_token:
            params.append(("starting_after", page_token))
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{STRIPE_API_BASE}{endpoint}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                response.raise_for_status()
                body = response.json() or {}
        except Exception as e:
            logger.warning(f"[StripeNode] load_field_options({field_name}) failed: {e}")
            return {"options": [], "next_page_token": None}

        items = body.get("data") or []
        options = []
        for obj in items:
            oid = obj.get("id")
            if not oid:
                continue
            label = next((str(obj[k]) for k in label_keys if obj.get(k)), oid)
            options.append({"value": oid, "label": f"{label} ({oid})" if label != oid else oid})
        next_token = items[-1].get("id") if body.get("has_more") and items else None
        return {"options": options, "next_page_token": next_token}

    # ----- trigger ----------------------------------------------------------

    async def _on_event_manual(self, config) -> Dict[str, Any]:
        op = getattr(config, "operation", "on_event")
        return {
            "type": "stripe",
            "action": op,
            "status": "success",
            "message": (
                "This trigger fires when Stripe sends a matching webhook event. "
                "It outputs the Stripe event object."
            ),
            "event_types": _TRIGGER_EVENTS.get(op) or getattr(config, "event_types", None),
        }

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Fire only for the event(s) this trigger op listens for. Decomposed ops
        match their single event type; the generic op uses its allowlist."""
        op = (config or {}).get("operation")
        event_type = _TRIGGER_EVENTS.get(op)
        if event_type is not None:
            return payload.get("type") == event_type
        # Generic "On Custom Event" — comma-separated allowlist (empty = all).
        allow = (config or {}).get("event_types")
        if not allow:
            return True
        wanted = {t.strip() for t in str(allow).split(",") if t.strip()}
        return not wanted or payload.get("type") in wanted

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Dict[str, Any]:
        """Surface the Stripe event type + object to a downstream agent."""
        import json

        event_type = output.get("type", "stripe.event")
        obj = ((output.get("data") or {}).get("object")) if isinstance(output, dict) else None
        text = f"Stripe event: {event_type}\n{json.dumps(obj or output, default=str)[:4000]}"
        return {"text": text, "conversation_key": None}

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Stripe's ``Stripe-Signature: t=…,v1=…`` header (HMAC-SHA256 of
        ``{t}.{payload}`` with the endpoint signing secret)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        sig_header = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not sig_header:
            return False
        parts = dict(
            p.split("=", 1) for p in sig_header.split(",") if "=" in p
        )
        timestamp = parts.get("t")
        provided = parts.get("v1")
        if not timestamp or not provided:
            return False
        signed_payload = f"{timestamp}.".encode() + body
        expected = hmac.new(
            secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ) -> Dict[str, Any]:
        token = _stripe_token_from_credential(credential)
        if not token:
            raise ValueError("Stripe credential is missing an API key / access token")
        # Decomposed ops register for their single event; the generic op uses its
        # allowlist (or all events).
        op = (config or {}).get("operation")
        event_type = _TRIGGER_EVENTS.get(op)
        if event_type is not None:
            events = [event_type]
        else:
            allow = (config or {}).get("event_types")
            events = [t.strip() for t in str(allow).split(",") if t.strip()] if allow else ["*"]
        stripe_account = (credential or {}).get("stripe_account")

        # Drop a stale endpoint from a prior registration first (not idempotent).
        existing = (config or {}).get("external_webhook_id")
        if existing:
            try:
                await unregister_stripe_webhook(token, existing, stripe_account)
            except Exception as e:
                logger.warning(f"[StripeNode] Could not remove stale webhook endpoint: {e}")

        endpoint_id, secret = await register_stripe_webhook(
            token, webhook_url, events, stripe_account
        )
        return {"signing_secret": secret, "external_webhook_id": endpoint_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        endpoint_id = (config or {}).get("external_webhook_id")
        token = _stripe_token_from_credential(credential or {})
        if not (endpoint_id and token):
            return
        stripe_account = (credential or {}).get("stripe_account")
        await unregister_stripe_webhook(token, endpoint_id, stripe_account)

"""PayPal REST automation using app client credentials.

The catalog follows PayPal's current Orders, Payments, Catalog Products,
Subscriptions, Invoicing, Payouts, Reporting, Webhooks, and Disputes APIs.
https://developer.paypal.com/api/rest/current-resources/
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
import zlib
from datetime import datetime, timezone
from functools import lru_cache
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.oauth_token_cache import OAuthTokenCache, oauth_authority_digest, token_expiry_input

_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}
_PATH_PARAM = re.compile(r"\{([a-z_]+)\}")
_TOKEN_CACHE = OAuthTokenCache(refresh_skew_seconds=120)


class PayPalClientCredential(BaseModel):
    model_config = ConfigDict(title="PayPal App", json_schema_extra={
        "x-credential-url": "https://developer.paypal.com/dashboard/applications",
        "x-credential-type": "api_key",
    })
    credential_type: Literal["paypal_client_credentials"] = Field(
        "paypal_client_credentials", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="Client ID", description="PayPal REST app client ID.")
    client_secret: str = Field(..., title="Client Secret", json_schema_extra={"ui:widget": "password"})
    environment: Literal["sandbox", "live"] = Field(
        "sandbox", title="Environment", description="Use Sandbox while testing. Live can move real money.")


@dataclass(frozen=True)
class Operation:
    name: str
    method: str
    path: str
    category: str
    body: bool = False


def _ops(category: str, *rows: tuple[str, str, str]) -> list[Operation]:
    return [Operation(name, method, path, category, method in {"POST", "PUT", "PATCH"})
            for name, method, path in rows]


OPERATIONS: tuple[Operation, ...] = (
    *_ops("Orders",
        ("create_order", "POST", "/v2/checkout/orders"),
        ("get_order", "GET", "/v2/checkout/orders/{order_id}"),
        ("update_order", "PATCH", "/v2/checkout/orders/{order_id}"),
        ("confirm_order_payment_source", "POST", "/v2/checkout/orders/{order_id}/confirm-payment-source"),
        ("authorize_order", "POST", "/v2/checkout/orders/{order_id}/authorize"),
        ("capture_order", "POST", "/v2/checkout/orders/{order_id}/capture"),
        ("add_order_tracking", "POST", "/v2/checkout/orders/{order_id}/track"),
        ("update_order_tracking", "PATCH", "/v2/checkout/orders/{order_id}/trackers/{tracker_id}")),
    *_ops("Catalog Products",
        ("list_products", "GET", "/v1/catalogs/products"),
        ("create_product", "POST", "/v1/catalogs/products"),
        ("get_product", "GET", "/v1/catalogs/products/{product_id}"),
        ("update_product", "PATCH", "/v1/catalogs/products/{product_id}")),
    *_ops("Billing Plans",
        ("list_plans", "GET", "/v1/billing/plans"),
        ("create_plan", "POST", "/v1/billing/plans"),
        ("get_plan", "GET", "/v1/billing/plans/{plan_id}"),
        ("update_plan", "PATCH", "/v1/billing/plans/{plan_id}"),
        ("activate_plan", "POST", "/v1/billing/plans/{plan_id}/activate"),
        ("deactivate_plan", "POST", "/v1/billing/plans/{plan_id}/deactivate"),
        ("update_plan_pricing", "POST", "/v1/billing/plans/{plan_id}/update-pricing-schemes")),
    *_ops("Subscriptions",
        ("list_subscriptions", "GET", "/v1/billing/subscriptions"),
        ("create_subscription", "POST", "/v1/billing/subscriptions"),
        ("get_subscription", "GET", "/v1/billing/subscriptions/{subscription_id}"),
        ("update_subscription", "PATCH", "/v1/billing/subscriptions/{subscription_id}"),
        ("revise_subscription", "POST", "/v1/billing/subscriptions/{subscription_id}/revise"),
        ("suspend_subscription", "POST", "/v1/billing/subscriptions/{subscription_id}/suspend"),
        ("cancel_subscription", "POST", "/v1/billing/subscriptions/{subscription_id}/cancel"),
        ("activate_subscription", "POST", "/v1/billing/subscriptions/{subscription_id}/activate"),
        ("capture_subscription_payment", "POST", "/v1/billing/subscriptions/{subscription_id}/capture"),
        ("list_subscription_transactions", "GET", "/v1/billing/subscriptions/{subscription_id}/transactions")),
    *_ops("Invoices",
        ("list_invoices", "GET", "/v2/invoicing/invoices"),
        ("create_draft_invoice", "POST", "/v2/invoicing/invoices"),
        ("send_invoice", "POST", "/v2/invoicing/invoices/{invoice_id}/send"),
        ("remind_invoice", "POST", "/v2/invoicing/invoices/{invoice_id}/remind"),
        ("cancel_sent_invoice", "POST", "/v2/invoicing/invoices/{invoice_id}/cancel"),
        ("record_invoice_payment", "POST", "/v2/invoicing/invoices/{invoice_id}/payments"),
        ("delete_invoice_payment", "DELETE", "/v2/invoicing/invoices/{invoice_id}/payments/{transaction_id}"),
        ("record_invoice_refund", "POST", "/v2/invoicing/invoices/{invoice_id}/refunds"),
        ("delete_invoice_refund", "DELETE", "/v2/invoicing/invoices/{invoice_id}/refunds/{transaction_id}"),
        ("generate_invoice_qr_code", "POST", "/v2/invoicing/invoices/{invoice_id}/generate-qr-code"),
        ("generate_invoice_number", "POST", "/v2/invoicing/generate-next-invoice-number"),
        ("get_invoice", "GET", "/v2/invoicing/invoices/{invoice_id}"),
        ("delete_invoice", "DELETE", "/v2/invoicing/invoices/{invoice_id}"),
        ("update_invoice", "PUT", "/v2/invoicing/invoices/{invoice_id}"),
        ("cancel_invoice_reminders", "POST", "/v2/invoicing/invoices/{invoice_id}/cancel-reminders"),
        ("search_invoices", "POST", "/v2/invoicing/search-invoices")),
    *_ops("Invoice Templates",
        ("list_invoice_templates", "GET", "/v2/invoicing/templates"),
        ("create_invoice_template", "POST", "/v2/invoicing/templates"),
        ("get_invoice_template", "GET", "/v2/invoicing/templates/{template_id}"),
        ("delete_invoice_template", "DELETE", "/v2/invoicing/templates/{template_id}"),
        ("update_invoice_template", "PUT", "/v2/invoicing/templates/{template_id}")),
    *_ops("Invoice Conditional Rules",
        ("get_invoice_conditional_rule", "GET", "/v2/invoicing/invoices/{invoice_id}/conditional-rules/{rule_id}"),
        ("delete_invoice_conditional_rule", "DELETE", "/v2/invoicing/invoices/{invoice_id}/conditional-rules/{rule_id}"),
        ("update_invoice_conditional_rule", "PUT", "/v2/invoicing/invoices/{invoice_id}/conditional-rules/{rule_id}"),
        ("list_invoice_conditional_rules", "GET", "/v2/invoicing/invoices/{invoice_id}/conditional-rules"),
        ("create_invoice_conditional_rule", "POST", "/v2/invoicing/invoices/{invoice_id}/conditional-rules")),
    *_ops("Recurring Invoices",
        ("create_recurring_invoice", "POST", "/v2/invoicing/recurring-invoices"),
        ("get_recurring_invoice", "GET", "/v2/invoicing/recurring-invoices/{series_id}"),
        ("delete_recurring_invoice", "DELETE", "/v2/invoicing/recurring-invoices/{series_id}"),
        ("update_recurring_invoice", "PUT", "/v2/invoicing/recurring-invoices/{series_id}"),
        ("activate_recurring_invoice", "POST", "/v2/invoicing/recurring-invoices/{series_id}/activate"),
        ("cancel_recurring_invoice", "POST", "/v2/invoicing/recurring-invoices/{series_id}/cancel"),
        ("search_recurring_invoices", "POST", "/v2/invoicing/search-recurring-invoices")),
    *_ops("Invoice Reminders",
        ("setup_auto_reminders", "POST", "/v2/invoicing/setup-reminders"),
        ("list_auto_reminders", "GET", "/v2/invoicing/reminders"),
        ("get_auto_reminder", "GET", "/v2/invoicing/reminders/{reminder_id}"),
        ("update_auto_reminder", "PUT", "/v2/invoicing/reminders/{reminder_id}"),
        ("suspend_auto_reminder", "POST", "/v2/invoicing/reminders/{reminder_id}/suspend"),
        ("resume_auto_reminder", "POST", "/v2/invoicing/reminders/{reminder_id}/resume")),
    *_ops("Payments",
        ("get_authorization", "GET", "/v2/payments/authorizations/{authorization_id}"),
        ("capture_authorization", "POST", "/v2/payments/authorizations/{authorization_id}/capture"),
        ("reauthorize_payment", "POST", "/v2/payments/authorizations/{authorization_id}/reauthorize"),
        ("void_authorization", "POST", "/v2/payments/authorizations/{authorization_id}/void"),
        ("get_capture", "GET", "/v2/payments/captures/{capture_id}"),
        ("refund_capture", "POST", "/v2/payments/captures/{capture_id}/refund"),
        ("find_eligible_payment_methods", "POST", "/v2/payments/find-eligible-methods"),
        ("get_refund", "GET", "/v2/payments/refunds/{refund_id}")),
    *_ops("Payouts",
        ("create_batch_payout", "POST", "/v1/payments/payouts"),
        ("get_payout_batch", "GET", "/v1/payments/payouts/{batch_id}"),
        ("get_payout_item", "GET", "/v1/payments/payouts-item/{item_id}"),
        ("cancel_payout_item", "POST", "/v1/payments/payouts-item/{item_id}/cancel")),
    *_ops("Reporting",
        ("list_transactions", "GET", "/v1/reporting/transactions"),
        ("list_balances", "GET", "/v1/reporting/balances"),
        ("get_balance_net_summary", "GET", "/v1/reporting/get-balance-net-summary"),
        ("get_daily_summary", "GET", "/v1/reporting/get-daily-summary")),
    *_ops("Webhooks",
        ("list_webhooks", "GET", "/v1/notifications/webhooks"),
        ("create_webhook", "POST", "/v1/notifications/webhooks"),
        ("get_webhook", "GET", "/v1/notifications/webhooks/{webhook_id}"),
        ("update_webhook", "PATCH", "/v1/notifications/webhooks/{webhook_id}"),
        ("delete_webhook", "DELETE", "/v1/notifications/webhooks/{webhook_id}"),
        ("list_webhook_event_subscriptions", "GET", "/v1/notifications/webhooks/{webhook_id}/event-types"),
        ("list_webhook_lookups", "GET", "/v1/notifications/webhooks-lookup"),
        ("create_webhook_lookup", "POST", "/v1/notifications/webhooks-lookup"),
        ("get_webhook_lookup", "GET", "/v1/notifications/webhooks-lookup/{lookup_id}"),
        ("delete_webhook_lookup", "DELETE", "/v1/notifications/webhooks-lookup/{lookup_id}"),
        ("verify_webhook_signature", "POST", "/v1/notifications/verify-webhook-signature"),
        ("list_webhook_event_types", "GET", "/v1/notifications/webhooks-event-types"),
        ("list_webhook_events", "GET", "/v1/notifications/webhooks-events"),
        ("get_webhook_event", "GET", "/v1/notifications/webhooks-events/{event_id}"),
        ("resend_webhook_event", "POST", "/v1/notifications/webhooks-events/{event_id}/resend"),
        ("simulate_webhook_event", "POST", "/v1/notifications/simulate-event")),
    *_ops("Disputes",
        ("list_disputes", "GET", "/v1/customer/disputes"),
        ("get_dispute", "GET", "/v1/customer/disputes/{dispute_id}"),
        ("update_dispute", "PATCH", "/v1/customer/disputes/{dispute_id}"),
        ("provide_dispute_evidence", "POST", "/v1/customer/disputes/{dispute_id}/provide-evidence"),
        ("appeal_dispute", "POST", "/v1/customer/disputes/{dispute_id}/appeal"),
        ("accept_dispute_claim", "POST", "/v1/customer/disputes/{dispute_id}/accept-claim"),
        ("escalate_dispute", "POST", "/v1/customer/disputes/{dispute_id}/escalate"),
        ("send_dispute_message", "POST", "/v1/customer/disputes/{dispute_id}/send-message"),
        ("make_dispute_offer", "POST", "/v1/customer/disputes/{dispute_id}/make-offer"),
        ("accept_dispute_offer", "POST", "/v1/customer/disputes/{dispute_id}/accept-offer"),
        ("deny_dispute_offer", "POST", "/v1/customer/disputes/{dispute_id}/deny-offer"),
        ("acknowledge_dispute_return", "POST", "/v1/customer/disputes/{dispute_id}/acknowledge-return-item"),
        ("provide_dispute_supporting_info", "POST", "/v1/customer/disputes/{dispute_id}/provide-supporting-info")),
)
BY_NAME = {op.name: op for op in OPERATIONS}
assert len(BY_NAME) == len(OPERATIONS), "Duplicate PayPal operation names"


def _operation_model(op: Operation) -> type[BaseModel]:
    title = op.name.replace("_", " ").title()
    fields: dict[str, Any] = {"operation": (
        Literal[op.name], Field(op.name, title=title, json_schema_extra={
            "const": op.name, "ui:hidden": True, "x-category": op.category,
            "x-display-name": title, "x-is-trigger": False}))}
    for param in _PATH_PARAM.findall(op.path):
        fields[param] = (str, Field(..., title=param.replace("_", " ").title()))
    if op.method == "GET":
        fields["query_json"] = (Optional[str], Field(
            None, title="Filters (JSON)", description="Optional PayPal query parameters as a JSON object.",
            json_schema_extra={"ui:widget": "textarea"}))
    if op.body:
        fields["body_json"] = (Optional[str], Field(
            None, title="Request Body (JSON)",
            description="PayPal request body as JSON. PATCH actions usually require a JSON Patch array.",
            json_schema_extra={"ui:widget": "textarea"}))
    if op.method == "POST":
        fields["request_id"] = (Optional[str], Field(
            None, title="Idempotency Key", description="Optional PayPal-Request-Id. Reuse the same key when retrying a payment-changing call."))
    return create_model(f"PayPal_{op.name}_Config", **fields)


# Event names: https://developer.paypal.com/api/rest/webhooks/event-names/
PAYPAL_WEBHOOK_EVENTS = (
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.SALE.COMPLETED", "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED", "CUSTOMER.DISPUTE.CREATED",
)


class PayPalOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On PayPal Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On PayPal Event",
    })
    event_type: Literal[*PAYPAL_WEBHOOK_EVENTS] = Field(
        "PAYMENT.CAPTURE.COMPLETED", title="Event Type",
        description="The payment, subscription or dispute event that starts this workflow.")
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="Registered with PayPal automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


@lru_cache(maxsize=32)
def _webhook_certificate(url: str) -> x509.Certificate:
    # Certificates are fetched only from PayPal's documented certificate origins.
    # No redirects, query strings, ports or user-controlled alternate hosts.
    if not re.fullmatch(
        r"https://api(?:\.sandbox)?\.paypal\.com/v1/notifications/certs/[A-Za-z0-9-]+", url
    ):
        raise ValueError("Invalid PayPal certificate URL")
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
    if len(response.content) > 65536:
        raise ValueError("Invalid PayPal certificate size")
    return x509.load_pem_x509_certificate(response.content)


_CONFIG_MODELS = tuple(_operation_model(op) for op in OPERATIONS) + (PayPalOnEventConfig,)
PayPalConfig = Annotated[Union[_CONFIG_MODELS], Discriminator("operation")]


class PayPalNodeConfig(NodeConfig[PayPalConfig, PayPalClientCredential]):
    pass


def _json_value(value: Optional[str], field: str, *, array: bool = False) -> Any:
    if not value:
        return None if array else {}
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} must contain valid JSON: {exc}") from exc
    if not isinstance(parsed, list if array else dict):
        raise ValueError(f"{field} must be a JSON {'array' if array else 'object'}")
    return parsed


async def _access_token(credential: PayPalClientCredential) -> str:
    base = _BASE[credential.environment]
    key = oauth_authority_digest(provider="paypal", base=base, grant_type="client_credentials",
                                 client_id=credential.client_id, client_secret=credential.client_secret)
    cached = _TOKEN_CACHE.get(key, now=time.monotonic())
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            base + "/v1/oauth2/token", auth=(credential.client_id, credential.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
    if response.is_error:
        raise ValueError(f"PayPal authentication failed (HTTP {response.status_code})")
    payload = response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("PayPal authentication response lacked an access token")
    _TOKEN_CACHE.put(key, token, expires_in=token_expiry_input(payload), now=time.monotonic())
    return token


class PayPalNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-paypal"
    edit_examples = ["List PayPal products", "Find recent PayPal transactions",
                     "Review disputes", "Create a draft invoice"]
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products")

    @classmethod
    def get_config_model(cls):
        return PayPalNodeConfig

    # PayPal issues no shared secret: signatures use its certificate and the
    # registered webhook ID. Mirror that public ID in the row's secret slot so
    # the receiver's synchronous fallback also works before config autosave.
    webhook_signing_secret_not_issued = True
    webhook_replace_stale_endpoint = True

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type") or "PAYMENT.CAPTURE.COMPLETED"}

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        cred = PayPalClientCredential.model_validate(credential or {})
        token = await _access_token(cred)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, _BASE[cred.environment] + path, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if method == "DELETE" and response.status_code == 404:
            return {}
        if response.is_error:
            raise ValueError(f"PayPal webhook request failed (HTTP {response.status_code})")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type") or "PAYMENT.CAPTURE.COMPLETED"
        if event not in PAYPAL_WEBHOOK_EVENTS:
            raise ValueError("Choose a supported PayPal event")
        # https://developer.paypal.com/api/webhooks/v1/webhooks-post
        data = await cls._webhook_request(credential, "POST", "/v1/notifications/webhooks",
                                         body={"url": webhook_url, "event_types": [{"name": event}]})
        webhook_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(webhook_id, str) or not webhook_id.strip():
            raise ValueError("PayPal did not return a webhook ID")
        return {"external_webhook_id": webhook_id, "signing_secret": webhook_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if not webhook_id or not credential:
            return
        await cls._webhook_request(credential, "DELETE",
                                  "/v1/notifications/webhooks/" + quote(str(webhook_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://developer.paypal.com/api/rest/webhooks/rest/#link-selfverificationmethod
        headers = {k.lower(): v for k, v in headers.items()}
        webhook_id = (config or {}).get("signing_secret") or (config or {}).get("external_webhook_id")
        if not webhook_id or headers.get("paypal-auth-algo") != "SHA256withRSA":
            return False
        transmission_id = headers.get("paypal-transmission-id")
        timestamp = headers.get("paypal-transmission-time")
        signature = headers.get("paypal-transmission-sig")
        if (not transmission_id or not timestamp or not signature or not headers.get("paypal-cert-url")
                or "|" in transmission_id or "|" in timestamp):
            return False
        try:
            certificate = _webhook_certificate(headers.get("paypal-cert-url", ""))
            now = datetime.now(timezone.utc)
            if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
                return False
            key = certificate.public_key()
            if not isinstance(key, rsa.RSAPublicKey):
                return False
            message = f"{transmission_id}|{timestamp}|{webhook_id}|{zlib.crc32(body) & 0xffffffff}"
            key.verify(base64.b64decode(signature, validate=True), message.encode(),
                       padding.PKCS1v15(), hashes.SHA256())
            return True
        except (ValueError, TypeError, InvalidSignature, binascii.Error, httpx.HTTPError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict) and isinstance(payload.get("resource"), dict)
                and bool(payload.get("id")) and payload.get("event_type") in PAYPAL_WEBHOOK_EVENTS
                and payload.get("event_type") == (config or {}).get("event_type", "PAYMENT.CAPTURE.COMPLETED"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        event = output.get("data") if "status" in output and isinstance(output.get("data"), dict) else output
        resource = event.get("resource")
        if event.get("event_type") not in PAYPAL_WEBHOOK_EVENTS or not isinstance(resource, dict):
            return super().resolve_agent_event(output)
        related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
        amount = resource.get("amount") or {}
        payer = resource.get("payer") or resource.get("subscriber") or resource.get("payee") or {}
        who = payer.get("email_address") or payer.get("payer_id") or payer.get("merchant_id")
        name = payer.get("name") or {}
        if isinstance(name, dict):
            who = " ".join(str(v) for v in (name.get("given_name"), name.get("surname"), who) if v)
        kind = event["event_type"]
        rid = resource.get("id") or resource.get("dispute_id")
        title = f"PayPal {kind}: {event.get('summary') or rid or event.get('id')}"
        lines = [title]
        facts = [("Account/person", who), ("Status", resource.get("status")),
                 ("Amount", " ".join(str(v) for v in (amount.get("value"), amount.get("currency_code")) if v)),
                 ("At", event.get("create_time")), ("Event ID", event.get("id")),
                 ("Resource ID", rid), ("Order ID", related.get("order_id")),
                 ("Plan ID", resource.get("plan_id"))]
        lines.extend(f"{label}: {value}" for label, value in facts if value)
        for link in resource.get("links") or []:
            if isinstance(link, dict) and link.get("rel") in {"self", "up"} and link.get("href"):
                lines.append(f"{link['rel']}: {link['href']}")
        if rid:
            action = ("get_dispute dispute_id" if kind.startswith("CUSTOMER.DISPUTE.") else
                      "get_subscription subscription_id" if kind.startswith("BILLING.SUBSCRIPTION.") else
                      "get_refund refund_id" if kind == "PAYMENT.CAPTURE.REFUNDED" else
                      "get_capture capture_id" if kind.startswith("PAYMENT.CAPTURE.") else None)
            if action:
                lines.append(f"To inspect: {action}={rid}.")
        return {"text": "\n".join(lines), "title": title,
                "conversation_key": str(related.get("order_id") or rid or event.get("id"))}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        config = self.config
        if not isinstance(config, PayPalNodeConfig) or not config.credentials:
            raise ValueError("Connect PayPal client credentials before running this action")
        action = config.config
        if isinstance(action, PayPalOnEventConfig):
            return {"status": "success", "action": "on_event", "data": inputs}
        spec = BY_NAME[action.operation]
        try:
            path = spec.path
            for param in _PATH_PARAM.findall(path):
                identifier = str(getattr(action, param))
                if not identifier or identifier in {".", ".."} or "/" in identifier or "\\" in identifier:
                    raise ValueError(f"{param} must be a valid PayPal identifier")
                path = path.replace("{" + param + "}", quote(identifier, safe=""))
            query = _json_value(getattr(action, "query_json", None), "Filters")
            body = _json_value(getattr(action, "body_json", None), "Request Body",
                               array=spec.method == "PATCH") if spec.body else None
            if spec.method in {"PATCH", "PUT"} and not body:
                raise ValueError("Request Body is required for PATCH and PUT actions")
            request_id = getattr(action, "request_id", None)
            if request_id and (len(request_id) > 108 or not re.fullmatch(r"[A-Za-z0-9_-]+", request_id)):
                raise ValueError("Idempotency Key must be at most 108 letters, numbers, underscores or hyphens")
            token = await _access_token(config.credentials)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.request(
                    spec.method, _BASE[config.credentials.environment] + path,
                    headers=headers, params=query or None, json=body,
                )
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type.startswith("image/"):
                payload = BinaryOutput(
                    data=response.content, content_type=content_type,
                    filename="paypal-qr-code." + content_type.split("/", 1)[1],
                )
            else:
                try:
                    payload = response.json() if response.content else {}
                except ValueError:
                    payload = {"message": response.text[:1000]}
            if response.is_error:
                detail = payload.get("message") if isinstance(payload, dict) else None
                return {"status": "error", "action": spec.name, "status_code": response.status_code,
                        "error": str(detail or f"PayPal returned HTTP {response.status_code}"),
                        "data": payload, "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}
            return {"status": "success", "action": spec.name, "status_code": response.status_code,
                    "data": payload, "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}
        except (ValueError, httpx.HTTPError) as exc:
            return {"status": "error", "action": spec.name, "error": str(exc),
                    "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}

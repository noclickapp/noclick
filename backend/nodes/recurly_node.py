"""Recurly Subscriptions API v3 workflow node.

The operation table keeps the public API surface explicit: workflows cannot send
credentials to an arbitrary URL. Complex billing payloads use a JSON body field
while common identifiers and account fields remain first-class form fields.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://v3.recurly.com"
API_ACCEPT = "application/vnd.recurly.v2021-02-25+json"


class RecurlyApiKeyCredential(BaseModel):
    """A Recurly private API key, used as the HTTP Basic username."""

    credential_type: Literal["recurly_api_key"] = Field(
        "recurly_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="Private API key", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://docs.recurly.com/recurly-subscriptions/docs/api-keys",
        "x-credential-instructions": "Create a private API key in Recurly Admin under Integrations → API Credentials. Use a sandbox key when trying billing writes.",
    })


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    title: str
    doc: str
    list_result: bool = False
    json_body: bool = False


# Endpoints and methods are pinned to the official v2021-02-25 reference.
# These cover core subscription billing work without exposing an unrestricted
# request URL or accidental refund/payment operations.
OPERATIONS: Dict[str, Operation] = {
    "list_sites": Operation("GET", "/sites", "Site", "List Sites", "list_sites", True),
    "list_accounts": Operation("GET", "/accounts", "Accounts", "List Accounts", "list_accounts", True),
    "get_account": Operation("GET", "/accounts/{account_id}", "Accounts", "Get Account", "get_account"),
    "create_account": Operation("POST", "/accounts", "Accounts", "Create Account", "create_account"),
    "update_account": Operation("PUT", "/accounts/{account_id}", "Accounts", "Update Account", "update_account"),
    "list_plans": Operation("GET", "/plans", "Plans", "List Plans", "list_plans", True),
    "get_plan": Operation("GET", "/plans/{plan_id}", "Plans", "Get Plan", "get_plan"),
    "create_plan": Operation("POST", "/plans", "Plans", "Create Plan", "create_plan", json_body=True),
    "update_plan": Operation("PUT", "/plans/{plan_id}", "Plans", "Update Plan", "update_plan", json_body=True),
    "list_subscriptions": Operation("GET", "/subscriptions", "Subscriptions", "List Subscriptions", "list_subscriptions", True),
    "get_subscription": Operation("GET", "/subscriptions/{subscription_id}", "Subscriptions", "Get Subscription", "get_subscription"),
    "create_subscription": Operation("POST", "/subscriptions", "Subscriptions", "Create Subscription", "create_subscription", json_body=True),
    "update_subscription": Operation("PUT", "/subscriptions/{subscription_id}", "Subscriptions", "Update Subscription", "update_subscription", json_body=True),
    "preview_subscription_change": Operation("POST", "/subscriptions/{subscription_id}/change/preview", "Subscriptions", "Preview Subscription Change", "preview_subscription_change", json_body=True),
    "create_subscription_change": Operation("POST", "/subscriptions/{subscription_id}/change", "Subscriptions", "Create Subscription Change", "create_subscription_change", json_body=True),
    "cancel_subscription": Operation("POST", "/subscriptions/{subscription_id}/cancel", "Subscriptions", "Cancel Subscription", "cancel_subscription"),
    "get_renewal_preview": Operation("GET", "/subscriptions/{subscription_id}/preview_renewal", "Subscriptions", "Get Renewal Preview", "get_preview_renewal"),
    "list_invoices": Operation("GET", "/invoices", "Invoices", "List Invoices", "list_invoices", True),
    "get_invoice": Operation("GET", "/invoices/{invoice_id}", "Invoices", "Get Invoice", "get_invoice"),
    "list_transactions": Operation("GET", "/transactions", "Transactions", "List Transactions", "list_transactions", True),
    "get_transaction": Operation("GET", "/transactions/{transaction_id}", "Transactions", "Get Transaction", "get_transaction"),
    "list_coupons": Operation("GET", "/coupons", "Coupons", "List Coupons", "list_coupons", True),
    "get_coupon": Operation("GET", "/coupons/{coupon_id}", "Coupons", "Get Coupon", "get_coupon"),
}


def _operation_model(name: str, spec: Operation) -> type[BaseModel]:
    fields: Dict[str, Any] = {
        "operation": (Literal[name], Field(
            name, title=spec.title,
            json_schema_extra={
                "const": name, "ui:hidden": True, "x-category": spec.category,
                "x-display-name": spec.title, "x-is-trigger": False,
            },
        )),
    }
    for key in ("account_id", "plan_id", "subscription_id", "invoice_id", "transaction_id", "coupon_id"):
        if "{" + key + "}" in spec.path:
            fields[key] = (str, Field(..., title=key.replace("_", " ").title(), description="Recurly ID, or code prefixed with code- where supported"))
    if spec.list_result:
        fields["limit"] = (Optional[int], Field(None, ge=1, le=200, title="Page size"))
        fields["cursor"] = (Optional[str], Field(None, title="Cursor", description="Cursor from the previous page's next URL"))
    if name == "list_accounts":
        fields["email"] = (Optional[str], Field(None, title="Exact email"))
    if name in {"create_account", "update_account"}:
        if name == "create_account":
            fields["code"] = (str, Field(..., title="Unique account code", min_length=1, max_length=50))
        for key in ("email", "first_name", "last_name", "company"):
            fields[key] = (Optional[str], Field(None, title=key.replace("_", " ").title()))
        fields["extra_json"] = (Optional[str], Field(None, title="Additional account fields (JSON object)", json_schema_extra={"ui:widget": "textarea"}))
    if spec.json_body:
        # The API accepts nested account, currencies, add-on, and proration
        # objects. Keep their exact structure rather than flattening or losing
        # optional fields in a generated form.
        fields["body_json"] = (str, Field(..., title="Request body (JSON object)", description="Recurly v3 request object. See the operation's API reference for required fields.", json_schema_extra={"ui:widget": "textarea"}))
    return create_model(
        "Recurly" + "".join(part.title() for part in name.split("_")) + "Config",
        __doc__=f"{spec.title} using the Recurly Subscriptions API v3.",
        **fields,
    )


CONFIG_MODELS = {name: _operation_model(name, spec) for name, spec in OPERATIONS.items()}
RecurlyConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class RecurlyNodeConfig(NodeConfig[RecurlyConfig, RecurlyApiKeyCredential]):
    """Selected Recurly operation and its API key."""


def _json_object(raw: Optional[str], *, field: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return value


class RecurlyNode(WorkflowNode):
    """Run explicit Recurly v3 billing API operations."""

    edit_examples = [
        "Find a customer by email and list their subscriptions",
        "Create a Recurly account for a new customer",
        "Preview a subscription change before applying it",
        "Read an invoice and its payment status",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_sites", noun="sites", label_keys=("subdomain", "name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return RecurlyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, RecurlyNodeConfig):
            raise ValueError("Recurly configuration is required")
        if not config.credentials or not config.credentials.api_key:
            raise ValueError("Recurly private API key is required")

        selected = config.config
        name = selected.operation
        spec = OPERATIONS[name]
        values = selected.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in ("account_id", "plan_id", "subscription_id", "invoice_id", "transaction_id", "coupon_id"):
            if "{" + key + "}" in path:
                value = values.pop(key)
                if not value or value in {".", ".."} or "/" in value:
                    raise ValueError(f"Invalid {key}")
                path = path.replace("{" + key + "}", quote(value, safe=""))

        params: Dict[str, Any] = {}
        body: Optional[Dict[str, Any]] = None
        if spec.list_result:
            params = values
        elif name == "cancel_subscription":
            body = None
        elif spec.method != "GET":
            body = _json_object(values.pop("body_json", None), field="Request body")
            extra = _json_object(values.pop("extra_json", None), field="Additional account fields")
            body.update(extra)
            # Typed fields take priority over the advanced JSON object.
            body.update(values)
            if not body:
                raise ValueError("Request body cannot be empty")

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                spec.method, API_BASE + path,
                auth=httpx.BasicAuth(config.credentials.api_key, ""),
                headers={"Accept": API_ACCEPT, "Content-Type": "application/json"},
                params=params or None,
                json=body,
            )
        elapsed = round((time.monotonic() - start) * 1000, 1)
        try:
            payload = response.json() if response.content else None
        except ValueError:
            payload = {"message": response.text[:500]}

        result: Dict[str, Any] = {
            "type": "recurly", "action": name,
            "status": "error" if response.status_code >= 300 else "success",
            "status_code": response.status_code, "data": payload if response.status_code < 300 else None,
            "timing_ms": {"api_request": elapsed, "total": elapsed},
        }
        if response.status_code >= 300:
            error = payload.get("error", payload) if isinstance(payload, dict) else {}
            result["error"] = error.get("message", "Recurly API request failed") if isinstance(error, dict) else str(error)
            result["error_code"] = error.get("type") if isinstance(error, dict) else None
        elif spec.list_result and isinstance(payload, dict):
            result["has_more"] = bool(payload.get("has_more"))
            result["next"] = payload.get("next")
        await self.emit(result)
        return result

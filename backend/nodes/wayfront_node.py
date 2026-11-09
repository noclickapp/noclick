"""Wayfront workspace API: one documented request per operation.

Contract: https://clients.wayfront.com/api.yaml (version latest).
Lists return one provider page; URLs in responses are data, never followed.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class WayfrontTokenCredential(BaseModel):
    model_config = ConfigDict(title="Wayfront API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://wayfront.com/docs/api",
        "x-credential-instructions": "Paste your Wayfront workspace URL and existing API bearer token. Use a token with permission for your chosen operations. Listing clients verifies access to workspace data; it does not verify write permissions.",
    })
    credential_type: Literal["wayfront_api_token"] = Field("wayfront_api_token", json_schema_extra={"ui:hidden": True})
    workspace_url: str = Field(..., title="Workspace URL", description="Your HTTPS workspace origin, such as https://example.wayfront.com.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("workspace_url")
    @classmethod
    def workspace(cls, value):
        return normalize_provider_https_origin(value, "wayfront.com", field_name="Workspace URL")

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API token, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. Use next_page to continue.")
    limit: int = Field(20, ge=1, le=100, description="Items per page.")
    sort: str | None = Field(None, max_length=200, description="Documented field:direction sort, for example id:desc.")


class _ClientFields(_Input):
    name_f: str | None = Field(None, max_length=255, title="First name")
    name_l: str | None = Field(None, max_length=255, title="Last name")
    email: str | None = Field(None, max_length=320)
    company: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=10000)
    status_id: int | None = Field(None, ge=1)
    optin: bool | None = Field(None, description="Explicit marketing consent; omitted by default.")


class _OrderFields(_Input):
    status: int | None = Field(None, ge=1)
    service_id: int | None = Field(None, ge=1)
    note: str | None = Field(None, max_length=10000)


class _TaskFields(_Input):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10000)
    employee_ids: list[int] | None = Field(None, max_length=50)
    sort_order: int | None = None
    is_public: bool | None = None
    for_client: bool | None = None
    deadline: int | None = Field(None, ge=0, description="Hours after previous task or order creation.")
    due_at: str | None = Field(None, description="ISO 8601 due date and time; mutually exclusive with deadline.")

    @model_validator(mode="after")
    def deadline_choice(self):
        if self.deadline is not None and self.due_at is not None:
            raise ValueError("Choose deadline or due_at")
        if self.employee_ids is not None and any(i < 1 for i in self.employee_ids):
            raise ValueError("Employee IDs must be positive")
        if self.due_at is not None:
            from datetime import datetime
            parsed = datetime.fromisoformat(self.due_at.replace("Z", "+00:00"))
            if "T" not in self.due_at or parsed.tzinfo is None:
                raise ValueError("Use an ISO 8601 date-time with a timezone")
        return self


class WayfrontListClients(_Page):
    """List clients."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})


class WayfrontGetClient(_Input):
    """Get client."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)


class WayfrontCreateClient(_ClientFields):
    """Create client."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=320)


class WayfrontUpdateClient(_ClientFields):
    """Update client."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)


class WayfrontListCompanies(_Page):
    """List companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class WayfrontGetCompany(_Input):
    """Get company."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1)


class WayfrontCreateCompany(_Input):
    """Create company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    owner_user_id: int | None = Field(None, ge=1)


class WayfrontUpdateCompany(_Input):
    """Update company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    owner_user_id: int | None = Field(None, ge=1)
    company_id: int = Field(..., ge=1)


class WayfrontListOrders(_Page):
    """List orders."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})


class WayfrontGetOrder(_Input):
    """Get order."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")


class WayfrontCreateOrder(_OrderFields):
    """Create order."""
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1)


class WayfrontUpdateOrder(_OrderFields):
    """Update order."""
    operation: Literal["update_order"] = Field("update_order", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")


class WayfrontListOrderTasks(_Input):
    """List order tasks."""
    operation: Literal["list_order_tasks"] = Field("list_order_tasks", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")


class WayfrontCreateOrderTask(_TaskFields):
    """Create order task."""
    operation: Literal["create_order_task"] = Field("create_order_task", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")


class WayfrontUpdateTask(_TaskFields):
    """Update task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)


class WayfrontDeleteTask(_Input):
    """Delete task."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., ge=1)


class WayfrontListOrderMessages(_Input):
    """List order messages."""
    operation: Literal["list_order_messages"] = Field("list_order_messages", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")


class WayfrontCreateOrderMessage(_Input):
    """Create order message."""
    operation: Literal["create_order_message"] = Field("create_order_message", json_schema_extra={"ui:hidden": True})
    order_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront order number, such as E4A269FC.")
    message: str = Field(..., min_length=1, max_length=50000)
    user_id: int | None = Field(None, ge=1)
    staff_only: bool = Field(False, description="Whether this is an internal staff message.")


class WayfrontListServices(_Page):
    """List services."""
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True})


class WayfrontGetService(_Input):
    """Get service."""
    operation: Literal["get_service"] = Field("get_service", json_schema_extra={"ui:hidden": True})
    service_id: int = Field(..., ge=1)


class WayfrontListInvoices(_Page):
    """List invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class WayfrontGetInvoice(_Input):
    """Get invoice."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Wayfront invoice number.")


class WayfrontListSubscriptions(_Page):
    """List subscriptions."""
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", json_schema_extra={"ui:hidden": True})


class WayfrontGetSubscription(_Input):
    """Get subscription."""
    operation: Literal["get_subscription"] = Field("get_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1)


class WayfrontListTeam(_Page):
    """List team."""
    operation: Literal["list_team"] = Field("list_team", json_schema_extra={"ui:hidden": True})


WayfrontOperation = Annotated[Union[
    WayfrontListClients,
    WayfrontGetClient,
    WayfrontCreateClient,
    WayfrontUpdateClient,
    WayfrontListCompanies,
    WayfrontGetCompany,
    WayfrontCreateCompany,
    WayfrontUpdateCompany,
    WayfrontListOrders,
    WayfrontGetOrder,
    WayfrontCreateOrder,
    WayfrontUpdateOrder,
    WayfrontListOrderTasks,
    WayfrontCreateOrderTask,
    WayfrontUpdateTask,
    WayfrontDeleteTask,
    WayfrontListOrderMessages,
    WayfrontCreateOrderMessage,
    WayfrontListServices,
    WayfrontGetService,
    WayfrontListInvoices,
    WayfrontGetInvoice,
    WayfrontListSubscriptions,
    WayfrontGetSubscription,
    WayfrontListTeam,
], Field(discriminator="operation")]


class WayfrontConfig(NodeConfig[WayfrontOperation, WayfrontTokenCredential]):
    pass


ROUTES = {
    'list_clients': ('GET', '/clients', ()),
    'get_client': ('GET', '/clients/{client_id}', ()),
    'create_client': ('POST', '/clients', ('name_f', 'name_l', 'email', 'company', 'phone', 'note', 'status_id', 'optin')),
    'update_client': ('PUT', '/clients/{client_id}', ('name_f', 'name_l', 'email', 'company', 'phone', 'note', 'status_id', 'optin')),
    'list_companies': ('GET', '/companies', ()),
    'get_company': ('GET', '/companies/{company_id}', ()),
    'create_company': ('POST', '/companies', ('name', 'owner_user_id')),
    'update_company': ('PUT', '/companies/{company_id}', ('name', 'owner_user_id')),
    'list_orders': ('GET', '/orders', ()),
    'get_order': ('GET', '/orders/{order_id}', ()),
    'create_order': ('POST', '/orders', ('user_id', 'status', 'service_id', 'note')),
    'update_order': ('PUT', '/orders/{order_id}', ('status', 'service_id', 'note')),
    'list_order_tasks': ('GET', '/order_tasks/{order_id}', ()),
    'create_order_task': ('POST', '/order_tasks/{order_id}', ('name', 'description', 'employee_ids', 'sort_order', 'is_public', 'for_client', 'deadline', 'due_at')),
    'update_task': ('PUT', '/order_tasks/{task_id}', ('name', 'description', 'employee_ids', 'sort_order', 'is_public', 'for_client', 'deadline', 'due_at')),
    'delete_task': ('DELETE', '/order_tasks/{task_id}', ()),
    'list_order_messages': ('GET', '/order_messages/{order_id}', ()),
    'create_order_message': ('POST', '/order_messages/{order_id}', ('message', 'user_id', 'staff_only')),
    'list_services': ('GET', '/services', ()),
    'get_service': ('GET', '/services/{service_id}', ()),
    'list_invoices': ('GET', '/invoices', ()),
    'get_invoice': ('GET', '/invoices/{invoice_id}', ()),
    'list_subscriptions': ('GET', '/subscriptions', ()),
    'get_subscription': ('GET', '/subscriptions/{subscription_id}', ()),
    'list_team': ('GET', '/team', ()),
}


class WayfrontNode(WorkflowNode):
    integration_type = "automation-wayfront"
    connection_evidence = ConnectionEvidence(noun="clients", operation="list_clients", label_keys=("email", "name_f", "id"))

    @classmethod
    def get_config_model(cls):
        return WayfrontConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wayfront API token")
        credential = self.config.credentials
        op = self.config.config
        method, path, body_fields = ROUTES[op.operation]
        values = op.model_dump()
        for field in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {k: values[k] for k in ("page", "limit", "sort") if values.get(k) is not None} if isinstance(op, _Page) else {}
        body = {k: values[k] for k in body_fields if values[k] is not None} if body_fields else None
        if method == "PUT" and not body:
            raise ValueError("Provide at least one field to update")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, credential.workspace_url + "/api" + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Wayfront request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for the shared connection verdict.
            try:
                error = response.json().get("message")
            except (ValueError, AttributeError):
                error = None
            message = str(error or "Wayfront request failed")[:2000].replace(credential.api_token, "[redacted]")
            output = {"status": "error", "error": message, "http_status": response.status_code}
        else:
            if response.status_code == 204:
                payload = None
            else:
                try:
                    payload = response.json()
                except ValueError:
                    raise ValueError("Wayfront returned an unexpected response; inspect writes before retrying") from None
                if not isinstance(payload, (dict, list)):
                    raise ValueError("Wayfront returned an unexpected JSON shape")
            if op.operation.startswith("list_"):
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("Wayfront returned an invalid list envelope")
                output = {"status": "success", "data": payload["data"], "http_status": response.status_code}
                for key in ("meta", "links"):
                    if key in payload:
                        output[key] = payload[key]
                meta = payload.get("meta")
                if isinstance(meta, dict) and type(meta.get("current_page")) is int and type(meta.get("last_page")) is int:
                    output["next_page"] = meta["current_page"] + 1 if meta["current_page"] < meta["last_page"] else None
            else:
                output = {"status": "success", "data": payload, "http_status": response.status_code}
        await self.emit(output)
        return output

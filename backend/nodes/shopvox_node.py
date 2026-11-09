"""shopVOX REST API v1: fixed operations from the published OpenAPI 1.0.0 contract.

One call per operation; page explicitly using returned pagination. Tokens are
supplied by the person, never obtained by logging in on their behalf.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.shopvox.com/v1"


class ShopvoxTokenCredential(BaseModel):
    model_config = ConfigDict(title="Shopvox API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.shopvox.com/",
            "x-credential-instructions": "Paste your shopVOX account UUID and existing REST auth token (accountID and authToken from shopVOX). The token belongs to a user and account. If it expires, replace it here. API access depends on your plan; jobs listing must be enabled by shopVOX support. NoClick verifies the connection using the authenticated user and business name.",
        })
    credential_type: Literal["shopvox_api_token"] = Field("shopvox_api_token", json_schema_extra={"ui:hidden": True})
    account_id: UUID = Field(..., title="Account ID", description="The accountID UUID supplied by shopVOX.")
    auth_token: str = Field(..., min_length=1, title="Auth token", json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; use next_page from the preceding response.")
    per_page: int = Field(10, ge=1, le=100, description="Requested page size. Accounts without index_api_enabled are capped at 5; quotes use 10.")


class GetConnection(_Input):
    """Verify the authenticated shopVOX user and business (all plans)."""
    operation: Literal["get_connection"] = Field("get_connection", json_schema_extra={"ui:hidden": True})


class ListCompanies(_Page):
    """Read one page. Pro plan."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    active: bool = Field(True, description="Filter by active status; sends false as well as true.")
    name: Optional[str] = None


class GetCompany(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: UUID


class CreateCompany(_Input):
    """Create (Pro plan)."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    primary_email: Optional[str] = Field(None)
    primary_phone: Optional[str] = Field(None)
    website: Optional[str] = Field(None)
    legal_name: Optional[str] = Field(None)
    taxable: Optional[bool] = Field(None)
    special_notes: Optional[str] = Field(None)


class UpdateCompany(_Input):
    """Update using PUT (Paid API add-on)."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: UUID
    name: str = Field(..., min_length=1)
    primary_email: Optional[str] = Field(None)
    primary_phone: Optional[str] = Field(None)
    website: Optional[str] = Field(None)
    legal_name: Optional[str] = Field(None)
    taxable: Optional[bool] = Field(None)
    special_notes: Optional[str] = Field(None)


class ListContacts(_Page):
    """Read one page. Pro plan."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    active: bool = Field(True, description="Filter by active status; sends false as well as true.")
    name: Optional[str] = None
    company_id: Optional[UUID] = None
    search: Optional[str] = None


class GetContact(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID


class CreateContact(_Input):
    """Create (Pro plan)."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    company_id: UUID = Field(...)
    email: Optional[str] = Field(None)
    phone: Optional[str] = Field(None)
    title: Optional[str] = Field(None)
    department: Optional[str] = Field(None)


class UpdateContact(_Input):
    """Update using PUT (Paid API add-on)."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID
    name: str = Field(..., min_length=1)
    company_id: UUID = Field(...)
    email: Optional[str] = Field(None)
    phone: Optional[str] = Field(None)
    title: Optional[str] = Field(None)
    department: Optional[str] = Field(None)


class ListQuotes(_Page):
    """Read one page. Paid API add-on."""
    operation: Literal["list_quotes"] = Field("list_quotes", json_schema_extra={"ui:hidden": True})


class GetQuote(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})
    quote_id: UUID


class ListSalesOrders(_Page):
    """Read one page. Paid API add-on."""
    operation: Literal["list_sales_orders"] = Field("list_sales_orders", json_schema_extra={"ui:hidden": True})
    txn_date_from: Optional[date] = None
    txn_date_to: Optional[date] = None


class GetSalesOrder(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_sales_order"] = Field("get_sales_order", json_schema_extra={"ui:hidden": True})
    sales_order_id: UUID


class SalesOrderLine(_Input):
    name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    price_in_dollars: float
    description: Optional[str] = None
    taxable: Optional[bool] = None


class CreateSalesOrder(_Input):
    """Create (Pro plan)."""
    operation: Literal["create_sales_order"] = Field("create_sales_order", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    company_id: UUID = Field(...)
    description: Optional[str] = Field(None)
    txn_date: Optional[date] = Field(None)
    due_date: Optional[date] = Field(None)
    customer_po_number: Optional[str] = Field(None)
    primary_contact_id: Optional[UUID] = Field(None)
    line_items: list[SalesOrderLine] = Field(default_factory=list, description="Line items to create. Prices are in dollars.")


class UpdateSalesOrder(_Input):
    """Update using PUT (Paid API add-on). Header fields only; line items are not updated."""
    operation: Literal["update_sales_order"] = Field("update_sales_order", json_schema_extra={"ui:hidden": True})
    sales_order_id: UUID
    title: str = Field(..., min_length=1)
    company_id: UUID = Field(...)
    description: Optional[str] = Field(None)
    txn_date: Optional[date] = Field(None)
    due_date: Optional[date] = Field(None)
    customer_po_number: Optional[str] = Field(None)
    primary_contact_id: Optional[UUID] = Field(None)


class ListInvoices(_Page):
    """Read one page. Paid API add-on."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class GetInvoice(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: UUID


class ListJobs(_Page):
    """Read one page. Requires shopVOX support enablement."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    txn_type: Literal["invoice", "sales_order", "quote"] = Field(..., description="Required transaction filter; shopVOX support must enable this endpoint.")
    txn_number: int = Field(..., description="Transaction number, for example 1001.")


class GetJob(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: UUID


class CreateJob(_Input):
    """Create (Pro plan)."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    company_id: Optional[UUID] = Field(None)
    description: Optional[str] = Field(None)
    quantity: Optional[float] = Field(None)
    due_date: Optional[date] = Field(None)
    production_details: Optional[str] = Field(None)


class ListSalesLeads(_Page):
    """Read one page. Paid API add-on."""
    operation: Literal["list_sales_leads"] = Field("list_sales_leads", json_schema_extra={"ui:hidden": True})
    active: bool = Field(True, description="Filter by active status; sends false as well as true.")


class GetSalesLead(_Input):
    """Get one resource by UUID (Paid API add-on)."""
    operation: Literal["get_sales_lead"] = Field("get_sales_lead", json_schema_extra={"ui:hidden": True})
    sales_lead_id: UUID


class CreateSalesLead(_Input):
    """Create (Pro plan)."""
    operation: Literal["create_sales_lead"] = Field("create_sales_lead", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    company_id: Optional[UUID] = Field(None)
    details: Optional[str] = Field(None)
    qualified: Optional[bool] = Field(None)
    deal_value_in_dollars: Optional[float] = Field(None)
    next_contact_date: Optional[date] = Field(None)
    expected_close_date: Optional[date] = Field(None)
    pipeline_id: Optional[UUID] = Field(None)
    pipeline_stage_id: Optional[UUID] = Field(None)


class UpdateSalesLead(_Input):
    """Update using PUT (Paid API add-on)."""
    operation: Literal["update_sales_lead"] = Field("update_sales_lead", json_schema_extra={"ui:hidden": True})
    sales_lead_id: UUID
    title: str = Field(..., min_length=1)
    company_id: Optional[UUID] = Field(None)
    details: Optional[str] = Field(None)
    qualified: Optional[bool] = Field(None)
    deal_value_in_dollars: Optional[float] = Field(None)
    next_contact_date: Optional[date] = Field(None)
    expected_close_date: Optional[date] = Field(None)
    pipeline_id: Optional[UUID] = Field(None)
    pipeline_stage_id: Optional[UUID] = Field(None)


class ListPayments(_Page):
    """Read payment records (Paid API add-on); money is preserved in provider units."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})


ShopvoxConfig = Annotated[Union[
    GetConnection,
    ListCompanies,
    GetCompany,
    CreateCompany,
    UpdateCompany,
    ListContacts,
    GetContact,
    CreateContact,
    UpdateContact,
    ListQuotes,
    GetQuote,
    ListSalesOrders,
    GetSalesOrder,
    CreateSalesOrder,
    UpdateSalesOrder,
    ListInvoices,
    GetInvoice,
    ListJobs,
    GetJob,
    CreateJob,
    ListSalesLeads,
    GetSalesLead,
    CreateSalesLead,
    UpdateSalesLead,
    ListPayments
], Field(discriminator="operation")]


class ShopvoxFullConfig(NodeConfig[ShopvoxConfig, ShopvoxTokenCredential]):
    pass


OPERATIONS = {'get_connection': ('GET', '/connections', None, None),
 'list_companies': ('GET', '/companies', 'companies', None),
 'get_company': ('GET', '/companies/{id}', None, None),
 'create_company': ('POST', '/companies', None, 'company'),
 'update_company': ('PUT', '/companies/{id}', None, 'company'),
 'list_contacts': ('GET', '/contacts', 'contacts', None),
 'get_contact': ('GET', '/contacts/{id}', None, None),
 'create_contact': ('POST', '/contacts', None, 'contact'),
 'update_contact': ('PUT', '/contacts/{id}', None, 'contact'),
 'list_quotes': ('GET', '/quotes', 'quotes', None),
 'get_quote': ('GET', '/quotes/{id}', None, None),
 'list_sales_orders': ('GET', '/sales_orders', 'salesOrders', None),
 'get_sales_order': ('GET', '/sales_orders/{id}', None, None),
 'create_sales_order': ('POST', '/sales_orders', None, 'sales_order'),
 'update_sales_order': ('PUT', '/sales_orders/{id}', None, 'sales_order'),
 'list_invoices': ('GET', '/invoices', 'invoices', None),
 'get_invoice': ('GET', '/invoices/{id}', None, None),
 'list_jobs': ('GET', '/jobs', 'jobs', None),
 'get_job': ('GET', '/jobs/{id}', None, None),
 'create_job': ('POST', '/jobs', None, 'job'),
 'list_sales_leads': ('GET', '/sales_leads', 'salesLeads', None),
 'get_sales_lead': ('GET', '/sales_leads/{id}', None, None),
 'create_sales_lead': ('POST', '/sales_leads', None, None),
 'update_sales_lead': ('PUT', '/sales_leads/{id}', None, None),
 'list_payments': ('GET', '/payments', 'payments', None)}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"authtoken", "auth_token", "password"}}
    return value


class ShopvoxNode(WorkflowNode):
    integration_type = "automation-shopvox"
    connection_evidence = ConnectionEvidence(noun="shopVOX account", identity_operation="get_connection", identity_keys=("account", "name"))

    @classmethod
    def get_config_model(cls):
        return ShopvoxFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a shopVOX API token")
        credential = self.config.credentials
        op = self.config.config
        method, path, list_key, wrapper = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            singular = op.operation.split("_", 1)[1]
            path = path.replace("{id}", values.pop(singular + "_id"))
        params = {"account_id": str(credential.account_id), "authToken": credential.auth_token}
        body = None
        if method == "GET":
            params.update({k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()})
        else:
            body = {wrapper: values} if wrapper else values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Accept": "application/json", "Content-Type": "application/json"})
            if response.status_code != 200:
                message = "shopVOX request failed"
                try:
                    error = response.json()
                    if isinstance(error, str): message = error
                    elif isinstance(error, dict): message = str(error.get("message") or error.get("error") or error.get("errors") or message)
                except (ValueError, TypeError):
                    pass
                result = {"status": "error", "success": False, "http_status": response.status_code, "message": message}
                if method != "GET" and response.status_code >= 500:
                    result["write_outcome"] = "unknown; inspect shopVOX before retrying"
            else:
                data = response.json()
                if not isinstance(data, dict) or "error" in data or "errors" in data:
                    raise ValueError("Unexpected shopVOX JSON response")
                result = {"status": "success", "success": True, "data": data, "http_status": 200}
                if list_key:
                    rows = data.get(list_key)
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError("Unexpected shopVOX list response")
                    stats = data.get("stats")
                    if not isinstance(stats, dict):
                        raise ValueError("Missing shopVOX pagination stats")
                    result.update(items=rows, pagination=stats, next_page=stats.get("nextPage"))
                elif op.operation == "get_connection":
                    if data.get("status") != "ok" or not any(isinstance(data.get(k), str) and data[k] for k in ("account", "name")):
                        raise ValueError("shopVOX did not confirm an account identity")
                    result.update({k: data[k] for k in ("account", "name") if k in data})
                elif not isinstance(data.get("id"), str) or not data["id"]:
                    raise ValueError("Missing shopVOX resource ID")
                if method != "GET":
                    result["write_acknowledged"] = True
        except (httpx.HTTPError, ValueError):
            result = {"status": "unknown", "success": False, "message": "shopVOX response could not be verified"}
            if method != "GET":
                result["write_outcome"] = "unknown; inspect shopVOX before retrying"
        result = _redact(result, credential.auth_token)
        await self.emit(result)
        return result

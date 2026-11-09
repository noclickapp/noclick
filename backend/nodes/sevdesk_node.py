"""Sevdesk REST v1 operations pinned to the publisher's OpenAPI 2.0.0 contract.

Each operation makes one request. Lists return one bounded page; writes return
provider acknowledgements, without claiming delivery or independent readback.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://my.sevdesk.de/api/v1"
CREDENTIAL_TYPE = "sevdesk_api_token"
Identifier = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class SevdeskAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Sevdesk API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://hilfe.sevdesk.de/de/articles/9374740-wo-finde-ich-meinen-api-token-in-sevdesk",
            "x-credential-instructions": "In Sevdesk, open Extensions > Integrations (Erweiterungen > Integrationen), reveal the API token for integrations and copy it. Paste the token itself, without an Authorization or Bearer prefix. NoClick sends it only to my.sevdesk.de. Listing your contacts checks the connection; this does not verify write permissions.",
        })
    credential_type: Literal["sevdesk_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token",
        description="Your Sevdesk administrator's API token.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token")
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum records in this page.")
    offset: int = Field(0, ge=0, le=10_000_000, description="Number of records to skip. Use next_offset for the next page.")


class ListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"
    depth: Literal["0", "1"] = Field("1", description="0: organizations only; 1: organizations and people.")
    customer_number: Text | None = None


class GetContact(_Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: Identifier


class _ContactFields(_Input):
    name: Text | None = Field(None, description="Organization name; omit for a person.")
    first_name: Text | None = None
    last_name: Text | None = None
    customer_number: Text | None = None
    status: Literal[100, 500, 1000] | None = None
    description: Text | None = None
    vat_number: Text | None = None
    payment_days: int | None = Field(None, ge=0)


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"
    category_id: Identifier = Field(..., description="Contact category ID. The provider documents category 3 for customers.")

    @model_validator(mode="after")
    def named(self):
        if not self.name and not (self.first_name or self.last_name):
            raise ValueError("Provide an organization name or a person's name")
        return self


class UpdateContact(_ContactFields):
    operation: Literal["update_contact"] = "update_contact"
    contact_id: Identifier
    category_id: Identifier | None = None

    @model_validator(mode="after")
    def changed(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "contact_id"}):
            raise ValueError("Provide at least one contact field to update")
        return self


class DeleteContact(_Input):
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: Identifier


class ListParts(_Page):
    operation: Literal["list_parts"] = "list_parts"
    name: Text | None = None
    part_number: Text | None = None


class GetPart(_Input):
    operation: Literal["get_part"] = "get_part"
    part_id: Identifier


class _PartFields(_Input):
    name: Text | None = None
    part_number: Text | None = None
    text: Text | None = None
    tax_rate: Literal[0, 7, 19] | None = None
    unity_id: Identifier | None = None
    stock: float | None = Field(None, allow_inf_nan=False)
    stock_enabled: bool | None = None
    price_net: float | None = Field(None, ge=0, allow_inf_nan=False)
    price_gross: float | None = Field(None, ge=0, allow_inf_nan=False)
    status: Literal[50, 100] | None = None


class CreatePart(_PartFields):
    operation: Literal["create_part"] = "create_part"
    name: Text
    part_number: Text
    tax_rate: Literal[0, 7, 19]
    unity_id: Identifier
    stock: float = Field(..., allow_inf_nan=False)


class UpdatePart(_PartFields):
    operation: Literal["update_part"] = "update_part"
    part_id: Identifier

    @model_validator(mode="after")
    def changed(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "part_id"}):
            raise ValueError("Provide at least one part field to update")
        return self


class _DocumentPage(_Page):
    contact_id: Identifier | None = None
    start_date: int | None = Field(None, ge=0, description="Inclusive Unix timestamp.")
    end_date: int | None = Field(None, ge=0, description="Inclusive Unix timestamp.")

    @model_validator(mode="after")
    def dates(self):
        if self.start_date is not None and self.end_date is not None and self.start_date > self.end_date:
            raise ValueError("End date must be on or after start date")
        return self


class ListInvoices(_DocumentPage):
    operation: Literal["list_invoices"] = "list_invoices"
    status: Literal[100, 200, 1000] | None = None
    invoice_number: Text | None = None


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = "get_invoice"
    invoice_id: Identifier


class ListInvoicePositions(_Page):
    operation: Literal["list_invoice_positions"] = "list_invoice_positions"
    invoice_id: Identifier


class ListOrders(_DocumentPage):
    operation: Literal["list_orders"] = "list_orders"
    status: Literal[100, 200, 300, 500, 750, 1000] | None = None
    order_number: Text | None = None


class GetOrder(_Input):
    operation: Literal["get_order"] = "get_order"
    order_id: Identifier


class ListVouchers(_DocumentPage):
    operation: Literal["list_vouchers"] = "list_vouchers"
    status: Literal[50, 100, 1000] | None = None
    credit_debit: Literal["C", "D"] | None = None
    description_like: Text | None = None


class GetVoucher(_Input):
    operation: Literal["get_voucher"] = "get_voucher"
    voucher_id: Identifier


class ListCheckAccounts(_Page):
    operation: Literal["list_check_accounts"] = "list_check_accounts"


class GetCheckAccount(_Input):
    operation: Literal["get_check_account"] = "get_check_account"
    check_account_id: Identifier


class ListTags(_Page):
    operation: Literal["list_tags"] = "list_tags"
    name: Text | None = None


class GetTag(_Input):
    operation: Literal["get_tag"] = "get_tag"
    tag_id: Identifier


class CreateTag(_Input):
    """Create a tag and attach it to one invoice, voucher, order or credit note."""
    operation: Literal["create_tag"] = "create_tag"
    name: Text
    object_id: Identifier
    object_name: Literal["Invoice", "Voucher", "Order", "CreditNote"]


class UpdateTag(_Input):
    operation: Literal["update_tag"] = "update_tag"
    tag_id: Identifier
    name: Text


SevdeskConfig = Annotated[Union[
    ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact,
    ListParts, GetPart, CreatePart, UpdatePart, ListInvoices, GetInvoice,
    ListInvoicePositions, ListOrders, GetOrder, ListVouchers, GetVoucher,
    ListCheckAccounts, GetCheckAccount, ListTags, GetTag, CreateTag, UpdateTag,
], Field(discriminator="operation")]


class SevdeskNodeConfig(NodeConfig[SevdeskConfig, SevdeskAPITokenCredential]):
    pass


# Each entry is exactly one operation in https://api.sevdesk.de/openapi.yaml.
ROUTES = {
    "list_contacts": ("GET", "/Contact"),
    "get_contact": ("GET", "/Contact/{contact_id}"),
    "create_contact": ("POST", "/Contact"),
    "update_contact": ("PUT", "/Contact/{contact_id}"),
    "delete_contact": ("DELETE", "/Contact/{contact_id}"),
    "list_parts": ("GET", "/Part"),
    "get_part": ("GET", "/Part/{part_id}"),
    "create_part": ("POST", "/Part"),
    "update_part": ("PUT", "/Part/{part_id}"),
    "list_invoices": ("GET", "/Invoice"),
    "get_invoice": ("GET", "/Invoice/{invoice_id}"),
    "list_invoice_positions": ("GET", "/Invoice/{invoice_id}/getPositions"),
    "list_orders": ("GET", "/Order"),
    "get_order": ("GET", "/Order/{order_id}"),
    "list_vouchers": ("GET", "/Voucher"),
    "get_voucher": ("GET", "/Voucher/{voucher_id}"),
    "list_check_accounts": ("GET", "/CheckAccount"),
    "get_check_account": ("GET", "/CheckAccount/{check_account_id}"),
    "list_tags": ("GET", "/Tag"),
    "get_tag": ("GET", "/Tag/{tag_id}"),
    "create_tag": ("POST", "/Tag/Factory/create"),
    "update_tag": ("PUT", "/Tag/{tag_id}"),
}
CONTACT_FIELDS = {"name": "name", "first_name": "surename", "last_name": "familyname",
    "customer_number": "customerNumber", "status": "status", "description": "description",
    "vat_number": "vatNumber", "payment_days": "defaultTimeToPay"}
PART_FIELDS = {"name": "name", "part_number": "partNumber", "text": "text",
    "tax_rate": "taxRate", "stock": "stock", "stock_enabled": "stockEnabled",
    "price_net": "priceNet", "price_gross": "priceGross", "status": "status"}
QUERY_FIELDS = {"depth": "depth", "customer_number": "customerNumber", "name": "name",
    "part_number": "partNumber", "status": "status", "invoice_number": "invoiceNumber",
    "order_number": "orderNumber", "start_date": "startDate", "end_date": "endDate",
    "credit_debit": "creditDebit", "description_like": "descriptionLike"}


def _body(config):
    values = config.model_dump(exclude_none=True)
    if config.operation.endswith("_contact"):
        body = {target: values[source] for source, target in CONTACT_FIELDS.items() if source in values}
        if values.get("category_id") is not None:
            body["category"] = {"id": values["category_id"], "objectName": "Category"}
        return body
    if config.operation.endswith("_part"):
        body = {target: values[source] for source, target in PART_FIELDS.items() if source in values}
        if values.get("unity_id") is not None:
            body["unity"] = {"id": values["unity_id"], "objectName": "Unity"}
        return body
    body = {"name": config.name}
    if isinstance(config, CreateTag):
        body["object"] = {"id": config.object_id, "objectName": config.object_name}
    return body


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class SevdeskNode(WorkflowNode):
    integration_type = "automation-sevdesk"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts",
        label_keys=("name", "familyname", "surename", "customerNumber", "id"))

    @classmethod
    def get_config_model(cls):
        return SevdeskNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(raw, dict) and raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Attach a Sevdesk API token credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Sevdesk API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[config.operation]
        path = template.format(**config.model_dump())
        params, body = {}, None
        if method == "GET" and isinstance(config, _Page):
            params = {"limit": config.limit, "offset": config.offset}
            values = config.model_dump(exclude_none=True)
            params.update({target: values[source] for source, target in QUERY_FIELDS.items() if source in values})
            if isinstance(config, _DocumentPage) and config.contact_id is not None:
                params.update({"contact[id]": config.contact_id, "contact[objectName]": "Contact"})
        elif method in {"POST", "PUT"}:
            body = _body(config)
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": token, "Accept": "application/json", "User-Agent": "NoClick Sevdesk integration"})
            if response.status_code not in {200, 201}:
                # Preserve the provider's rejection text for connection evidence.
                result = {"status": "unknown" if writing and response.status_code >= 500 else "error",
                    "success": False, "http_status": response.status_code, "status_code": response.status_code,
                    "message": response.text[:2000] or "Sevdesk returned an unsuccessful status",
                    "write_outcome": "unverified" if writing else None}
            else:
                payload = response.json()
                if not isinstance(payload, dict) or any(payload.get(k) for k in ("error", "errors", "exception")):
                    raise ValueError("Invalid Sevdesk response envelope")
                if config.operation.startswith("list_"):
                    rows = payload.get("objects")
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError("Invalid Sevdesk list response")
                    if len(rows) > config.limit:
                        raise ValueError("Sevdesk returned more than the requested page limit")
                    has_more = len(rows) == config.limit
                    result = {"status": "success", "success": True, "objects": rows,
                        "has_more": has_more, "next_offset": config.offset + len(rows) if has_more else None,
                        "pagination": {"limit": config.limit, "offset": config.offset}, "http_status": response.status_code}
                else:
                    result = {"status": "success", "success": True, "data": payload, "http_status": response.status_code}
                    if writing:
                        result.update({"write_acknowledged": True, "readback_verified": False})
        except (httpx.HTTPError, ValueError):
            result = {"status": "unknown" if writing else "error", "success": False,
                "message": "Sevdesk write outcome could not be verified; inspect the account before retrying" if writing else "Sevdesk response could not be verified",
                "write_outcome": "unverified" if writing else None}
        result = _redact(result, token)
        await self.emit(result)
        return result

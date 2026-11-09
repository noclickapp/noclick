"""Fatture in Cloud API v2 against the provider's 2.1.8 contract.

Operations make one request, return one page with provider pagination metadata,
and never retry writes automatically.
"""
from __future__ import annotations
from datetime import date
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api-v2.fattureincloud.it"
AUTH_DOCS = "https://developers.fattureincloud.it/docs/authentication/manual-authentication/"


class FattureInCloudTokenCredential(BaseModel):
    model_config = ConfigDict(title="Fatture in Cloud Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Paste a manually generated access token from Settings > Connected Applications. Token generation requires a Fatture in Cloud application Client ID. Select the companies and permissions you need: entity.clients:r/a, entity.suppliers:r/a, products:r/a, issued_documents.<document type>:r/a and received_documents:r. Tokens do not expire but can be revoked. Listing companies proves access; each operation still needs its own permissions."})
    credential_type: Literal["fatture_in_cloud_token"] = Field("fatture_in_cloud_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Company(_Input):
    company_id: int = Field(..., gt=0, title="Company ID", json_schema_extra={"x-dynamic-options": {
        "field_name": "company_id", "allow_custom": True, "searchable": True}})


class _Page(_Company):
    page: int = Field(1, ge=1, description="Page number; returns one page only.")
    per_page: int = Field(25, ge=1, le=100)
    q: str | None = Field(None, max_length=2000, description="Provider query expression, for example name = 'Rossi S.r.l.'.")
    sort: str | None = Field(None, max_length=500, description="Provider sort fields, prefixed with - for descending.")


class ContactData(_Input):
    name: str = Field(..., min_length=1, max_length=500)
    code: str | None = None
    type: Literal["company", "person", "pa", "condo"] | None = None
    first_name: str | None = None
    last_name: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    address_street: str | None = None
    address_postal_code: str | None = None
    address_city: str | None = None
    address_province: str | None = None
    country: str | None = None
    email: str | None = None
    certified_email: str | None = None
    phone: str | None = None
    notes: str | None = None
    bank_iban: str | None = None
    ei_code: str | None = None


class VatData(_Input):
    id: int | None = Field(None, gt=0)
    value: float = Field(..., ge=0, le=100)


class ProductData(_Input):
    name: str = Field(..., min_length=1, max_length=500)
    code: str | None = None
    net_price: float | None = None
    gross_price: float | None = None
    use_gross_price: bool | None = None
    default_vat: VatData | None = None
    net_cost: float | None = None
    measure: str | None = None
    description: str | None = None
    category: str | None = None
    notes: str | None = None
    in_stock: bool | None = None
    stock_initial: float | None = None


DocumentType = Literal["invoice", "quote", "proforma", "receipt", "delivery_note", "credit_note", "order", "work_report", "supplier_order", "self_own_invoice", "self_supplier_invoice"]


class InvoiceEntity(ContactData):
    id: int | None = Field(None, gt=0)


class InvoiceItem(_Input):
    product_id: int | None = Field(None, gt=0)
    name: str = Field(..., min_length=1)
    description: str | None = None
    qty: float = Field(..., gt=0)
    net_price: float
    vat: VatData
    measure: str | None = None
    discount: float | None = Field(None, ge=0, le=100)


class PaymentAccount(_Input):
    id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)


class InvoicePayment(_Input):
    due_date: date
    amount: float
    status: Literal["not_paid", "paid", "reversed"] = "not_paid"
    paid_date: date | None = None
    payment_account: PaymentAccount | None = None


class IssuedDocumentData(_Input):
    type: DocumentType
    entity: InvoiceEntity
    date: date
    number: int | None = None
    numeration: str | None = None
    subject: str | None = None
    visible_subject: str | None = None
    notes: str | None = None
    items_list: list[InvoiceItem] = Field(..., min_length=1, max_length=500)
    payments_list: list[InvoicePayment] | None = Field(None, max_length=100)
    use_gross_prices: bool | None = None
    e_invoice: bool | None = Field(None, description="Creates electronic-invoice data only; does not send it to SDI.")


class GetUserInfo(_Input):
    operation: Literal["get_user_info"] = Field("get_user_info", json_schema_extra={"ui:hidden": True})


class ListCompanies(_Input):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class GetCompanyInfo(_Company):
    operation: Literal["get_company_info"] = Field("get_company_info", json_schema_extra={"ui:hidden": True})


class ListClients(_Page):
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})


class GetClient(_Company):
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., gt=0)


class CreateClient(_Company):
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    data: ContactData = Field(..., description="Documented data object; modification sends the supplied fields.")


class ModifyClient(_Company):
    operation: Literal["modify_client"] = Field("modify_client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., gt=0)
    data: ContactData = Field(..., description="Documented data object; modification sends the supplied fields.")


class DeleteClient(_Company):
    operation: Literal["delete_client"] = Field("delete_client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., gt=0)


class ListSuppliers(_Page):
    operation: Literal["list_suppliers"] = Field("list_suppliers", json_schema_extra={"ui:hidden": True})


class GetSupplier(_Company):
    operation: Literal["get_supplier"] = Field("get_supplier", json_schema_extra={"ui:hidden": True})
    supplier_id: int = Field(..., gt=0)


class CreateSupplier(_Company):
    operation: Literal["create_supplier"] = Field("create_supplier", json_schema_extra={"ui:hidden": True})
    data: ContactData = Field(..., description="Documented data object; modification sends the supplied fields.")


class ModifySupplier(_Company):
    operation: Literal["modify_supplier"] = Field("modify_supplier", json_schema_extra={"ui:hidden": True})
    supplier_id: int = Field(..., gt=0)
    data: ContactData = Field(..., description="Documented data object; modification sends the supplied fields.")


class DeleteSupplier(_Company):
    operation: Literal["delete_supplier"] = Field("delete_supplier", json_schema_extra={"ui:hidden": True})
    supplier_id: int = Field(..., gt=0)


class ListProducts(_Page):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})


class GetProduct(_Company):
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., gt=0)


class CreateProduct(_Company):
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    data: ProductData = Field(..., description="Documented data object; modification sends the supplied fields.")


class ModifyProduct(_Company):
    operation: Literal["modify_product"] = Field("modify_product", json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., gt=0)
    data: ProductData = Field(..., description="Documented data object; modification sends the supplied fields.")


class DeleteProduct(_Company):
    operation: Literal["delete_product"] = Field("delete_product", json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., gt=0)


class ListIssuedDocuments(_Page):
    operation: Literal["list_issued_documents"] = Field("list_issued_documents", json_schema_extra={"ui:hidden": True})
    type: DocumentType = Field(..., title="Document type")


class GetIssuedDocument(_Company):
    operation: Literal["get_issued_document"] = Field("get_issued_document", json_schema_extra={"ui:hidden": True})
    document_id: int = Field(..., gt=0)


class CreateIssuedDocument(_Company):
    operation: Literal["create_issued_document"] = Field("create_issued_document", json_schema_extra={"ui:hidden": True})
    data: IssuedDocumentData


class ModifyIssuedDocument(_Company):
    operation: Literal["modify_issued_document"] = Field("modify_issued_document", json_schema_extra={"ui:hidden": True})
    document_id: int = Field(..., gt=0)
    data: IssuedDocumentData


class ListReceivedDocuments(_Page):
    type: Literal["expense", "passive_credit_note", "passive_delivery_note", "self_invoice"] = Field(..., title="Document type")
    operation: Literal["list_received_documents"] = Field("list_received_documents", json_schema_extra={"ui:hidden": True})


class GetReceivedDocument(_Company):
    operation: Literal["get_received_document"] = Field("get_received_document", json_schema_extra={"ui:hidden": True})
    document_id: int = Field(..., gt=0)


FattureInCloudConfig = Annotated[Union[
    GetUserInfo,
    ListCompanies,
    GetCompanyInfo,
    ListClients,
    GetClient,
    CreateClient,
    ModifyClient,
    DeleteClient,
    ListSuppliers,
    GetSupplier,
    CreateSupplier,
    ModifySupplier,
    DeleteSupplier,
    ListProducts,
    GetProduct,
    CreateProduct,
    ModifyProduct,
    DeleteProduct,
    ListIssuedDocuments,
    GetIssuedDocument,
    CreateIssuedDocument,
    ModifyIssuedDocument,
    ListReceivedDocuments,
    GetReceivedDocument
], Field(discriminator="operation")]


class FattureInCloudFullConfig(NodeConfig[FattureInCloudConfig, FattureInCloudTokenCredential]):
    pass


# Each entry is exactly one provider operation.
ROUTES = {
    "get_user_info": ("GET", "/user/info"),
    "list_companies": ("GET", "/user/companies"),
    "get_company_info": ("GET", "/c/{company_id}/company/info"),
    "list_clients": ("GET", "/c/{company_id}/entities/clients"),
    "get_client": ("GET", "/c/{company_id}/entities/clients/{client_id}"),
    "create_client": ("POST", "/c/{company_id}/entities/clients"),
    "modify_client": ("PUT", "/c/{company_id}/entities/clients/{client_id}"),
    "delete_client": ("DELETE", "/c/{company_id}/entities/clients/{client_id}"),
    "list_suppliers": ("GET", "/c/{company_id}/entities/suppliers"),
    "get_supplier": ("GET", "/c/{company_id}/entities/suppliers/{supplier_id}"),
    "create_supplier": ("POST", "/c/{company_id}/entities/suppliers"),
    "modify_supplier": ("PUT", "/c/{company_id}/entities/suppliers/{supplier_id}"),
    "delete_supplier": ("DELETE", "/c/{company_id}/entities/suppliers/{supplier_id}"),
    "list_products": ("GET", "/c/{company_id}/products"),
    "get_product": ("GET", "/c/{company_id}/products/{product_id}"),
    "create_product": ("POST", "/c/{company_id}/products"),
    "modify_product": ("PUT", "/c/{company_id}/products/{product_id}"),
    "delete_product": ("DELETE", "/c/{company_id}/products/{product_id}"),
    "list_issued_documents": ("GET", "/c/{company_id}/issued_documents"),
    "get_issued_document": ("GET", "/c/{company_id}/issued_documents/{document_id}"),
    "create_issued_document": ("POST", "/c/{company_id}/issued_documents"),
    "modify_issued_document": ("PUT", "/c/{company_id}/issued_documents/{document_id}"),
    "list_received_documents": ("GET", "/c/{company_id}/received_documents"),
    "get_received_document": ("GET", "/c/{company_id}/received_documents/{document_id}"),
}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
            if k.lower() not in {"access_token", "refresh_token", "token", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class FattureInCloudNode(WorkflowNode):
    integration_type = "automation-fatture-in-cloud"
    connection_evidence = ConnectionEvidence(noun="companies", field="company_id",
        operation="list_companies", identity_operation="get_user_info")

    @classmethod
    def get_config_model(cls):
        return FattureInCloudFullConfig

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None):
        token = credential.access_token
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Fatture in Cloud HTTP {response.status_code}: {message}")
        if method == "DELETE" and not response.content:
            return {"deletion_acknowledged": True, "http_status": response.status_code}
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Fatture in Cloud returned an unexpected response envelope")
        return _redact(payload, token)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Fatture in Cloud access token")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = template.format(**values)
        params = {key: values[key] for key in ("page", "per_page", "q", "sort") if key in values}
        if config.operation in {"list_issued_documents", "list_received_documents"}:
            params["type"] = values["type"]
        body = {"data": values["data"]} if "data" in values else None
        result = await self._request(self.config.credentials, method, path, params=params or None, body=body)
        await self.emit(result)
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "company_id":
            return []
        credential = FattureInCloudTokenCredential.model_validate(credential_data)
        payload = await cls._request(credential, "GET", "/user/companies")
        companies = payload.get("data", {}).get("companies")
        if not isinstance(companies, list):
            raise ValueError("Fatture in Cloud company list is missing")
        options = []
        for row in companies:
            rows = row.get("controlled_companies", []) if row.get("type") == "accountant" else [row]
            for company in rows or []:
                if not isinstance(company.get("id"), int) or not isinstance(company.get("name"), str):
                    raise ValueError("Fatture in Cloud returned an invalid company")
                if search is None or search.casefold() in company["name"].casefold():
                    options.append({"value": str(company["id"]), "label": company["name"]})
        return options

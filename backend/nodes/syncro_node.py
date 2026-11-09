"""Syncro customer, service-desk and RMM workflows using a pasted API token.

Each operation issues one documented v1 request. Lists return one page so the
caller controls pagination and the provider's per-IP rate budget.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

DOCS = "https://docs.syncrosecure.com/imported/api-tokens"
ID = Annotated[int, Field(gt=0)]
TEXT = Annotated[str, Field(min_length=1, max_length=10000)]


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "allow_custom": True,
        "searchable": False, "placeholder": "Choose a Syncro record"}}


class SyncroAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Syncro API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "In Syncro, open Admin > API - API Tokens and create a Custom Permissions token. Paste it with your account subdomain. Grant only the customer, ticket, invoice and asset permissions your operations need. NoClick verifies the token with the current-user read; this does not prove every write permission."})
    credential_type: Literal["syncro_api_token"] = Field("syncro_api_token", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Account subdomain", description="The part before .syncromsp.com in your Syncro account URL.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def valid_subdomain(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your Syncro subdomain")
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only the account subdomain, without a URL or domain suffix")
        return value

    @field_validator("api_token", mode="before")
    @classmethod
    def valid_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="One page per execution. Pass next_page to continue with the same filters.")


class _Customer(_Input):
    customer_id: ID = Field(..., title="Customer", json_schema_extra=_picker("customer_id"))


class _Contact(_Input):
    contact_id: ID = Field(..., title="Contact", json_schema_extra=_picker("contact_id"))


class _Ticket(_Input):
    ticket_id: ID = Field(..., title="Ticket", json_schema_extra=_picker("ticket_id"))


class _Asset(_Input):
    asset_id: ID = Field(..., title="Asset", json_schema_extra=_picker("asset_id"))


class _CustomerFields(_Input):
    business_name: TEXT | None = None
    firstname: TEXT | None = None
    lastname: TEXT | None = None
    email: TEXT | None = None
    phone: TEXT | None = None
    mobile: TEXT | None = None
    address: TEXT | None = None
    address_2: TEXT | None = None
    city: TEXT | None = None
    state: TEXT | None = None
    zip: TEXT | None = None
    notes: TEXT | None = None
    no_email: bool | None = Field(None, description="Disable customer email when true.")


class _ContactFields(_Input):
    email: TEXT | None = None
    phone: TEXT | None = None
    mobile: TEXT | None = None
    notes: TEXT | None = None


class _TicketFields(_Input):
    status: TEXT | None = None
    problem_type: TEXT | None = None
    priority: TEXT | None = None
    user_id: ID | None = None
    contact_id: ID | None = None
    due_date: date | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None


class _AssetFields(_Input):
    asset_serial: TEXT | None = None
    customer_id: ID | None = None
    properties: dict | None = Field(None, description="Syncro asset custom fields by their documented names.")


class SyncroGetCurrentUser(_Input):
    """Identify the API token's user and account."""
    operation: Literal["get_current_user"] = "get_current_user"


class SyncroListCustomers(_Page):
    operation: Literal["list_customers"] = "list_customers"
    query: TEXT | None = None
    email: TEXT | None = None
    business_name: TEXT | None = None


class SyncroGetCustomer(_Customer):
    operation: Literal["get_customer"] = "get_customer"


class SyncroCreateCustomer(_CustomerFields):
    operation: Literal["create_customer"] = "create_customer"
    firstname: TEXT = Field(..., title="First name")


class SyncroUpdateCustomer(_Customer, _CustomerFields):
    operation: Literal["update_customer"] = "update_customer"

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in _CustomerFields.model_fields):
            raise ValueError("Supply at least one customer field to update")
        return self


class SyncroListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"
    customer_id: ID | None = None


class SyncroGetContact(_Contact):
    operation: Literal["get_contact"] = "get_contact"


class SyncroCreateContact(_Customer, _ContactFields):
    operation: Literal["create_contact"] = "create_contact"
    name: TEXT


class SyncroUpdateContact(_Contact, _ContactFields):
    operation: Literal["update_contact"] = "update_contact"
    name: TEXT = Field(..., description="Syncro requires the contact name on updates.")


class SyncroListTickets(_Page):
    operation: Literal["list_tickets"] = "list_tickets"
    customer_id: ID | None = None
    status: TEXT | None = None
    query: TEXT | None = None
    since_updated_at: AwareDatetime | None = None
    created_after: AwareDatetime | None = None
    user_id: ID | None = None


class SyncroGetTicket(_Ticket):
    operation: Literal["get_ticket"] = "get_ticket"


class SyncroCreateTicket(_Customer, _TicketFields):
    operation: Literal["create_ticket"] = "create_ticket"
    subject: TEXT


class SyncroUpdateTicket(_Ticket, _TicketFields):
    operation: Literal["update_ticket"] = "update_ticket"
    subject: TEXT | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in (*_TicketFields.model_fields, "subject")):
            raise ValueError("Supply at least one ticket field to update")
        return self


class SyncroAddTicketComment(_Ticket):
    operation: Literal["add_ticket_comment"] = "add_ticket_comment"
    body: TEXT = Field(..., title="Comment body")
    subject: TEXT | None = None
    hidden: bool = Field(True, description="Internal comment when true.")
    do_not_email: bool = Field(True, title="Do not email", description="False allows Syncro to email the comment to the customer.")


class SyncroListInvoices(_Page):
    operation: Literal["list_invoices"] = "list_invoices"
    paid: bool | None = None
    unpaid: bool | None = None
    ticket_id: ID | None = None
    since_updated_at: AwareDatetime | None = None


class SyncroGetInvoice(_Input):
    operation: Literal["get_invoice"] = "get_invoice"
    invoice_id: ID = Field(..., title="Invoice", json_schema_extra=_picker("invoice_id"))


class SyncroListAssets(_Page):
    operation: Literal["list_assets"] = "list_assets"
    customer_id: ID | None = None
    query: TEXT | None = None
    asset_type_id: ID | None = None


class SyncroGetAsset(_Asset):
    operation: Literal["get_asset"] = "get_asset"


class SyncroCreateAsset(_AssetFields):
    operation: Literal["create_asset"] = "create_asset"
    name: TEXT
    asset_type_name: TEXT = Field(..., description="An existing Syncro asset type name.")


class SyncroUpdateAsset(_Asset, _AssetFields):
    operation: Literal["update_asset"] = "update_asset"
    name: TEXT = Field(..., description="Syncro requires the asset name on updates.")
    asset_type_name: TEXT | None = None


class SyncroListRMMAlerts(_Page):
    operation: Literal["list_rmm_alerts"] = "list_rmm_alerts"
    status: Literal["active", "resolved", "all"] = "active"
    created_after: AwareDatetime | None = None


class SyncroGetRMMAlert(_Input):
    operation: Literal["get_rmm_alert"] = "get_rmm_alert"
    alert_id: ID = Field(..., title="RMM alert ID")


SyncroConfig = Annotated[Union[
    SyncroGetCurrentUser, SyncroListCustomers, SyncroGetCustomer, SyncroCreateCustomer,
    SyncroUpdateCustomer, SyncroListContacts, SyncroGetContact, SyncroCreateContact,
    SyncroUpdateContact, SyncroListTickets, SyncroGetTicket, SyncroCreateTicket,
    SyncroUpdateTicket, SyncroAddTicketComment, SyncroListInvoices, SyncroGetInvoice,
    SyncroListAssets, SyncroGetAsset, SyncroCreateAsset, SyncroUpdateAsset,
    SyncroListRMMAlerts, SyncroGetRMMAlert,
], Field(discriminator="operation")]


class SyncroNodeConfig(NodeConfig[SyncroConfig, SyncroAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# method, path, path-ID field, documented response envelope (None is a bare record).
OPERATIONS = {
    "get_current_user": ("GET", "/me", None, None),
    "list_customers": ("GET", "/customers", None, "customers"),
    "get_customer": ("GET", "/customers/{id}", "customer_id", "customer"),
    "create_customer": ("POST", "/customers", None, "customer"),
    "update_customer": ("PUT", "/customers/{id}", "customer_id", "customer"),
    "list_contacts": ("GET", "/contacts", None, "contacts"),
    "get_contact": ("GET", "/contacts/{id}", "contact_id", None),
    "create_contact": ("POST", "/contacts", None, None),
    "update_contact": ("PUT", "/contacts/{id}", "contact_id", None),
    "list_tickets": ("GET", "/tickets", None, "tickets"),
    "get_ticket": ("GET", "/tickets/{id}", "ticket_id", "ticket"),
    "create_ticket": ("POST", "/tickets", None, "ticket"),
    "update_ticket": ("PUT", "/tickets/{id}", "ticket_id", "ticket"),
    "add_ticket_comment": ("POST", "/tickets/{id}/comment", "ticket_id", "comment"),
    "list_invoices": ("GET", "/invoices", None, "invoices"),
    "get_invoice": ("GET", "/invoices/{id}", "invoice_id", "invoice"),
    "list_assets": ("GET", "/customer_assets", None, "assets"),
    "get_asset": ("GET", "/customer_assets/{id}", "asset_id", "asset"),
    "create_asset": ("POST", "/customer_assets", None, "asset"),
    "update_asset": ("PUT", "/customer_assets/{id}", "asset_id", "asset"),
    "list_rmm_alerts": ("GET", "/rmm_alerts", None, "rmm_alerts"),
    "get_rmm_alert": ("GET", "/rmm_alerts/{id}", "alert_id", "rmm_alert"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    return value


def _record(value):
    if not isinstance(value, dict) or type(value.get("id")) is not int or value["id"] <= 0:
        raise ValueError("Syncro returned an invalid record")
    return value


class SyncroNode(WorkflowNode):
    integration_type = "automation-syncro"
    connection_evidence = ConnectionEvidence(noun="Syncro account", identity_operation="get_current_user",
        identity_keys=("user_name", "user_email", "subdomain"))

    @classmethod
    def get_config_model(cls):
        return SyncroNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Syncro API token")
        credential = self.config.credentials
        config = self.config.config
        method, template, id_field, envelope = OPERATIONS[config.operation]
        path = template.replace("{id}", str(getattr(config, id_field))) if id_field else template
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation", *([id_field] if id_field else [])})
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()} if method == "GET" else None
        writing = method != "GET"
        base = {"operation": config.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method,
                    f"https://{credential.subdomain}.syncromsp.com/api/v1{path}",
                    headers={"Authorization": f"Bearer {credential.api_token}", "Accept": "application/json"},
                    params=params, **({"json": values} if writing else {}))
        except (httpx.HTTPError, SSRFError):
            return {**base, "status": "error", "error": "Syncro request could not be completed",
                **({"write_outcome": "unknown", "message": "Inspect Syncro before retrying this write"} if writing else {})}
        try:
            if response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("Syncro returned a non-JSON response")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Syncro returned an invalid response envelope")
            if not 200 <= response.status_code < 300 or payload.get("success") is False or payload.get("error") or payload.get("errors"):
                message = payload.get("error") or payload.get("errors") or payload.get("message") or f"Syncro HTTP {response.status_code}"
                output = {**base, "status": "error", "http_status": response.status_code,
                    "error": _redact(message, credential.api_token)}
                if writing and response.status_code >= 500:
                    output["write_outcome"] = "unknown"
                return output
            data = payload[envelope] if envelope else payload
            output = {**base, "status": "success", "http_status": response.status_code, "data": data}
            if config.operation.startswith("list_"):
                if not isinstance(data, list):
                    raise ValueError("Syncro returned an invalid list")
                for row in data:
                    _record(row)
                meta = payload.get("meta")
                next_page = None
                if meta is not None:
                    if not isinstance(meta, dict) or type(meta.get("total_pages")) is not int or meta["total_pages"] < 0:
                        raise ValueError("Syncro returned invalid pagination")
                    if type(meta.get("page")) is not int or meta["page"] != config.page:
                        raise ValueError("Syncro returned a different page")
                    next_page = config.page + 1 if config.page < meta["total_pages"] else None
                output.update({"page": config.page, "next_page": next_page,
                    "pagination_known": meta is not None, "meta": meta})
            elif config.operation == "get_current_user":
                if type(data.get("user_id")) is not int or not data.get("user_email") or not data.get("subdomain"):
                    raise ValueError("Syncro returned an invalid current user")
            else:
                _record(data)
                if id_field and config.operation != "add_ticket_comment" and data["id"] != getattr(config, id_field):
                    raise ValueError("Syncro returned a different record")
            return _redact(output, credential.api_token)
        except (ValueError, KeyError, TypeError):
            return {**base, "status": "error", "http_status": response.status_code,
                "error": "Syncro response could not be verified",
                **({"write_outcome": "unknown", "message": "Inspect Syncro before retrying this write"} if writing else {})}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        operations = {"customer_id": "list_customers", "contact_id": "list_contacts",
            "ticket_id": "list_tickets", "invoice_id": "list_invoices", "asset_id": "list_assets"}
        if field_name not in operations:
            raise ValueError("Unknown Syncro choice field")
        if search:
            raise ValueError("Syncro choices use page navigation")
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,6}", page_token)):
            raise ValueError("Use the returned Syncro page token")
        config = cls.parse_config({"config": {"operation": operations[field_name], "page": int(page_token or 1)}, "credentials": credential_data})
        node = cls("syncro-options", cls.integration_type, {}, config=config)
        result = await node.execute({})
        if result.get("status") != "success":
            raise ValueError(result.get("error", "Syncro choices could not be loaded"))
        return {"options": [{"value": str(row["id"]), "label": str(row.get("business_name") or row.get("name") or row.get("subject") or row.get("fullname") or row.get("number") or row["id"])} for row in result["data"]],
            "next_page_token": str(result["next_page"]) if result["next_page"] else None}

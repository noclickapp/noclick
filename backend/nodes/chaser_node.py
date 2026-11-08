"""Chaser v1.11.1 receivables operations (https://openapi.chaserhq.com/docs/).

One configured operation makes one API request. Lists return a single explicit
page; pause/resume operations change reminder delivery. No automatic write retries.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://openapi.chaserhq.com"

class ChaserAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Chaser API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://my.chaserhq.com/settings/integrations",
        "x-credential-instructions": "In Chaser, open Organisation Settings > Integrations > Get API keys. Paste both the API key and API secret. NoClick uses Basic authentication to the Chaser API."})
    credential_type: Literal["chaser_api_key"] = Field("chaser_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API credential without control characters")
        if info.field_name == "api_key" and ":" in value:
            raise ValueError("Paste only the API key, without a colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="after")
    @classmethod
    def validate_wire_value(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"customer_id", "contact_person_id", "note_id"} or (info.field_name == "invoice_id" and cls.__name__ != "ChaserCreateInvoiceConfig"):
            if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
                raise ValueError("Use one Chaser resource ID; prefix an external ID with ext_")
        if info.field_name.endswith("_date") or info.field_name == "date":
            if not isinstance(value, str):
                raise ValueError("Use an RFC 3339 date and time")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an RFC 3339 date and time including timezone") from None
        return value


class ChaserGetOrganisationConfig(_Input):
    """Get current organisation."""
    operation: Literal["get_organisation"] = Field("get_organisation", json_schema_extra={"ui:hidden": True})

class ChaserListCustomersConfig(_Input):
    """Get customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=100)
    page: int = Field(0, ge=0)
    external_id: str | None = Field(None, description="Exact-match external_id filter.")
    company_name: str | None = Field(None, description="Exact-match company_name filter.")
    contact_first_name: str | None = Field(None, description="Exact-match contact_first_name filter.")
    contact_last_name: str | None = Field(None, description="Exact-match contact_last_name filter.")
    contact_email_address: str | None = Field(None, description="Exact-match contact_email_address filter.")
    status: str | None = Field(None, description="Exact-match status filter.")

class ChaserGetCustomerConfig(_Input):
    """Get customers by id."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserCreateCustomerConfig(_Input):
    """Create customer."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(...)
    company_name: str = Field(..., min_length=1)
    contact_first_name: str | None = Field(None, min_length=1)
    contact_last_name: str | None = Field(None, min_length=1)
    contact_email_address: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone_number: str | None = Field(None)
    mobile_number: str | None = Field(None)
    status: Literal['ACTIVE', 'ARCHIVED'] | None = Field(None)

class ChaserUpdateCustomerConfig(_Input):
    """Update customer."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    external_id: str | None = Field(None)
    company_name: str | None = Field(None, min_length=1)
    contact_first_name: str | None = Field(None, min_length=1)
    contact_last_name: str | None = Field(None, min_length=1)
    contact_email_address: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone_number: str | None = Field(None)
    mobile_number: str | None = Field(None)
    status: Literal['ACTIVE', 'ARCHIVED'] | None = Field(None)

    @model_validator(mode="after")
    def changed_fields(self):
        if not ({key for key, value in self.model_dump().items() if value is not None} - {"operation", 'customer_id'}):
            raise ValueError("Provide at least one field to update")
        return self

class ChaserListInvoicesConfig(_Input):
    """Get invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=100)
    page: int = Field(0, ge=0)
    invoice_id: str | None = Field(None, description="Exact-match invoice_id filter.")
    invoice_number: str | None = Field(None, description="Exact-match invoice_number filter.")
    status: str | None = Field(None, description="Exact-match status filter.")
    currency_code: str | None = Field(None, description="Exact-match currency_code filter.")
    amount_due: float | None = Field(None, allow_inf_nan=False)
    amount_paid: float | None = Field(None, allow_inf_nan=False)
    total: float | None = Field(None, allow_inf_nan=False)
    sub_total: float | None = Field(None, allow_inf_nan=False)
    customer_external_id: str | None = Field(None, description="Exact-match customer_external_id filter.")

class ChaserGetInvoiceConfig(_Input):
    """Get invoice by id."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserCreateInvoiceConfig(_Input):
    """Create invoice."""
    operation: Literal["create_invoice"] = Field("create_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(...)
    invoice_number: str = Field(...)
    status: Literal['DRAFT', 'SUBMITTED', 'AUTHORISED', 'PAID', 'VOIDED', 'DELETED'] = Field(...)
    currency_code: str = Field(..., pattern='^[A-Z]{3}$')
    amount_due: float = Field(..., ge=0, allow_inf_nan=False)
    amount_paid: float | None = Field(None, ge=0, allow_inf_nan=False)
    total: float = Field(..., ge=0, allow_inf_nan=False)
    sub_total: float | None = Field(None, ge=0, allow_inf_nan=False)
    date: str = Field(..., description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    due_date: str = Field(..., description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    fully_paid_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    expect_payment_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    customer_external_id: str = Field(...)
    invoice_pdf_link_source: str | None = Field(None, min_length=1, pattern=r"^https?://[^\s]+$")

class ChaserUpdateInvoiceConfig(_Input):
    """Update invoice."""
    operation: Literal["update_invoice"] = Field("update_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    invoice_number: str | None = Field(None)
    status: Literal['DRAFT', 'SUBMITTED', 'AUTHORISED', 'PAID', 'VOIDED', 'DELETED'] | None = Field(None)
    currency_code: str | None = Field(None, pattern='^[A-Z]{3}$')
    amount_due: float | None = Field(None, ge=0, allow_inf_nan=False)
    amount_paid: float | None = Field(None, ge=0, allow_inf_nan=False)
    total: float | None = Field(None, ge=0, allow_inf_nan=False)
    sub_total: float | None = Field(None, ge=0, allow_inf_nan=False)
    date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    due_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    fully_paid_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    expect_payment_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    customer_external_id: str | None = Field(None)
    invoice_pdf_link_source: str | None = Field(None, min_length=1, pattern=r"^https?://[^\s]+$")

    @model_validator(mode="after")
    def changed_fields(self):
        if not ({key for key, value in self.model_dump().items() if value is not None} - {"operation", 'invoice_id'}):
            raise ValueError("Provide at least one field to update")
        return self

class ChaserListContactPersonsConfig(_Input):
    """Get contact persons."""
    operation: Literal["list_contact_persons"] = Field("list_contact_persons", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserGetContactPersonConfig(_Input):
    """Get contact person by id."""
    operation: Literal["get_contact_person"] = Field("get_contact_person", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    contact_person_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserCreateContactPersonConfig(_Input):
    """Create contact person."""
    operation: Literal["create_contact_person"] = Field("create_contact_person", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    external_id: str = Field(...)
    contact_first_name: str | None = Field(None, min_length=1)
    contact_last_name: str | None = Field(None, min_length=1)
    contact_email_address: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone_number: str | None = Field(None)
    mobile_number: str | None = Field(None)
    status: Literal['ACTIVE', 'ARCHIVED'] | None = Field(None)

class ChaserUpdateContactPersonConfig(_Input):
    """Update contact person."""
    operation: Literal["update_contact_person"] = Field("update_contact_person", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    contact_person_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    external_id: str | None = Field(None)
    contact_first_name: str | None = Field(None, min_length=1)
    contact_last_name: str | None = Field(None, min_length=1)
    contact_email_address: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone_number: str | None = Field(None)
    mobile_number: str | None = Field(None)
    status: Literal['ACTIVE', 'ARCHIVED'] | None = Field(None)

    @model_validator(mode="after")
    def changed_fields(self):
        if not ({key for key, value in self.model_dump().items() if value is not None} - {"operation", 'customer_id', 'contact_person_id'}):
            raise ValueError("Provide at least one field to update")
        return self

class ChaserDeleteContactPersonConfig(_Input):
    """Delete contact person."""
    operation: Literal["delete_contact_person"] = Field("delete_contact_person", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    contact_person_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserListCustomerNotesConfig(_Input):
    """Get customer notes."""
    operation: Literal["list_customer_notes"] = Field("list_customer_notes", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserCreateCustomerNoteConfig(_Input):
    """Create customer note."""
    operation: Literal["create_customer_note"] = Field("create_customer_note", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    message: str = Field(..., min_length=1)
    reminder_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    type: str | None = Field(None)

class ChaserUpdateCustomerNoteConfig(_Input):
    """Update customer note."""
    operation: Literal["update_customer_note"] = Field("update_customer_note", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    note_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    message: str | None = Field(None, min_length=1)
    reminder_date: str | None = Field(None, description="RFC 3339 date and time including timezone.", json_schema_extra={"format": "date-time"})
    type: str | None = Field(None)

    @model_validator(mode="after")
    def changed_fields(self):
        if not ({key for key, value in self.model_dump().items() if value is not None} - {"operation", 'customer_id', 'note_id'}):
            raise ValueError("Provide at least one field to update")
        return self

class ChaserDeleteCustomerNoteConfig(_Input):
    """Delete customer note."""
    operation: Literal["delete_customer_note"] = Field("delete_customer_note", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")
    note_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserPauseCustomerChasingConfig(_Input):
    """Pause customer chasing."""
    operation: Literal["pause_customer_chasing"] = Field("pause_customer_chasing", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserResumeCustomerChasingConfig(_Input):
    """Resume customer chasing."""
    operation: Literal["resume_customer_chasing"] = Field("resume_customer_chasing", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserPauseInvoiceChasingConfig(_Input):
    """Pause invoice chasing."""
    operation: Literal["pause_invoice_chasing"] = Field("pause_invoice_chasing", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

class ChaserResumeInvoiceChasingConfig(_Input):
    """Resume invoice chasing."""
    operation: Literal["resume_invoice_chasing"] = Field("resume_invoice_chasing", json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, description="Chaser internal ID or ext_ prefixed external ID.")

ChaserConfig = Annotated[Union[
    ChaserGetOrganisationConfig,
    ChaserListCustomersConfig,
    ChaserGetCustomerConfig,
    ChaserCreateCustomerConfig,
    ChaserUpdateCustomerConfig,
    ChaserListInvoicesConfig,
    ChaserGetInvoiceConfig,
    ChaserCreateInvoiceConfig,
    ChaserUpdateInvoiceConfig,
    ChaserListContactPersonsConfig,
    ChaserGetContactPersonConfig,
    ChaserCreateContactPersonConfig,
    ChaserUpdateContactPersonConfig,
    ChaserDeleteContactPersonConfig,
    ChaserListCustomerNotesConfig,
    ChaserCreateCustomerNoteConfig,
    ChaserUpdateCustomerNoteConfig,
    ChaserDeleteCustomerNoteConfig,
    ChaserPauseCustomerChasingConfig,
    ChaserResumeCustomerChasingConfig,
    ChaserPauseInvoiceChasingConfig,
    ChaserResumeInvoiceChasingConfig
], Field(discriminator="operation")]


class ChaserFullConfig(NodeConfig[ChaserConfig, ChaserAPIKeyCredential]):
    pass


OPERATIONS = {'get_organisation': {'method': 'GET',
                      'path': '/v1/organisation',
                      'path_fields': [],
                      'query_fields': [],
                      'body_fields': []},
 'list_customers': {'method': 'GET',
                    'path': '/v1/customers',
                    'path_fields': [],
                    'query_fields': ['limit',
                                     'page',
                                     'external_id',
                                     'company_name',
                                     'contact_first_name',
                                     'contact_last_name',
                                     'contact_email_address',
                                     'status'],
                    'body_fields': []},
 'get_customer': {'method': 'GET',
                  'path': '/v1/customers/{customer_id}',
                  'path_fields': ['customer_id'],
                  'query_fields': [],
                  'body_fields': []},
 'create_customer': {'method': 'POST',
                     'path': '/v1/customers',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['external_id',
                                     'company_name',
                                     'contact_first_name',
                                     'contact_last_name',
                                     'contact_email_address',
                                     'phone_number',
                                     'mobile_number',
                                     'status']},
 'update_customer': {'method': 'PUT',
                     'path': '/v1/customers/{customer_id}',
                     'path_fields': ['customer_id'],
                     'query_fields': [],
                     'body_fields': ['external_id',
                                     'company_name',
                                     'contact_first_name',
                                     'contact_last_name',
                                     'contact_email_address',
                                     'phone_number',
                                     'mobile_number',
                                     'status']},
 'list_invoices': {'method': 'GET',
                   'path': '/v1/invoices',
                   'path_fields': [],
                   'query_fields': ['limit',
                                    'page',
                                    'invoice_id',
                                    'invoice_number',
                                    'status',
                                    'currency_code',
                                    'amount_due',
                                    'amount_paid',
                                    'total',
                                    'sub_total',
                                    'customer_external_id'],
                   'body_fields': []},
 'get_invoice': {'method': 'GET',
                 'path': '/v1/invoices/{invoice_id}',
                 'path_fields': ['invoice_id'],
                 'query_fields': [],
                 'body_fields': []},
 'create_invoice': {'method': 'POST',
                    'path': '/v1/invoices',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': ['invoice_id',
                                    'invoice_number',
                                    'status',
                                    'currency_code',
                                    'amount_due',
                                    'amount_paid',
                                    'total',
                                    'sub_total',
                                    'date',
                                    'due_date',
                                    'fully_paid_date',
                                    'expect_payment_date',
                                    'customer_external_id',
                                    'invoice_pdf_link_source']},
 'update_invoice': {'method': 'PUT',
                    'path': '/v1/invoices/{invoice_id}',
                    'path_fields': ['invoice_id'],
                    'query_fields': [],
                    'body_fields': ['invoice_number',
                                    'status',
                                    'currency_code',
                                    'amount_due',
                                    'amount_paid',
                                    'total',
                                    'sub_total',
                                    'date',
                                    'due_date',
                                    'fully_paid_date',
                                    'expect_payment_date',
                                    'customer_external_id',
                                    'invoice_pdf_link_source']},
 'list_contact_persons': {'method': 'GET',
                          'path': '/v1/customers/{customer_id}/contact_persons',
                          'path_fields': ['customer_id'],
                          'query_fields': [],
                          'body_fields': []},
 'get_contact_person': {'method': 'GET',
                        'path': '/v1/customers/{customer_id}/contact_persons/{contact_person_id}',
                        'path_fields': ['customer_id', 'contact_person_id'],
                        'query_fields': [],
                        'body_fields': []},
 'create_contact_person': {'method': 'POST',
                           'path': '/v1/customers/{customer_id}/contact_persons',
                           'path_fields': ['customer_id'],
                           'query_fields': [],
                           'body_fields': ['external_id',
                                           'contact_first_name',
                                           'contact_last_name',
                                           'contact_email_address',
                                           'phone_number',
                                           'mobile_number',
                                           'status']},
 'update_contact_person': {'method': 'PUT',
                           'path': '/v1/customers/{customer_id}/contact_persons/{contact_person_id}',
                           'path_fields': ['customer_id', 'contact_person_id'],
                           'query_fields': [],
                           'body_fields': ['external_id',
                                           'contact_first_name',
                                           'contact_last_name',
                                           'contact_email_address',
                                           'phone_number',
                                           'mobile_number',
                                           'status']},
 'delete_contact_person': {'method': 'DELETE',
                           'path': '/v1/customers/{customer_id}/contact_persons/{contact_person_id}',
                           'path_fields': ['customer_id', 'contact_person_id'],
                           'query_fields': [],
                           'body_fields': []},
 'list_customer_notes': {'method': 'GET',
                         'path': '/v1/customers/{customer_id}/notes',
                         'path_fields': ['customer_id'],
                         'query_fields': [],
                         'body_fields': []},
 'create_customer_note': {'method': 'POST',
                          'path': '/v1/customers/{customer_id}/notes',
                          'path_fields': ['customer_id'],
                          'query_fields': [],
                          'body_fields': ['message', 'reminder_date', 'type']},
 'update_customer_note': {'method': 'PATCH',
                          'path': '/v1/customers/{customer_id}/notes/{note_id}',
                          'path_fields': ['customer_id', 'note_id'],
                          'query_fields': [],
                          'body_fields': ['message', 'reminder_date', 'type']},
 'delete_customer_note': {'method': 'DELETE',
                          'path': '/v1/customers/{customer_id}/notes/{note_id}',
                          'path_fields': ['customer_id', 'note_id'],
                          'query_fields': [],
                          'body_fields': []},
 'pause_customer_chasing': {'method': 'POST',
                            'path': '/v1/customers/{customer_id}/chasing/pause',
                            'path_fields': ['customer_id'],
                            'query_fields': [],
                            'body_fields': []},
 'resume_customer_chasing': {'method': 'POST',
                             'path': '/v1/customers/{customer_id}/chasing/resume',
                             'path_fields': ['customer_id'],
                             'query_fields': [],
                             'body_fields': []},
 'pause_invoice_chasing': {'method': 'POST',
                           'path': '/v1/invoices/{invoice_id}/chasing/pause',
                           'path_fields': ['invoice_id'],
                           'query_fields': [],
                           'body_fields': []},
 'resume_invoice_chasing': {'method': 'POST',
                            'path': '/v1/invoices/{invoice_id}/chasing/resume',
                            'path_fields': ['invoice_id'],
                            'query_fields': [],
                            'body_fields': []}}

class ChaserNode(WorkflowNode):
    integration_type = "automation-chaser"
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="customers", identity_operation="get_organisation")

    @classmethod
    def get_config_model(cls):
        return ChaserFullConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Chaser API key and secret")
        credential = config.credentials
        op = config.config
        route = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = route["path"]
        for field in route["path_fields"]:
            path = path.replace("{" + field + "}", quote(values[field], safe=""))
        params = {key: values[key] for key in route["query_fields"] if key in values}
        body = {key: values[key] for key in route["body_fields"] if key in values}
        authorization = "Basic " + base64.b64encode((credential.api_key + ":" + credential.api_secret).encode()).decode("ascii")
        kwargs = {"headers": {"Authorization": authorization, "Accept": "application/json"}, "params": params}
        if route["body_fields"]:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(route["method"], BASE_URL + path, **kwargs)
        if not 200 <= response.status_code < 300:
            message = "Chaser rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            for secret in (credential.api_key, credential.api_secret, authorization):
                message = message.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        if response.status_code == 204 or not response.content:
            return {"status": "success", "data": None}
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected a Chaser JSON object")
        if payload.get("type", "").endswith("_error"):
            raise ValueError("Chaser returned an error envelope")
        return {**payload, "status": "success"}

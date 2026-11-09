"""Outseta v1 CRM, email-list and billing operations.

Contract: https://docs.outseta.com/api-reference/openapi.json (v1).
Authentication and page-number pagination: https://docs.outseta.com/api-reference/overview.
Each operation makes exactly one request; writes are never retried automatically.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class OutsetaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Outseta API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.outseta.com/api-reference/overview#server-side-api-keys",
        "x-credential-instructions": "In Outseta, open Settings > Integrations > API Keys. Paste the API key and secret, and enter your account subdomain or admin URL. These server-side keys grant full account access. NoClick reads a page of CRM people to check the connection.",
    })
    credential_type: Literal["outseta_api_key"] = Field("outseta_api_key", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., min_length=1, max_length=253, title="Account subdomain", description="The part before .outseta.com, or your HTTPS Outseta admin URL.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def account_host(cls, value):
        value = str(value or "").strip().lower()
        if "." in value or "://" in value:
            parts = urlsplit(value if "://" in value else "https://" + value)
            if parts.scheme != "https" or parts.username or parts.password or parts.port or not (parts.hostname or "").endswith(".outseta.com"):
                raise ValueError("Use your HTTPS account URL at <subdomain>.outseta.com")
            value = parts.hostname.removesuffix(".outseta.com")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter one Outsetan account subdomain")
        return value

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API credential", key=True)
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the key or secret alone, without a header or colon")
        return value


Uid = Annotated[str, Field(min_length=1, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=250)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, description="Requested page size; the server may cap it. The returned metadata.limit is authoritative.")
    offset: int = Field(0, ge=0, le=1000000, description="Zero-based page number. Use next_offset from the previous page, not a record count.")


class ListPeopleConfig(_Page):
    """Read one page of people."""
    operation: Literal["list_people"] = Field("list_people", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=250, description="Provider search text.")

class GetPersonConfig(_Input):
    """Retrieve a person by UID."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra={"ui:hidden": True})
    person_uid: Uid

class CreatePersonConfig(_Input):
    """Create a person."""
    operation: Literal["create_person"] = Field("create_person", json_schema_extra={"ui:hidden": True})
    email: EmailStr
    first_name: Text | None = None
    last_name: Text | None = None
    phone_mobile: Text | None = None
    phone_work: Text | None = None
    title: Text | None = None

class UpdatePersonConfig(_Input):
    """Update a person with the supplied fields."""
    operation: Literal["update_person"] = Field("update_person", json_schema_extra={"ui:hidden": True})
    person_uid: Uid
    email: EmailStr | None = None
    first_name: Text | None = None
    last_name: Text | None = None
    phone_mobile: Text | None = None
    phone_work: Text | None = None
    title: Text | None = None

class DeletePersonConfig(_Input):
    """Delete the selected person record."""
    operation: Literal["delete_person"] = Field("delete_person", json_schema_extra={"ui:hidden": True})
    person_uid: Uid

class ListAccountsConfig(_Page):
    """Read one page of accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=250, description="Provider search text.")

class GetAccountConfig(_Input):
    """Retrieve an account by UID."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})
    account_uid: Uid

class CreateAccountConfig(_Input):
    """Create an account."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})
    name: Text
    client_identifier: Text | None = None

class UpdateAccountConfig(_Input):
    """Update an account with the supplied fields."""
    operation: Literal["update_account"] = Field("update_account", json_schema_extra={"ui:hidden": True})
    account_uid: Uid
    name: Text
    client_identifier: Text | None = None

class DeleteAccountConfig(_Input):
    """Delete the selected account record."""
    operation: Literal["delete_account"] = Field("delete_account", json_schema_extra={"ui:hidden": True})
    account_uid: Uid

class ListDealsConfig(_Page):
    """Read one page of deals."""
    operation: Literal["list_deals"] = Field("list_deals", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=250, description="Provider search text.")

class GetDealConfig(_Input):
    """Retrieve a deal by UID."""
    operation: Literal["get_deal"] = Field("get_deal", json_schema_extra={"ui:hidden": True})
    deal_uid: Uid

class CreateDealConfig(_Input):
    """Create a deal."""
    operation: Literal["create_deal"] = Field("create_deal", json_schema_extra={"ui:hidden": True})
    name: Text
    amount: float | None = Field(None, allow_inf_nan=False)
    due_date: datetime | None = None
    pipeline_uid: Uid | None = None

class UpdateDealConfig(_Input):
    """Update a deal with the supplied fields."""
    operation: Literal["update_deal"] = Field("update_deal", json_schema_extra={"ui:hidden": True})
    deal_uid: Uid
    name: Text
    amount: float | None = Field(None, allow_inf_nan=False)
    due_date: datetime | None = None
    pipeline_uid: Uid | None = None

class DeleteDealConfig(_Input):
    """Delete the selected deal record."""
    operation: Literal["delete_deal"] = Field("delete_deal", json_schema_extra={"ui:hidden": True})
    deal_uid: Uid

class ListEmailListsConfig(_Page):
    """Read one page of email lists."""
    operation: Literal["list_email_lists"] = Field("list_email_lists", json_schema_extra={"ui:hidden": True})

class GetEmailListConfig(_Input):
    """Retrieve an email list."""
    operation: Literal["get_email_list"] = Field("get_email_list", json_schema_extra={"ui:hidden": True})
    email_list_uid: Uid

class ListEmailSubscribersConfig(_Page):
    """Read subscribers to the selected email list."""
    operation: Literal["list_email_subscribers"] = Field("list_email_subscribers", json_schema_extra={"ui:hidden": True})
    email_list_uid: Uid
    q: str | None = Field(None, max_length=250)

class SubscribePersonConfig(_Input):
    """Subscribe an existing person to an email list."""
    operation: Literal["subscribe_person"] = Field("subscribe_person", json_schema_extra={"ui:hidden": True})
    email_list_uid: Uid
    person_uid: Uid

class UnsubscribePersonConfig(_Input):
    """Remove the selected email-list subscription, using its subscription UID."""
    operation: Literal["unsubscribe_person"] = Field("unsubscribe_person", json_schema_extra={"ui:hidden": True})
    email_list_uid: Uid
    subscription_uid: Uid

class ListPlansConfig(_Page):
    """Read a page of Outseta billing v2 plans."""
    operation: Literal["list_plans"] = Field("list_plans", json_schema_extra={"ui:hidden": True})

class GetPlanConfig(_Input):
    """Retrieve an Outseta billing v2 plan."""
    operation: Literal["get_plan"] = Field("get_plan", json_schema_extra={"ui:hidden": True})
    plan_uid: Uid

class ListSubscriptionsConfig(_Page):
    """Read a page of Outseta billing v2 subscriptions."""
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", json_schema_extra={"ui:hidden": True})
    status: Literal["current", "future", "past"] | None = None

class ListInvoicesConfig(_Page):
    """Read a page of Outseta billing v2 invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})

OutsetaConfig = Annotated[Union[
    ListPeopleConfig,
    GetPersonConfig,
    CreatePersonConfig,
    UpdatePersonConfig,
    DeletePersonConfig,
    ListAccountsConfig,
    GetAccountConfig,
    CreateAccountConfig,
    UpdateAccountConfig,
    DeleteAccountConfig,
    ListDealsConfig,
    GetDealConfig,
    CreateDealConfig,
    UpdateDealConfig,
    DeleteDealConfig,
    ListEmailListsConfig,
    GetEmailListConfig,
    ListEmailSubscribersConfig,
    SubscribePersonConfig,
    UnsubscribePersonConfig,
    ListPlansConfig,
    GetPlanConfig,
    ListSubscriptionsConfig,
    ListInvoicesConfig
], Field(discriminator="operation")]


class OutsetaFullConfig(NodeConfig[OutsetaConfig, OutsetaAPIKeyCredential]):
    pass


ROUTES = {'list_people': ('GET', 'crm/people'),
 'get_person': ('GET', 'crm/people/{person_uid}'),
 'create_person': ('POST', 'crm/people'),
 'update_person': ('PUT', 'crm/people/{person_uid}'),
 'delete_person': ('DELETE', 'crm/people/{person_uid}'),
 'list_accounts': ('GET', 'crm/accounts'),
 'get_account': ('GET', 'crm/accounts/{account_uid}'),
 'create_account': ('POST', 'crm/accounts'),
 'update_account': ('PUT', 'crm/accounts/{account_uid}'),
 'delete_account': ('DELETE', 'crm/accounts/{account_uid}'),
 'list_deals': ('GET', 'crm/deals'),
 'get_deal': ('GET', 'crm/deals/{deal_uid}'),
 'create_deal': ('POST', 'crm/deals'),
 'update_deal': ('PUT', 'crm/deals/{deal_uid}'),
 'delete_deal': ('DELETE', 'crm/deals/{deal_uid}'),
 'list_email_lists': ('GET', 'email/lists'),
 'get_email_list': ('GET', 'email/lists/{email_list_uid}'),
 'list_email_subscribers': ('GET', 'email/lists/{email_list_uid}/subscriptions'),
 'subscribe_person': ('POST', 'email/lists/{email_list_uid}/subscriptions'),
 'unsubscribe_person': ('DELETE', 'email/lists/{email_list_uid}/subscriptions/{subscription_uid}'),
 'list_plans': ('GET', 'billing/plans'),
 'get_plan': ('GET', 'billing/plans/{plan_uid}'),
 'list_subscriptions': ('GET', 'billing/subscriptions'),
 'list_invoices': ('GET', 'billing/invoices')}

BODY_FIELDS = {
    "email": "Email", "first_name": "FirstName", "last_name": "LastName",
    "phone_mobile": "PhoneMobile", "phone_work": "PhoneWork", "title": "Title",
    "name": "Name", "client_identifier": "ClientIdentifier", "amount": "Amount",
    "due_date": "DueDate", "pipeline_uid": "PipelineUid",
}


def _redact(value, credential):
    """Never expose authentication/password material, including nested provider echoes."""
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()
                if not re.search(r"password|secret|token|recoverycode", k, re.I)}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
    return value


class OutsetaNode(WorkflowNode):
    integration_type = "automation-outseta"
    connection_evidence = ConnectionEvidence(noun="Outseta people", operation="list_people")

    @classmethod
    def get_config_model(cls):
        return OutsetaFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Outseta API key")
        op = self.config.config
        credential = self.config.credentials
        method, template = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {k: values[k] for k in ("limit", "offset", "q", "status") if k in values}
        body = None
        if method in {"POST", "PUT"}:
            body = {target: values[source] for source, target in BODY_FIELDS.items() if source in values}
            if not body and op.operation != "subscribe_person":
                raise ValueError("Provide at least one field to update")
            if op.operation == "subscribe_person":
                body = {"Person": {"Uid": op.person_uid}}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://" + credential.subdomain + ".outseta.com/api/v1/" + path,
                headers={"Authorization": "Outseta " + credential.api_key + ":" + credential.api_secret, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            raise ValueError(_redact(f"Outseta HTTP {response.status_code}: {message}", credential))
        if method == "DELETE":
            output = {"status": "success", "http_status": response.status_code, "deletion_acknowledged": True}
        else:
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if mime != "application/json" or len(response.content) > 10000000:
                raise ValueError("Expected a bounded Outseta JSON response")
            data = response.json()
            if not isinstance(data, dict) or any(k in data for k in ("Error", "error", "errors")):
                raise ValueError("Outseta returned an unexpected response envelope")
            output = {"status": "success", "http_status": response.status_code}
            if isinstance(op, _Page):
                rows, metadata = data.get("items"), data.get("metadata")
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows) or not isinstance(metadata, dict):
                    raise ValueError("Outseta collection must contain items and metadata")
                if any(type(metadata.get(k)) is not int or metadata[k] < 0 for k in ("limit", "offset", "total")):
                    raise ValueError("Outseta pagination metadata is invalid")
                applied = metadata["limit"]
                if applied <= 0 or applied > op.limit or metadata["offset"] != op.offset or len(rows) > applied:
                    raise ValueError("Outseta pagination does not match this request")
                more = (op.offset + 1) * applied < metadata["total"]
                output.update(items=rows, metadata=metadata, has_more=more, next_offset=op.offset + 1 if more else None)
            else:
                output["item"] = data
        output = _redact(output, credential)
        await self.emit(output)
        return output

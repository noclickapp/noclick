"""Benchmark Email Classic REST v3, pinned to the provider's Postman collection.

This API uses AuthToken and decimal IDs, separately from Benchmark's newer API.
List reads return the provider's default page and Count, never an all-pages claim.
Email creation makes a draft; sending and scheduling are separate, unexposed APIs.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class BenchmarkEmailClassicCredential(BaseModel):
    model_config = ConfigDict(title="Benchmark Email Classic API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ui.benchmarkemail.com/Integrate#AP",
            "x-credential-instructions": "In Benchmark Email Classic, open Integrations → API and copy your Admin API Token. Paste the token alone. NoClick sends it in the AuthToken header to Benchmark's Classic API. This is separate from the newer Benchmark Email API key.",
        })
    credential_type: Literal["benchmark_email_classic_api_token"] = Field(
        "benchmark_email_classic_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Admin API Token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Admin API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Admin API Token without a header prefix or whitespace")
        return value


def _op(value: str, title: str, category: str):
    return Field(value, title=title, json_schema_extra={
        "ui:hidden": True, "x-display-name": title, "x-category": category})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ListID(_Input):
    list_id: str = Field(..., title="List ID", min_length=1, max_length=20, pattern=r"^[0-9]+$")


class _ContactID(_ListID):
    contact_id: str = Field(..., title="Contact ID", min_length=1, max_length=20, pattern=r"^[0-9]+$")


class _EmailID(_Input):
    email_id: str = Field(..., title="Email Campaign ID", min_length=1, max_length=20, pattern=r"^[0-9]+$")


class GetAccount(_Input):
    operation: Literal["get_account"] = _op("get_account", "Get Account", "Account")


class ListLists(_Input):
    """Read the API's default page of lists; Count is the provider's total."""
    operation: Literal["list_lists"] = _op("list_lists", "List Contact Lists", "Lists")


class GetList(_ListID):
    operation: Literal["get_list"] = _op("get_list", "Get Contact List", "Lists")


class GetListFields(_ListID):
    operation: Literal["get_list_fields"] = _op("get_list_fields", "Get Contact List Fields", "Lists")


class CreateList(_Input):
    operation: Literal["create_list"] = _op("create_list", "Create Contact List", "Lists")
    name: str = Field(..., title="List Name", min_length=1, max_length=500)
    description: str | None = Field(None, title="Description", max_length=5000)


class UpdateList(_ListID):
    operation: Literal["update_list"] = _op("update_list", "Update Contact List", "Lists")
    name: str = Field(..., title="List Name", min_length=1, max_length=500)
    description: str | None = Field(None, title="Description", max_length=5000)


class DeleteList(_ListID):
    operation: Literal["delete_list"] = _op("delete_list", "Delete Contact List", "Lists")


class ListContacts(_ListID):
    """Read the API's default page of contacts in one list."""
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contacts", "Contacts")


class GetContact(_ContactID):
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact", "Contacts")


class SearchContacts(_Input):
    operation: Literal["search_contacts"] = _op("search_contacts", "Search Contacts by Email", "Contacts")
    email: str = Field(..., title="Email", min_length=1, max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    search_filter: str | None = Field(None, title="Search Filter", max_length=500)


class CreateContact(_ListID):
    operation: Literal["create_contact"] = _op("create_contact", "Add Contact to List", "Contacts")
    email: str = Field(..., title="Email", min_length=1, max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: str | None = Field(None, title="First Name", max_length=500)
    last_name: str | None = Field(None, title="Last Name", max_length=500)
    email_permission: Literal["0", "1"] = Field(..., title="Email Permission",
        description="1 only when the contact gave permission to receive email; 0 otherwise.")


class UpdateContact(_ContactID):
    operation: Literal["update_contact"] = _op("update_contact", "Update Contact", "Contacts")
    email: str | None = Field(None, title="Email", min_length=1, max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: str | None = Field(None, title="First Name", max_length=500)
    last_name: str | None = Field(None, title="Last Name", max_length=500)

    @model_validator(mode="after")
    def changes(self):
        if all(value is None for value in (self.email, self.first_name, self.last_name)):
            raise ValueError("Supply at least one contact field to update")
        return self


class DeleteContact(_ContactID):
    """Delete from the specified list only; not the all-lists endpoint."""
    operation: Literal["delete_contact"] = _op("delete_contact", "Delete Contact from List", "Contacts")


class UnsubscribeContact(_ContactID):
    """Move the contact to the master Do Not Contact list."""
    operation: Literal["unsubscribe_contact"] = _op("unsubscribe_contact", "Unsubscribe Contact Globally", "Contacts")


class ListEmails(_Input):
    """Read the API's default page of email campaigns, with the total Count."""
    operation: Literal["list_emails"] = _op("list_emails", "List Email Campaigns", "Emails")


class GetEmail(_EmailID):
    operation: Literal["get_email"] = _op("get_email", "Get Email Campaign", "Emails")


class CreateEmail(_Input):
    """Create campaign details without calling the send or schedule endpoints."""
    operation: Literal["create_email"] = _op("create_email", "Create Email Campaign Draft", "Emails")
    name: str = Field(..., title="Campaign Name", min_length=1, max_length=500)
    subject: str = Field(..., title="Subject", min_length=1, max_length=1000)
    from_name: str = Field(..., title="From Name", min_length=1, max_length=500)
    from_email: str = Field(..., title="From Email", max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    reply_email: str = Field(..., title="Reply Email", max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    version: str = Field("400", title="Editor Version", max_length=20,
        description="Classic editor version; the collection's draft example uses 400.")


class RenameEmail(_EmailID):
    operation: Literal["rename_email"] = _op("rename_email", "Rename Email Campaign", "Emails")
    name: str = Field(..., title="Campaign Name", min_length=1, max_length=500)


class DeleteEmail(_EmailID):
    operation: Literal["delete_email"] = _op("delete_email", "Delete Email Campaign", "Emails")


class GetEmailReport(_EmailID):
    operation: Literal["get_email_report"] = _op("get_email_report", "Get Email Campaign Report", "Reports")


class GetEmailOpens(_EmailID):
    operation: Literal["get_email_opens"] = _op("get_email_opens", "Get Email Opens", "Reports")


class GetEmailClicks(_EmailID):
    operation: Literal["get_email_clicks"] = _op("get_email_clicks", "Get Email Clicks", "Reports")


Operation = Annotated[Union[GetAccount, ListLists, GetList, GetListFields, CreateList,
    UpdateList, DeleteList, ListContacts, GetContact, SearchContacts, CreateContact,
    UpdateContact, DeleteContact, UnsubscribeContact, ListEmails, GetEmail,
    CreateEmail, RenameEmail, DeleteEmail, GetEmailReport, GetEmailOpens, GetEmailClicks],
    Field(discriminator="operation")]


class BenchmarkEmailClassicNodeConfig(NodeConfig[Operation, BenchmarkEmailClassicCredential]):
    pass


# Each action is exactly one saved request in the pinned Classic collection.
ROUTES = {
    "get_account": ("GET", "https://clientapi.benchmarkemail.com/Client/"),
    "list_lists": ("GET", "https://clientapi.benchmarkemail.com/Contact/"),
    "get_list": ("GET", "https://clientapi.benchmarkemail.com/Contact/{list_id}"),
    "get_list_fields": ("GET", "https://clientapi.benchmarkemail.com/Contact/{list_id}/Fields"),
    "create_list": ("POST", "https://clientapi.benchmarkemail.com/Contact/"),
    "update_list": ("PATCH", "https://clientapi.benchmarkemail.com/Contact/{list_id}"),
    "delete_list": ("DELETE", "https://clientapi.benchmarkemail.com/Contact/{list_id}"),
    "list_contacts": ("GET", "https://clientapi.benchmarkemail.com/Contact/{list_id}/ContactDetails"),
    "get_contact": ("GET", "https://clientapi.benchmarkemail.com/Contact/{list_id}/ContactDetails/{contact_id}"),
    "search_contacts": ("GET", "https://clientapi.benchmarkemail.com/Contact/ContactDetails"),
    "create_contact": ("POST", "https://clientapi.benchmarkemail.com/Contact/{list_id}/ContactDetails"),
    "update_contact": ("PATCH", "https://clientapi.benchmarkemail.com/Contact/{list_id}/ContactDetails/{contact_id}"),
    "delete_contact": ("DELETE", "https://clientapi.benchmarkemail.com/Contact/{list_id}/ContactDetails/{contact_id}"),
    "unsubscribe_contact": ("DELETE", "https://clientapi.benchmarkemail.com/Contact/{list_id}/MoveToDNC/{contact_id}"),
    "list_emails": ("GET", "https://restapi.benchmarkemail.com/Emails/"),
    "get_email": ("GET", "https://clientapi.benchmarkemail.com/Emails/{email_id}"),
    "create_email": ("POST", "https://clientapi.benchmarkemail.com/Emails/"),
    "rename_email": ("PATCH", "https://clientapi.benchmarkemail.com/Emails/{email_id}"),
    "delete_email": ("DELETE", "https://clientapi.benchmarkemail.com/Emails/{email_id}"),
    "get_email_report": ("GET", "https://clientapi.benchmarkemail.com/Emails/{email_id}/Report"),
    "get_email_opens": ("GET", "https://clientapi.benchmarkemail.com/Emails/{email_id}/Report/Opens"),
    "get_email_clicks": ("GET", "https://clientapi.benchmarkemail.com/Emails/{email_id}/Report/Clicks"),
}


def _body(op):
    if op.operation in {"create_list", "update_list"}:
        return {"Data": {key: getattr(op, name) for name, key in
            (("name", "Name"), ("description", "Description")) if getattr(op, name) is not None}}
    if op.operation in {"create_contact", "update_contact"}:
        return {"Data": {key: getattr(op, name) for name, key in
            (("email", "Email"), ("first_name", "FirstName"), ("last_name", "LastName"),
             ("email_permission", "EmailPerm")) if getattr(op, name, None) is not None}}
    if op.operation == "create_email":
        return {"Detail": {key: getattr(op, name) for name, key in
            (("name", "Name"), ("subject", "Subject"), ("from_name", "FromName"),
             ("from_email", "FromEmail"), ("reply_email", "ReplyEmail"), ("version", "Version"))}}
    if op.operation == "rename_email":
        return {"Detail": {"Name": op.name}}
    return None


class BenchmarkEmailClassicNode(WorkflowNode):
    integration_type = "automation-benchmark-email-classic"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="contact lists",
        label_keys=("Name", "ID"), identity_operation="get_account", identity_keys=("Email", "Login"))

    @classmethod
    def get_config_model(cls):
        return BenchmarkEmailClassicNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, BenchmarkEmailClassicNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Benchmark Email Classic Admin API Token")
        op = self.config.config
        action = op.operation
        method, template = ROUTES[action]
        url = template.format(**op.model_dump())
        params = None
        if action == "search_contacts":
            params = {"Search": op.email}
            if op.search_filter is not None:
                params["SearchFilter"] = op.search_filter
        body = _body(op)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, params=params,
                    headers={"AuthToken": self.config.credentials.api_token,
                             "Content-Type": "application/json", "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "error", "action": action,
                "error": "Benchmark Email Classic request did not complete; inspect before retrying a write"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "action": action, "status_code": response.status_code,
                "error": "Benchmark Email Classic returned an unexpected response"}
        envelope = payload.get("Response") if isinstance(payload, dict) else None
        if not isinstance(envelope, dict):
            return {"status": "error", "action": action, "status_code": response.status_code,
                "error": "Benchmark Email Classic response is missing its Response object"}
        errors = envelope.get("Errors") or envelope.get("Error")
        status = envelope.get("Status")
        # Account details have an empty profile Status; report summary has no Status.
        allowed_status = (None, "", "1", 1) if action == "get_account" else (
            (None, "1", 1) if action == "get_email_report" else ("1", 1))
        if response.status_code >= 300 or errors or status not in allowed_status:
            return {"status": "error", "action": action, "status_code": response.status_code,
                "error": str(errors or f"Benchmark Email Classic rejected the request (HTTP {response.status_code}, Status {status})"),
                "data": envelope}
        if action == "get_account":
            valid_data = bool(envelope.get("Email") or envelope.get("Login"))
        elif action in {"delete_list", "delete_contact", "unsubscribe_contact", "delete_email"}:
            valid_data = True
        elif action in {"list_lists", "list_contacts", "search_contacts", "list_emails", "get_list_fields", "get_email_opens", "get_email_clicks"}:
            valid_data = isinstance(envelope.get("Data"), list)
        else:
            valid_data = isinstance(envelope.get("Data"), dict)
        if not valid_data:
            return {"status": "error", "action": action, "status_code": response.status_code,
                "error": "Benchmark Email Classic returned an unexpected data shape"}
        result = {"status": "success", "action": action, "status_code": response.status_code,
            "data": envelope.get("Data", envelope)}
        if "Count" in envelope:
            result["count"] = envelope["Count"]
        return result

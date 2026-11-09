"""Pylon support automation against the published API v1 contract.

Each operation issues one request. List operations return one page and an opaque
cursor; writes report the API acknowledgement and are never automatically retried.
References: https://api.usepylon.com/openapi.json and
https://docs.usepylon.com/pylon-docs/developer/api/authentication.md
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class PylonAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Pylon API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.usepylon.com/settings/api-tokens",
            "x-credential-instructions": "An Admin creates a token in Settings > Integrations & dev > API tokens. Paste the token and select your tenant region. Its role controls access; Pylon API tokens have no separate scopes. NoClick checks /me to identify the connected organization."
        })
    credential_type: Literal["pylon_1_api_token"] = Field("pylon_1_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    region: Literal["US", "EU"] = Field("US", description="Region hosting your Pylon tenant.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the API token without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_id(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value):
                raise ValueError("Use a Pylon ID without path separators or whitespace")
        return value


class Page(Input):
    cursor: str | None = Field(None, max_length=4096, description="Opaque next_page_cursor from a previous result; leave empty for the first page.")
    limit: int = Field(100, ge=1, le=999, description="Number of records to request in this page.")


class GetMe(Input):
    """Identify the organization and API token user."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ListIssues(Page):
    """List issues."""
    operation: Literal["list_issues"] = Field("list_issues", json_schema_extra={"ui:hidden": True})
    start_time: datetime = Field(..., description="Inclusive created_at boundary, RFC3339 with timezone.")
    end_time: datetime = Field(..., description="Exclusive created_at boundary; at most 365 days after start_time.")

    @model_validator(mode="after")
    def time_range(self):
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("Use timestamps with a timezone")
        if not timedelta(0) < self.end_time - self.start_time <= timedelta(days=365):
            raise ValueError("Choose an increasing range of at most 365 days")
        return self


class GetIssue(Input):
    """Get issue."""
    operation: Literal["get_issue"] = Field("get_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str


class CreateIssue(Input):
    """Create an internal issue and first note without messaging a customer."""
    operation: Literal["create_issue"] = Field("create_issue", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=1000)
    body_html: str = Field(..., min_length=1, max_length=100000)
    account_id: str = Field(..., description="Account for this internal issue. No destination is sent, so the first message is an internal note.")
    priority: Literal["urgent", "high", "medium", "low"] | None = None
    assignee_id: str | None = None
    team_id: str | None = None


class UpdateIssue(Input):
    """Update issue."""
    operation: Literal["update_issue"] = Field("update_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str
    title: str | None = Field(None, min_length=1, max_length=1000)
    state: str | None = Field(None, min_length=1, max_length=256, description="Standard or custom status slug, for example closed or waiting_on_customer.")
    assignee_id: str | None = None
    team_id: str | None = None
    tags: list[str] | None = Field(None, max_length=100, description="Replaces all issue tags with this exact list; an empty list clears tags.")


class ListIssueMessages(Page):
    """List issue messages."""
    operation: Literal["list_issue_messages"] = Field("list_issue_messages", json_schema_extra={"ui:hidden": True})
    issue_id: str


class CreateIssueNote(Input):
    """Post an internal note that is not visible to the requester."""
    operation: Literal["create_issue_note"] = Field("create_issue_note", json_schema_extra={"ui:hidden": True})
    issue_id: str
    body_html: str = Field(..., min_length=1, max_length=100000)
    thread_id: str | None = Field(None, description="Internal thread ID. When omitted, Pylon selects or creates an internal thread.")


class ReplyIssue(Input):
    """Send a customer-facing reply to the selected existing conversation."""
    operation: Literal["reply_issue"] = Field("reply_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str
    message_id: str = Field(..., description="Top-level Pylon message ID from list_issue_messages, identifying the customer-visible conversation.")
    body_html: str = Field(..., min_length=1, max_length=100000)
    to_emails: list[Annotated[str, Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]] | None = Field(None, max_length=100, description="For an email conversation, provide at least one recipient; recipients are not inferred from the referenced message.")

    @field_validator("to_emails")
    @classmethod
    def emails(cls, value):
        if value is not None and (not value or any(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) for email in value)):
            raise ValueError("Provide one or more recipient email addresses")
        return value


class ListAccounts(Page):
    """List accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class GetAccount(Input):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})
    account_id: str


class CreateAccount(Input):
    """Create account."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    owner_id: str | None = None


class UpdateAccount(Input):
    """Update the account name."""
    operation: Literal["update_account"] = Field("update_account", json_schema_extra={"ui:hidden": True})
    account_id: str
    name: str = Field(..., min_length=1, max_length=1000)


class ListContacts(Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class GetContact(Input):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str


class CreateContact(Input):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    email: str = Field(..., min_length=3, max_length=320)
    account_id: str | None = None


class UpdateContact(Input):
    """Update the contact name."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str
    name: str = Field(..., min_length=1, max_length=1000)


class ListTags(Input):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class GetTag(Input):
    """Get tag."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})
    tag_id: str


class CreateTag(Input):
    """Create tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., min_length=1, max_length=500)
    object_type: Literal["account", "article", "issue"]
    hex_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ListUsers(Input):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    include_deactivated: bool = False


class GetUser(Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str


class ListTeams(Input):
    """List teams."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})


class ListIssueStatuses(Input):
    """List issue statuses."""
    operation: Literal["list_issue_statuses"] = Field("list_issue_statuses", json_schema_extra={"ui:hidden": True})


PylonConfig = Annotated[Union[GetMe, ListIssues, GetIssue, CreateIssue, UpdateIssue, ListIssueMessages, CreateIssueNote, ReplyIssue, ListAccounts, GetAccount, CreateAccount, UpdateAccount, ListContacts, GetContact, CreateContact, UpdateContact, ListTags, GetTag, CreateTag, ListUsers, GetUser, ListTeams, ListIssueStatuses], Field(discriminator="operation")]


class PylonFullConfig(NodeConfig[PylonConfig, PylonAPITokenCredential]):
    pass


# Fixed routes, one operation per published contract endpoint.
ROUTES = {
    "get_me": ('GET', '/me', None),
    "list_issues": ('GET', '/issues', None),
    "get_issue": ('GET', '/issues/{issue_id}', 'issue_id'),
    "create_issue": ('POST', '/issues', None),
    "update_issue": ('PATCH', '/issues/{issue_id}', 'issue_id'),
    "list_issue_messages": ('GET', '/issues/{issue_id}/messages', 'issue_id'),
    "create_issue_note": ('POST', '/issues/{issue_id}/note', 'issue_id'),
    "reply_issue": ('POST', '/issues/{issue_id}/reply', 'issue_id'),
    "list_accounts": ('GET', '/accounts', None),
    "get_account": ('GET', '/accounts/{account_id}', 'account_id'),
    "create_account": ('POST', '/accounts', None),
    "update_account": ('PATCH', '/accounts/{account_id}', 'account_id'),
    "list_contacts": ('GET', '/contacts', None),
    "get_contact": ('GET', '/contacts/{contact_id}', 'contact_id'),
    "create_contact": ('POST', '/contacts', None),
    "update_contact": ('PATCH', '/contacts/{contact_id}', 'contact_id'),
    "list_tags": ('GET', '/tags', None),
    "get_tag": ('GET', '/tags/{tag_id}', 'tag_id'),
    "create_tag": ('POST', '/tags', None),
    "list_users": ('GET', '/users', None),
    "get_user": ('GET', '/users/{user_id}', 'user_id'),
    "list_teams": ('GET', '/teams', None),
    "list_issue_statuses": ('GET', '/issue-statuses', None),
}


class PylonNode(WorkflowNode):
    integration_type = "automation-pylon-1"
    connection_evidence = ConnectionEvidence(noun="Pylon organization", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return PylonFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Connect a Pylon API token")
        credential = self.config.credentials
        op = self.config.config
        method, path, id_field = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if id_field:
            path = path.format(**{id_field: quote(values.pop(id_field), safe="")})
        if op.operation == "reply_issue" and "to_emails" in values:
            values["email_info"] = {"to_emails": values.pop("to_emails")}
        if method == "PATCH" and not values:
            raise ValueError("Provide at least one field to update")
        base = "https://api.eu.usepylon.com" if credential.region == "EU" else "https://api.usepylon.com"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, base + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values}))
        except httpx.RequestError:
            return {"status": "error", "error": "Pylon request could not be completed; inspect writes before retrying."}
        # No retries: a lost write response can already have applied the mutation.
        if response.status_code != 200:
            message = "Pylon returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    errors = error.get("errors")
                    if isinstance(errors, list) and all(isinstance(item, str) for item in errors) and errors:
                        message = "; ".join(errors)[:2000]
                    elif isinstance(error.get("message"), str):
                        message = error["message"][:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(credential.api_token, "[redacted]")}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "error": "Pylon returned invalid JSON"}
        expected = list if op.operation.startswith("list_") else dict
        if not isinstance(body, dict) or not isinstance(body.get("data"), expected) or "error" in body or body.get("errors"):
            return {"status": "error", "error": "Pylon returned an unexpected response envelope"}
        result = {"status": "success", "data": body["data"], "request_id": body.get("request_id")}
        if op.operation.startswith("list_"):
            pagination = body.get("pagination")
            if pagination is not None and (not isinstance(pagination, dict)
                or type(pagination.get("has_next_page")) is not bool or not isinstance(pagination.get("cursor"), str)
                or (pagination["has_next_page"] and (not pagination["cursor"] or pagination["cursor"] == getattr(op, "cursor", None)))):
                return {"status": "error", "error": "Pylon returned invalid pagination"}
            more = bool(pagination and pagination["has_next_page"])
            result.update(has_more=more, next_page_cursor=pagination["cursor"] if more else None, complete=not more)
        if op.operation == "get_me":
            organization = body["data"]
            if not isinstance(organization, dict) or not organization.get("id") or not organization.get("name"):
                return {"status": "error", "error": "Pylon did not identify the organization"}
            result["name"] = organization["name"]
        return result

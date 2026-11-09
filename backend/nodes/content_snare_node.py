"""Content Snare Partner API v1: personal-token client and request automation.

Each action maps to one published API operation. Lists return one bounded page;
request builds may remain building, and write acknowledgements do not prove delivery.
Contract: https://api.contentsnare.com/partner_api/v1/doc_data.json
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.contentsnare.com/partner_api/v1"
CREDENTIAL = "content_snare_personal_token"


class ContentSnarePersonalToken(BaseModel):
    model_config = ConfigDict(title="Content Snare Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.contentsnare.com/settings/security/access-tokens",
            "x-credential-instructions": "In Content Snare, open Settings → Security → Personal access tokens and generate a token. Paste only the token, without Bearer. Select read_clients, write_clients, read_requests, write_requests, review_requests, read_templates, read_team_members for all these actions, or only the scopes you need. NoClick checks your name with /me. Tokens expire and must be rotated manually; rotation invalidates the old token."})
    credential_type: Literal["content_snare_personal_token"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without spaces or a Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    limit: int = Field(20, ge=1, le=200, description="Maximum results in this page. Follow next_offset to fetch another page.")
    offset: int = Field(0, ge=0, le=10000000)


class ClientFields(Input):
    email: str | None = Field(None, min_length=1)
    full_name: str | None = Field(None, min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    salutation: str | None = None
    language_code: Literal["en", "en-gb", "es", "fr", "de", "nl", "pt-br"] | None = None


class Assignment(Input):
    account_id: str = Field(..., min_length=1)
    client_company_id: str | None = None
    primary: bool | None = None


class RequestFields(Input):
    name: str | None = Field(None, min_length=1)
    due: str | None = Field(None, description="Due date as YYYY-MM-DD")
    folder_id: str | None = None
    owner_id: str | None = None
    communication_template_id: str | None = None
    comments_enabled: bool | None = None
    expires_after_due: bool | None = None
    passcode_enabled: bool | None = None
    share_via_link_enabled: bool | None = None

    @field_validator("due")
    @classmethod
    def due_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use YYYY-MM-DD")
        return value


class GetIdentity(Input):
    """Read the authenticated member name and token scopes without requiring an additional scope."""
    operation: Literal["get_identity"] = Field("get_identity", title="Get Identity", json_schema_extra={"ui:hidden": True})


class ListClients(Page):
    """List clients."""
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Search using the provider default fields")
    email: str | None = Field(None, description="Exact case-insensitive email filter")
    include_external: bool | None = None


class ListRequests(Page):
    """List requests."""
    operation: Literal["list_requests"] = Field("list_requests", title="List Requests", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Search using the provider default fields")
    statuses: list[Literal["draft", "published", "completed", "archived"]] | None = None


class ListClientCompanies(Page):
    """List client companies."""
    operation: Literal["list_client_companies"] = Field("list_client_companies", title="List Client Companies", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Search using the provider default fields")


class ListFolders(Page):
    """List folders."""
    operation: Literal["list_folders"] = Field("list_folders", title="List Folders", json_schema_extra={"ui:hidden": True})


class ListRequestTemplates(Page):
    """List request templates."""
    operation: Literal["list_request_templates"] = Field("list_request_templates", title="List Request Templates", json_schema_extra={"ui:hidden": True})
    source: Literal["company", "built_in", "shared"] | None = None


class ListPageTemplates(Page):
    """List page templates."""
    operation: Literal["list_page_templates"] = Field("list_page_templates", title="List Page Templates", json_schema_extra={"ui:hidden": True})
    source: Literal["company", "built_in", "shared"] | None = None


class ListSectionTemplates(Page):
    """List section templates."""
    operation: Literal["list_section_templates"] = Field("list_section_templates", title="List Section Templates", json_schema_extra={"ui:hidden": True})
    source: Literal["company", "built_in", "shared"] | None = None


class ListCommunicationTemplates(Page):
    """List communication templates."""
    operation: Literal["list_communication_templates"] = Field("list_communication_templates", title="List Communication Templates", json_schema_extra={"ui:hidden": True})
    source: Literal["company", "built_in", "shared"] | None = None


class ListTeamMembers(Page):
    """List team members."""
    operation: Literal["list_team_members"] = Field("list_team_members", title="List Team Members", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Search using the provider default fields")


class GetClient(Input):
    """Get client."""
    operation: Literal["get_client"] = Field("get_client", title="Get Client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")


class DeleteClient(Input):
    """Delete the selected client; success acknowledges deletion without verifying absence."""
    operation: Literal["delete_client"] = Field("delete_client", title="Delete Client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")


class CreateClient(ClientFields):
    """Create client."""
    operation: Literal["create_client"] = Field("create_client", title="Create Client", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    full_name: str = Field(..., min_length=1)


class UpdateClient(ClientFields):
    """Update client."""
    operation: Literal["update_client"] = Field("update_client", title="Update Client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")


class GetRequest(Input):
    """Get request."""
    operation: Literal["get_request"] = Field("get_request", title="Get Request", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")


class DeleteRequest(Input):
    """Delete the selected request; success acknowledges deletion without verifying absence."""
    operation: Literal["delete_request"] = Field("delete_request", title="Delete Request", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")


class CreateRequest(RequestFields):
    """Create a request for one existing client; inspect build_status and use Get Request later if still building."""
    operation: Literal["create_request"] = Field("create_request", title="Create Request", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1, description="Existing client ID; use Create Client first to add a client")
    request_template_id: str | None = None
    status: Literal["draft", "published"] = Field("draft", description="Publishing may notify assigned clients")


class UpdateRequest(RequestFields):
    """Update request."""
    operation: Literal["update_request"] = Field("update_request", title="Update Request", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., min_length=1, max_length=256, description="Content Snare resource ID")
    client_assignments: list[Assignment] | None = Field(None, min_length=1)
    instruction_text: str | None = None
    show_instruction: bool | None = None
    status: Literal["draft", "published", "completed", "archived"] | None = None


class ApproveRequestFields(Input):
    """Approve request fields."""
    operation: Literal["approve_request_fields"] = Field("approve_request_fields", title="Approve Request Fields", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., min_length=1, max_length=256)


class SubmitRequestFields(Input):
    """Submit request fields."""
    operation: Literal["submit_request_fields"] = Field("submit_request_fields", title="Submit Request Fields", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., min_length=1, max_length=256)


class ReviewField(Input):
    """Review field."""
    operation: Literal["review_field"] = Field("review_field", title="Review Field", json_schema_extra={"ui:hidden": True})
    field_id: str = Field(..., min_length=1, max_length=256)
    status: Literal["approved", "done", "redo", "todo"]
    rejection_comment: str | None = None


Operation = Annotated[Union[GetIdentity, ListClients, ListRequests, ListClientCompanies, ListFolders, ListRequestTemplates, ListPageTemplates, ListSectionTemplates, ListCommunicationTemplates, ListTeamMembers, GetClient, DeleteClient, CreateClient, UpdateClient, GetRequest, DeleteRequest, CreateRequest, UpdateRequest, ApproveRequestFields, SubmitRequestFields, ReviewField], Field(discriminator="operation")]


class ContentSnareConfig(NodeConfig[Operation, ContentSnarePersonalToken]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_identity': ('GET', '/me'), 'list_clients': ('GET', '/clients'), 'list_requests': ('GET', '/requests'), 'list_client_companies': ('GET', '/client_companies'), 'list_folders': ('GET', '/folders'), 'list_request_templates': ('GET', '/request_templates'), 'list_page_templates': ('GET', '/page_templates'), 'list_section_templates': ('GET', '/section_templates'), 'list_communication_templates': ('GET', '/communication_templates'), 'list_team_members': ('GET', '/team_members'), 'get_client': ('GET', '/clients/{id}'), 'delete_client': ('DELETE', '/clients/{id}'), 'create_client': ('POST', '/clients'), 'update_client': ('PUT', '/clients/{id}'), 'get_request': ('GET', '/requests/{id}'), 'delete_request': ('DELETE', '/requests/{id}'), 'create_request': ('POST', '/requests'), 'update_request': ('PUT', '/requests/{id}'), 'approve_request_fields': ('PUT', '/requests/{id}/approve_all_submitted_fields'), 'submit_request_fields': ('PUT', '/requests/{id}/submit_all_fields'), 'review_field': ('PUT', '/fields/{id}/review')}


class ContentSnareNode(WorkflowNode):
    integration_type = "automation-content-snare"
    connection_evidence = ConnectionEvidence(noun="Content Snare account", identity_operation="get_identity", identity_keys=("full_name",))

    @classmethod
    def get_config_model(cls):
        return ContentSnareConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", CREDENTIAL) != CREDENTIAL:
            raise ValueError("Choose a Content Snare personal access token")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Content Snare personal access token")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        if "{id}" in path:
            key = "client_id" if "/clients/" in path else "field_id" if "/fields/" in path else "request_id"
            path = path.replace("{id}", quote(values.pop(key), safe=""))
        for source, target in {"email": "filter_by[email]", "source": "filter_by[source]", "statuses": "filter_by[statuses][]"}.items():
            if method == "GET" and source in values:
                values[target] = values.pop(source)
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, **kwargs)
        except (httpx.HTTPError, SSRFError, OSError):
            raise ValueError("Content Snare request did not complete; inspect the account before retrying a write") from None
        if len(response.content) > 8000000:
            raise ValueError("Content Snare response exceeds the supported size")
        if response.status_code == 204 and method == "DELETE":
            return {"deleted": True, "http_status": 204, "absence_verified": False}
        if op.operation in {"approve_request_fields", "submit_request_fields"} and response.status_code == 200 and not response.content:
            return {"acknowledged": True, "http_status": 200}
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise ValueError(f"Content Snare returned an unexpected response (HTTP {response.status_code})") from None
        if response.status_code not in {200, 201} or not isinstance(payload, dict) or payload.get("errors"):
            detail = payload.get("errors") if isinstance(payload, dict) else None
            message = str(detail).replace(credential.access_token, "[redacted]")[:1000] if detail else "Request was not confirmed"
            raise ValueError(f"Content Snare HTTP {response.status_code}: {message}")
        if op.operation == "get_identity":
            if not isinstance(payload.get("full_name"), str) or not payload["full_name"].strip():
                raise ValueError("Content Snare identity response is missing the member name")
        elif op.operation.startswith("list_"):
            rows, page = payload.get("results"), payload.get("pagination")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows) or not isinstance(page, dict):
                raise ValueError("Content Snare list response is missing results or pagination")
            total = page.get("total_count")
            if type(total) is not int or total < 0:
                raise ValueError("Content Snare list response is missing total_count")
            payload["next_offset"] = op.offset + op.limit if op.offset + op.limit < total else None
        elif not isinstance(payload.get("id"), str):
            raise ValueError("Content Snare response is missing the resource ID")
        # Never return an accidentally echoed credential in provider data.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.access_token, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {redact(key): redact(item) for key, item in value.items()}
            return value
        return redact(payload)

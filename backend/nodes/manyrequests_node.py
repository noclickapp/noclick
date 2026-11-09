"""ManyRequests v1 tenant API. Each operation makes one documented request.

Contract: https://app.manyrequests.com/docs/v1/api.json (0.0.1).
List operations return one page, preserving the provider's links/meta; they do
not claim that a page is the full collection. Writes report API acknowledgments.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

TYPE = "manyrequests_api_token"
AUTH_DOCS = "https://help.manyrequests.com/en/articles/12749373-how-to-get-started-with-the-manyrequests-api"


def portal_origin(value):
    """Accept a portal domain or HTTPS origin, including custom portal domains."""
    if not isinstance(value, str):
        raise ValueError("Paste your ManyRequests portal domain")
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        p = urlsplit(value)
        host = p.hostname or ""
        if (p.scheme != "https" or p.username is not None or p.password is not None
                or p.port not in {None, 443} or p.path not in {"", "/"} or p.query or p.fragment
                or not host.isascii() or len(host) > 253 or "." not in host
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split("."))):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except ValueError:
        raise ValueError("Use the public HTTPS portal domain, without a path, query, or credentials") from None
    return "https://" + host.lower()


class ManyRequestsAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="ManyRequests API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Requires the ManyRequests Pro plan. In your portal, open Settings → Integrations → API → Create token. Paste the token and your portal domain below. Custom portal domains are supported."})
    credential_type: Literal["manyrequests_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    portal_url: str = Field(..., title="Portal domain", description="Your ManyRequests portal, for example youragency.manyrequests.com, or its custom domain.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False,
        description="Paste the token itself, without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})
    _portal = field_validator("portal_url", mode="before")(portal_origin)

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your API token")
        value = clean_secret(value, field_name="API token", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without spaces or an authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    per_page: int = Field(25, ge=1, le=100, description="Maximum records in this single page. Provider links and metadata are returned for pagination.")


class _RequestKey(_Input):
    request_key: str = Field(..., min_length=1, max_length=255, description="Request ID or slug.")

    @field_validator("request_key")
    @classmethod
    def key(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a request ID or slug, without a URL or path")
        return value


class _Name(_Input):
    name: str = Field(..., min_length=1, max_length=255)


class Owner(_Name):
    email: str = Field(..., min_length=3, max_length=255, json_schema_extra={"format": "email"})

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use an email address")
        return value


class ListClients(_List):
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    organization_id: str | None = None


class GetClient(_Input):
    operation: Literal["get_client"] = Field("get_client", title="Get Client", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)


class ListOrganizations(_List):
    operation: Literal["list_organizations"] = Field("list_organizations", title="List Organizations", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class GetOrganization(_Input):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"ui:hidden": True})
    organization_id: int = Field(..., ge=1)


class CreateOrganization(_Name):
    operation: Literal["create_organization"] = Field("create_organization", title="Create Organization", json_schema_extra={"ui:hidden": True})
    owner: Owner = Field(..., description="The owner may receive provider notifications.")


class UpdateOrganization(_Name):
    operation: Literal["update_organization"] = Field("update_organization", title="Update Organization", json_schema_extra={"ui:hidden": True})
    organization_id: int = Field(..., ge=1)


class ListRequests(_List):
    operation: Literal["list_requests"] = Field("list_requests", title="List Requests", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    client_id: str | None = None
    status_id: str | None = None


class GetRequest(_RequestKey):
    operation: Literal["get_request"] = Field("get_request", title="Get Request", json_schema_extra={"ui:hidden": True})


class CreateRequest(_Input):
    operation: Literal["create_request"] = Field("create_request", title="Create Request", json_schema_extra={"ui:hidden": True})
    service_id: int = Field(..., ge=1)
    client_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    status_id: int | None = Field(None, ge=1)
    due_date: datetime | None = None
    brand_id: int | None = Field(None, ge=1)
    assignee_ids: list[int] | None = None
    tag_ids: list[int] | None = None
    fields: list[str] | None = None


class DeleteRequest(_Input):
    operation: Literal["delete_request"] = Field("delete_request", title="Delete Request", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)


class ListComments(_RequestKey, _List):
    operation: Literal["list_comments"] = Field("list_comments", title="List Comments", json_schema_extra={"ui:hidden": True})


class CreateComment(_RequestKey):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=100000)
    user_id: int = Field(..., ge=1)
    is_internal: bool | None = Field(None, description="True limits visibility to the team; false is visible to the client. Omitted uses the provider default.")
    scheduled_at: datetime | None = None


class ListRequestStatuses(_List):
    operation: Literal["list_request_statuses"] = Field("list_request_statuses", title="List Request Statuses", json_schema_extra={"ui:hidden": True})


class CreateRequestStatus(_Name):
    operation: Literal["create_request_status"] = Field("create_request_status", title="Create Request Status", json_schema_extra={"ui:hidden": True})
    color: str = Field(..., min_length=1, max_length=255)
    position: float | None = None


class UpdateRequestStatus(_Input):
    operation: Literal["update_request_status"] = Field("update_request_status", title="Update Request Status", json_schema_extra={"ui:hidden": True})
    status_id: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=255)
    color: str | None = None
    position: float | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, field) is None for field in ("name", "color", "position")):
            raise ValueError("Supply a status field to change")
        return self


class ListRequestTags(_List):
    operation: Literal["list_request_tags"] = Field("list_request_tags", title="List Request Tags", json_schema_extra={"ui:hidden": True})
    name: str | None = None


class CreateRequestTag(_Name):
    operation: Literal["create_request_tag"] = Field("create_request_tag", title="Create Request Tag", json_schema_extra={"ui:hidden": True})


class ListServices(_List):
    operation: Literal["list_services"] = Field("list_services", title="List Services", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    is_for_sale: bool | None = None


class GetService(_Input):
    operation: Literal["get_service"] = Field("get_service", title="Get Service", json_schema_extra={"ui:hidden": True})
    service_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]+$", max_length=255)


class ListFormFields(_Input):
    operation: Literal["list_form_fields"] = Field("list_form_fields", title="List Form Fields", json_schema_extra={"ui:hidden": True})
    service_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]+$", max_length=255)


class ListTeamMembers(_List):
    operation: Literal["list_team_members"] = Field("list_team_members", title="List Team Members", json_schema_extra={"ui:hidden": True})
    email: str | None = None
    role: Literal["portal admin", "admin", "team"] | None = None


class ListTimeEntries(_RequestKey, _List):
    operation: Literal["list_time_entries"] = Field("list_time_entries", title="List Time Entries", json_schema_extra={"ui:hidden": True})
    user_id: str | None = None
    description: str | None = None


class CreateTimeEntry(_Input):
    operation: Literal["create_time_entry"] = Field("create_time_entry", title="Create Time Entry", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    started_at: datetime
    ended_at: datetime
    description: str | None = Field(None, max_length=255)
    billable: bool | None = Field(None, description="Billable hours may reduce the organization balance after approval.")

    @model_validator(mode="after")
    def ordered(self):
        try:
            if self.ended_at < self.started_at:
                raise ValueError("End must not precede start")
        except TypeError:
            raise ValueError("Start and end must both use the same timezone convention") from None
        return self


class ListInvoices(_List):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices", json_schema_extra={"ui:hidden": True})


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., ge=1)


Operation = Annotated[Union[ListClients, GetClient, ListOrganizations, GetOrganization, CreateOrganization, UpdateOrganization, ListRequests, GetRequest, CreateRequest, DeleteRequest, ListComments, CreateComment, ListRequestStatuses, CreateRequestStatus, UpdateRequestStatus, ListRequestTags, CreateRequestTag, ListServices, GetService, ListFormFields, ListTeamMembers, ListTimeEntries, CreateTimeEntry, ListInvoices, GetInvoice], Field(discriminator="operation")]


class ManyRequestsConfig(NodeConfig[Operation, ManyRequestsAPITokenCredential]):
    pass


ROUTES = {'list_clients': ('GET',
                  '/clients',
                  {'search': 'filter[search]', 'organization_id': 'filter[organization_id]'}),
 'get_client': ('GET', '/clients/{client_id}', {}),
 'list_organizations': ('GET', '/organizations', {'search': 'filter[search]'}),
 'get_organization': ('GET', '/organizations/{organization_id}', {}),
 'create_organization': ('POST', '/organizations', {}),
 'update_organization': ('PATCH', '/organizations/{organization_id}', {}),
 'list_requests': ('GET',
                   '/requests',
                   {'search': 'filter[search]',
                    'priority': 'filter[priority]',
                    'client_id': 'filter[client_id]',
                    'status_id': 'filter[status_id]'}),
 'get_request': ('GET', '/requests/{request_key}', {}),
 'create_request': ('POST', '/requests', {}),
 'delete_request': ('DELETE', '/requests/{request_id}', {}),
 'list_comments': ('GET', '/requests/{request_key}/comments', {}),
 'create_comment': ('POST', '/requests/{request_key}/comments', {}),
 'list_request_statuses': ('GET', '/request-statuses', {}),
 'create_request_status': ('POST', '/request-statuses', {}),
 'update_request_status': ('PATCH', '/request-statuses/{status_id}', {}),
 'list_request_tags': ('GET', '/request-tags', {'name': 'filter[name]'}),
 'create_request_tag': ('POST', '/request-tags', {}),
 'list_services': ('GET',
                   '/services',
                   {'search': 'filter[search]', 'is_for_sale': 'filter[is_for_sale]'}),
 'get_service': ('GET', '/services/{service_id}', {}),
 'list_form_fields': ('GET', '/services/{service_id}/form-fields', {}),
 'list_team_members': ('GET', '/team-members', {'email': 'filter[email]', 'role': 'filter[role]'}),
 'list_time_entries': ('GET',
                       '/requests/{request_key}/time-entries',
                       {'user_id': 'filter[user_id]', 'description': 'filter[description]'}),
 'create_time_entry': ('POST', '/requests/{request_id}/time-entries', {}),
 'list_invoices': ('GET', '/invoices', {}),
 'get_invoice': ('GET', '/invoices/{invoice_id}', {})}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class ManyRequestsNode(WorkflowNode):
    integration_type = "automation-manyrequests"
    connection_evidence = ConnectionEvidence(noun="clients", operation="list_clients", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return ManyRequestsConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a ManyRequests API token and portal domain")
        credential = self.config.credentials
        op = self.config.config
        method, template, filters = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path_fields = set(re.findall(r"\{(\w+)\}", template))
        route = template.format(**values)
        params = {}
        if isinstance(op, _List):
            params["per_page"] = op.per_page
        for name, wire in filters.items():
            if name in values:
                value = values[name]
                params[wire] = str(value).lower() if isinstance(value, bool) else value
        body = None
        if method in {"POST", "PATCH"}:
            body = {key: value for key, value in values.items() if key not in path_fields | {"operation"}}
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/vnd.api+json"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.portal_url + "/api/v1" + route,
                headers=headers, params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            message = "ManyRequests request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    if isinstance(payload.get("message"), str):
                        message = payload["message"][:2000]
                    elif isinstance(payload.get("errors"), list):
                        message = "; ".join(str(err.get("detail", "")) for err in payload["errors"] if isinstance(err, dict))[:2000] or message
            except ValueError:
                pass
            raise ValueError(_redact(f"ManyRequests HTTP {response.status_code}: {message}", credential.api_token))
        expected = 204 if method == "DELETE" else 201 if method == "POST" and op.operation not in {"create_request_status", "create_request_tag"} else 200
        if response.status_code != expected:
            raise ValueError("ManyRequests did not return the documented completion status; inspect before retrying a write")
        if expected == 204:
            return {"success": True, "operation": op.operation, "http_status": 204, "deletion_acknowledged": True}
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media not in {"application/json", "application/vnd.api+json"} or len(response.content) > 5_000_000:
            raise ValueError("Expected a bounded JSON response from ManyRequests")
        payload = response.json()
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload or "data" not in payload:
            raise ValueError("ManyRequests returned an invalid or error response")
        result = {"success": True, "operation": op.operation, "http_status": response.status_code, **payload}
        rows = payload["data"]
        if isinstance(op, _List) or op.operation == "list_form_fields":
            if not isinstance(rows, list):
                raise ValueError("ManyRequests list response has no data array")
            # Flatten a separate items view for connection evidence; keep JSON:API data intact.
            result["items"] = [{**row.get("attributes", {}), "id": row["id"], "type": row["type"]} for row in rows]
            if isinstance(op, _List):
                result["page_only"] = True
        elif not isinstance(rows, dict):
            raise ValueError("ManyRequests resource response has no data object")
        if method in {"POST", "PATCH"}:
            result["write_acknowledged"] = True
        return _redact(result, credential.api_token)

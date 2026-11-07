"""Jira Service Management Cloud: requests, customers, queues and SLAs.

Official contract: https://developer.atlassian.com/cloud/jira/service-desk/swagger.v3.json
Authentication: Atlassian account email + unscoped API token via HTTP Basic.
Use the site's own HTTPS *.atlassian.net origin. API permissions are those of
that user; customer management and queues can require agent/admin permissions.
Lists return one page and preserve start/limit/isLastPage/_links for pagination.
Jira webhooks are configured separately; this node exposes REST operations only.
"""
from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import https_origin


class JiraServiceManagementAPITokenCredential(BaseModel):
    credential_type: Literal["jiraservicemanagement_api_token"] = Field(
        "jiraservicemanagement_api_token", json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="Site URL", description="Your Jira Cloud site, for example https://your-team.atlassian.net")
    email: str = Field(..., min_length=3, title="Atlassian Account Email", description="Email of the Atlassian account that created the API token")
    api_token: str = Field(..., min_length=1, title="API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Jira Service Management API Token", json_schema_extra={
        "x-credential-url": "https://id.atlassian.com/manage-profile/security/api-tokens",
        "x-credential-instructions": "Create an API token without scopes in your Atlassian account security settings. Paste the token, the account email and your Jira Cloud site URL. The token inherits your account permissions.",
    })

    @field_validator("site_url")
    @classmethod
    def normalize_site(cls, value: str) -> str:
        origin = https_origin(value, field_name="Site URL")
        if not re.fullmatch(r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.atlassian\.net", origin):
            raise ValueError("Site URL must be your HTTPS Jira Cloud site at <site>.atlassian.net")
        return origin

    @field_validator("email")
    @classmethod
    def account_email(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[^\s:@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter the email of the Atlassian account that created the token")
        return value


class _Page(BaseModel):
    start: int = Field(0, ge=0, title="Start", description="Zero-based offset; use the returned next-page link to continue")
    limit: int = Field(50, ge=1, le=100, title="Limit", description="Page size; Jira may return fewer items")


class _Desk(BaseModel):
    service_desk_id: str = Field(..., min_length=1, title="Service Desk", json_schema_extra={
        "x-dynamic-options": {"field_name": "service_desk_id", "searchable": True,
                              "allow_custom": True, "placeholder": "Select a service desk..."}})


class _DeskPage(_Desk, _Page):
    pass


class _Request(BaseModel):
    issue_id_or_key: str = Field(..., min_length=1, title="Request ID or Key", description="For example HELPDESK-1")


class _RequestPage(_Request, _Page):
    pass


class JiraServiceManagementListServiceDesksConfig(_Page):
    """GET /rest/servicedeskapi/servicedesk."""
    operation: Literal["list_service_desks"] = Field("list_service_desks", title="List Service Desks",
        json_schema_extra={"const": "list_service_desks", "ui:hidden": True, "x-category": "Service Desks", "x-display-name": "List Service Desks", "x-is-trigger": False})


class JiraServiceManagementGetServiceDeskConfig(_Desk):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}."""
    operation: Literal["get_service_desk"] = Field("get_service_desk", title="Get Service Desk",
        json_schema_extra={"const": "get_service_desk", "ui:hidden": True, "x-category": "Service Desks", "x-display-name": "Get Service Desk", "x-is-trigger": False})


class JiraServiceManagementListRequestTypesConfig(_DeskPage):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}/requesttype."""
    operation: Literal["list_request_types"] = Field("list_request_types", title="List Request Types",
        json_schema_extra={"const": "list_request_types", "ui:hidden": True, "x-category": "Service Desks", "x-display-name": "List Request Types", "x-is-trigger": False})


class JiraServiceManagementGetRequestTypeFieldsConfig(_Desk):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}/requesttype/{request_type_id}/field."""
    operation: Literal["get_request_type_fields"] = Field("get_request_type_fields", title="Get Request Type Fields",
        json_schema_extra={"const": "get_request_type_fields", "ui:hidden": True, "x-category": "Service Desks", "x-display-name": "Get Request Type Fields", "x-is-trigger": False})
    request_type_id: int = Field(..., title="Request Type ID", ge=1)


class JiraServiceManagementListRequestsConfig(_Page):
    """GET /rest/servicedeskapi/request."""
    operation: Literal["list_requests"] = Field("list_requests", title="List Requests",
        json_schema_extra={"const": "list_requests", "ui:hidden": True, "x-category": "Requests", "x-display-name": "List Requests", "x-is-trigger": False})
    search_term: Optional[str] = Field(None, title="Search Term")
    service_desk_id: Optional[int] = Field(None, title="Service Desk ID")
    request_status: Optional[Literal["OPEN_REQUESTS", "CLOSED_REQUESTS", "ALL_REQUESTS"]] = Field(None, title="Request Status")


class JiraServiceManagementGetRequestConfig(_Request):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}."""
    operation: Literal["get_request"] = Field("get_request", title="Get Request",
        json_schema_extra={"const": "get_request", "ui:hidden": True, "x-category": "Requests", "x-display-name": "Get Request", "x-is-trigger": False})


class JiraServiceManagementCreateRequestConfig(_Desk):
    """POST /rest/servicedeskapi/request."""
    operation: Literal["create_request"] = Field("create_request", title="Create Request",
        json_schema_extra={"const": "create_request", "ui:hidden": True, "x-category": "Requests", "x-display-name": "Create Request", "x-is-trigger": False})
    request_type_id: str = Field(..., title="Request Type ID", min_length=1)
    summary: str = Field(..., title="Summary", min_length=1)
    description: Optional[str] = Field(None, title="Description")
    request_field_values: Optional[str] = Field(None, title="Additional Request Fields (JSON)", description="JSON object mapping custom Jira field IDs to values. Summary and description are set above.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    raise_on_behalf_of: Optional[str] = Field(None, title="Raise on Behalf of Account ID")

    @field_validator("request_field_values")
    @classmethod
    def json_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not isinstance(json.loads(value), dict):
            raise ValueError("Additional Request Fields must be a JSON object")
        return value



class JiraServiceManagementListCommentsConfig(_RequestPage):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}/comment."""
    operation: Literal["list_comments"] = Field("list_comments", title="List Comments",
        json_schema_extra={"const": "list_comments", "ui:hidden": True, "x-category": "Requests", "x-display-name": "List Comments", "x-is-trigger": False})


class JiraServiceManagementAddCommentConfig(_Request):
    """POST /rest/servicedeskapi/request/{issue_id_or_key}/comment."""
    operation: Literal["add_comment"] = Field("add_comment", title="Add Comment",
        json_schema_extra={"const": "add_comment", "ui:hidden": True, "x-category": "Requests", "x-display-name": "Add Comment", "x-is-trigger": False})
    body: str = Field(..., title="Comment", min_length=1)
    public: bool = Field(True, title="Public Comment")


class JiraServiceManagementListParticipantsConfig(_RequestPage):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}/participant."""
    operation: Literal["list_participants"] = Field("list_participants", title="List Participants",
        json_schema_extra={"const": "list_participants", "ui:hidden": True, "x-category": "Requests", "x-display-name": "List Participants", "x-is-trigger": False})


class JiraServiceManagementAddParticipantsConfig(_Request):
    """POST /rest/servicedeskapi/request/{issue_id_or_key}/participant."""
    operation: Literal["add_participants"] = Field("add_participants", title="Add Participants",
        json_schema_extra={"const": "add_participants", "ui:hidden": True, "x-category": "Requests", "x-display-name": "Add Participants", "x-is-trigger": False})
    account_ids: str = Field(..., title="Account IDs", min_length=1, description="Comma-separated Atlassian account IDs (not usernames)")


class JiraServiceManagementListTransitionsConfig(_RequestPage):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}/transition."""
    operation: Literal["list_transitions"] = Field("list_transitions", title="List Transitions",
        json_schema_extra={"const": "list_transitions", "ui:hidden": True, "x-category": "Requests", "x-display-name": "List Transitions", "x-is-trigger": False})


class JiraServiceManagementTransitionRequestConfig(_Request):
    """POST /rest/servicedeskapi/request/{issue_id_or_key}/transition."""
    operation: Literal["transition_request"] = Field("transition_request", title="Transition Request",
        json_schema_extra={"const": "transition_request", "ui:hidden": True, "x-category": "Requests", "x-display-name": "Transition Request", "x-is-trigger": False})
    transition_id: str = Field(..., title="Transition ID", min_length=1)
    additional_comment: Optional[str] = Field(None, title="Additional Comment")


class JiraServiceManagementListSlasConfig(_RequestPage):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}/sla."""
    operation: Literal["list_slas"] = Field("list_slas", title="List SLAs",
        json_schema_extra={"const": "list_slas", "ui:hidden": True, "x-category": "SLAs", "x-display-name": "List SLAs", "x-is-trigger": False})


class JiraServiceManagementGetSlaConfig(_Request):
    """GET /rest/servicedeskapi/request/{issue_id_or_key}/sla/{sla_metric_id}."""
    operation: Literal["get_sla"] = Field("get_sla", title="Get SLA",
        json_schema_extra={"const": "get_sla", "ui:hidden": True, "x-category": "SLAs", "x-display-name": "Get SLA", "x-is-trigger": False})
    sla_metric_id: int = Field(..., title="SLA Metric ID", ge=1)


class JiraServiceManagementListCustomersConfig(_DeskPage):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}/customer."""
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers",
        json_schema_extra={"const": "list_customers", "ui:hidden": True, "x-category": "Customers", "x-display-name": "List Customers", "x-is-trigger": False})
    query: Optional[str] = Field(None, title="Customer Search")


class JiraServiceManagementCreateCustomerConfig(BaseModel):
    """POST /rest/servicedeskapi/customer."""
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer",
        json_schema_extra={"const": "create_customer", "ui:hidden": True, "x-category": "Customers", "x-display-name": "Create Customer", "x-is-trigger": False})
    email: str = Field(..., title="Customer Email", min_length=1)
    display_name: str = Field(..., title="Display Name", min_length=1)


class JiraServiceManagementAddCustomersConfig(_Desk):
    """POST /rest/servicedeskapi/servicedesk/{service_desk_id}/customer."""
    operation: Literal["add_customers"] = Field("add_customers", title="Add Customers",
        json_schema_extra={"const": "add_customers", "ui:hidden": True, "x-category": "Customers", "x-display-name": "Add Customers", "x-is-trigger": False})
    account_ids: str = Field(..., title="Account IDs", min_length=1, description="Comma-separated Atlassian account IDs (not usernames)")


class JiraServiceManagementListQueuesConfig(_DeskPage):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}/queue."""
    operation: Literal["list_queues"] = Field("list_queues", title="List Queues",
        json_schema_extra={"const": "list_queues", "ui:hidden": True, "x-category": "Queues", "x-display-name": "List Queues", "x-is-trigger": False})
    include_count: bool = Field(False, title="Include Issue Count")


class JiraServiceManagementListQueueIssuesConfig(_DeskPage):
    """GET /rest/servicedeskapi/servicedesk/{service_desk_id}/queue/{queue_id}/issue."""
    operation: Literal["list_queue_issues"] = Field("list_queue_issues", title="List Queue Issues",
        json_schema_extra={"const": "list_queue_issues", "ui:hidden": True, "x-category": "Queues", "x-display-name": "List Queue Issues", "x-is-trigger": False})
    queue_id: int = Field(..., title="Queue ID", ge=1)


JiraServiceManagementConfig = Annotated[Union[
    JiraServiceManagementListServiceDesksConfig,
    JiraServiceManagementGetServiceDeskConfig,
    JiraServiceManagementListRequestTypesConfig,
    JiraServiceManagementGetRequestTypeFieldsConfig,
    JiraServiceManagementListRequestsConfig,
    JiraServiceManagementGetRequestConfig,
    JiraServiceManagementCreateRequestConfig,
    JiraServiceManagementListCommentsConfig,
    JiraServiceManagementAddCommentConfig,
    JiraServiceManagementListParticipantsConfig,
    JiraServiceManagementAddParticipantsConfig,
    JiraServiceManagementListTransitionsConfig,
    JiraServiceManagementTransitionRequestConfig,
    JiraServiceManagementListSlasConfig,
    JiraServiceManagementGetSlaConfig,
    JiraServiceManagementListCustomersConfig,
    JiraServiceManagementCreateCustomerConfig,
    JiraServiceManagementAddCustomersConfig,
    JiraServiceManagementListQueuesConfig,
    JiraServiceManagementListQueueIssuesConfig,
], Discriminator("operation")]


class JiraServiceManagementNodeConfig(NodeConfig[JiraServiceManagementConfig, JiraServiceManagementAPITokenCredential]):
    model_config = ConfigDict(title="Jira Service Management Node Configuration")


# Each entry maps to exactly one operation in Atlassian's published contract.
OPERATIONS = {'list_service_desks': ('GET', '/servicedesk'), 'get_service_desk': ('GET', '/servicedesk/{service_desk_id}'), 'list_request_types': ('GET', '/servicedesk/{service_desk_id}/requesttype'), 'get_request_type_fields': ('GET', '/servicedesk/{service_desk_id}/requesttype/{request_type_id}/field'), 'list_requests': ('GET', '/request'), 'get_request': ('GET', '/request/{issue_id_or_key}'), 'create_request': ('POST', '/request'), 'list_comments': ('GET', '/request/{issue_id_or_key}/comment'), 'add_comment': ('POST', '/request/{issue_id_or_key}/comment'), 'list_participants': ('GET', '/request/{issue_id_or_key}/participant'), 'add_participants': ('POST', '/request/{issue_id_or_key}/participant'), 'list_transitions': ('GET', '/request/{issue_id_or_key}/transition'), 'transition_request': ('POST', '/request/{issue_id_or_key}/transition'), 'list_slas': ('GET', '/request/{issue_id_or_key}/sla'), 'get_sla': ('GET', '/request/{issue_id_or_key}/sla/{sla_metric_id}'), 'list_customers': ('GET', '/servicedesk/{service_desk_id}/customer'), 'create_customer': ('POST', '/customer'), 'add_customers': ('POST', '/servicedesk/{service_desk_id}/customer'), 'list_queues': ('GET', '/servicedesk/{service_desk_id}/queue'), 'list_queue_issues': ('GET', '/servicedesk/{service_desk_id}/queue/{queue_id}/issue')}


_QUERY_NAMES = {"search_term": "searchTerm", "request_status": "requestStatus",
                "service_desk_id": "serviceDeskId", "include_count": "includeCount"}


def _account_ids(value: str) -> list[str]:
    ids = [item.strip() for item in value.split(",") if item.strip()]
    if not ids:
        raise ValueError("Provide at least one Atlassian account ID")
    return ids


async def _request(credential: JiraServiceManagementAPITokenCredential, operation: str,
                   values: Dict[str, Any]) -> Dict[str, Any]:
    method, route = OPERATIONS[operation]
    path_fields = re.findall(r"\{([^}]+)\}", route)
    for field in path_fields:
        route = route.replace("{" + field + "}", quote(str(values[field]), safe=""))
    params = {}
    if method == "GET":
        params = {_QUERY_NAMES.get(k, k): (str(v).lower() if isinstance(v, bool) else v)
                  for k, v in values.items()
                  if k not in path_fields and k != "operation" and v is not None}
    body = None
    if operation == "create_request":
        fields = json.loads(values["request_field_values"]) if values.get("request_field_values") else {}
        if not isinstance(fields, dict):
            raise ValueError("Additional Request Fields must be a JSON object")
        fields["summary"] = values["summary"]
        if values.get("description") is not None:
            fields["description"] = values["description"]
        body = {"serviceDeskId": values["service_desk_id"], "requestTypeId": values["request_type_id"],
                "requestFieldValues": fields}
        if values.get("raise_on_behalf_of"):
            body["raiseOnBehalfOf"] = values["raise_on_behalf_of"]
    elif operation == "add_comment":
        body = {"body": values["body"], "public": values["public"]}
    elif operation in ("add_participants", "add_customers"):
        body = {"accountIds": _account_ids(values["account_ids"])}
    elif operation == "transition_request":
        body = {"id": values["transition_id"]}
        if values.get("additional_comment"):
            body["additionalComment"] = {"body": values["additional_comment"]}
    elif operation == "create_customer":
        body = {"email": values["email"], "displayName": values["display_name"]}
    started = time.perf_counter()
    def result(status: str, **kwargs: Any) -> Dict[str, Any]:
        return {"status": status, "action": operation, **kwargs,
                "timing_ms": {"api_request": round((time.perf_counter() - started) * 1000, 2)}}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(method, credential.site_url + "/rest/servicedeskapi" + route,
                auth=httpx.BasicAuth(credential.email, credential.api_token),
                headers={"Accept": "application/json"}, params=params, json=body)
        if not 200 <= response.status_code < 300:
            # Never expose response bodies or exception text: they can echo credentials.
            return result("error", status_code=response.status_code,
                          error=f"Jira Service Management API returned HTTP {response.status_code}")
        if response.status_code == 204:
            data: Any = {"success": True}
        else:
            try:
                data = response.json()
            except ValueError:
                return result("error", status_code=response.status_code, error="Jira Service Management returned invalid JSON")
            if (not isinstance(data, dict) or not data or "errorMessages" in data or "errors" in data
                    or "errorMessage" in data or data.get("success") is False):
                return result("error", status_code=response.status_code, error="Jira Service Management returned an unexpected response")
            if operation.startswith("list_") or operation == "add_participants":
                if not isinstance(data.get("values"), list) or any(not isinstance(row, dict) for row in data["values"]):
                    return result("error", status_code=response.status_code, error="Jira Service Management returned an invalid page")
            if operation == "list_service_desks" and any(
                not row.get("id") or not isinstance(row.get("projectName"), str) or not row["projectName"].strip()
                for row in data["values"]
            ):
                return result("error", status_code=response.status_code, error="Jira Service Management returned invalid service desks")
        return result("success", status_code=response.status_code, data=data)
    except httpx.TimeoutException:
        return result("error", status_code=408, error="Jira Service Management request timed out")
    except httpx.RequestError:
        return result("error", error="Could not reach Jira Service Management")


class JiraServiceManagementNode(WorkflowNode):
    integration_type = "automation-jiraservicemanagement"
    connection_evidence = ConnectionEvidence(field="service_desk_id", noun="service desks")
    edit_examples = ["Create a service request for a new laptop", "List requests waiting in a service desk queue",
                     "Check a request's SLA", "Add an internal comment to a request"]

    @classmethod
    def get_config_model(cls):
        return JiraServiceManagementNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Optional[Dict[str, Any]],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None, search: Optional[str] = None) -> Dict[str, Any]:
        if field_name != "service_desk_id":
            return {"options": []}
        credential = JiraServiceManagementAPITokenCredential.model_validate(credential_data or {})
        start = int(page_token or 0)
        response = await _request(credential, "list_service_desks", {"start": start, "limit": 50})
        if response["status"] != "success":
            return response
        data = response["data"]
        options = [{"value": str(row["id"]), "label": row["projectName"]}
                   for row in data["values"] if row.get("id") is not None and row.get("projectName")]
        if search:
            options = [o for o in options if search.casefold() in o["label"].casefold()]
        next_page = str(data.get("start", start) + data.get("limit", 50)) if data.get("isLastPage") is False else None
        return {"options": options, "next_page_token": next_page}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, JiraServiceManagementNodeConfig):
            raise ValueError("Jira Service Management configuration is required")
        if not self.config.credentials:
            raise ValueError("Connect your Jira Service Management account first")
        config = self.config.config
        return await _request(self.config.credentials, config.operation, config.model_dump(exclude_none=True))

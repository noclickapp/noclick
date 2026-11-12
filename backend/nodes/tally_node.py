"""Tally form, submission, analytics, workspace, and webhook workflow node.

Endpoint contract: https://developers.tally.so/api-reference/openapi.json
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.tally.so"
API_VERSION = "2025-02-01"


class TallyApiKeyCredential(BaseModel):
    credential_type: Literal["tally_api_key"] = Field(
        "tally_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(
        title="Tally API Key",
        json_schema_extra={"x-credential-url": "https://tally.so/settings/api-keys"}
    )


# Tally's own MCP server: agents get its tools through a person's Tally sign-in.
TallyMcpCredential = mcp_credential("tally", "https://api.tally.so/mcp", app="Tally")
TallyCredential = Union[TallyApiKeyCredential, TallyMcpCredential]


def _op(name: str, category: str, title: str):
    return Field(
        name,
        title=title,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": title,
            "x-is-trigger": False,
        },
    )


class ListFormsConfig(BaseModel):
    operation: Literal["list_forms"] = _op("list_forms", "Forms", "List Forms")
    page: Optional[int] = Field(None, title="page")
    limit: Optional[int] = Field(None, title="limit")
    workspace_ids_json: Optional[str] = Field(
        None,
        title="workspaceIds JSON Array",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class CreateFormConfig(BaseModel):
    operation: Literal["create_form"] = _op("create_form", "Forms", "Create Form")
    body_json: str = Field(
        ...,
        min_length=2,
        title="Request Body JSON",
        description="JSON object matching the Tally API request body for this action",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class GetFormConfig(BaseModel):
    operation: Literal["get_form"] = _op("get_form", "Forms", "Get Form")
    form_id: str = Field(..., min_length=1, title="Form Id")


class UpdateFormConfig(BaseModel):
    operation: Literal["update_form"] = _op("update_form", "Forms", "Update Form")
    form_id: str = Field(..., min_length=1, title="Form Id")
    body_json: str = Field(
        ...,
        min_length=2,
        title="Request Body JSON",
        description="JSON object matching the Tally API request body for this action",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class DeleteFormConfig(BaseModel):
    operation: Literal["delete_form"] = _op("delete_form", "Forms", "Delete Form")
    form_id: str = Field(..., min_length=1, title="Form Id")


class GetCurrentUserConfig(BaseModel):
    operation: Literal["get_current_user"] = _op(
        "get_current_user", "Account", "Current User"
    )
    timezone: Optional[str] = Field(None, title="timezone")


class ListWorkspacesConfig(BaseModel):
    operation: Literal["list_workspaces"] = _op(
        "list_workspaces", "Workspaces", "List Workspaces"
    )
    page: Optional[int] = Field(None, title="page")


class CreateWorkspaceConfig(BaseModel):
    operation: Literal["create_workspace"] = _op(
        "create_workspace", "Workspaces", "Create Workspace"
    )
    name: str = Field(..., title="Workspace Name")


class GetWorkspaceConfig(BaseModel):
    operation: Literal["get_workspace"] = _op(
        "get_workspace", "Workspaces", "Get Workspace"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")


class UpdateWorkspaceConfig(BaseModel):
    operation: Literal["update_workspace"] = _op(
        "update_workspace", "Workspaces", "Update Workspace"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")
    name: str = Field(..., title="Workspace Name")


class DeleteWorkspaceConfig(BaseModel):
    operation: Literal["delete_workspace"] = _op(
        "delete_workspace", "Workspaces", "Delete Workspace"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")


class ListFoldersConfig(BaseModel):
    operation: Literal["list_folders"] = _op("list_folders", "Folders", "List Folders")
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")


class CreateFolderConfig(BaseModel):
    operation: Literal["create_folder"] = _op(
        "create_folder", "Folders", "Create Folder"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")
    name: str = Field(..., title="Folder Name")
    parent_id: Optional[str] = Field(None, title="Parent Folder ID")


class UpdateFolderConfig(BaseModel):
    operation: Literal["update_folder"] = _op(
        "update_folder", "Folders", "Update Folder"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")
    id: str = Field(..., min_length=1, title="Folder ID")
    name: str = Field(..., title="Folder Name")


class DeleteFolderConfig(BaseModel):
    operation: Literal["delete_folder"] = _op(
        "delete_folder", "Folders", "Delete Folder"
    )
    workspace_id: str = Field(..., min_length=1, title="Workspace Id")
    id: str = Field(..., min_length=1, title="Folder ID")


class ListOrganizationUsersConfig(BaseModel):
    operation: Literal["list_organization_users"] = _op(
        "list_organization_users", "Organization", "List Organization Users"
    )
    organization_id: str = Field(..., min_length=1, title="Organization Id")


class RemoveOrganizationUserConfig(BaseModel):
    operation: Literal["remove_organization_user"] = _op(
        "remove_organization_user", "Organization", "Remove Organization User"
    )
    organization_id: str = Field(..., min_length=1, title="Organization Id")
    user_id: str = Field(..., min_length=1, title="User Id")


class ListOrganizationInvitesConfig(BaseModel):
    operation: Literal["list_organization_invites"] = _op(
        "list_organization_invites", "Organization", "List Organization Invites"
    )
    organization_id: str = Field(..., min_length=1, title="Organization Id")


class CreateOrganizationInvitesConfig(BaseModel):
    operation: Literal["create_organization_invites"] = _op(
        "create_organization_invites", "Organization", "Create Organization Invites"
    )
    organization_id: str = Field(..., min_length=1, title="Organization Id")
    workspace_ids: list[str] = Field(..., title="Workspace IDs")
    emails: str = Field(
        ..., title="Email Addresses",
        description="Comma or semicolon separated email addresses to invite",
    )


class CancelOrganizationInviteConfig(BaseModel):
    operation: Literal["cancel_organization_invite"] = _op(
        "cancel_organization_invite", "Organization", "Cancel Organization Invite"
    )
    organization_id: str = Field(..., min_length=1, title="Organization Id")
    invite_id: str = Field(..., min_length=1, title="Invite Id")


class ListFormQuestionsConfig(BaseModel):
    operation: Literal["list_form_questions"] = _op(
        "list_form_questions", "Forms", "List Form Questions"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")


class UpdateFormQuestionConfig(BaseModel):
    operation: Literal["update_form_question"] = _op(
        "update_form_question", "Forms", "Update Form Question"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    question_id: str = Field(..., min_length=1, title="Question Id")
    body_json: str = Field(
        ...,
        min_length=2,
        title="Request Body JSON",
        description="JSON object matching the Tally API request body for this action",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class ListFormBlocksConfig(BaseModel):
    operation: Literal["list_form_blocks"] = _op(
        "list_form_blocks", "Forms", "List Form Blocks"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")


class UpdateFormBlocksConfig(BaseModel):
    operation: Literal["update_form_blocks"] = _op(
        "update_form_blocks", "Forms", "Update Form Blocks"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    body_json: str = Field(
        ...,
        min_length=2,
        title="Request Body JSON",
        description="JSON object matching the Tally API request body for this action",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class ListSubmissionsConfig(BaseModel):
    operation: Literal["list_submissions"] = _op(
        "list_submissions", "Submissions", "List Submissions"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    page: Optional[int] = Field(None, title="page")
    filter: Optional[str] = Field(None, title="filter")
    start_date: Optional[str] = Field(None, title="startDate")
    end_date: Optional[str] = Field(None, title="endDate")
    after_id: Optional[str] = Field(None, title="afterId")
    limit: Optional[int] = Field(None, title="limit")


class GetSubmissionConfig(BaseModel):
    operation: Literal["get_submission"] = _op(
        "get_submission", "Submissions", "Get Submission"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    submission_id: str = Field(..., min_length=1, title="Submission Id")


class DeleteSubmissionConfig(BaseModel):
    operation: Literal["delete_submission"] = _op(
        "delete_submission", "Submissions", "Delete Submission"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    submission_id: str = Field(..., min_length=1, title="Submission Id")


class GetFormMetricsConfig(BaseModel):
    operation: Literal["get_form_metrics"] = _op(
        "get_form_metrics", "Analytics", "Get Form Metrics"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    period: Literal[
        "today", "yesterday", "24h", "7d", "30d", "3m", "6m", "12m", "all"
    ] = Field(..., title="Period")


class GetFormVisitsConfig(BaseModel):
    operation: Literal["get_form_visits"] = _op(
        "get_form_visits", "Analytics", "Get Form Visits"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    period: Literal[
        "today", "yesterday", "24h", "7d", "30d", "3m", "6m", "12m", "all"
    ] = Field(..., title="Period")


class GetFormSubmissionAnalyticsConfig(BaseModel):
    operation: Literal["get_form_submission_analytics"] = _op(
        "get_form_submission_analytics", "Analytics", "Get Form Submission Analytics"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    period: Literal[
        "today", "yesterday", "24h", "7d", "30d", "3m", "6m", "12m", "all"
    ] = Field(..., title="Period")


class GetFormDimensionsConfig(BaseModel):
    operation: Literal["get_form_dimensions"] = _op(
        "get_form_dimensions", "Analytics", "Get Form Dimensions"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    period: Literal[
        "today", "yesterday", "24h", "7d", "30d", "3m", "6m", "12m", "all"
    ] = Field(..., title="Period")


class GetFormDropOffConfig(BaseModel):
    operation: Literal["get_form_drop_off"] = _op(
        "get_form_drop_off", "Analytics", "Get Form Drop-off"
    )
    form_id: str = Field(..., min_length=1, title="Form Id")
    period: Literal[
        "today", "yesterday", "24h", "7d", "30d", "3m", "6m", "12m", "all"
    ] = Field(..., title="Period")


class ListWebhooksConfig(BaseModel):
    operation: Literal["list_webhooks"] = _op(
        "list_webhooks", "Webhooks", "List Webhooks"
    )
    page: Optional[int] = Field(None, title="page")
    limit: Optional[int] = Field(None, title="limit")


class CreateWebhookConfig(BaseModel):
    operation: Literal["create_webhook"] = _op(
        "create_webhook", "Webhooks", "Create Webhook"
    )
    body_json: str = Field(
        ...,
        min_length=2,
        title="Request Body JSON",
        description="JSON object matching the Tally API request body for this action",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class TallyWebhookHeader(BaseModel):
    name: str = Field(..., title="Header Name")
    value: str = Field(..., title="Header Value", json_schema_extra={"ui:widget": "password"})


class UpdateWebhookConfig(BaseModel):
    operation: Literal["update_webhook"] = _op(
        "update_webhook", "Webhooks", "Update Webhook"
    )
    webhook_id: str = Field(..., min_length=1, title="Webhook Id")
    url: str = Field(..., title="Webhook URL")
    event_types: list[Literal["FORM_RESPONSE"]] = Field(..., title="Event Types")
    is_enabled: bool = Field(..., title="Enabled")
    signing_secret: Optional[str] = Field(
        None, title="Signing Secret", json_schema_extra={"ui:widget": "password"}
    )
    http_headers: Optional[list[TallyWebhookHeader]] = Field(
        None, title="HTTP Headers",
        description="Custom request headers; set to null to clear existing headers",
    )


class DeleteWebhookConfig(BaseModel):
    operation: Literal["delete_webhook"] = _op(
        "delete_webhook", "Webhooks", "Delete Webhook"
    )
    webhook_id: str = Field(..., min_length=1, title="Webhook Id")


class ListWebhookEventsConfig(BaseModel):
    operation: Literal["list_webhook_events"] = _op(
        "list_webhook_events", "Webhooks", "List Webhook Events"
    )
    webhook_id: str = Field(..., min_length=1, title="Webhook Id")
    page: Optional[int] = Field(None, title="page")


class RetryWebhookEventConfig(BaseModel):
    operation: Literal["retry_webhook_event"] = _op(
        "retry_webhook_event", "Webhooks", "Retry Webhook Event"
    )
    webhook_id: str = Field(..., min_length=1, title="Webhook Id")
    event_id: str = Field(..., min_length=1, title="Event Id")


TallyConfig = Annotated[
    Union[
        ListFormsConfig,
        CreateFormConfig,
        GetFormConfig,
        UpdateFormConfig,
        DeleteFormConfig,
        GetCurrentUserConfig,
        ListWorkspacesConfig,
        CreateWorkspaceConfig,
        GetWorkspaceConfig,
        UpdateWorkspaceConfig,
        DeleteWorkspaceConfig,
        ListFoldersConfig,
        CreateFolderConfig,
        UpdateFolderConfig,
        DeleteFolderConfig,
        ListOrganizationUsersConfig,
        RemoveOrganizationUserConfig,
        ListOrganizationInvitesConfig,
        CreateOrganizationInvitesConfig,
        CancelOrganizationInviteConfig,
        ListFormQuestionsConfig,
        UpdateFormQuestionConfig,
        ListFormBlocksConfig,
        UpdateFormBlocksConfig,
        ListSubmissionsConfig,
        GetSubmissionConfig,
        DeleteSubmissionConfig,
        GetFormMetricsConfig,
        GetFormVisitsConfig,
        GetFormSubmissionAnalyticsConfig,
        GetFormDimensionsConfig,
        GetFormDropOffConfig,
        ListWebhooksConfig,
        CreateWebhookConfig,
        UpdateWebhookConfig,
        DeleteWebhookConfig,
        ListWebhookEventsConfig,
        RetryWebhookEventConfig,
    ],
    Discriminator("operation"),
]


class TallyNodeConfig(NodeConfig[TallyConfig, TallyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


# Fixed, reviewed endpoint catalogue from the official OpenAPI specification.
# User content can fill path/query/body values but never selects an arbitrary host.
_ENDPOINTS: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    "list_forms": (
        "GET",
        "/forms",
        (("page", "page"), ("limit", "limit"), ("workspaceIds", "workspace_ids_json")),
    ),
    "create_form": ("POST", "/forms", ()),
    "get_form": ("GET", "/forms/{formId}", ()),
    "update_form": ("PATCH", "/forms/{formId}", ()),
    "delete_form": ("DELETE", "/forms/{formId}", ()),
    "get_current_user": ("GET", "/users/me", (("timezone", "timezone"),)),
    "list_workspaces": ("GET", "/workspaces", (("page", "page"),)),
    "create_workspace": ("POST", "/workspaces", ()),
    "get_workspace": ("GET", "/workspaces/{workspaceId}", ()),
    "update_workspace": ("PATCH", "/workspaces/{workspaceId}", ()),
    "delete_workspace": ("DELETE", "/workspaces/{workspaceId}", ()),
    "list_folders": ("GET", "/workspaces/{workspaceId}/folders", ()),
    "create_folder": ("POST", "/workspaces/{workspaceId}/folders", ()),
    "update_folder": ("PATCH", "/workspaces/{workspaceId}/folders/{id}", ()),
    "delete_folder": ("DELETE", "/workspaces/{workspaceId}/folders/{id}", ()),
    "list_organization_users": ("GET", "/organizations/{organizationId}/users", ()),
    "remove_organization_user": (
        "DELETE",
        "/organizations/{organizationId}/users/{userId}",
        (),
    ),
    "list_organization_invites": ("GET", "/organizations/{organizationId}/invites", ()),
    "create_organization_invites": (
        "POST",
        "/organizations/{organizationId}/invites",
        (),
    ),
    "cancel_organization_invite": (
        "DELETE",
        "/organizations/{organizationId}/invites/{inviteId}",
        (),
    ),
    "list_form_questions": ("GET", "/forms/{formId}/questions", ()),
    "update_form_question": ("PATCH", "/forms/{formId}/questions/{questionId}", ()),
    "list_form_blocks": ("GET", "/forms/{formId}/blocks", ()),
    "update_form_blocks": ("PATCH", "/forms/{formId}/blocks", ()),
    "list_submissions": (
        "GET",
        "/forms/{formId}/submissions",
        (
            ("page", "page"),
            ("filter", "filter"),
            ("startDate", "start_date"),
            ("endDate", "end_date"),
            ("afterId", "after_id"),
            ("limit", "limit"),
        ),
    ),
    "get_submission": ("GET", "/forms/{formId}/submissions/{submissionId}", ()),
    "delete_submission": ("DELETE", "/forms/{formId}/submissions/{submissionId}", ()),
    "get_form_metrics": (
        "GET",
        "/forms/{formId}/analytics/metrics",
        (("period", "period"),),
    ),
    "get_form_visits": (
        "GET",
        "/forms/{formId}/analytics/visits",
        (("period", "period"),),
    ),
    "get_form_submission_analytics": (
        "GET",
        "/forms/{formId}/analytics/submissions",
        (("period", "period"),),
    ),
    "get_form_dimensions": (
        "GET",
        "/forms/{formId}/analytics/dimensions",
        (("period", "period"),),
    ),
    "get_form_drop_off": (
        "GET",
        "/forms/{formId}/analytics/drop-off",
        (("period", "period"),),
    ),
    "list_webhooks": ("GET", "/webhooks", (("page", "page"), ("limit", "limit"))),
    "create_webhook": ("POST", "/webhooks", ()),
    "update_webhook": ("PATCH", "/webhooks/{webhookId}", ()),
    "delete_webhook": ("DELETE", "/webhooks/{webhookId}", ()),
    "list_webhook_events": ("GET", "/webhooks/{webhookId}/events", (("page", "page"),)),
    "retry_webhook_event": ("POST", "/webhooks/{webhookId}/events/{eventId}", ()),
}

# Model fields for the small, fixed request bodies. Exposing required API fields
# lets configuration validation catch missing values before making a request.
_BODY_FIELDS = {
    "create_workspace": {"name": "name"},
    "update_workspace": {"name": "name"},
    "create_folder": {"name": "name", "parent_id": "parentId"},
    "update_folder": {"name": "name"},
    "create_organization_invites": {"workspace_ids": "workspaceIds", "emails": "emails"},
    "update_webhook": {
        "url": "url", "event_types": "eventTypes", "is_enabled": "isEnabled",
        "signing_secret": "signingSecret", "http_headers": "httpHeaders",
    },
}

_PATH_TOKEN = re.compile(r"\{(\w+)\}")


def _request_details(config: TallyConfig) -> tuple[str, str, dict[str, Any], Any]:
    method, path, query_fields = _ENDPOINTS[config.operation]

    def replace_path(match: re.Match[str]) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", match.group(1)).lower()
        value = getattr(config, name)
        return quote(value, safe="")

    path = _PATH_TOKEN.sub(replace_path, path)
    params: dict[str, Any] = {}
    for api_name, field in query_fields:
        value = getattr(config, field)
        if value is None:
            continue
        if field.endswith("_json"):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise ValueError(f"{api_name} must be a valid JSON array") from exc
            if not isinstance(value, list) or not all(
                isinstance(x, str) for x in value
            ):
                raise ValueError(f"{api_name} must be a JSON array of strings")
        params[api_name] = value

    body = None
    if config.operation in _BODY_FIELDS:
        values = config.model_dump()
        body = {
            api_name: values[field]
            for field, api_name in _BODY_FIELDS[config.operation].items()
            if values[field] is not None
            or (field in {"signing_secret", "http_headers"} and field in config.model_fields_set)
        }
    if hasattr(config, "body_json"):
        try:
            body = json.loads(config.body_json)
        except ValueError as exc:
            raise ValueError("Request Body JSON must be valid JSON") from exc
        if not isinstance(body, dict):
            raise ValueError("Request Body JSON must be a JSON object")
    return method, path, params, body


class TallyNode(WorkflowNode):
    integration_type = "automation-tally"
    credential_provider_labels = {"tally": "Tally Account"}

    connection_evidence = ConnectionEvidence(
        operation="list_forms", noun="forms", identity_operation="get_current_user"
    )
    edit_examples = [
        "List my Tally forms and their latest submissions",
        "Get form analytics for the last month",
        "Create a Tally webhook for new responses",
    ]

    @classmethod
    def get_config_model(cls):
        return TallyNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, TallyNodeConfig) or not self.config.credentials:
            raise ValueError("Connect Tally before running this action")
        config = self.config.config
        method, path, params, body = _request_details(config)
        headers = {
            "Authorization": f"Bearer {self.config.credentials.api_key}",
            "Accept": "application/json",
            "tally-version": API_VERSION,
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                method, f"{API_BASE}{path}", headers=headers, params=params, json=body
            )
        if response.is_error or response.is_redirect:
            try:
                payload = response.json()
                message = (
                    payload.get("message") or payload.get("error")
                    if isinstance(payload, dict)
                    else None
                )
            except ValueError:
                message = None
            raise ValueError(
                f"Tally API error {response.status_code}: {message or response.reason_phrase}"
            )
        if response.status_code == 204:
            data: Any = {"deleted": method == "DELETE", "accepted": method != "DELETE"}
        else:
            try:
                data = response.json()
            except ValueError as exc:
                raise ValueError("Tally returned invalid JSON") from exc
        return {"status": "success", "operation": config.operation, "data": data}

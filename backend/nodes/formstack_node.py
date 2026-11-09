"""Formstack Forms v2025 operations using a manually supplied personal access token.

Each operation sends one documented request. Provider JSON and page metadata are
preserved so downstream steps can use fields and explicitly request later pages.
Contract: https://developers.formstack.com/openapi/api2025-openapi.yaml (0.0.4).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://www.formstack.com/api/v2025"


class FormstackTokenCredential(BaseModel):
    model_config = ConfigDict(title="Formstack Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://admin.formstack.com/",
            "x-credential-instructions": "In Formstack Administration, open Personal Access Tokens and generate a token. An organization admin must enable token creation for your user, and your account needs the Forms API add-on. Paste the token itself, without Bearer. It follows your Formstack user permissions. NoClick checks the connection by reading your forms.",
        })
    credential_type: Literal["formstack_token"] = Field("formstack_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the personal access token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    pageNumber: int = Field(1, ge=1, description="Page number, starting at 1. Request each page explicitly.")
    pageSize: int = Field(50, ge=10, le=100, description="Records per page; returned page metadata is preserved.")


class SubmissionField(_Input):
    id: str = Field(..., min_length=1, description="Formstack field ID, as returned by List Fields.")
    value: dict[str, Any] | None = Field(..., description="Parsed field value object from the Formstack contract; for text use {\"value\": \"text\"}, for names use {\"first\": \"Ada\", \"last\": \"Lovelace\"}.")


class ListFormsConfig(_Page):
    operation: Literal["list_forms"] = Field("list_forms", title="List Forms", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    orderBy: str | None = None
    order: Literal["ASC", "DESC"] | None = None
    folder: int | None = Field(None, gt=0)


class GetFormConfig(_Input):
    operation: Literal["get_form"] = Field("get_form", title="Get Form", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    withFields: bool = False


class CreateFormConfig(_Input):
    operation: Literal["create_form"] = Field("create_form", title="Create Form", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    folder: int | None = Field(None, gt=0)
    submitButtonTitle: str | None = None
    isActive: bool | None = None
    disabledMessage: str | None = None


class UpdateFormConfig(_Input):
    operation: Literal["update_form"] = Field("update_form", title="Update Form", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    name: str = Field(..., min_length=1)
    folder: int | None = Field(None, gt=0)
    submitButtonTitle: str | None = None
    isActive: bool | None = None
    disabledMessage: str | None = None


class DeleteFormConfig(_Input):
    operation: Literal["delete_form"] = Field("delete_form", title="Delete Form", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")


class CopyFormConfig(_Input):
    operation: Literal["copy_form"] = Field("copy_form", title="Copy Form", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    includeIntegrations: bool = Field(False, description="Copy integrations only when explicitly enabled.")
    includeEmails: bool = Field(False, description="Copy emails only when explicitly enabled.")
    folder: int | None = Field(None, gt=0)
    template: int | None = Field(None, gt=0)


class ListFieldsConfig(_Input):
    operation: Literal["list_fields"] = Field("list_fields", title="List Fields", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")


class GetFieldConfig(_Input):
    operation: Literal["get_field"] = Field("get_field", title="Get Field", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    field_id: int = Field(..., gt=0)


class ListFoldersConfig(_Input):
    operation: Literal["list_folders"] = Field("list_folders", title="List Folders", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    perPage: int = Field(50, ge=10, le=100)


class GetFolderConfig(_Input):
    operation: Literal["get_folder"] = Field("get_folder", title="Get Folder", json_schema_extra={"ui:hidden": True})
    folder_id: int = Field(..., gt=0, description="Folder ID.")


class CreateFolderConfig(_Input):
    operation: Literal["create_folder"] = Field("create_folder", title="Create Folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    parent: int | None = Field(None, gt=0)


class UpdateFolderConfig(_Input):
    operation: Literal["update_folder"] = Field("update_folder", title="Update Folder", json_schema_extra={"ui:hidden": True})
    folder_id: int = Field(..., gt=0, description="Folder ID.")
    name: str = Field(..., min_length=1)


class DeleteFolderConfig(_Input):
    operation: Literal["delete_folder"] = Field("delete_folder", title="Delete Folder", json_schema_extra={"ui:hidden": True})
    folder_id: int = Field(..., gt=0, description="Folder ID.")


class ListFormSubmissionsConfig(_Page):
    operation: Literal["list_form_submissions"] = Field("list_form_submissions", title="List Form Submissions", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    order: Literal["ASC", "DESC"] | None = None
    keyword: str | None = None
    minTime: str | None = Field(None, description="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS in Eastern Time.")
    maxTime: str | None = Field(None, description="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS in Eastern Time.")
    data: Literal["true", "false"] = "true"
    expandData: Literal["true", "false"] | None = None
    prettyName: Literal["true", "false"] | None = None
    dataFormat: Literal["legacy", "standardized"] = "standardized"


class SearchSubmissionsConfig(_Page):
    operation: Literal["search_submissions"] = Field("search_submissions", title="Search Submissions", json_schema_extra={"ui:hidden": True})
    search: str = Field(..., min_length=1)
    order: Literal["ASC", "DESC"] | None = None


class GetSubmissionConfig(_Input):
    operation: Literal["get_submission"] = Field("get_submission", title="Get Submission", json_schema_extra={"ui:hidden": True})
    submission_id: int = Field(..., gt=0, description="Submission ID.")


class CreateSubmissionConfig(_Input):
    operation: Literal["create_submission"] = Field("create_submission", title="Create Submission", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    fields: list[SubmissionField] = Field(..., min_length=1)
    read: Literal["true", "false"] | None = None
    userAgent: str | None = None
    remoteAddr: str | None = None


class UpdateSubmissionConfig(_Input):
    operation: Literal["update_submission"] = Field("update_submission", title="Update Submission", json_schema_extra={"ui:hidden": True})
    submission_id: int = Field(..., gt=0, description="Submission ID.")
    fields: list[SubmissionField] = Field(..., min_length=1)
    read: Literal["true", "false"] | None = None


class DeleteSubmissionConfig(_Input):
    operation: Literal["delete_submission"] = Field("delete_submission", title="Delete Submission", json_schema_extra={"ui:hidden": True})
    submission_id: int = Field(..., gt=0, description="Submission ID.")


class CountFormSubmissionsConfig(_Input):
    operation: Literal["count_form_submissions"] = Field("count_form_submissions", title="Count Form Submissions", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    startDate: str | None = Field(None, description="Start date for counting submissions.")
    lookbackPeriod: int | None = Field(None, ge=1, le=7)


class ListWebhooksConfig(_Input):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")


class GetWebhookConfig(_Input):
    operation: Literal["get_webhook"] = Field("get_webhook", title="Get Webhook", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    webhook_id: int = Field(..., gt=0, description="Webhook ID within this form.")


class CreateWebhookConfig(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"})
    contentType: Literal["urlencoded", "json"] = "json"
    fileTransferType: Literal["downloadLink", "signedUrl"] = "downloadLink"
    postDataFieldKeys: Literal["field_names", "field_ids", "api_friendly_field_names", "internal_labels", "internal_labels_api_friendly"] | None = None
    includeFieldType: bool | None = None
    includeSubfieldNames: bool | None = None
    standardizeValues: bool | None = None
    errorEmails: str | None = None


class UpdateWebhookConfig(_Input):
    operation: Literal["update_webhook"] = Field("update_webhook", title="Update Webhook", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    webhook_id: int = Field(..., gt=0, description="Webhook ID within this form.")
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"})
    contentType: Literal["urlencoded", "json"] = "json"
    fileTransferType: Literal["downloadLink", "signedUrl"] = "downloadLink"
    postDataFieldKeys: Literal["field_names", "field_ids", "api_friendly_field_names", "internal_labels", "internal_labels_api_friendly"] | None = None
    includeFieldType: bool | None = None
    includeSubfieldNames: bool | None = None
    standardizeValues: bool | None = None
    errorEmails: str | None = None


class DeleteWebhookConfig(_Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., gt=0, description="Form ID.")
    webhook_id: int = Field(..., gt=0, description="Webhook ID within this form.")


FormstackOperation = Annotated[Union[
    ListFormsConfig,
    GetFormConfig,
    CreateFormConfig,
    UpdateFormConfig,
    DeleteFormConfig,
    CopyFormConfig,
    ListFieldsConfig,
    GetFieldConfig,
    ListFoldersConfig,
    GetFolderConfig,
    CreateFolderConfig,
    UpdateFolderConfig,
    DeleteFolderConfig,
    ListFormSubmissionsConfig,
    SearchSubmissionsConfig,
    GetSubmissionConfig,
    CreateSubmissionConfig,
    UpdateSubmissionConfig,
    DeleteSubmissionConfig,
    CountFormSubmissionsConfig,
    ListWebhooksConfig,
    GetWebhookConfig,
    CreateWebhookConfig,
    UpdateWebhookConfig,
    DeleteWebhookConfig,
], Field(discriminator="operation")]


class FormstackConfig(NodeConfig[FormstackOperation, FormstackTokenCredential]):
    pass


# A fixed route table prevents user input from selecting a method or destination.
ROUTES = {
    "list_forms": ('GET', '/forms', ('pageNumber', 'pageSize', 'search', 'orderBy', 'order', 'folder')),
    "get_form": ('GET', '/forms/{form_id}', ('withFields',)),
    "create_form": ('POST', '/forms', ()),
    "update_form": ('PUT', '/forms/{form_id}', ()),
    "delete_form": ('DELETE', '/forms/{form_id}', ()),
    "copy_form": ('POST', '/forms/{form_id}/copy', ('includeIntegrations', 'includeEmails', 'folder', 'template')),
    "list_fields": ('GET', '/forms/{form_id}/fields', ()),
    "get_field": ('GET', '/forms/{form_id}/fields/{field_id}', ()),
    "list_folders": ('GET', '/folders', ('page', 'perPage')),
    "get_folder": ('GET', '/folders/{folder_id}', ()),
    "create_folder": ('POST', '/folders', ()),
    "update_folder": ('PUT', '/folders/{folder_id}', ()),
    "delete_folder": ('DELETE', '/folders/{folder_id}', ()),
    "list_form_submissions": ('GET', '/forms/{form_id}/submissions', ('pageNumber', 'pageSize', 'order', 'keyword', 'minTime', 'maxTime', 'data', 'expandData', 'prettyName', 'dataFormat')),
    "search_submissions": ('GET', '/submissions', ('search', 'pageNumber', 'pageSize', 'order')),
    "get_submission": ('GET', '/submissions/{submission_id}', ()),
    "create_submission": ('POST', '/forms/{form_id}/submissions', ()),
    "update_submission": ('PUT', '/submissions/{submission_id}', ()),
    "delete_submission": ('DELETE', '/submissions/{submission_id}', ()),
    "count_form_submissions": ('GET', '/forms/{form_id}/submissions/count', ('startDate', 'lookbackPeriod')),
    "list_webhooks": ('GET', '/forms/{form_id}/webhooks', ()),
    "get_webhook": ('GET', '/forms/{form_id}/webhooks/{webhook_id}', ()),
    "create_webhook": ('POST', '/forms/{form_id}/webhooks', ()),
    "update_webhook": ('PUT', '/forms/{form_id}/webhooks/{webhook_id}', ()),
    "delete_webhook": ('DELETE', '/forms/{form_id}/webhooks/{webhook_id}', ()),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class FormstackNode(WorkflowNode):
    integration_type = "automation-formstack"
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms", label_keys=("name", "id"))
    edit_examples = ["Find submissions for this form", "Copy my form to another folder", "Create a webhook for new submissions"]

    @classmethod
    def get_config_model(cls):
        return FormstackConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Formstack personal access token")
        op = self.config.config
        token = self.config.credentials.access_token
        method, template, query_names = ROUTES[op.operation]
        values = {k: v for k, v in op.model_dump(exclude={"operation"}).items() if v is not None}
        path_keys = {part[1:-1] for part in template.split("/") if part.startswith("{")}
        path = template.format(**{k: values.pop(k) for k in path_keys})
        params = {k: values.pop(k) for k in query_names if k in values}
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        body = values if method in {"POST", "PUT"} and values else None
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body, headers=headers)
        except httpx.RequestError:
            raise ValueError("Formstack request failed; inspect the provider before retrying a write") from None
        if not response.is_success:
            message = _redact(response.text, token)[:2000]
            raise ValueError(f"Formstack HTTP {response.status_code}: {message}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Formstack returned an invalid JSON response") from None
        if not isinstance(payload, (dict, list)):
            raise ValueError("Formstack returned an unexpected JSON response")
        if isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False):
            raise ValueError("Formstack rejected the request: " + str(_redact(payload, token)))
        output = {"data": _redact(payload, token), "http_status": response.status_code}
        await self.emit(output)
        return output

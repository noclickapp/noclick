"""Formcarry v1 forms, submissions and webhook administration.

Every operation makes one request to the published API using a pasted API key.
List responses retain the provider cursor and pagination envelope unchanged.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class FormcarryApiKey(BaseModel):
    model_config = ConfigDict(title="Formcarry API Key", json_schema_extra={
        "x-credential-url": "https://app.formcarry.com/",
        "x-credential-instructions": "Create an API key in Formcarry with access to the forms and scopes needed by your operations. Paste the key alone. NoClick sends it as a Bearer token to api.formcarry.com."})
    credential_type: Literal["formcarry_api_key"] = "formcarry_api_key"
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListForms(_Input):
    operation: Literal["list_forms"] = Field("list_forms", title="List Forms", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(25, ge=1, le=100)
    cursor: str | None = Field(None)
    team_id: str | None = Field(None)


class CreateForm(_Input):
    operation: Literal["create_form"] = Field("create_form", title="Create Form", json_schema_extra={"ui:hidden": True})
    active: bool | None = Field(None)
    folder_id: str | None = Field(None)
    team_id: str | None = Field(None)
    name: str = Field(..., max_length=128)


class GetForm(_Input):
    operation: Literal["get_form"] = Field("get_form", title="Get Form", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)


class UpdateForm(_Input):
    operation: Literal["update_form"] = Field("update_form", title="Update Form", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    name: str | None = Field(None, max_length=128)
    active: bool | None = Field(None)
    folder_id: str | None = Field(None)


class DeleteForm(_Input):
    operation: Literal["delete_form"] = Field("delete_form", title="Delete Form", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)


class AddRecipient(_Input):
    operation: Literal["add_recipient"] = Field("add_recipient", title="Add Recipient", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    email: str = Field(...)


class RemoveRecipient(_Input):
    operation: Literal["remove_recipient"] = Field("remove_recipient", title="Remove Recipient", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    email: str = Field(...)


class ListFields(_Input):
    operation: Literal["list_fields"] = Field("list_fields", title="List Fields", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)


class ListWebhooks(_Input):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)


class CreateWebhook(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    url: str = Field(..., max_length=2048)
    enabled: bool | None = Field(True)
    description: str | None = Field(None, max_length=128)
    events: list[Literal['submission.created']] | None = Field(None)


class GetWebhook(_Input):
    operation: Literal["get_webhook"] = Field("get_webhook", title="Get Webhook", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)


class UpdateWebhook(_Input):
    operation: Literal["update_webhook"] = Field("update_webhook", title="Update Webhook", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)
    url: str | None = Field(None, max_length=2048)
    enabled: bool | None = Field(None)
    description: str | None = Field(None, max_length=128)
    events: list[Literal['submission.created']] | None = Field(None)


class DeleteWebhook(_Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)


class ListDeliveries(_Input):
    operation: Literal["list_deliveries"] = Field("list_deliveries", title="List Deliveries", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)
    status: Literal['succeeded', 'failed', 'retrying', 'pending', 'skipped'] | None = Field(None)
    limit: int | None = Field(25, ge=1, le=100)
    before: str | None = Field(None)


class GetDelivery(_Input):
    operation: Literal["get_delivery"] = Field("get_delivery", title="Get Delivery", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)
    submission_id: str = Field(...)


class RedeliverSubmission(_Input):
    operation: Literal["redeliver_submission"] = Field("redeliver_submission", title="Redeliver Submission", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    webhook_id: str = Field(...)
    submission_id: str = Field(...)


class ListSubmissions(_Input):
    operation: Literal["list_submissions"] = Field("list_submissions", title="List Submissions", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    status: Literal['inbox', 'spam', 'all'] | None = Field('inbox')
    read: Literal['true', 'false'] | None = Field(None)
    has_attachments: Literal['true', 'false'] | None = Field(None)
    created_after: str | None = Field(None)
    created_before: str | None = Field(None)
    country: str | None = Field(None)
    q: str | None = Field(None)
    order: Literal['newest', 'oldest'] | None = Field('newest')
    limit: int | None = Field(25, ge=1, le=100)
    cursor: str | None = Field(None)
    fields: str | None = Field(None)


class CountSubmissions(_Input):
    operation: Literal["count_submissions"] = Field("count_submissions", title="Count Submissions", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    status: Literal['inbox', 'spam', 'all'] | None = Field('inbox')
    read: Literal['true', 'false'] | None = Field(None)
    has_attachments: Literal['true', 'false'] | None = Field(None)
    created_after: str | None = Field(None)
    created_before: str | None = Field(None)
    country: str | None = Field(None)
    q: str | None = Field(None)
    group_by: str | None = Field(None)


class GetSubmission(_Input):
    operation: Literal["get_submission"] = Field("get_submission", title="Get Submission", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    submission_id: str = Field(...)


class DeleteSubmission(_Input):
    operation: Literal["delete_submission"] = Field("delete_submission", title="Delete Submission", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    submission_id: str = Field(...)


class MarkSpam(_Input):
    operation: Literal["mark_spam"] = Field("mark_spam", title="Mark Spam", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    submission_id: str = Field(...)


class RestoreSubmission(_Input):
    operation: Literal["restore_submission"] = Field("restore_submission", title="Restore Submission", json_schema_extra={"ui:hidden": True})
    form_id: str = Field(...)
    submission_id: str = Field(...)


class GetConnection(_Input):
    operation: Literal["get_connection"] = Field("get_connection", title="Get Connection", json_schema_extra={"ui:hidden": True})


FormcarryOperation = Annotated[Union[ListForms, CreateForm, GetForm, UpdateForm, DeleteForm, AddRecipient, RemoveRecipient, ListFields, ListWebhooks, CreateWebhook, GetWebhook, UpdateWebhook, DeleteWebhook, ListDeliveries, GetDelivery, RedeliverSubmission, ListSubmissions, CountSubmissions, GetSubmission, DeleteSubmission, MarkSpam, RestoreSubmission, GetConnection], Field(discriminator="operation")]


class FormcarryConfig(NodeConfig[FormcarryOperation, FormcarryApiKey]):
    pass


ROUTES = {'list_forms': ('GET', '/v1/forms', ['limit', 'cursor', 'team_id'], []),
 'create_form': ('POST', '/v1/forms', [], ['active', 'folder_id', 'team_id', 'name']),
 'get_form': ('GET', '/v1/forms/{form_id}', [], []),
 'update_form': ('PATCH', '/v1/forms/{form_id}', [], ['name', 'active', 'folder_id']),
 'delete_form': ('DELETE', '/v1/forms/{form_id}', [], []),
 'add_recipient': ('POST', '/v1/forms/{form_id}/self-email-notification/recipients', [], ['email']),
 'remove_recipient': ('DELETE',
                      '/v1/forms/{form_id}/self-email-notification/recipients/{email}',
                      [],
                      []),
 'list_fields': ('GET', '/v1/forms/{form_id}/fields', [], []),
 'list_webhooks': ('GET', '/v1/forms/{form_id}/webhooks', [], []),
 'create_webhook': ('POST',
                    '/v1/forms/{form_id}/webhooks',
                    [],
                    ['url', 'enabled', 'description', 'events']),
 'get_webhook': ('GET', '/v1/forms/{form_id}/webhooks/{webhook_id}', [], []),
 'update_webhook': ('PATCH',
                    '/v1/forms/{form_id}/webhooks/{webhook_id}',
                    [],
                    ['url', 'enabled', 'description', 'events']),
 'delete_webhook': ('DELETE', '/v1/forms/{form_id}/webhooks/{webhook_id}', [], []),
 'list_deliveries': ('GET',
                     '/v1/forms/{form_id}/webhooks/{webhook_id}/deliveries',
                     ['status', 'limit', 'before'],
                     []),
 'get_delivery': ('GET',
                  '/v1/forms/{form_id}/webhooks/{webhook_id}/deliveries/{submission_id}',
                  [],
                  []),
 'redeliver_submission': ('POST',
                          '/v1/forms/{form_id}/webhooks/{webhook_id}/deliveries/{submission_id}/redeliver',
                          [],
                          []),
 'list_submissions': ('GET',
                      '/v1/forms/{form_id}/submissions',
                      ['status',
                       'read',
                       'has_attachments',
                       'created_after',
                       'created_before',
                       'country',
                       'q',
                       'order',
                       'limit',
                       'cursor',
                       'fields'],
                      []),
 'count_submissions': ('GET',
                       '/v1/forms/{form_id}/submissions/summary',
                       ['status',
                        'read',
                        'has_attachments',
                        'created_after',
                        'created_before',
                        'country',
                        'q',
                        'group_by'],
                       []),
 'get_submission': ('GET', '/v1/forms/{form_id}/submissions/{submission_id}', [], []),
 'delete_submission': ('DELETE', '/v1/forms/{form_id}/submissions/{submission_id}', [], []),
 'mark_spam': ('POST', '/v1/forms/{form_id}/submissions/{submission_id}/spam', [], []),
 'restore_submission': ('POST', '/v1/forms/{form_id}/submissions/{submission_id}/restore', [], []),
 'get_connection': ('GET', '/v1/me', [], [])}


class FormcarryNode(WorkflowNode):
    integration_type = "automation-formcarry"
    connection_evidence = ConnectionEvidence(operation="list_forms", noun="forms", identity_operation="get_connection")

    @classmethod
    def get_config_model(cls):
        return FormcarryConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Formcarry API key")
        method, path, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field, value in values.items():
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(value), safe=""))
        query = {k: values[k] for k in query_fields if k in values}
        body = {k: getattr(config, k) for k in body_fields if k in config.model_fields_set
                and (getattr(config, k) is not None or k in {"folder_id", "description"})}
        # Required fields are always supplied, including values equal to defaults.
        body.update({k: values[k] for k in body_fields if config.model_fields[k].is_required() and k in values})
        kwargs = {"params": query, "headers": {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://api.formcarry.com" + path, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except (ValueError, AttributeError):
                message = None
            return {"status": "error", "http_status": response.status_code, "error": message or "Formcarry request failed"}
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {"status": "success"}
        return response.json()

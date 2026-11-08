"""OpnForm hosted API, pinned to the provider's OpenAPI 1.0.0 contract."""
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.opnform.com"

class OpnFormToken(BaseModel):
    model_config = ConfigDict(title="Opn Form API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.opnform.com/api-reference/introduction",
        "x-credential-instructions": "Paste a Personal Access Token from OpnForm Settings → Access Tokens. Include workspaces-read for connection evidence, forms-read for form reads, forms-write for changes, workspace-users-read for members, and manage-integrations for webhooks. Workspace changes need workspaces-write. NoClick sends the token only to api.opnform.com."})
    credential_type: Literal["opn_form_api_token"] = "opn_form_api_token"
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class FormBody(Input):
    workspace_id: int | None = Field(None, gt=0)
    title: str | None = None
    visibility: Literal["public", "draft", "closed"] | None = None
    properties: list[dict] | None = None
    tags: list[str] | None = None
    language: str | None = None
    submit_button_text: str | None = Field(None, max_length=50)
    submitted_text: str | None = Field(None, max_length=2000)

class WorkspaceBody(Input):
    name: str = Field(..., min_length=1)
    icon: str | None = None

class WebhookData(Input):
    webhook_url: str = Field(..., description="HTTPS destination for submission events.")

    @field_validator("webhook_url")
    @classmethod
    def url(cls, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Use an HTTPS webhook URL without credentials")
        return value

class WebhookBody(Input):
    integration_id: Literal["webhook"] = "webhook"
    status: Literal["active", "inactive"] = "active"
    data: WebhookData

class ListWorkspaces(Input):
    operation: Literal["list_workspaces"] = "list_workspaces"

class CreateWorkspace(Input):
    operation: Literal["create_workspace"] = "create_workspace"
    name: str = Field(..., min_length=1)
    emoji: str | None = None

class UpdateWorkspace(Input):
    operation: Literal["update_workspace"] = "update_workspace"
    workspace_id: int = Field(..., gt=0)
    body: WorkspaceBody

class ListWorkspaceUsers(Input):
    operation: Literal["list_workspace_users"] = "list_workspace_users"
    workspace_id: int = Field(..., gt=0)

class ListForms(Input):
    operation: Literal["list_forms"] = "list_forms"
    workspace_id: int = Field(..., gt=0)
    page: int = Field(1, ge=1)
    per_page: int = Field(10, ge=1, le=100)

class GetForm(Input):
    operation: Literal["get_form"] = "get_form"
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

class CreateForm(Input):
    operation: Literal["create_form"] = "create_form"
    body: FormBody

class UpdateForm(Input):
    operation: Literal["update_form"] = "update_form"
    form_id: int = Field(..., gt=0)
    body: FormBody

class DeleteForm(Input):
    operation: Literal["delete_form"] = "delete_form"
    form_id: int = Field(..., gt=0)

class ListSubmissions(Input):
    operation: Literal["list_submissions"] = "list_submissions"
    form_id: int = Field(..., gt=0)
    page: int = Field(1, ge=1)
    per_page: int = Field(100, ge=1, le=100)
    search: str | None = None
    status: Literal["completed", "partial", "all"] = "all"

class CreateSubmission(Input):
    operation: Literal["create_submission"] = "create_submission"
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    body: dict = Field(..., description="Answers keyed by form field IDs, with optional completion_time, is_partial and tracking_parameters. Validation follows the target form.")

class DeleteSubmission(Input):
    operation: Literal["delete_submission"] = "delete_submission"
    form_id: int = Field(..., gt=0)
    submission_id: int = Field(..., gt=0)

class ListIntegrations(Input):
    operation: Literal["list_integrations"] = "list_integrations"
    form_id: int = Field(..., gt=0)

class CreateWebhook(Input):
    operation: Literal["create_webhook"] = "create_webhook"
    form_id: int = Field(..., gt=0)
    body: WebhookBody

class UpdateWebhook(Input):
    operation: Literal["update_webhook"] = "update_webhook"
    form_id: int = Field(..., gt=0)
    integration_id: int = Field(..., gt=0)
    body: WebhookBody

class DeleteWebhook(Input):
    operation: Literal["delete_webhook"] = "delete_webhook"
    form_id: int = Field(..., gt=0)
    integration_id: int = Field(..., gt=0)

class ListWebhookEvents(Input):
    operation: Literal["list_webhook_events"] = "list_webhook_events"
    form_id: int = Field(..., gt=0)
    integration_id: int = Field(..., gt=0)

OpnFormConfig = Annotated[Union[ListWorkspaces, CreateWorkspace, UpdateWorkspace, ListWorkspaceUsers, ListForms, GetForm, CreateForm, UpdateForm, DeleteForm, ListSubmissions, CreateSubmission, DeleteSubmission, ListIntegrations, CreateWebhook, UpdateWebhook, DeleteWebhook, ListWebhookEvents], Field(discriminator="operation")]

class OpnFormFullConfig(NodeConfig[OpnFormConfig, OpnFormToken]):
    pass

ROUTES = {'list_workspaces': ('GET', '/open/workspaces'), 'create_workspace': ('POST', '/open/workspaces/create'), 'update_workspace': ('PUT', '/open/workspaces/{workspace_id}'), 'list_workspace_users': ('GET', '/open/workspaces/{workspace_id}/users'), 'list_forms': ('GET', '/open/workspaces/{workspace_id}/forms'), 'get_form': ('GET', '/open/forms/{slug}'), 'create_form': ('POST', '/open/forms'), 'update_form': ('PUT', '/open/forms/{form_id}'), 'delete_form': ('DELETE', '/open/forms/{form_id}'), 'list_submissions': ('GET', '/open/forms/{form_id}/submissions'), 'create_submission': ('POST', '/forms/{slug}/answer'), 'delete_submission': ('DELETE', '/open/forms/{form_id}/submissions/{submission_id}'), 'list_integrations': ('GET', '/open/forms/{form_id}/integrations'), 'create_webhook': ('POST', '/open/forms/{form_id}/integrations'), 'update_webhook': ('PUT', '/open/forms/{form_id}/integrations/{integration_id}'), 'delete_webhook': ('DELETE', '/open/forms/{form_id}/integrations/{integration_id}'), 'list_webhook_events': ('GET', '/open/forms/{form_id}/integrations/{integration_id}/events')}

class OpnFormNode(WorkflowNode):
    integration_type = "automation-opn-form"
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="workspaces", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return OpnFormFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Opn Form API token")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {k: values[k] for k in ("page", "per_page", "search", "status") if k in values}
        body = values.get("body")
        if op.operation == "create_workspace":
            body = {k: values[k] for k in ("name", "emoji") if k in values}
        # Submission creation is public; never attach the account token there.
        headers = {"Accept": "application/json"}
        if op.operation != "create_submission":
            headers["Authorization"] = "Bearer " + self.config.credentials.api_token
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            # The provider's message is useful at connect, but must never leak a token.
            try:
                message = response.json().get("message", "OpnForm request failed")
            except Exception:
                message = "OpnForm request failed"
            message = str(message).replace(self.config.credentials.api_token, "[redacted]")
            raise ValueError(f"OpnForm HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            result = {"acknowledged": True}
        else:
            result = response.json()
            if not isinstance(result, (dict, list)):
                raise ValueError("OpnForm returned an unexpected JSON shape")
            if isinstance(result, dict) and (result.get("type") == "error" or result.get("errors")):
                raise ValueError("OpnForm reported an unsuccessful operation")
        output = {"data": result, "http_status": response.status_code}
        await self.emit(output)
        return output

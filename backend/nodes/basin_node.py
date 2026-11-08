"""Basin v1 account API. Each operation makes one documented API request.

Contract: https://usebasin.com/api_docs/v1/swagger.yaml (v1).
Lists return one provider page; no implicit pagination or mutation retries.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://usebasin.com"

class BasinAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Basin API Key", hide_input_in_errors=True, extra="ignore",
        json_schema_extra={"x-credential-url": "https://usebasin.com/api_docs",
            "x-credential-instructions": "Paste your Basin account API key from the account dashboard. Account keys access account-wide resources; form keys are limited to one form. NoClick sends Authorization: Token to usebasin.com. Listing forms verifies readable account data, not all write permissions. Webhook creation requires the Growth plan."})
    credential_type: Literal["basin_api_key"] = Field("basin_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Basin API key, without an Authorization header")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class _Page(_Input):
    page: Optional[str] = Field(None, pattern=r"^[1-9][0-9]{0,6}$", description="Provider page number; each execution reads one page.")
    query: Optional[str] = Field(None, max_length=1000, description="Basin's resource search query.")

class _ID(_Input):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Resource ID")

class _SubmissionID(_Input):
    id: int = Field(..., ge=1, title="Submission ID")

class _Name(_Input):
    name: str = Field(..., min_length=1, max_length=1000)

class _FormFields(_Input):
    name: Optional[str] = Field(None, min_length=1, max_length=1000)
    timezone: Optional[str] = None
    redirect_url: Optional[str] = None
    use_ajax: Optional[bool] = None
    autoreply: Optional[bool] = None
    autoreply_body: Optional[str] = None
    force_recaptcha: Optional[bool] = None
    force_hcaptcha: Optional[bool] = None
    force_turnstile: Optional[bool] = None
    retention_days: Optional[int] = Field(None, ge=0)
    duplicate_filter: Optional[bool] = None
    honeypot_field: Optional[str] = None
    project_id: Optional[int] = Field(None, ge=0)

class _WebhookFields(_Input):
    name: Optional[str] = Field(None, min_length=1, max_length=1000)
    url: Optional[str] = None
    format: Optional[str] = None
    trigger_when_spam: Optional[bool] = None
    enabled: Optional[bool] = None
    form_id: Optional[int] = Field(None, ge=0)


class BasinListProjectsConfig(_Page):
    """GET /api/v1/projects"""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class BasinGetProjectConfig(_ID):
    """GET /api/v1/projects/{id}"""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class BasinCreateProjectConfig(_Name):
    """POST /api/v1/projects/"""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})


class BasinUpdateProjectConfig(_ID, _Name):
    """PUT /api/v1/projects/{id}"""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})


class BasinDeleteProjectConfig(_ID):
    """DELETE /api/v1/projects/{id}"""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class BasinListFormsConfig(_Page):
    """GET /api/v1/forms"""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})


class BasinGetFormConfig(_ID):
    """GET /api/v1/forms/{id}"""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})


class BasinCreateFormConfig(_FormFields):
    """POST /api/v1/forms/"""
    operation: Literal["create_form"] = Field("create_form", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    project_id: int = Field(..., ge=0)


class BasinUpdateFormConfig(_ID, _FormFields):
    """PUT /api/v1/forms/{id}"""
    operation: Literal["update_form"] = Field("update_form", json_schema_extra={"ui:hidden": True})


class BasinDeleteFormConfig(_ID):
    """DELETE /api/v1/forms/{id}"""
    operation: Literal["delete_form"] = Field("delete_form", json_schema_extra={"ui:hidden": True})


class BasinListFormWebhooksConfig(_Page):
    """GET /api/v1/form_webhooks"""
    operation: Literal["list_form_webhooks"] = Field("list_form_webhooks", json_schema_extra={"ui:hidden": True})


class BasinGetFormWebhookConfig(_ID):
    """GET /api/v1/form_webhooks/{id}"""
    operation: Literal["get_form_webhook"] = Field("get_form_webhook", json_schema_extra={"ui:hidden": True})


class BasinCreateFormWebhookConfig(_WebhookFields):
    """POST /api/v1/form_webhooks/"""
    operation: Literal["create_form_webhook"] = Field("create_form_webhook", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    form_id: int = Field(..., ge=0)
    url: str = Field(..., min_length=1)


class BasinUpdateFormWebhookConfig(_ID, _WebhookFields):
    """PUT /api/v1/form_webhooks/{id}"""
    operation: Literal["update_form_webhook"] = Field("update_form_webhook", json_schema_extra={"ui:hidden": True})


class BasinDeleteFormWebhookConfig(_ID):
    """DELETE /api/v1/form_webhooks/{id}"""
    operation: Literal["delete_form_webhook"] = Field("delete_form_webhook", json_schema_extra={"ui:hidden": True})


class BasinListSubmissionsConfig(_Input):
    """GET /api/v1/submissions/"""
    operation: Literal["list_submissions"] = Field("list_submissions", json_schema_extra={"ui:hidden": True})
    form_id: Optional[str] = None
    filter_by: Optional[str] = None
    query: Optional[str] = None
    order_by: Optional[str] = None
    date_range: Optional[str] = None


class BasinGetSubmissionConfig(_SubmissionID):
    """GET /api/v1/submissions/{id}"""
    operation: Literal["get_submission"] = Field("get_submission", json_schema_extra={"ui:hidden": True})


class BasinUpdateSubmissionConfig(_SubmissionID):
    """PATCH /api/v1/submissions/{id}"""
    operation: Literal["update_submission"] = Field("update_submission", json_schema_extra={"ui:hidden": True})
    spam: Optional[bool] = None
    read: Optional[bool] = None
    trash: Optional[bool] = None


class BasinDeleteSubmissionConfig(_SubmissionID):
    """DELETE /api/v1/submissions/{id}"""
    operation: Literal["delete_submission"] = Field("delete_submission", json_schema_extra={"ui:hidden": True})


class BasinRefireSubmissionWebhooksConfig(_SubmissionID):
    """POST /api/v1/submissions/{id}/refire_webhooks"""
    operation: Literal["refire_submission_webhooks"] = Field("refire_submission_webhooks", json_schema_extra={"ui:hidden": True})


class BasinRefireMultipleSubmissionWebhooksConfig(_Input):
    """POST /api/v1/submissions/refire_webhooks"""
    operation: Literal["refire_multiple_submission_webhooks"] = Field("refire_multiple_submission_webhooks", json_schema_extra={"ui:hidden": True})
    submission_ids: list[int] = Field(..., min_length=1, max_length=1000)


class BasinListFormViewsConfig(_Page):
    """GET /api/v1/form_views"""
    operation: Literal["list_form_views"] = Field("list_form_views", json_schema_extra={"ui:hidden": True})


class BasinGetFormViewConfig(_ID):
    """GET /api/v1/form_views/{id}"""
    operation: Literal["get_form_view"] = Field("get_form_view", json_schema_extra={"ui:hidden": True})


class BasinListDomainsConfig(_Page):
    """GET /api/v1/domains"""
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})


BasinOperations = Annotated[Union[
    BasinListProjectsConfig,
    BasinGetProjectConfig,
    BasinCreateProjectConfig,
    BasinUpdateProjectConfig,
    BasinDeleteProjectConfig,
    BasinListFormsConfig,
    BasinGetFormConfig,
    BasinCreateFormConfig,
    BasinUpdateFormConfig,
    BasinDeleteFormConfig,
    BasinListFormWebhooksConfig,
    BasinGetFormWebhookConfig,
    BasinCreateFormWebhookConfig,
    BasinUpdateFormWebhookConfig,
    BasinDeleteFormWebhookConfig,
    BasinListSubmissionsConfig,
    BasinGetSubmissionConfig,
    BasinUpdateSubmissionConfig,
    BasinDeleteSubmissionConfig,
    BasinRefireSubmissionWebhooksConfig,
    BasinRefireMultipleSubmissionWebhooksConfig,
    BasinListFormViewsConfig,
    BasinGetFormViewConfig,
    BasinListDomainsConfig,
], Field(discriminator="operation")]

class BasinNodeConfig(NodeConfig[BasinOperations, BasinAPIKeyCredential]):
    pass

ROUTES = {
    'list_projects': ('GET', '/api/v1/projects', None),
    'get_project': ('GET', '/api/v1/projects/{id}', None),
    'create_project': ('POST', '/api/v1/projects/', 'project'),
    'update_project': ('PUT', '/api/v1/projects/{id}', 'project'),
    'delete_project': ('DELETE', '/api/v1/projects/{id}', None),
    'list_forms': ('GET', '/api/v1/forms', None),
    'get_form': ('GET', '/api/v1/forms/{id}', None),
    'create_form': ('POST', '/api/v1/forms/', 'form'),
    'update_form': ('PUT', '/api/v1/forms/{id}', 'form'),
    'delete_form': ('DELETE', '/api/v1/forms/{id}', None),
    'list_form_webhooks': ('GET', '/api/v1/form_webhooks', None),
    'get_form_webhook': ('GET', '/api/v1/form_webhooks/{id}', None),
    'create_form_webhook': ('POST', '/api/v1/form_webhooks/', 'form_webhook'),
    'update_form_webhook': ('PUT', '/api/v1/form_webhooks/{id}', 'form_webhook'),
    'delete_form_webhook': ('DELETE', '/api/v1/form_webhooks/{id}', None),
    'list_submissions': ('GET', '/api/v1/submissions/', None),
    'get_submission': ('GET', '/api/v1/submissions/{id}', None),
    'update_submission': ('PATCH', '/api/v1/submissions/{id}', 'submission'),
    'delete_submission': ('DELETE', '/api/v1/submissions/{id}', None),
    'refire_submission_webhooks': ('POST', '/api/v1/submissions/{id}/refire_webhooks', None),
    'refire_multiple_submission_webhooks': ('POST', '/api/v1/submissions/refire_webhooks', ''),
    'list_form_views': ('GET', '/api/v1/form_views', None),
    'get_form_view': ('GET', '/api/v1/form_views/{id}', None),
    'list_domains': ('GET', '/api/v1/domains', None),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value

class BasinNode(WorkflowNode):
    integration_type = "automation-basin"
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms")

    @classmethod
    def get_config_model(cls):
        return BasinNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Basin API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, wrapper = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        params, body = None, None
        if method == "GET":
            params = values
        elif wrapper is not None:
            if not values:
                raise ValueError("Provide at least one field to update")
            body = {wrapper: values} if wrapper else values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Token " + secret, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Basin request could not be confirmed", "write_outcome": "unknown" if method != "GET" else None}
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(response.text[:4000], secret)}
        try:
            data = response.json() if response.content else None
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Basin returned an unexpected non-JSON response"}
        if data is not None and not isinstance(data, (dict, list)):
            return {"status": "error", "error": "Basin returned an unexpected JSON shape"}
        if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
            return {"status": "error", "http_status": response.status_code, "error": _redact(data, secret)}
        return {"status": "success", "operation": op.operation, "http_status": response.status_code,
            "data": _redact(data, secret), **({"page_scope": "single_provider_page"} if op.operation.startswith("list_") else {})}

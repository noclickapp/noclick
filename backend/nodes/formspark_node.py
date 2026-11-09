"""Formspark public v1: one documented request per operation, with pasted API tokens.

Contract: https://api.formspark.io/public/v1/openapi.json (1.0.0).
Docs: https://documentation.formspark.io/api/reference.html.
Lists return one page and preserve the provider's opaque nextCursor. Writes are
never automatically retried: repeated POSTs can create duplicate resources.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.formspark.io/public/v1"


class FormsparkAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Formspark API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.formspark.io/",
            "x-credential-instructions": "Create an API token in the Formspark dashboard under API tokens and paste it here without the Bearer prefix. Include workspaces:read for the connection check, plus forms:read, forms:write, submissions:read, submissions:write or workspaces:write for the operations you use. Form and submission access requires an upgraded workspace. Tokens expire unless you choose Never; replace expired or revoked tokens manually.",
        })
    credential_type: Literal["formspark_api_token"] = Field("formspark_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("workspaceId", "formId", "submissionId", mode="before", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a single Formspark resource ID")
        return value

    @field_validator("webhookUrl", mode="after", check_fields=False)
    @classmethod
    def webhook(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a public HTTP or HTTPS webhook URL")
        return value


class FormsparkGetTokenConfig(_Input):
    """Describe the current token."""
    operation: Literal["get_token"] = Field("get_token", json_schema_extra={"ui:hidden": True})


class FormsparkListWorkspacesConfig(_Input):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(25, ge=1, le=100, strict=True)
    startingAfter: str | None = Field(None, description='Opaque nextCursor from the previous page; pass it unchanged. Keep the same filters.')


class FormsparkCreateWorkspaceConfig(_Input):
    """Create a workspace."""
    operation: Literal["create_workspace"] = Field("create_workspace", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=128)


class FormsparkUpdateWorkspaceConfig(_Input):
    """Update a workspace."""
    operation: Literal["update_workspace"] = Field("update_workspace", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=128)


class FormsparkListFormsConfig(_Input):
    """List forms."""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(25, ge=1, le=100, strict=True)
    startingAfter: str | None = Field(None, description='Opaque nextCursor from the previous page; pass it unchanged. Keep the same filters.')
    workspaceId: str = Field(..., min_length=1)


class FormsparkCreateFormConfig(_Input):
    """Create a form."""
    operation: Literal["create_form"] = Field("create_form", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)
    technology: str | None = Field(None, max_length=128)
    notificationEmails: list[str] | None = Field(None, max_length=100, description='Complete replacement list of notification email addresses (at most 100).')
    emailThreading: bool | None = Field(None, strict=True)
    automaticSpamFilter: bool | None = Field(None, strict=True, description="Whether submissions to this form are screened by the automatic spam filter. Defaults to true. Setting it to false stores every submission, including the ones the filter would have held back, and each of those counts against the workspace's quota.")
    webhookUrl: str | None = Field(None, max_length=512, description='Where each submission is delivered. Must be an http or https URL, and must resolve to a public address when called.')
    slackChannel: str | None = Field(None, max_length=128)
    customHoneypot: str | None = Field(None, max_length=128)
    customSpamWords: str | None = Field(None, max_length=2560, json_schema_extra={'ui:widget': 'textarea'})
    allowedDomains: list[str] | None = Field(None, max_length=100, description='The sites a submission may be sent from. Each entry also covers its subdomains, and a pasted address is reduced to its host. Once the list is set, a submission must carry an Origin or Referer header naming one of them, so a server-side request is rejected unless it sends one. An empty list or null accepts submissions from anywhere.')
    spamProtection: Literal['BOTPOISON', 'GOOGLE_RECAPTCHA_V2', 'HCAPTCHA', 'TURNSTILE'] | None = Field(None, description="The challenge a submitter must pass. Requires the provider's secret key, stored on the form earlier or sent in the same request. Null disables it.")
    botpoisonSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The Botpoison secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    recaptchaV2SecretKey: str | None = Field(None, min_length=1, max_length=64, description="The reCAPTCHA v2 secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    hCaptchaSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The hCaptcha secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    turnstileSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The Turnstile secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    workspaceId: str = Field(..., min_length=1)


class FormsparkGetFormConfig(_Input):
    """Retrieve a form."""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)


class FormsparkUpdateFormConfig(_Input):
    """Update a form."""
    operation: Literal["update_form"] = Field("update_form", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)
    technology: str | None = Field(None, max_length=128)
    notificationEmails: list[str] | None = Field(None, max_length=100, description='Complete replacement list of notification email addresses (at most 100).')
    emailThreading: bool | None = Field(None, strict=True)
    automaticSpamFilter: bool | None = Field(None, strict=True, description="Whether submissions to this form are screened by the automatic spam filter. Defaults to true. Setting it to false stores every submission, including the ones the filter would have held back, and each of those counts against the workspace's quota.")
    webhookUrl: str | None = Field(None, max_length=512, description='Where each submission is delivered. Must be an http or https URL, and must resolve to a public address when called.')
    slackChannel: str | None = Field(None, max_length=128)
    customHoneypot: str | None = Field(None, max_length=128)
    customSpamWords: str | None = Field(None, max_length=2560, json_schema_extra={'ui:widget': 'textarea'})
    allowedDomains: list[str] | None = Field(None, max_length=100, description='The sites a submission may be sent from. Each entry also covers its subdomains, and a pasted address is reduced to its host. Once the list is set, a submission must carry an Origin or Referer header naming one of them, so a server-side request is rejected unless it sends one. An empty list or null accepts submissions from anywhere.')
    spamProtection: Literal['BOTPOISON', 'GOOGLE_RECAPTCHA_V2', 'HCAPTCHA', 'TURNSTILE'] | None = Field(None, description="The challenge a submitter must pass. Requires the provider's secret key, stored on the form earlier or sent in the same request. Null disables it.")
    botpoisonSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The Botpoison secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    recaptchaV2SecretKey: str | None = Field(None, min_length=1, max_length=64, description="The reCAPTCHA v2 secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    hCaptchaSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The hCaptcha secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})
    turnstileSecretKey: str | None = Field(None, min_length=1, max_length=64, description="The Turnstile secret key the form verifies challenges with. Write-only: it is stored on the form and never returned. Null removes it, which is refused while the form's spamProtection uses it.", repr=False, json_schema_extra={'ui:widget': 'password'})


class FormsparkDeleteFormConfig(_Input):
    """Delete a form and all of its submissions."""
    operation: Literal["delete_form"] = Field("delete_form", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)


class FormsparkGetTemplateConfig(_Input):
    """Retrieve a form's email template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    kind: Literal['notification', 'autoresponder'] = Field(...)


class FormsparkWriteTemplateConfig(_Input):
    """Write a form's email template."""
    operation: Literal["write_template"] = Field("write_template", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    kind: Literal['notification', 'autoresponder'] = Field(...)
    code: str | None = Field(None, min_length=1, max_length=262144, description='HTML with Handlebars placeholders. Replaces the visual layout; required to create a template. Writing an autoresponder enables replies. Check paused in the response.', json_schema_extra={'ui:widget': 'textarea'})
    subject: str | None = Field(None, max_length=998, description='Leave unset to keep the current subject; null or empty clears it to the default subject.')


class FormsparkDeleteTemplateConfig(_Input):
    """Delete a template: notifications revert to default; autoresponder replies stop."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    kind: Literal['notification', 'autoresponder'] = Field(...)


class FormsparkPreviewTemplateConfig(_Input):
    """Preview a form's email template."""
    operation: Literal["preview_template"] = Field("preview_template", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    kind: Literal['notification', 'autoresponder'] = Field(...)
    data: dict[str, Any] | None = Field(None, description="Stand-in submission data to render against. Defaults to example data derived from the form's own recent submissions.")


class FormsparkListFormSubmissionsConfig(_Input):
    """List a form's submissions, excluding spam and deleted submissions."""
    operation: Literal["list_form_submissions"] = Field("list_form_submissions", json_schema_extra={"ui:hidden": True})
    formId: str = Field(..., min_length=1)
    limit: int | None = Field(25, ge=1, le=100, strict=True)
    startingAfter: str | None = Field(None, description='Opaque nextCursor from the previous page; pass it unchanged. Keep the same filters.')
    search: str | None = Field(None, min_length=1, max_length=256)


class FormsparkListWorkspaceSubmissionsConfig(_Input):
    """List submissions across a workspace, excluding spam and deleted submissions."""
    operation: Literal["list_workspace_submissions"] = Field("list_workspace_submissions", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., min_length=1)
    limit: int | None = Field(25, ge=1, le=100, strict=True)
    startingAfter: str | None = Field(None, description='Opaque nextCursor from the previous page; pass it unchanged. Keep the same filters.')
    search: str | None = Field(None, min_length=1, max_length=256)


class FormsparkDeleteSubmissionConfig(_Input):
    """Delete a submission."""
    operation: Literal["delete_submission"] = Field("delete_submission", json_schema_extra={"ui:hidden": True})
    submissionId: str = Field(..., min_length=1)


FormsparkConfig = Annotated[Union[FormsparkGetTokenConfig, FormsparkListWorkspacesConfig, FormsparkCreateWorkspaceConfig, FormsparkUpdateWorkspaceConfig, FormsparkListFormsConfig, FormsparkCreateFormConfig, FormsparkGetFormConfig, FormsparkUpdateFormConfig, FormsparkDeleteFormConfig, FormsparkGetTemplateConfig, FormsparkWriteTemplateConfig, FormsparkDeleteTemplateConfig, FormsparkPreviewTemplateConfig, FormsparkListFormSubmissionsConfig, FormsparkListWorkspaceSubmissionsConfig, FormsparkDeleteSubmissionConfig], Field(discriminator="operation")]


class FormsparkFullConfig(NodeConfig[FormsparkConfig, FormsparkAPITokenCredential]):
    pass


ROUTES = {'get_token': {'method': 'GET',
               'path': '/me',
               'query': [],
               'body': [],
               'nullable': [],
               'status': 200},
 'list_workspaces': {'method': 'GET',
                     'path': '/workspaces',
                     'query': ['limit', 'startingAfter'],
                     'body': [],
                     'nullable': [],
                     'status': 200},
 'create_workspace': {'method': 'POST',
                      'path': '/workspaces',
                      'query': [],
                      'body': ['name'],
                      'nullable': [],
                      'status': 201},
 'update_workspace': {'method': 'PATCH',
                      'path': '/workspaces/{workspaceId}',
                      'query': [],
                      'body': ['name'],
                      'nullable': [],
                      'status': 200},
 'list_forms': {'method': 'GET',
                'path': '/forms',
                'query': ['limit', 'startingAfter', 'workspaceId'],
                'body': [],
                'nullable': [],
                'status': 200},
 'create_form': {'method': 'POST',
                 'path': '/forms',
                 'query': [],
                 'body': ['name',
                          'description',
                          'technology',
                          'notificationEmails',
                          'emailThreading',
                          'automaticSpamFilter',
                          'webhookUrl',
                          'slackChannel',
                          'customHoneypot',
                          'customSpamWords',
                          'allowedDomains',
                          'spamProtection',
                          'botpoisonSecretKey',
                          'recaptchaV2SecretKey',
                          'hCaptchaSecretKey',
                          'turnstileSecretKey',
                          'workspaceId'],
                 'nullable': ['description',
                              'technology',
                              'webhookUrl',
                              'slackChannel',
                              'customHoneypot',
                              'customSpamWords',
                              'allowedDomains',
                              'spamProtection',
                              'botpoisonSecretKey',
                              'recaptchaV2SecretKey',
                              'hCaptchaSecretKey',
                              'turnstileSecretKey'],
                 'status': 201},
 'get_form': {'method': 'GET',
              'path': '/forms/{formId}',
              'query': [],
              'body': [],
              'nullable': [],
              'status': 200},
 'update_form': {'method': 'PATCH',
                 'path': '/forms/{formId}',
                 'query': [],
                 'body': ['name',
                          'description',
                          'technology',
                          'notificationEmails',
                          'emailThreading',
                          'automaticSpamFilter',
                          'webhookUrl',
                          'slackChannel',
                          'customHoneypot',
                          'customSpamWords',
                          'allowedDomains',
                          'spamProtection',
                          'botpoisonSecretKey',
                          'recaptchaV2SecretKey',
                          'hCaptchaSecretKey',
                          'turnstileSecretKey'],
                 'nullable': ['description',
                              'technology',
                              'webhookUrl',
                              'slackChannel',
                              'customHoneypot',
                              'customSpamWords',
                              'allowedDomains',
                              'spamProtection',
                              'botpoisonSecretKey',
                              'recaptchaV2SecretKey',
                              'hCaptchaSecretKey',
                              'turnstileSecretKey'],
                 'status': 200},
 'delete_form': {'method': 'DELETE',
                 'path': '/forms/{formId}',
                 'query': [],
                 'body': [],
                 'nullable': [],
                 'status': 204},
 'get_template': {'method': 'GET',
                  'path': '/forms/{formId}/templates/{kind}',
                  'query': [],
                  'body': [],
                  'nullable': [],
                  'status': 200},
 'write_template': {'method': 'PUT',
                    'path': '/forms/{formId}/templates/{kind}',
                    'query': [],
                    'body': ['code', 'subject'],
                    'nullable': ['subject'],
                    'status': 200},
 'delete_template': {'method': 'DELETE',
                     'path': '/forms/{formId}/templates/{kind}',
                     'query': [],
                     'body': [],
                     'nullable': [],
                     'status': 204},
 'preview_template': {'method': 'POST',
                      'path': '/forms/{formId}/templates/{kind}/preview',
                      'query': [],
                      'body': ['data'],
                      'nullable': [],
                      'status': 200},
 'list_form_submissions': {'method': 'GET',
                           'path': '/forms/{formId}/submissions',
                           'query': ['limit', 'startingAfter', 'search'],
                           'body': [],
                           'nullable': [],
                           'status': 200},
 'list_workspace_submissions': {'method': 'GET',
                                'path': '/workspaces/{workspaceId}/submissions',
                                'query': ['limit', 'startingAfter', 'search'],
                                'body': [],
                                'nullable': [],
                                'status': 200},
 'delete_submission': {'method': 'DELETE',
                       'path': '/submissions/{submissionId}',
                       'query': [],
                       'body': [],
                       'nullable': [],
                       'status': 204}}


class FormsparkNode(WorkflowNode):
    integration_type = "automation-formspark"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces")

    @classmethod
    def get_config_model(cls):
        return FormsparkFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Formspark API token")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(exclude_unset=True)
        # Include list defaults while keeping optional writes absent unless set.
        query = {key: getattr(config, key) for key in route["query"] if getattr(config, key) is not None}
        path = route["path"]
        for key in ("workspaceId", "formId", "submissionId", "kind"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(getattr(config, key), safe=""))
        body = {key: values[key] for key in route["body"] if key in values and (values[key] is not None or key in route["nullable"])}
        token = self.config.credentials.api_token
        is_write = route["method"] != "GET" and config.operation != "preview_template"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=query, **({"json": body} if route["body"] else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Formspark request could not be confirmed; check the resource before retrying a write.", "ambiguous": is_write}
        if response.status_code != route["status"]:
            message = "Formspark rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("detail"), str):
                    message = error["detail"][:2000].replace(token, "[redacted]")
            except (ValueError, UnicodeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": message,
                "ambiguous": is_write and (response.status_code >= 500 or 200 <= response.status_code < 300)}
        if response.status_code == 204:
            return {"status": "success", "deleted": True}
        if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Expected bounded JSON from Formspark; check the resource before retrying a write")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Expected a Formspark response object")
        if config.operation.startswith("list_"):
            if not isinstance(result.get("data"), list) or type(result.get("hasMore")) is not bool or "nextCursor" not in result:
                raise ValueError("Formspark returned an incomplete page")
            cursor = result["nextCursor"]
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("Formspark returned an invalid cursor")
            if result["hasMore"] and (not cursor or cursor == getattr(config, "startingAfter", None)):
                raise ValueError("Formspark returned a missing or stalled cursor")
            return {"status": "success", **result}
        return {"status": "success", "data": result}

"""MotaWord translation projects, source files and milestone callbacks.

Contract: https://api.motaword.com/openapi.yaml (1.0).
Manual tokens: https://www.motaword.com/motaword-for/developer-portal
Callbacks: https://motaword.readme.io/reference/webhooks
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.motaword import MOTAWORD_SCOPES

BASE = "https://api.motaword.com"
EVENTS = ("translated", "proofread", "completed")


class MotaWordAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="MotaWord Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.motaword.com/developer",
        "x-credential-instructions": "In your MotaWord developer account, choose your application in the Authorization Tool and copy its access token. Request privileged scope for private endpoints. Paste only the token. Temporary tokens must be replaced when they expire. NoClick checks your account with GET /me.",
    })
    credential_type: Literal["motaword_access_token"] = Field("motaword_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the MotaWord access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Project(_Input):
    project_id: int = Field(..., gt=0, title="Project ID")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(10, ge=1, le=100, title="Page Size")


def operation(name, label, category):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category})


class GetAccount(_Input):
    operation: Literal["get_account"] = operation("get_account", "Get Account", "Account")


class ListLanguages(_Input):
    operation: Literal["list_languages"] = operation("list_languages", "List Languages", "Reference")


class ListFormats(_Input):
    operation: Literal["list_formats"] = operation("list_formats", "List File Formats", "Reference")


class ListProjects(_Page):
    operation: Literal["list_projects"] = operation("list_projects", "List Projects", "Projects")
    status: Literal["pending", "started", "completed"] | None = None
    order_by: Literal["id", "status", "delivery", "price"] = "id"
    order_type: Literal["asc", "desc"] = "desc"


class GetProject(_Project):
    operation: Literal["get_project"] = operation("get_project", "Get Project", "Projects")


class CreateProject(_Input):
    operation: Literal["create_project"] = operation("create_project", "Create Translation Project", "Projects")
    source_language: str = Field(..., min_length=1, title="Source Language")
    target_languages: list[str] = Field(..., min_length=1, title="Target Languages")
    notes: str | None = None
    custom: dict[str, Any] | None = Field(None, description="Custom metadata returned with the project.")


class UpdateProject(_Project):
    operation: Literal["update_project"] = operation("update_project", "Update Project", "Projects")
    source_language: str | None = None
    target_languages: list[str] | None = Field(None, min_length=1)
    notes: str | None = None
    reference_code: str | None = None
    custom: dict[str, Any] | None = None


class LaunchProject(_Project):
    operation: Literal["launch_project"] = operation("launch_project", "Launch Paid Translation", "Projects")
    payment_method: Literal["corporate", "client", "app", "corporate_card"] = Field(..., description="Starts translation and charges the selected payment method under your MotaWord account policy.")
    card_id: int | None = Field(None, gt=0)
    payment_code: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    reference_code: str | None = None

    @model_validator(mode="after")
    def payment_fields(self):
        if self.payment_method == "corporate" and not self.payment_code:
            raise ValueError("Corporate payment requires a payment code")
        if self.payment_method != "corporate" and self.card_id is None:
            raise ValueError("This payment method requires a saved card ID")
        return self


class CancelProject(_Project):
    operation: Literal["cancel_project"] = operation("cancel_project", "Cancel Project", "Projects")
    reason: str | None = Field(None, description="Cancels started work or deletes an unlaunched quote; refunds follow MotaWord policy.")


class GetProgress(_Project):
    operation: Literal["get_progress"] = operation("get_progress", "Get Translation Progress", "Projects")


class GetInvoice(_Project):
    operation: Literal["get_invoice"] = operation("get_invoice", "Get Invoice", "Projects")


class ListDocuments(_Page):
    operation: Literal["list_documents"] = operation("list_documents", "List Account Documents", "Documents")
    search: str | None = None
    language_code: str | None = None
    order_by: Literal["id", "updated_at", "created_at", "name"] = "updated_at"
    order_type: Literal["asc", "desc"] = "desc"


class GetDocument(_Input):
    operation: Literal["get_document"] = operation("get_document", "Get Account Document", "Documents")
    document_id: str = Field(..., min_length=1)


class ListProjectDocuments(_Project):
    operation: Literal["list_project_documents"] = operation("list_project_documents", "List Project Documents", "Documents")


class AddLinkedDocument(_Project):
    operation: Literal["add_linked_document"] = operation("add_linked_document", "Add Linked Source Document", "Documents")
    source: Literal["dropbox", "googledrive", "icloud"]
    url: str = Field(..., description="Publicly downloadable source URL; MotaWord downloads this file.", json_schema_extra={"format": "uri"})
    name: str = Field(..., min_length=1, title="File Name")

    @field_validator("url")
    @classmethod
    def url_https(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTPS document URL without embedded credentials")
        return value


class ListProjectGlossaries(_Project):
    operation: Literal["list_project_glossaries"] = operation("list_project_glossaries", "List Project Glossaries", "Glossaries")


class ListProjectStyleGuides(_Project):
    operation: Literal["list_project_style_guides"] = operation("list_project_style_guides", "List Project Style Guides", "Style Guides")


class ListActivities(_Project):
    operation: Literal["list_activities"] = operation("list_activities", "List Project Activities", "Activities")


class AddActivity(_Project):
    operation: Literal["add_activity"] = operation("add_activity", "Add Project Activity", "Activities")
    info: str = Field(..., min_length=1, title="Activity Text")
    action_type: str | None = None
    action_value: str | None = None


class ListProjectStrings(_Project):
    operation: Literal["list_project_strings"] = operation("list_project_strings", "List Project Strings and Translations", "Translations")


class PackageTranslations(_Project):
    operation: Literal["package_translations"] = operation("package_translations", "Package Translations", "Translations")


class CheckPackage(_Project):
    operation: Literal["check_package"] = operation("check_package", "Check Translation Package", "Translations")
    key: str | None = Field(None, description="Packaging key returned by MotaWord.")


class OnProjectStatus(WebhookTriggerConfigBase):
    operation: Literal["on_project_status"] = Field("on_project_status", title="On Project Milestone", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Project Milestone", "x-category": "Triggers"})
    project_id: int = Field(..., gt=0, title="Project ID", description="One callback URL is supported per project. An existing different callback is never overwritten.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Receives translated, proofread and completed callbacks. MotaWord documents no signature; keep this address private.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


MotaWordConfig = Annotated[Union[GetAccount, ListLanguages, ListFormats, ListProjects, GetProject, CreateProject,
    UpdateProject, LaunchProject, CancelProject, GetProgress, GetInvoice, ListDocuments, GetDocument,
    ListProjectDocuments, AddLinkedDocument, ListProjectGlossaries, ListProjectStyleGuides, ListActivities,
    AddActivity, ListProjectStrings, PackageTranslations, CheckPackage, OnProjectStatus], Field(discriminator="operation")]


class MotaWordNodeConfig(NodeConfig[MotaWordConfig, MotaWordAccessTokenCredential]):
    pass


# Each action maps to exactly one published operation. No pagination URLs are followed.
ROUTES = {
    "get_account": ("GET", "/me"),
    "list_languages": ("GET", "/languages"),
    "list_formats": ("GET", "/formats"),
    "list_projects": ("GET", "/projects"),
    "get_project": ("GET", "/projects/{project_id}"),
    "create_project": ("POST", "/projects"),
    "update_project": ("PUT", "/projects/{project_id}"),
    "launch_project": ("POST", "/projects/{project_id}/launch"),
    "cancel_project": ("POST", "/projects/{project_id}/cancel"),
    "get_progress": ("GET", "/projects/{project_id}/progress"),
    "get_invoice": ("GET", "/projects/{project_id}/invoice"),
    "list_documents": ("GET", "/documents"),
    "get_document": ("GET", "/documents/{document_id}"),
    "list_project_documents": ("GET", "/projects/{project_id}/documents"),
    "add_linked_document": ("POST", "/projects/{project_id}/documents"),
    "list_project_glossaries": ("GET", "/projects/{project_id}/glossaries"),
    "list_project_style_guides": ("GET", "/projects/{project_id}/styleguides"),
    "list_activities": ("GET", "/projects/{project_id}/activities"),
    "add_activity": ("POST", "/projects/{project_id}/activities"),
    "list_project_strings": ("GET", "/projects/{project_id}/strings"),
    "package_translations": ("POST", "/projects/{project_id}/package"),
    "check_package": ("GET", "/projects/{project_id}/package/check"),
}


class MotaWordNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-motaword"
    scope_registry = MOTAWORD_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="account")
    webhook_signing_secret_not_issued = True
    edit_examples = ["Create a translation quote", "Track translation progress", "Add a source document", "When a project is completed"]

    @classmethod
    def get_config_model(cls):
        return MotaWordNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None, binary=False):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream" if binary else "application/json"})
        if response.is_error or response.is_redirect:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or "Request failed"
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"MotaWord API {response.status_code}: {str(detail).replace(token, '[redacted]')}")
        if binary:
            return BinaryOutput(data=response.content, content_type=response.headers.get("content-type", "application/octet-stream").split(";")[0], filename="motaword-translations.zip")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise ValueError("MotaWord returned an invalid JSON response") from None

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MotaWord access token")
        op = self.config.config
        if isinstance(op, OnProjectStatus):
            return self.no_event_output(op.operation)
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("project_id", "document_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        if "status" in values:
            values["status[]"] = [values.pop("status")]
        if isinstance(op, AddLinkedDocument):
            values = {"source-links[]": [values]}
        binary = isinstance(op, PackageTranslations)
        data = await self._request(self.config.credentials.access_token, method, path,
            params={"async": 0} if binary else values if method == "GET" else None,
            body=values if method in ("POST", "PUT") and values else None, binary=binary)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"project_id": config.get("project_id")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        project = OnProjectStatus.model_validate(config)
        token = MotaWordAccessTokenCredential.model_validate(credential).access_token
        path = f"/projects/{project.project_id}/webhooks"
        current = await cls._request(token, "GET", path)
        if current.get("callback_url") and current["callback_url"] != webhook_url:
            raise ValueError("This MotaWord project already has a different callback URL; choose another project or remove that callback first")
        data = await cls._request(token, "POST", path, body={"callback_url": webhook_url})
        if "callback_url" in data and data["callback_url"] != webhook_url:
            raise ValueError("MotaWord did not confirm the registered callback URL")
        return {"external_webhook_id": str(project.project_id)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id"):
            return
        project_id = int(config["external_webhook_id"])
        if project_id <= 0:
            raise ValueError("Invalid registered MotaWord project")
        token = MotaWordAccessTokenCredential.model_validate(credential).access_token
        path = f"/projects/{project_id}/webhooks"
        current = await cls._request(token, "GET", path)
        if current.get("callback_url") != config.get("webhook_url") or not config.get("webhook_url"):
            return
        await cls._request(token, "DELETE", path)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Published callbacks have no documented signature or signing secret.
        # The private, platform-minted URL is the delivery capability.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        project = payload.get("project")
        return (payload.get("type") == "project" and payload.get("action") in EVENTS
            and isinstance(project, dict) and str(project.get("id")) == str(config.get("project_id")))

    @classmethod
    def resolve_agent_event(cls, output):
        project = output.get("project")
        action = output.get("action")
        if not isinstance(project, dict) or action not in EVENTS or not project.get("id"):
            return super().resolve_agent_event(output)
        project_id = project["id"]
        text = (f"MotaWord project {project_id} {action}. "
            f"Translation from {project.get('source_language', '')} to {', '.join(project.get('target_languages') or [])}. "
            f"{project.get('word_count', 0)} words. "
            f"Use get_project or get_progress with project_id={project_id} to act.")
        return {"text": text, "title": f"Project {project_id} {action}", "conversation_key": str(project_id)}

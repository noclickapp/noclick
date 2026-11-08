"""DocuSeal API v1 operations. Each operation makes one documented request.

Contract: https://console.docuseal.com/openapi.yml (1.0.0).
Lists return a single page with the provider's pagination cursors. Document
operations return URLs from DocuSeal; they do not download or encode responses.
"""
from typing import Annotated, Literal, Optional, Union, Any
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class DocusealAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Docuseal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.docuseal.com/api",
            "x-credential-instructions": "Copy your API key from the DocuSeal API console and paste the key alone. Choose the region that holds your account. NoClick sends X-Auth-Token only to that region's DocuSeal API. Connecting reads your templates; writes use this key's permissions. Creating submissions sends signature request emails by default; turn Send email off to create without emailing signers.",
        })
    credential_type: Literal["docuseal_api_key"] = Field("docuseal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["global", "eu"] = Field("global", title="Account region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Operation):
    limit: int = Field(20, ge=1, le=100, description="One page only. Use pagination.next as After for the next page.")
    after: Optional[int] = Field(None, ge=1, description="Read records after this cursor ID.")
    before: Optional[int] = Field(None, ge=1, description="Read records before this cursor ID.")
    q: Optional[str] = Field(None, title="Search")
    slug: Optional[str] = None


class ListTemplatesConfig(Page):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    external_id: Optional[str] = None
    folder: Optional[str] = None
    archived: Optional[bool] = None
    shared: Optional[bool] = None


class ListSubmissionsConfig(Page):
    """List submissions."""
    operation: Literal["list_submissions"] = Field("list_submissions", json_schema_extra={"ui:hidden": True})
    template_id: Optional[int] = Field(None, ge=1)
    status: Optional[Literal["completed", "declined", "expired", "pending"]] = None
    template_folder: Optional[str] = None
    archived: Optional[bool] = None


class ListSubmittersConfig(Page):
    """List submitters."""
    operation: Literal["list_submitters"] = Field("list_submitters", json_schema_extra={"ui:hidden": True})
    submission_id: Optional[int] = Field(None, ge=1)
    external_id: Optional[str] = None
    completed_after: Optional[str] = Field(None, description="ISO 8601 date and time.")
    completed_before: Optional[str] = Field(None, description="ISO 8601 date and time.")


class TemplateID(Operation):
    id: int = Field(..., ge=1, title="Template ID")


class SubmissionID(Operation):
    id: int = Field(..., ge=1, title="Submission ID")


class SubmitterID(Operation):
    id: int = Field(..., ge=1, title="Submitter ID")


class GetTemplateConfig(TemplateID):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class ArchiveTemplateConfig(TemplateID):
    """Archive template."""
    operation: Literal["archive_template"] = Field("archive_template", json_schema_extra={"ui:hidden": True})


class UpdateTemplateConfig(TemplateID):
    """Update template."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = None
    external_id: Optional[str] = None
    folder_name: Optional[str] = None
    roles: Optional[list[str]] = None
    archived: Optional[bool] = None


class CloneTemplateConfig(TemplateID):
    """Clone template."""
    operation: Literal["clone_template"] = Field("clone_template", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = None
    external_id: Optional[str] = None
    folder_name: Optional[str] = None


class GetSubmissionConfig(SubmissionID):
    """Get submission."""
    operation: Literal["get_submission"] = Field("get_submission", json_schema_extra={"ui:hidden": True})


class ArchiveSubmissionConfig(SubmissionID):
    """Archive submission."""
    operation: Literal["archive_submission"] = Field("archive_submission", json_schema_extra={"ui:hidden": True})


class UpdateSubmissionConfig(SubmissionID):
    """Update submission."""
    operation: Literal["update_submission"] = Field("update_submission", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = None
    expire_at: Optional[str] = Field(None, description="Expiration date and time. Omit to leave unchanged.")
    archived: Optional[bool] = None


class GetSubmissionDocumentsConfig(SubmissionID):
    """Get submission documents."""
    operation: Literal["get_submission_documents"] = Field("get_submission_documents", json_schema_extra={"ui:hidden": True})
    merge: bool = Field(False, description="Return a merged document URL instead of separate documents.")


class GetSubmitterConfig(SubmitterID):
    """Get submitter."""
    operation: Literal["get_submitter"] = Field("get_submitter", json_schema_extra={"ui:hidden": True})


class UpdateSubmitterConfig(SubmitterID):
    """Update submitter."""
    operation: Literal["update_submitter"] = Field("update_submitter", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = None
    email: Optional[str] = Field(None, json_schema_extra={"format": "email"})
    phone: Optional[str] = None
    external_id: Optional[str] = None
    values: Optional[dict[str, Any]] = Field(None, description="Pre-filled values keyed by document field name.")
    metadata: Optional[dict[str, Any]] = None
    send_email: Optional[bool] = Field(None, description="Set true to re-send the signature request email.")
    send_sms: Optional[bool] = Field(None, description="Set true to re-send the signature request SMS.")
    reply_to: Optional[str] = None
    completed_redirect_url: Optional[str] = None


class Message(Operation):
    subject: Optional[str] = None
    body: Optional[str] = None


class SubmissionSubmitter(Operation):
    email: str = Field(..., json_schema_extra={"format": "email"})
    role: Optional[str] = Field(None, description="Role name from the template, for example First Party.")
    name: Optional[str] = None
    phone: Optional[str] = None
    external_id: Optional[str] = None
    values: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None
    send_email: Optional[bool] = None
    send_sms: Optional[bool] = None
    order: Optional[int] = Field(None, ge=0)


class PdfDocument(Operation):
    name: str = Field(..., min_length=1)
    file: str = Field(..., min_length=1, description="Downloadable PDF URL or base64-encoded PDF content.")


class CreateSubmissionConfig(Operation):
    """Create submission."""
    operation: Literal["create_submission"] = Field("create_submission", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., ge=1)
    submitters: list[SubmissionSubmitter] = Field(..., min_length=1)
    send_email: bool = Field(True, description="Send signature request emails. Set false to create without emailing.")
    send_sms: bool = False
    order: Literal["random", "preserved"] = "preserved"
    completed_redirect_url: Optional[str] = None
    bcc_completed: Optional[str] = None
    reply_to: Optional[str] = None
    expire_at: Optional[str] = None
    variables: Optional[dict[str, Any]] = None
    message: Optional[Message] = None


class CreateTemplateFromPdfConfig(Operation):
    """Create template from pdf."""
    operation: Literal["create_template_from_pdf"] = Field("create_template_from_pdf", json_schema_extra={"ui:hidden": True})
    documents: list[PdfDocument] = Field(..., min_length=1)
    name: Optional[str] = None
    folder_name: Optional[str] = None
    external_id: Optional[str] = Field(None, description="Existing templates with this external ID will be updated.")
    shared_link: bool = Field(False, description="Make this template available via a shared link.")
    flatten: bool = False
    remove_tags: bool = True


class CreateTemplateFromHtmlConfig(Operation):
    """Create template from html."""
    operation: Literal["create_template_from_html"] = Field("create_template_from_html", json_schema_extra={"ui:hidden": True})
    html: str = Field(..., min_length=1, description="HTML with DocuSeal field tags.")
    name: Optional[str] = None
    html_header: Optional[str] = None
    html_footer: Optional[str] = None
    folder_name: Optional[str] = None
    external_id: Optional[str] = Field(None, description="Existing templates with this external ID will be updated.")
    shared_link: bool = Field(False, description="Make this template available via a shared link.")
    size: Literal["Letter", "Legal", "Tabloid", "Ledger", "A0", "A1", "A2", "A3", "A4", "A5", "A6"] = "Letter"


DocusealConfig = Annotated[Union[ListTemplatesConfig, ListSubmissionsConfig, ListSubmittersConfig, GetTemplateConfig, ArchiveTemplateConfig, UpdateTemplateConfig, CloneTemplateConfig, GetSubmissionConfig, ArchiveSubmissionConfig, UpdateSubmissionConfig, GetSubmissionDocumentsConfig, GetSubmitterConfig, UpdateSubmitterConfig, CreateSubmissionConfig, CreateTemplateFromPdfConfig, CreateTemplateFromHtmlConfig], Field(discriminator="operation")]

class DocusealFullConfig(NodeConfig[DocusealConfig, DocusealAPIKeyCredential]):
    pass

ROUTES = {'list_templates': ('GET', '/templates', False), 'list_submissions': ('GET', '/submissions', False), 'list_submitters': ('GET', '/submitters', False), 'get_template': ('GET', '/templates/{id}', False), 'archive_template': ('DELETE', '/templates/{id}', False), 'update_template': ('PUT', '/templates/{id}', True), 'clone_template': ('POST', '/templates/{id}/clone', True), 'get_submission': ('GET', '/submissions/{id}', False), 'archive_submission': ('DELETE', '/submissions/{id}', False), 'update_submission': ('PUT', '/submissions/{id}', True), 'get_submission_documents': ('GET', '/submissions/{id}/documents', False), 'get_submitter': ('GET', '/submitters/{id}', False), 'update_submitter': ('PUT', '/submitters/{id}', True), 'create_submission': ('POST', '/submissions', True), 'create_template_from_pdf': ('POST', '/templates/pdf', True), 'create_template_from_html': ('POST', '/templates/html', True)}


class DocusealNode(WorkflowNode):
    integration_type = "automation-docuseal"
    connection_evidence = ConnectionEvidence(operation="list_templates", noun="templates")

    @classmethod
    def get_config_model(cls):
        return DocusealFullConfig

    @staticmethod
    def _guard_credential(config_data):
        credential = config_data.get("credentials")
        if credential is not None and (not isinstance(credential, dict) or
                credential.get("credential_type", "docuseal_api_key") != "docuseal_api_key"):
            raise ValueError("Attach a DocuSeal API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a DocuSeal API key")
        config, credential = self.config.config, self.config.credentials
        method, path, has_body = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "id"})
        if "{id}" in path:
            path = path.replace("{id}", str(config.id))
        base = {"global": "https://api.docuseal.com", "eu": "https://api.docuseal.eu"}[credential.region]
        kwargs = {"json": values} if has_body else {"params": {
            k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()
        }}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, base + path,
                    headers={"X-Auth-Token": credential.api_key, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("DocuSeal request could not be confirmed; inspect writes before retrying") from None
        if response.status_code != 200:
            # Preserve provider rejection wording for the manual-connect seam.
            detail = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("error") or error.get("message")
                    if isinstance(message, str):
                        detail = ": " + message.replace(credential.api_key, "[redacted]")[:1000]
            except ValueError:
                pass
            raise ValueError(f"DocuSeal request failed (HTTP {response.status_code}){detail}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("DocuSeal returned an invalid JSON response; inspect writes before retrying") from None
        if config.operation.startswith("list_"):
            valid = (isinstance(payload, dict) and isinstance(payload.get("data"), list)
                     and isinstance(payload.get("pagination"), dict))
        elif config.operation == "create_submission":
            valid = isinstance(payload, list) and all(isinstance(v, dict) for v in payload)
        else:
            valid = isinstance(payload, dict) and isinstance(payload.get("id"), int)
        if not valid or isinstance(payload, dict) and ("error" in payload or "errors" in payload):
            raise ValueError("DocuSeal returned an unexpected response; inspect writes before retrying")

        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k.lower() not in {"api_key", "token", "secret", "x-auth-token"}}
            return value

        output = {"data": redact(payload), "http_status": response.status_code}
        await self.emit(output)
        return output

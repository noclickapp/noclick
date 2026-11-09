"""Youtrust Public API v3: one documented API request per operation.

Contract: https://developers.youtrust.com/openapi/public-api-v3.json (3.0).
The provider's published production/sandbox servers retain the yousign.app domain.
List operations return one page and expose the provider's next_cursor unchanged.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASES = {"production": "https://api.yousign.app/v3", "sandbox": "https://api-sandbox.yousign.app/v3"}
Locale = Literal["en", "fr", "de", "it", "nl", "es", "pl", "pt", "ro"]
ResourceID = Annotated[str, Field(min_length=36, max_length=36, json_schema_extra={"format": "uuid"})]


class YoutrustAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Youtrust API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.youtrust.com/docs/api-keys",
        "x-credential-instructions": "Paste your Youtrust API key. Choose the environment the key was created for. NoClick sends it as a Bearer token to the API server published by Youtrust (api.yousign.app or api-sandbox.yousign.app)."})
    credential_type: Literal["youtrust_api_token"] = Field("youtrust_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def ids(cls, value, info):
        if info.field_name.endswith("_id") and info.field_name != "external_id" and value is not None:
            try:
                UUID(value)
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use the resource UUID from Youtrust") from None
        return value


class Page(Input):
    after: str | None = Field(None, min_length=1, max_length=8192, description="Use next_cursor from the preceding page with the same filters.")
    limit: int = Field(100, ge=1, le=100)


class RequestID(Input):
    signature_request_id: ResourceID


class SignerID(RequestID):
    signer_id: ResourceID


class DocumentID(RequestID):
    document_id: ResourceID


class ContactID(Input):
    contact_id: ResourceID


class ListSignatureRequests(Page):
    operation: Literal["list_signature_requests"] = Field("list_signature_requests", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=1000, description="Search signature request names.")
    status: Literal["draft", "approval", "ongoing", "done", "deleted", "expired", "canceled", "declined", "rejected", "paused"] | None = None
    external_id: str | None = Field(None, max_length=255)
    workspace_id: ResourceID | None = None


class GetSignatureRequest(RequestID):
    operation: Literal["get_signature_request"] = Field("get_signature_request", json_schema_extra={"ui:hidden": True})


class RequestFields(Input):
    name: str = Field(..., min_length=1, max_length=128)
    delivery_mode: Literal["none", "email"] = Field("none", description="Email delivery sends invitations when activated.")
    ordered_signers: bool = False
    external_id: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\w\-@.%+]+$")
    workspace_id: ResourceID | None = None


class CreateSignatureRequest(RequestFields):
    operation: Literal["create_signature_request"] = Field("create_signature_request", json_schema_extra={"ui:hidden": True})
    template_id: ResourceID | None = Field(None, description="Create from a template, including its documents and recipients. Omit workspace_id when the template already belongs to a workspace.")


class UpdateSignatureRequest(RequestID):
    operation: Literal["update_signature_request"] = Field("update_signature_request", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=128)
    delivery_mode: Literal["none", "email"] | None = None
    ordered_signers: bool | None = None
    external_id: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\w\-@.%+]+$")


class DeleteSignatureRequest(RequestID):
    operation: Literal["delete_signature_request"] = Field("delete_signature_request", description="Delete the selected signature request. The provider enforces its status restrictions.", json_schema_extra={"ui:hidden": True})


class ActivateSignatureRequest(RequestID):
    operation: Literal["activate_signature_request"] = Field("activate_signature_request", description="Activate the request and notify recipients according to its delivery mode.", json_schema_extra={"ui:hidden": True})


class CancelSignatureRequest(RequestID):
    operation: Literal["cancel_signature_request"] = Field("cancel_signature_request", json_schema_extra={"ui:hidden": True})
    reason: Literal["contractualization_aborted", "errors_in_document", "other"]
    custom_note: str | None = Field(None, max_length=500)


class ListSigners(RequestID):
    operation: Literal["list_signers"] = Field("list_signers", json_schema_extra={"ui:hidden": True})


class GetSigner(SignerID):
    operation: Literal["get_signer"] = Field("get_signer", json_schema_extra={"ui:hidden": True})


class Person(Input):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=100, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    locale: Locale = "en"
    phone_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{1,14}$")


class CreateSigner(RequestID, Person):
    operation: Literal["create_signer"] = Field("create_signer", json_schema_extra={"ui:hidden": True})
    signature_level: Literal["electronic_signature", "advanced_electronic_signature", "qualified_electronic_signature"] = "electronic_signature"
    signature_authentication_mode: Literal["otp_email", "no_otp"] = Field("otp_email", description="Authentication mode; SMS authentication is not exposed here.")


class UpdateSigner(SignerID, Person):
    operation: Literal["update_signer"] = Field("update_signer", json_schema_extra={"ui:hidden": True})


class DeleteSigner(SignerID):
    operation: Literal["delete_signer"] = Field("delete_signer", json_schema_extra={"ui:hidden": True})


class SendSignerReminder(SignerID):
    operation: Literal["send_signer_reminder"] = Field("send_signer_reminder", description="Ask Youtrust to send a reminder to this signer.", json_schema_extra={"ui:hidden": True})


class ListDocuments(RequestID):
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})


class GetDocument(DocumentID):
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})


class DeleteDocument(DocumentID):
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})


class ListContacts(Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class GetContact(ContactID):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class CreateContact(Person):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    company_name: str | None = Field(None, min_length=1, max_length=255)
    job_title: str | None = Field(None, min_length=1, max_length=255)
    workspace_id: ResourceID | None = None


class UpdateContact(ContactID, Person):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    company_name: str | None = Field(None, min_length=1, max_length=255)
    job_title: str | None = Field(None, min_length=1, max_length=255)


class DeleteContact(ContactID):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=10)


class GetTemplate(Input):
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: ResourceID


class ListWorkspaces(Page):
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListSignatureRequests, GetSignatureRequest, CreateSignatureRequest,
    UpdateSignatureRequest, DeleteSignatureRequest, ActivateSignatureRequest, CancelSignatureRequest,
    ListSigners, GetSigner, CreateSigner, UpdateSigner, DeleteSigner, SendSignerReminder,
    ListDocuments, GetDocument, DeleteDocument, ListContacts, GetContact, CreateContact,
    UpdateContact, DeleteContact, ListTemplates, GetTemplate, ListWorkspaces], Field(discriminator="operation")]


class YoutrustConfig(NodeConfig[Operation, YoutrustAPITokenCredential]):
    pass


# Every catalog entry maps to exactly one published contract operation.
REQUEST = "/signature_requests/{signature_request_id}"
SIGNER = REQUEST + "/signers/{signer_id}"
DOCUMENT = REQUEST + "/documents/{document_id}"
ROUTES = {
    "list_signature_requests": ("GET", "/signature_requests", 200),
    "get_signature_request": ("GET", REQUEST, 200),
    "create_signature_request": ("POST", "/signature_requests", 201),
    "update_signature_request": ("PATCH", REQUEST, 200),
    "delete_signature_request": ("DELETE", REQUEST, 204),
    "activate_signature_request": ("POST", REQUEST + "/activate", 201),
    "cancel_signature_request": ("POST", REQUEST + "/cancel", 201),
    "list_signers": ("GET", REQUEST + "/signers", 200),
    "get_signer": ("GET", SIGNER, 200),
    "create_signer": ("POST", REQUEST + "/signers", 201),
    "update_signer": ("PATCH", SIGNER, 200),
    "delete_signer": ("DELETE", SIGNER, 204),
    "send_signer_reminder": ("POST", SIGNER + "/send_reminder", 201),
    "list_documents": ("GET", REQUEST + "/documents", 200),
    "get_document": ("GET", DOCUMENT, 200),
    "delete_document": ("DELETE", DOCUMENT, 204),
    "list_contacts": ("GET", "/contacts", 200),
    "get_contact": ("GET", "/contacts/{contact_id}", 200),
    "create_contact": ("POST", "/contacts", 201),
    "update_contact": ("PATCH", "/contacts/{contact_id}", 200),
    "delete_contact": ("DELETE", "/contacts/{contact_id}", 204),
    "list_templates": ("GET", "/templates", 200),
    "get_template": ("GET", "/templates/{template_id}", 200),
    "list_workspaces": ("GET", "/workspaces", 200),
}
PERSON_FIELDS = {"first_name", "last_name", "email", "locale", "phone_number"}


class YoutrustNode(WorkflowNode):
    integration_type = "automation-youtrust"
    connection_evidence = ConnectionEvidence(noun="Youtrust contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return YoutrustConfig

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Youtrust API token")
        method, template, expected = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for key in tuple(values):
            if "{" + key + "}" in template:
                path = path.replace("{" + key + "}", values.pop(key))
        params, body = None, None
        if method == "GET":
            params = values
            if op.operation == "list_signature_requests":
                params = {(key + "[eq]" if key in {"status", "external_id", "workspace_id"} else key): value for key, value in values.items()}
        elif method in {"POST", "PATCH"} and op.operation != "send_signer_reminder":
            body = values
            if op.operation in {"create_signer", "update_signer"}:
                body = {key: value for key, value in values.items() if key not in PERSON_FIELDS}
                body["info"] = {key: value for key, value in values.items() if key in PERSON_FIELDS}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASES[credential.environment] + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code != expected:
            # Preserve provider rejection text for the connect seam; redact the submitted secret.
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"Youtrust HTTP {response.status_code}: {detail}")
        if expected == 204 or op.operation == "send_signer_reminder":
            result = {"success": True, "http_status": response.status_code, "acknowledged": True}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Youtrust response exceeds the JSON size limit")
            data = response.json()
            if not isinstance(data, (dict, list)) or (isinstance(data, dict) and any(k in data for k in ("error", "errors"))):
                raise ValueError("Unexpected Youtrust response")
            if isinstance(op, Page):
                if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("meta"), dict):
                    raise ValueError("Youtrust page must contain data and pagination metadata")
                cursor = data["meta"].get("next_cursor")
                if cursor is not None and (not isinstance(cursor, str) or not cursor or cursor == op.after):
                    raise ValueError("Youtrust returned an invalid or stalled cursor")
                result = {"data": data["data"], "meta": data["meta"], "next_cursor": cursor, "has_more": cursor is not None}
            else:
                result = {"data": data}
            result.update(success=True, http_status=response.status_code)
        await self.emit(result)
        return result

"""Clicksign Envelope API v3: fixed JSON:API operations with pasted access tokens.

Contract: https://dash.readme.com/api/v1/api-registry/4zre5lmv17lvfy (2.1).
Auth/hosts: https://developers.clicksign.com/docs/ambientes-autenticacao-e-formato
"""
from __future__ import annotations
import json
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-clicksign"

class ClicksignAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Clicksign Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developers.clicksign.com/docs/access-token",
            "x-credential-instructions": "Generate an access token in your Clicksign account settings and paste it here without a Bearer prefix. Choose the environment that issued the token. NoClick reads your envelopes to verify the connection."})
    credential_type: Literal["clicksign_access_token"] = Field("clicksign_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Access token", json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", description="Use the environment that issued your access token.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_id(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value or len(value) > 128 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in value):
                raise ValueError("Paste a single Clicksign resource ID")
        return value

class _EnvelopeFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=1000)
    deadline_at: datetime | None = None
    locale: Literal["pt-BR", "en-US"] | None = None
    auto_close: bool | None = None
    remind_interval: Literal["1", "2", "3", "7", "14", "null"] | None = None
    block_after_refusal: bool | None = None
    default_subject: str | None = None
    default_message: str | None = None
    deadline_partial_signature_action: Literal["closed", "canceled"] | None = None
    folder_id: str | None = Field(None, description="Optional destination folder ID.")

class _Envelope(_Input):
    envelope_id: str = Field(..., min_length=1, description="Clicksign envelope ID.")

class _Document(_Envelope):
    document_id: str = Field(..., min_length=1, description="Document ID within the selected envelope.")

class _Signer(_Envelope):
    signer_id: str = Field(..., min_length=1, description="Signer ID within the selected envelope.")

class _Requirement(_Envelope):
    requirement_id: str = Field(..., min_length=1)

class ClicksignListEnvelopesConfig(_Input):
    """List envelopes."""
    operation: Literal["list_envelopes"] = Field("list_envelopes", json_schema_extra={"ui:hidden": True})
    status: Literal["draft", "running", "closed", "canceled"] | None = None
    name: str | None = None
    sort: Literal["name", "-name"] | None = None

class ClicksignCreateEnvelopeConfig(_EnvelopeFields):
    """Create envelope."""
    operation: Literal["create_envelope"] = Field("create_envelope", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)

class ClicksignGetEnvelopeConfig(_Envelope):
    """Get envelope."""
    operation: Literal["get_envelope"] = Field("get_envelope", json_schema_extra={"ui:hidden": True})

class ClicksignUpdateEnvelopeConfig(_EnvelopeFields):
    """Update envelope."""
    operation: Literal["update_envelope"] = Field("update_envelope", json_schema_extra={"ui:hidden": True})
    envelope_id: str = Field(..., min_length=1)
    status: Literal["draft", "running"] | None = Field(None, description="Set running to activate; activation cannot be undone.")

class ClicksignDeleteEnvelopeConfig(_Envelope):
    """Delete envelope."""
    operation: Literal["delete_envelope"] = Field("delete_envelope", json_schema_extra={"ui:hidden": True})

class ClicksignListDocumentsConfig(_Envelope):
    """List documents."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})

class ClicksignUploadDocumentConfig(_Envelope):
    """Upload document."""
    operation: Literal["upload_document"] = Field("upload_document", json_schema_extra={"ui:hidden": True})
    filename: str = Field(..., min_length=1, description="Filename including extension, e.g. contract.pdf.")
    content_base64: str = Field(..., min_length=1, description="File content as data:<mime>;base64,..., as documented by Clicksign.")
    metadata: dict[str, Any] | None = Field(None, description="JSON object included in document webhooks.")

class ClicksignGetDocumentConfig(_Document):
    """Get document."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})

class ClicksignUpdateDocumentConfig(_Document):
    """Update document."""
    operation: Literal["update_document"] = Field("update_document", json_schema_extra={"ui:hidden": True})
    status: Literal["canceled", "closed"] | None = None
    metadata: dict[str, Any] | None = Field(None, description="JSON object included in document webhooks.")

class ClicksignDeleteDocumentConfig(_Document):
    """Delete document."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})

class ClicksignListSignersConfig(_Envelope):
    """List signers."""
    operation: Literal["list_signers"] = Field("list_signers", json_schema_extra={"ui:hidden": True})

class _CommunicateEvents(_Input):
    signature_request: Literal["none", "email", "whatsapp", "sms"] = "email"
    signature_reminder: Literal["none", "email"] = "email"
    document_signed: Literal["email", "whatsapp"] = "email"

class ClicksignCreateSignerConfig(_Envelope):
    """Create signer."""
    operation: Literal["create_signer"] = Field("create_signer", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description="Full name with at least two words.")
    email: str = Field(..., min_length=1, description="Signer email used for notifications.")
    phone_number: str | None = None
    birthday: date | None = None
    documentation: str | None = None
    has_documentation: bool | None = None
    refusable: bool | None = None
    group: int | None = Field(None, ge=1)
    location_required_enabled: bool | None = None
    communicate_events: _CommunicateEvents | None = None

class ClicksignGetSignerConfig(_Signer):
    """Get signer."""
    operation: Literal["get_signer"] = Field("get_signer", json_schema_extra={"ui:hidden": True})

class ClicksignDeleteSignerConfig(_Signer):
    """Delete signer."""
    operation: Literal["delete_signer"] = Field("delete_signer", json_schema_extra={"ui:hidden": True})

class ClicksignListRequirementsConfig(_Envelope):
    """List requirements."""
    operation: Literal["list_requirements"] = Field("list_requirements", json_schema_extra={"ui:hidden": True})

class ClicksignCreateQualificationRequirementConfig(_Document):
    """Create qualification requirement."""
    operation: Literal["create_qualification_requirement"] = Field("create_qualification_requirement", json_schema_extra={"ui:hidden": True})
    signer_id: str = Field(..., min_length=1)
    role: Literal["sign", "party", "contractor"] = "sign"

class ClicksignCreateAuthenticationRequirementConfig(_Document):
    """Require signer authentication for a document before activating the envelope."""
    operation: Literal["create_authentication_requirement"] = Field("create_authentication_requirement", json_schema_extra={"ui:hidden": True})
    signer_id: str = Field(..., min_length=1)
    auth: Literal["email", "sms", "whatsapp", "pix", "icp_brasil", "handwritten", "selfie", "official_document", "address_proof", "liveness", "facial_biometrics", "identity_biometrics", "auto_signature", "presential", "embedded_signature", "biometric", "documentscopy"] = "email"


class ClicksignDeleteRequirementConfig(_Requirement):
    """Delete requirement."""
    operation: Literal["delete_requirement"] = Field("delete_requirement", json_schema_extra={"ui:hidden": True})

class ClicksignNotifyEnvelopeConfig(_Envelope):
    """Notify envelope."""
    operation: Literal["notify_envelope"] = Field("notify_envelope", json_schema_extra={"ui:hidden": True})
    message: str | None = Field(None, description="Omit to use the envelope default message.")

class ClicksignNotifySignerConfig(_Signer):
    """Notify signer."""
    operation: Literal["notify_signer"] = Field("notify_signer", json_schema_extra={"ui:hidden": True})
    message: str | None = Field(None, description="Omit to use the envelope default message.")

class ClicksignListTemplatesConfig(_Input):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})

class ClicksignGetTemplateConfig(_Input):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1)

class ClicksignListFoldersConfig(_Input):
    """List folders."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    in_root: bool | None = Field(None, description="Filter for folders in the root.")

class ClicksignCreateFolderConfig(_Input):
    """Create folder."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    folder_id: str | None = Field(None, description="Optional parent folder ID.")

class ClicksignGetFolderConfig(_Input):
    """Get folder."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1)

ClicksignConfig = Annotated[Union[
    ClicksignListEnvelopesConfig,
    ClicksignCreateEnvelopeConfig,
    ClicksignGetEnvelopeConfig,
    ClicksignUpdateEnvelopeConfig,
    ClicksignDeleteEnvelopeConfig,
    ClicksignListDocumentsConfig,
    ClicksignUploadDocumentConfig,
    ClicksignGetDocumentConfig,
    ClicksignUpdateDocumentConfig,
    ClicksignDeleteDocumentConfig,
    ClicksignListSignersConfig,
    ClicksignCreateSignerConfig,
    ClicksignGetSignerConfig,
    ClicksignDeleteSignerConfig,
    ClicksignListRequirementsConfig,
    ClicksignCreateQualificationRequirementConfig,
    ClicksignCreateAuthenticationRequirementConfig,
    ClicksignDeleteRequirementConfig,
    ClicksignNotifyEnvelopeConfig,
    ClicksignNotifySignerConfig,
    ClicksignListTemplatesConfig,
    ClicksignGetTemplateConfig,
    ClicksignListFoldersConfig,
    ClicksignCreateFolderConfig,
    ClicksignGetFolderConfig
], Field(discriminator="operation")]

class ClicksignFullConfig(NodeConfig[ClicksignConfig, ClicksignAccessTokenCredential]):
    pass

ROUTES = {'list_envelopes': ('GET', '/envelopes', 'envelopes', [], False),
 'create_envelope': ('POST',
                     '/envelopes',
                     'envelopes',
                     ['name',
                      'deadline_at',
                      'locale',
                      'auto_close',
                      'remind_interval',
                      'block_after_refusal',
                      'default_subject',
                      'default_message',
                      'deadline_partial_signature_action'],
                     True),
 'get_envelope': ('GET', '/envelopes/{envelope_id}', 'envelopes', [], False),
 'update_envelope': ('PATCH',
                     '/envelopes/{envelope_id}',
                     'envelopes',
                     ['name',
                      'deadline_at',
                      'locale',
                      'auto_close',
                      'remind_interval',
                      'block_after_refusal',
                      'default_subject',
                      'default_message',
                      'deadline_partial_signature_action',
                      'status'],
                     True),
 'delete_envelope': ('DELETE', '/envelopes/{envelope_id}', 'envelopes', [], False),
 'list_documents': ('GET', '/envelopes/{envelope_id}/documents', 'documents', [], False),
 'upload_document': ('POST',
                     '/envelopes/{envelope_id}/documents',
                     'documents',
                     ['filename', 'content_base64', 'metadata'],
                     False),
 'get_document': ('GET', '/envelopes/{envelope_id}/documents/{document_id}', 'documents', [], False),
 'update_document': ('PATCH',
                     '/envelopes/{envelope_id}/documents/{document_id}',
                     'documents',
                     ['status', 'metadata'],
                     False),
 'delete_document': ('DELETE', '/envelopes/{envelope_id}/documents/{document_id}', 'documents', [], False),
 'list_signers': ('GET', '/envelopes/{envelope_id}/signers', 'signers', [], False),
 'create_signer': ('POST',
                   '/envelopes/{envelope_id}/signers',
                   'signers',
                   ['name',
                    'email',
                    'phone_number',
                    'birthday',
                    'documentation',
                    'has_documentation',
                    'refusable',
                    'group',
                    'location_required_enabled',
                    'communicate_events'],
                   False),
 'get_signer': ('GET', '/envelopes/{envelope_id}/signers/{signer_id}', 'signers', [], False),
 'delete_signer': ('DELETE', '/envelopes/{envelope_id}/signers/{signer_id}', 'signers', [], False),
 'list_requirements': ('GET', '/envelopes/{envelope_id}/requirements', 'requirements', [], False),
 'create_qualification_requirement': ('POST',
                                      '/envelopes/{envelope_id}/requirements',
                                      'requirements',
                                      ['role'],
                                      False),
 'delete_requirement': ('DELETE',
                        '/envelopes/{envelope_id}/requirements/{requirement_id}',
                        'requirements',
                        [],
                        False),
 'notify_envelope': ('POST', '/envelopes/{envelope_id}/notifications', 'notifications', ['message'], False),
 'notify_signer': ('POST',
                   '/envelopes/{envelope_id}/signers/{signer_id}/notifications',
                   'notifications',
                   ['message'],
                   False),
 'list_templates': ('GET', '/templates', 'templates', [], False),
 'get_template': ('GET', '/templates/{template_id}', 'templates', [], False),
 'list_folders': ('GET', '/folders', 'folders', [], False),
 'create_folder': ('POST', '/folders', 'folders', ['name'], True),
 'get_folder': ('GET', '/folders/{folder_id}', 'folders', [], False),
 'create_authentication_requirement': ('POST',
                                       '/envelopes/{envelope_id}/requirements',
                                       'requirements',
                                       ['auth'],
                                       False)}

class ClicksignNode(WorkflowNode):
    integration_type = "automation-clicksign"
    connection_evidence = ConnectionEvidence(noun="Clicksign envelopes", operation="list_envelopes", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ClicksignFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Clicksign access token")
        credential = self.config.credentials
        op = self.config.config
        method, template, kind, attribute_names, folder_relationship = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items() if k.endswith("_id")})
        host = "app.clicksign.com" if credential.environment == "production" else "sandbox.clicksign.com"
        query = {}
        if op.operation == "list_envelopes":
            for field in ("status", "name"):
                if field in values:
                    query[f"filter[{field}]"] = values[field]
            if "sort" in values:
                query["sort"] = values["sort"]
        if op.operation == "list_folders" and "in_root" in values:
            query["filter[in_root]"] = str(values["in_root"]).lower()
        body = None
        if method in {"POST", "PATCH"}:
            attributes = {k: values[k] for k in attribute_names if k in values}
            data = {"type": kind, "attributes": attributes}
            if method == "PATCH":
                data["id"] = values[kind[:-1] + "_id"]
            if folder_relationship and values.get("folder_id"):
                data["relationships"] = {"folder": {"data": {"type": "folders", "id": values["folder_id"]}}}
            if op.operation in {"create_qualification_requirement", "create_authentication_requirement"}:
                attributes["action"] = "agree" if op.operation == "create_qualification_requirement" else "provide_evidence"
                data["relationships"] = {resource: {"data": {"type": resource + "s", "id": values[resource + "_id"]}} for resource in ("document", "signer")}
            body = {"data": data}
        headers = {"Authorization": credential.access_token, "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, f"https://{host}/api/v3" + path, params=query, headers=headers, **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                # Keep provider rejection text so manual connect can explain an invalid token.
                details = []
                try:
                    errors = response.json().get("errors", [])
                    details = [str(e.get("detail") or e.get("title") or "") for e in errors if isinstance(e, dict)]
                except (ValueError, AttributeError, TypeError):
                    pass
                message = "; ".join(details)[:2000] or f"Clicksign returned HTTP {response.status_code}"
                return {"status": "error", "http_status": response.status_code, "error": message.replace(credential.access_token, "[redacted]")}
            if response.status_code == 204 and method == "DELETE":
                return {"status": "success", "deleted": True}
            result = response.json()
            if not isinstance(result, dict) or "errors" in result or "data" not in result:
                raise ValueError("Expected a JSON:API data response")
            data = result["data"]
            listing = op.operation.startswith("list_")
            if not isinstance(data, list if listing else dict):
                raise ValueError("Unexpected JSON:API resource shape")
            rows = data if listing else [data]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("Expected JSON:API resource objects")
            # Return only the page received; links are metadata, never followed with a token.
            output = {"status": "success", "data": data}
            if listing:
                output["items"] = [{"id": row.get("id"), **(row.get("attributes") or {})} for row in data if isinstance(row, dict)]
                output["links"] = result.get("links", {})
                output["meta"] = result.get("meta", {})
            # Guard against accidentally echoing the secret in any provider field.
            return json.loads(json.dumps(output).replace(credential.access_token, "[redacted]"))
        except (ValueError, httpx.HTTPError):
            return {"status": "error", "error": "Clicksign returned an invalid response or the request could not be completed"}

"""Signable v1: account-scoped electronic signature workflows.

Contract: https://developers.signable.app/_spec/openapi.yaml (1.0.0).
Requests are single calls: pagination is explicit and queued sends are not
reported as delivered. API keys use Basic auth with the documented password x.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.signable.co.uk/v1"


class SignableAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Signable API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://signable.app/",
            "x-credential-instructions": "In Signable, open Company Settings → API & Webhooks, add an API key and paste it here. Use a test key for rehearsals. NoClick sends the key as the Basic username with password x to api.signable.co.uk.",
        })
    credential_type: Literal["signable_api_key"] = Field("signable_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if ":" in value or any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header or password")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    offset: int = Field(0, ge=0, description="Index of the first record. Fetch another page explicitly.")
    limit: int = Field(10, ge=1, le=50, description="Records per page; Signable supports at most 50.")


class _Envelope(_Input):
    envelope_fingerprint: str = Field(..., min_length=1, description="Envelope fingerprint from Signable.")


class SignableListEnvelopesConfig(_Page):
    operation: Literal["list_envelopes"] = "list_envelopes"
    envelope_status: Literal["processing", "failed", "draft", "sent", "qes_in_progress", "signed", "cancelled", "expired", "rejected", "verify"] | None = None
    q: str | None = Field(None, description="Case-insensitive search in the envelope title.")


class SignableParty(_Input):
    party_name: str = Field(..., min_length=1)
    party_email: str = Field(..., min_length=1)
    party_role: Literal["signer", "copy"] = "signer"
    party_id: str | None = Field(None, description="Required when sending a template: the party ID defined in it.")
    party_message: str | None = None
    party_mobile: str | None = Field(None, description="E.164 number; enables OTP for this signer. Omit for copy recipients.")
    party_password: str | None = None

    @model_validator(mode="after")
    def copy_has_no_mobile(self):
        if self.party_role == "copy" and self.party_mobile:
            raise ValueError("Copy recipients cannot use OTP")
        return self


class SignableMergeField(_Input):
    field_id: str
    field_value: str


class SignableDocumentURL(_Input):
    document_title: str = Field(..., min_length=1)
    document_url: str = Field(..., description="Public URL of a PDF, Word or Excel document for Signable to fetch.")


class SignableDocumentFile(_Input):
    document_title: str = Field(..., min_length=1)
    document_file_content: str = Field(..., description="Base64 encoded file contents.")
    document_file_name: str = Field(..., description="Filename ending in .pdf, .docx or .xlsx.")

    @field_validator("document_file_content")
    @classmethod
    def valid_base64(cls, value):
        try:
            base64.b64decode(value, validate=True)
        except ValueError:
            raise ValueError("Use base64 encoded file contents") from None
        return value


class SignableTemplateDocument(_Input):
    document_title: str = Field(..., min_length=1)
    document_template_fingerprint: str = Field(..., min_length=1)
    document_merge_fields: list[SignableMergeField] | None = None


class SignableCreateEnvelopeConfig(_Input):
    """Create an envelope; by default Signable queues it for sending."""
    operation: Literal["create_envelope"] = Field("create_envelope", json_schema_extra={"x-display-name": "Create Envelope (Send or Draft)"})
    envelope_title: str = Field(..., min_length=1)
    envelope_parties: list[SignableParty] = Field(..., min_length=1)
    envelope_documents: list[Union[SignableDocumentURL, SignableDocumentFile, SignableTemplateDocument]] = Field(..., min_length=1)
    is_draft: bool = Field(False, description="Save without sending. False queues the envelope and sends signing emails.")
    user_id: int | None = None
    envelope_redirect_url: str | None = None
    envelope_all_at_once_enabled: bool | None = None
    envelope_password_protect: bool | None = None
    envelope_auto_expire_hours: int | None = Field(None, ge=1)
    envelope_auto_remind_hours: int | None = Field(None, ge=1)
    envelope_meta: dict | None = None

    @model_validator(mode="after")
    def document_mode(self):
        templates = [isinstance(d, SignableTemplateDocument) for d in self.envelope_documents]
        if any(templates):
            if not all(templates) or len(templates) != 1:
                raise ValueError("Send one template per envelope, or send uploaded/URL documents")
            if any(not p.party_id for p in self.envelope_parties):
                raise ValueError("Each template party needs its party_id from the template")
        return self


class SignableGetEnvelopeConfig(_Envelope):
    operation: Literal["get_envelope"] = "get_envelope"


class SignableSendDraftEnvelopeConfig(_Envelope):
    """Send a draft; queues signing emails and can reserve QES credits."""
    operation: Literal["send_draft_envelope"] = "send_draft_envelope"


class SignableDeleteEnvelopeConfig(_Envelope):
    operation: Literal["delete_envelope"] = "delete_envelope"


class SignableRemindEnvelopeConfig(_Envelope):
    """Send reminder emails to outstanding signers and reset the reminder timer."""
    operation: Literal["remind_envelope"] = "remind_envelope"


class SignableCancelEnvelopeConfig(_Envelope):
    """Cancel an active envelope and email signing parties."""
    operation: Literal["cancel_envelope"] = "cancel_envelope"


class SignableExpireEnvelopeConfig(_Envelope):
    operation: Literal["expire_envelope"] = "expire_envelope"


class SignableUpdateEnvelopePartyConfig(_Envelope):
    operation: Literal["update_envelope_party"] = "update_envelope_party"
    party_id: int = Field(..., ge=1)
    party_email: str | None = None
    party_title: str | None = None

    @model_validator(mode="after")
    def changed_field(self):
        if not (self.party_email or self.party_title):
            raise ValueError("Provide a new party email or title")
        return self


class SignableListTemplatesConfig(_Page):
    operation: Literal["list_templates"] = "list_templates"


class SignableGetTemplateConfig(_Input):
    operation: Literal["get_template"] = "get_template"
    template_fingerprint: str = Field(..., min_length=1)


class _Contact(_Input):
    contact_id: int = Field(..., ge=1)


class SignableListContactsConfig(_Page):
    operation: Literal["list_contacts"] = "list_contacts"


class SignableCreateContactConfig(_Input):
    operation: Literal["create_contact"] = "create_contact"
    contact_name: str = Field(..., min_length=1)
    contact_email: str = Field(..., min_length=1)


class SignableGetContactConfig(_Contact):
    operation: Literal["get_contact"] = "get_contact"


class SignableUpdateContactConfig(_Contact):
    operation: Literal["update_contact"] = "update_contact"
    contact_name: str | None = None
    contact_email: str | None = None

    @model_validator(mode="after")
    def changed_field(self):
        if not (self.contact_name or self.contact_email):
            raise ValueError("Provide a contact name or email")
        return self


class SignableDeleteContactConfig(_Contact):
    operation: Literal["delete_contact"] = "delete_contact"


class SignableListContactEnvelopesConfig(_Page):
    operation: Literal["list_contact_envelopes"] = "list_contact_envelopes"
    contact_id: int = Field(..., ge=1)


class SignableListUsersConfig(_Page):
    operation: Literal["list_users"] = "list_users"


class SignableGetUserConfig(_Input):
    operation: Literal["get_user"] = "get_user"
    user_id: int = Field(..., ge=1)


class SignableGetBrandingConfig(_Input):
    operation: Literal["get_branding"] = "get_branding"


class SignableGetSettingsConfig(_Input):
    operation: Literal["get_settings"] = "get_settings"


SignableOperation = Annotated[Union[
    SignableListEnvelopesConfig, SignableCreateEnvelopeConfig, SignableGetEnvelopeConfig,
    SignableSendDraftEnvelopeConfig, SignableDeleteEnvelopeConfig, SignableRemindEnvelopeConfig,
    SignableCancelEnvelopeConfig, SignableExpireEnvelopeConfig, SignableUpdateEnvelopePartyConfig,
    SignableListTemplatesConfig, SignableGetTemplateConfig,
    SignableListContactsConfig, SignableCreateContactConfig, SignableGetContactConfig,
    SignableUpdateContactConfig, SignableDeleteContactConfig, SignableListContactEnvelopesConfig,
    SignableListUsersConfig, SignableGetUserConfig, SignableGetBrandingConfig, SignableGetSettingsConfig,
], Field(discriminator="operation")]


class SignableNodeConfig(NodeConfig[SignableOperation, SignableAPIKeyCredential]):
    pass


# One operation maps to one provider operation. No automatic readbacks, retries,
# redirect following or hidden pagination on writes.
ROUTES = {
    "list_envelopes": ("GET", "/envelopes"),
    "create_envelope": ("POST", "/envelopes"),
    "get_envelope": ("GET", "/envelopes/{envelope_fingerprint}"),
    "send_draft_envelope": ("POST", "/envelopes/{envelope_fingerprint}/send"),
    "delete_envelope": ("DELETE", "/envelopes/{envelope_fingerprint}"),
    "remind_envelope": ("PUT", "/envelopes/{envelope_fingerprint}/remind"),
    "cancel_envelope": ("PUT", "/envelopes/{envelope_fingerprint}/cancel"),
    "expire_envelope": ("PUT", "/envelopes/{envelope_fingerprint}/expire"),
    "update_envelope_party": ("PATCH", "/envelopes/{envelope_fingerprint}/parties/{party_id}"),
    "list_templates": ("GET", "/templates"),
    "get_template": ("GET", "/templates/{template_fingerprint}"),
    "list_contacts": ("GET", "/contacts"),
    "create_contact": ("POST", "/contacts"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "update_contact": ("PUT", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_contact_envelopes": ("GET", "/contacts/{contact_id}/envelopes"),
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/users/{user_id}"),
    "get_branding": ("GET", "/branding"),
    "get_settings": ("GET", "/settings"),
}


class SignableNode(WorkflowNode):
    integration_type = "automation-signable"
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts",
        label_keys=("contact_name", "contact_email", "contact_id"))

    @classmethod
    def get_config_model(cls):
        return SignableNodeConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Signable API key")
        cfg = self.config.config
        method, path = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True, exclude={"operation"})
        for name in tuple(values):
            if "{" + name + "}" in path:
                value = str(values.pop(name))
                if value in {".", ".."} or "/" in value or "\\" in value:
                    raise ValueError("Use a single Signable resource identifier")
                path = path.replace("{" + name + "}", quote(value, safe=""))
        key = self.config.credentials.api_key
        auth = "Basic " + base64.b64encode((key + ":x").encode()).decode()
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": auth, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            message = "Signable request failed"
            try:
                message = str(response.json().get("message", message))
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": message.replace(key, "[redacted]")}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Signable JSON object")
        if isinstance(data.get("http"), int) and data["http"] >= 400:
            return {"status": "error", "http_status": data["http"], "error": str(data.get("message", "Signable rejected the request")).replace(key, "[redacted]")}
        result = {"status": "success", "data": data, "http_status": response.status_code}
        if cfg.operation.startswith("list_"):
            resource = {"list_contact_envelopes": "envelopes"}.get(cfg.operation, cfg.operation.removeprefix("list_"))
            items = data.get(resource)
            if not isinstance(items, list):
                raise ValueError("Signable list response is missing its records")
            result["items"] = items
            result["offset"] = data.get("offset", cfg.offset)
            result["limit"] = data.get("limit", cfg.limit)
            # Return the provider page unchanged; do not follow its next URL.
        if cfg.operation == "create_envelope":
            result["delivery_verified"] = False
        return result

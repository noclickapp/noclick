"""Ignisign v4 JSON operations, pinned to the provider's 4.2.0 contract.

Each operation performs one request. Paginated reads return one provider page;
use the returned pagination data and the page field to continue explicitly.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class IgnisignCredential(BaseModel):
    model_config = ConfigDict(
        title="Ignisign API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.ignisign.io",
            "x-credential-instructions": "Copy your application ID and its environment API key from the Ignisign console. Choose the matching environment. NoClick sends the key as a Bearer token to api.ignisign.io. Connecting reads the application context to verify access.",
        },
    )
    credential_type: Literal["ignisign_api_key"] = Field(
        "ignisign_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )
    app_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        title="Application ID",
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    app_env: Literal["DEVELOPMENT", "STAGING", "PRODUCTION"] = Field(
        "PRODUCTION", title="Environment"
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class IgnisignGetApplication(_Operation):
    """Get Application Context."""

    operation: Literal["get_application"] = Field(
        "get_application", json_schema_extra={"ui:hidden": True}
    )


class IgnisignListSignerProfiles(_Operation):
    """Get Signer Profiles."""

    operation: Literal["list_signer_profiles"] = Field(
        "list_signer_profiles", json_schema_extra={"ui:hidden": True}
    )


class IgnisignGetSignerProfile(_Operation):
    """Get Signer Profile."""

    operation: Literal["get_signer_profile"] = Field(
        "get_signer_profile", json_schema_extra={"ui:hidden": True}
    )
    signer_profile_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignCreateSigner(_Operation):
    """Create a Signer."""

    operation: Literal["create_signer"] = Field(
        "create_signer", json_schema_extra={"ui:hidden": True}
    )
    signer_profile_id: str = Field(
        ...,
        description="The unique identifier of the signer profile that the signer which the signer will be associated.\nthe fields needed to initiate the signers will depends of the configuration of the signer profile. more info: https://ignisign.io/docs/core-concepts/Signers_and_Claims\n",
        max_length=100000,
    )
    external_id: str | None = Field(
        None,
        description="An external identifier that can be used to identify the signer.\nIt's a reference that can be used to identify the signer in the external system.\nIgnisign does not use internally this field to identify the signer.\n",
        max_length=100000,
    )
    first_name: str | None = Field(
        None, description="The first name of the signer.", max_length=100000
    )
    last_name: str | None = Field(
        None, description="The last name of the signer.", max_length=100000
    )
    email: str | None = Field(
        None, description="The email address of the signer.", max_length=100000
    )
    phone_number: str | None = Field(
        None, description="the phone number of the signer.", max_length=100000
    )
    nationality: str | None = Field(
        None, description="The nationality of the signer.", max_length=100000
    )
    birth_date: date | None = Field(
        None, description="the date of birth of the signer."
    )
    birth_place: str | None = Field(
        None, description="the place of birth of the signer.", max_length=100000
    )
    birth_country: str | None = Field(
        None, description="the country of birth of the signer.", max_length=100000
    )


class IgnisignGetSignerDetails(_Operation):
    """Get a Signer with details."""

    operation: Literal["get_signer_details"] = Field(
        "get_signer_details", json_schema_extra={"ui:hidden": True}
    )
    signer_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignGetSigner(_Operation):
    """Get Signer Summary."""

    operation: Literal["get_signer"] = Field(
        "get_signer", json_schema_extra={"ui:hidden": True}
    )
    signer_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignUpdateSigner(_Operation):
    """Update a Signer.  Existing claims are additive; only externalId can be replaced."""

    operation: Literal["update_signer"] = Field(
        "update_signer", json_schema_extra={"ui:hidden": True}
    )
    signer_id: str = Field(
        ...,
        description="The unique identifier of the signer to be updated.",
        max_length=256,
        min_length=1,
        pattern="^[A-Za-z0-9_-]+$",
    )
    signer_profile_id: str | None = Field(
        None,
        description="The unique identifier of the signer profile that the signer which the signer will be associated.\nthe fields needed to initiate the signers will depends of the configuration of the signer profile. more info: https://ignisign.io/docs/core-concepts/Signers_and_Claims\n",
        max_length=100000,
    )
    external_id: str | None = Field(
        None,
        description="An external identifier that can be used to identify the signer.\nIt's a reference that can be used to identify the signer in the external system.\nIgnisign does not use internally this field to identify the signer.\n",
        max_length=100000,
    )
    first_name: str | None = Field(
        None, description="The first name of the signer.", max_length=100000
    )
    last_name: str | None = Field(
        None, description="The last name of the signer.", max_length=100000
    )
    email: str | None = Field(
        None, description="The email address of the signer.", max_length=100000
    )
    phone_number: str | None = Field(
        None, description="the phone number of the signer.", max_length=100000
    )
    nationality: str | None = Field(
        None, description="The nationality of the signer.", max_length=100000
    )
    birth_date: date | None = Field(
        None, description="the date of birth of the signer."
    )
    birth_place: str | None = Field(
        None, description="the place of birth of the signer.", max_length=100000
    )
    birth_country: str | None = Field(
        None, description="the country of birth of the signer.", max_length=100000
    )


class IgnisignSearchSigners(_Operation):
    """Search  Signers."""

    operation: Literal["search_signers"] = Field(
        "search_signers", json_schema_extra={"ui:hidden": True}
    )
    filter: str | None = Field(
        None, description="Provider query filter; omitted when blank."
    )


class IgnisignListSigners(_Operation):
    """Search Signers - Pagination. Only one page is returned."""

    operation: Literal["list_signers"] = Field(
        "list_signers", json_schema_extra={"ui:hidden": True}
    )
    page: int | None = Field(
        None, description="Provider query filter; omitted when blank."
    )


class IgnisignRevokeSigner(_Operation):
    """Revoke a Signer."""

    operation: Literal["revoke_signer"] = Field(
        "revoke_signer", json_schema_extra={"ui:hidden": True}
    )
    signer_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignCreateDocument(_Operation):
    """Create a Document."""

    operation: Literal["create_document"] = Field(
        "create_document", json_schema_extra={"ui:hidden": True}
    )
    signature_request_id: str = Field(
        ...,
        description="The unique identifier of the signature request associated with the document initialization.",
        max_length=100000,
    )
    label: str | None = Field(
        None,
        description="A user-friendly label to identify the document.",
        max_length=100000,
    )
    description: str | None = Field(
        None,
        description="A detailed, human-readable description of the document.",
        max_length=100000,
    )
    external_id: str | None = Field(
        None,
        description="An optional external identifier that can be used to reference the document from external systems. \nIt's a free text. Ignisign's system do not interprete it.\n",
        max_length=100000,
    )


class IgnisignGetDocument(_Operation):
    """Get Document Information."""

    operation: Literal["get_document"] = Field(
        "get_document", json_schema_extra={"ui:hidden": True}
    )
    document_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignUpdateDocument(_Operation):
    """Update Document Information."""

    operation: Literal["update_document"] = Field(
        "update_document", json_schema_extra={"ui:hidden": True}
    )
    document_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )
    label: str | None = Field(
        None,
        description="A user-friendly label to identify the document.",
        max_length=100000,
    )
    description: str | None = Field(
        None,
        description="A detailed, human-readable description of the document.",
        max_length=100000,
    )
    external_id: str | None = Field(
        None,
        description="An optional external identifier that can be used to reference the document from external systems. \nIt's a free text. Ignisign's system do not interprete it.\n",
        max_length=100000,
    )
    template_displayer_id: str | None = Field(None, max_length=100000)
    template_displayer_version: float | None = Field(None)


class IgnisignDeleteDocument(_Operation):
    """Remove a Document."""

    operation: Literal["delete_document"] = Field(
        "delete_document", json_schema_extra={"ui:hidden": True}
    )
    document_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignGetDocumentContext(_Operation):
    """Get a Document Context."""

    operation: Literal["get_document_context"] = Field(
        "get_document_context", json_schema_extra={"ui:hidden": True}
    )
    document_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignListSignatureRequests(_Operation):
    """Get Signature Requests - Paginated. Only one page is returned."""

    operation: Literal["list_signature_requests"] = Field(
        "list_signature_requests", json_schema_extra={"ui:hidden": True}
    )
    page: int | None = Field(None, description="The page number to return.")


class IgnisignUpdateSignatureRequest(_Operation):
    """Update a Signature Request.  The request must be DRAFT. Supply document_ids and signer_ids before publishing."""

    operation: Literal["update_signature_request"] = Field(
        "update_signature_request", json_schema_extra={"ui:hidden": True}
    )
    signature_request_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )
    title: str | None = Field(
        None, description="The title of the signature request.", max_length=100000
    )
    description: str | None = Field(
        None, description="The description of the signature request.", max_length=100000
    )
    expiration_date: datetime | None = Field(
        None,
        description="The expiration date if the `expirationDateIsActivated` parameter is true The action linked to this date is performed every 5 minutes, at 5, 10, 15... 55.",
    )
    expiration_date_is_activated: bool | None = Field(
        None, description="Indicates whether the expiration date is activated."
    )
    language: Literal[
        "AR",
        "BG",
        "BN",
        "CS",
        "DA",
        "DE",
        "EL",
        "EN",
        "ES",
        "ET",
        "FI",
        "FR",
        "GA",
        "HI",
        "HR",
        "HU",
        "IS",
        "IT",
        "JA",
        "KO",
        "LT",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "RU",
        "SK",
        "SL",
        "SQ",
        "SR",
        "SV",
        "TR",
        "UK",
        "ZH",
    ] | None = Field(None)
    document_ids: list[str] | None = Field(
        None,
        description="The ids of the documents that are linked to the signature request.",
    )
    external_id: str | None = Field(
        None,
        description="a free field to store an identifier that can be used to link the signature request to an external system.",
        max_length=100000,
    )
    diffusion_mode: Literal["WHEN_READY", "SCHEDULED"] | None = Field(
        None,
        description="Represents the diffusion mode of a signature request. \n- **WHEN_READY** : The signature request will be sent to the signer as soon it is ready to be signed. This is the default value. <br/>\n  I.E: If there are no document request, the signature request will be sent to the signer as soon as the signature request is PUBLISHED. <br/>\n  If there are document request, the signature request will be sent to the signer as soon as all the document request are have been completed.\n- **SCHEDULED** : The signature request will be sent to the signer at a specific date. This date is specified in the diffusionDate field<br/>\n",
    )
    diffusion_date: datetime | None = Field(
        None,
        description="the diffusion date if `diffusionMode`parameter is `SCHEDULED` The action linked to this date is performed every 5 minutes, at 5, 10, 15... 55.",
    )
    signer_ids: list[str] | None = Field(
        None,
        description="The ids of the signers that have been invited to sign the signature request.",
    )
    extended_auth_session_enabled: bool | None = Field(
        None,
        description="Indicates whether the extended authentication session is enabled. by default took the value of the app setting.",
    )
    signer_ids_as_approver: list[str] | None = Field(
        None, description="the ids of signers that will be approvers"
    )
    recipients: list[str] | None = Field(
        None,
        description="the emails of signers that will receive a copy of the signed document",
    )
    default_signature_method: Literal[
        "SIMPLE_STD", "ADVANCED_SMS", "ADVANCED_STD"
    ] | None = Field(
        None,
        description="Represents the method used for signatures in a signature requests in an Ignisign application.",
    )
    individualize_requests: bool | None = Field(
        None,
        description="Indicates whether the signature request has been created with the `individualizeRequests` option activated. If activated, each signer will receive a separate signature request. Approvers will be included in each signature requests.",
    )
    sign_documents_together: bool | None = Field(
        None,
        description="Applies to `STANDARD` signature requests with several documents. Absent or false (default) - each signer signs the documents one by one, and can finish with some left unsigned (those are cancelled). true - one swipe signs every document.",
    )


class IgnisignPublishSignatureRequest(_Operation):
    """Publish a Signature Request.  Publishing starts signing and may notify signers."""

    operation: Literal["publish_signature_request"] = Field(
        "publish_signature_request", json_schema_extra={"ui:hidden": True}
    )
    signature_request_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignCloseSignatureRequest(_Operation):
    """Close a Signature Request."""

    operation: Literal["close_signature_request"] = Field(
        "close_signature_request", json_schema_extra={"ui:hidden": True}
    )
    signature_request_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignGetSignatureRequest(_Operation):
    """Get a Signature Request Context."""

    operation: Literal["get_signature_request"] = Field(
        "get_signature_request", json_schema_extra={"ui:hidden": True}
    )
    signature_request_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignListWebhooks(_Operation):
    """Get Webhook Endpoints."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks", json_schema_extra={"ui:hidden": True}
    )


class IgnisignCreateWebhook(_Operation):
    """Add a new Webhook Endpoint."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        description="The URL of the webhook endpoint.",
        max_length=100000,
        json_schema_extra={"format": "uri"},
    )
    description: str | None = Field(
        None, description="The description of the webhook endpoint.", max_length=100000
    )


class IgnisignDeleteWebhook(_Operation):
    """Remove a Webhook Endpoint."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook", json_schema_extra={"ui:hidden": True}
    )
    webhook_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )


class IgnisignListWebhookEvents(_Operation):
    """Get Webhook Events. Only one page is returned."""

    operation: Literal["list_webhook_events"] = Field(
        "list_webhook_events", json_schema_extra={"ui:hidden": True}
    )
    webhook_id: str = Field(
        ..., min_length=1, max_length=256, pattern="^[A-Za-z0-9_-]+$"
    )
    filter: str | None = Field(
        None, description="Provider query filter; omitted when blank."
    )
    page: int | None = Field(
        None, description="Provider query filter; omitted when blank."
    )


IgnisignConfig = Annotated[
    Union[
        IgnisignGetApplication,
        IgnisignListSignerProfiles,
        IgnisignGetSignerProfile,
        IgnisignCreateSigner,
        IgnisignGetSignerDetails,
        IgnisignGetSigner,
        IgnisignUpdateSigner,
        IgnisignSearchSigners,
        IgnisignListSigners,
        IgnisignRevokeSigner,
        IgnisignCreateDocument,
        IgnisignGetDocument,
        IgnisignUpdateDocument,
        IgnisignDeleteDocument,
        IgnisignGetDocumentContext,
        IgnisignListSignatureRequests,
        IgnisignUpdateSignatureRequest,
        IgnisignPublishSignatureRequest,
        IgnisignCloseSignatureRequest,
        IgnisignGetSignatureRequest,
        IgnisignListWebhooks,
        IgnisignCreateWebhook,
        IgnisignDeleteWebhook,
        IgnisignListWebhookEvents,
    ],
    Field(discriminator="operation"),
]


class IgnisignFullConfig(NodeConfig[IgnisignConfig, IgnisignCredential]):
    pass


# Fixed provider routes: workflow input can supply only encoded path components.
ROUTES = {
    "get_application": ("GET", "/v4/applications/{appId}/context", {}, {}, {}),
    "list_signer_profiles": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signer-profiles",
        {},
        {},
        {},
    ),
    "get_signer_profile": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signer-profiles/{signerProfileId}",
        {"signer_profile_id": "signerProfileId"},
        {},
        {},
    ),
    "create_signer": (
        "POST",
        "/v4/applications/{appId}/envs/{appEnv}/signers",
        {},
        {},
        {
            "signer_profile_id": "signerProfileId",
            "external_id": "externalId",
            "first_name": "firstName",
            "last_name": "lastName",
            "email": "email",
            "phone_number": "phoneNumber",
            "nationality": "nationality",
            "birth_date": "birthDate",
            "birth_place": "birthPlace",
            "birth_country": "birthCountry",
        },
    ),
    "get_signer_details": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signers/{signerId}/details",
        {"signer_id": "signerId"},
        {},
        {},
    ),
    "get_signer": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signers/{signerId}",
        {"signer_id": "signerId"},
        {},
        {},
    ),
    "update_signer": (
        "PUT",
        "/v4/applications/{appId}/envs/{appEnv}/signers/{signerId}",
        {"signer_id": "signerId"},
        {},
        {
            "signer_id": "signerId",
            "signer_profile_id": "signerProfileId",
            "external_id": "externalId",
            "first_name": "firstName",
            "last_name": "lastName",
            "email": "email",
            "phone_number": "phoneNumber",
            "nationality": "nationality",
            "birth_date": "birthDate",
            "birth_place": "birthPlace",
            "birth_country": "birthCountry",
        },
    ),
    "search_signers": (
        "POST",
        "/v4/applications/{appId}/envs/{appEnv}/signers-search",
        {},
        {"filter": "filter"},
        {},
    ),
    "list_signers": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signers-paginate",
        {},
        {"page": "page"},
        {},
    ),
    "revoke_signer": (
        "DELETE",
        "/v4/applications/{appId}/envs/{appEnv}/signers/{signerId}/revoke",
        {"signer_id": "signerId"},
        {},
        {},
    ),
    "create_document": (
        "POST",
        "/v4/applications/{appId}/envs/{appEnv}/init-documents",
        {},
        {},
        {
            "signature_request_id": "signatureRequestId",
            "label": "label",
            "description": "description",
            "external_id": "externalId",
        },
    ),
    "get_document": (
        "GET",
        "/v4/documents/{documentId}",
        {"document_id": "documentId"},
        {},
        {},
    ),
    "update_document": (
        "PUT",
        "/v4/documents/{documentId}",
        {"document_id": "documentId"},
        {},
        {
            "label": "label",
            "description": "description",
            "external_id": "externalId",
            "template_displayer_id": "templateDisplayerId",
            "template_displayer_version": "templateDisplayerVersion",
        },
    ),
    "delete_document": (
        "DELETE",
        "/v4/documents/{documentId}",
        {"document_id": "documentId"},
        {},
        {},
    ),
    "get_document_context": (
        "GET",
        "/v4/documents/{documentId}/context",
        {"document_id": "documentId"},
        {},
        {},
    ),
    "list_signature_requests": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/signature-requests",
        {},
        {"page": "page"},
        {},
    ),
    "update_signature_request": (
        "PUT",
        "/v4/signature-requests/{signatureRequestId}",
        {"signature_request_id": "signatureRequestId"},
        {},
        {
            "title": "title",
            "description": "description",
            "expiration_date": "expirationDate",
            "expiration_date_is_activated": "expirationDateIsActivated",
            "language": "language",
            "document_ids": "documentIds",
            "external_id": "externalId",
            "diffusion_mode": "diffusionMode",
            "diffusion_date": "diffusionDate",
            "signer_ids": "signerIds",
            "extended_auth_session_enabled": "extendedAuthSessionEnabled",
            "signer_ids_as_approver": "signerIdsAsApprover",
            "recipients": "recipients",
            "default_signature_method": "defaultSignatureMethod",
            "individualize_requests": "individualizeRequests",
            "sign_documents_together": "signDocumentsTogether",
        },
    ),
    "publish_signature_request": (
        "POST",
        "/v4/signature-requests/{signatureRequestId}/publish",
        {"signature_request_id": "signatureRequestId"},
        {},
        {},
    ),
    "close_signature_request": (
        "POST",
        "/v4/signature-requests/{signatureRequestId}/close",
        {"signature_request_id": "signatureRequestId"},
        {},
        {},
    ),
    "get_signature_request": (
        "GET",
        "/v4/signature-requests/{signatureRequestId}/context",
        {"signature_request_id": "signatureRequestId"},
        {},
        {},
    ),
    "list_webhooks": (
        "GET",
        "/v4/applications/{appId}/envs/{appEnv}/webhooks",
        {},
        {},
        {},
    ),
    "create_webhook": (
        "POST",
        "/v4/applications/{appId}/envs/{appEnv}/webhooks",
        {},
        {},
        {"url": "url", "description": "description"},
    ),
    "delete_webhook": (
        "DELETE",
        "/v4/webhooks/{webhookId}",
        {"webhook_id": "webhookId"},
        {},
        {},
    ),
    "list_webhook_events": (
        "GET",
        "/v4/webhooks/{webhookId}/events",
        {"webhook_id": "webhookId"},
        {"filter": "filter", "page": "page"},
        {},
    ),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {
            name: (
                "[redacted]"
                if name.lower() in {"apikey", "api_key", "apisecret", "clientsecret"}
                else _redact(item, key)
            )
            for name, item in value.items()
        }
    return value


class IgnisignNode(WorkflowNode):
    integration_type = "automation-ignisign"
    connection_evidence = ConnectionEvidence(
        noun="Ignisign application",
        identity_operation="get_application",
        identity_keys=("appName", "appId"),
    )

    @classmethod
    def get_config_model(cls):
        return IgnisignFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Ignisign API key")
        op = self.config.config
        method, path, path_fields, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = path.replace("{appId}", quote(credential.app_id, safe="")).replace(
            "{appEnv}", credential.app_env
        )
        for field, wire_name in path_fields.items():
            path = path.replace("{" + wire_name + "}", quote(values[field], safe=""))
        params = {
            wire: values[field]
            for field, wire in query_fields.items()
            if field in values
        }
        body = {
            wire: values[field]
            for field, wire in body_fields.items()
            if field in values
        }
        kwargs = {
            "params": params,
            "headers": {
                "Authorization": "Bearer " + credential.api_key,
                "Accept": "application/json",
            },
        }
        if body_fields:
            kwargs["json"] = body
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method, "https://api.ignisign.io" + path, **kwargs
                )
        except httpx.RequestError:
            return {
                "status": "error",
                "error": "Ignisign could not be reached; the request outcome is unknown",
            }
        if response.status_code != 200:
            # Preserve provider rejection text for the connect seam, without leaking our key.
            message = _redact(response.text[:2000], credential.api_key)
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message or "Ignisign rejected the request",
            }
        if "application/json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Ignisign returned an unexpected content type")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Ignisign returned an unexpected JSON shape")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": _redact(data, credential.api_key)}
        return {"status": "success", "data": _redact(data, credential.api_key)}

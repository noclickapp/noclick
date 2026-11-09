"""Paradym's canonical Wallets API (published OpenAPI version 0.1).

Each operation makes one request. List results retain the provider's cursor metadata;
URLs in responses are data and are never followed by this node.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.paradym.id"


class ParadymAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Paradym API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://paradym.id/app/settings/api-keys",
        "x-credential-instructions": "Create an API key in Paradym Settings → API keys, then paste it here. NoClick sends it in the x-access-token header to api.paradym.id. Wallet listing checks which wallets the key can access.",
    })
    credential_type: Literal["paradym_api_key"] = Field("paradym_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
                raise ValueError("Use a single Paradym resource ID")
        return value


class _Page(_Input):
    page_size: int = Field(10, ge=1, le=100, description="Items per page. Lists return data and meta.next/meta.prev; pass the cursor ID to page_after/page_before.")
    page_after: str | None = Field(None, max_length=200, description="ID of the last record on the previous page.")
    page_before: str | None = Field(None, max_length=200, description="ID of the first record on the next page.")

    @model_validator(mode="after")
    def one_cursor(self):
        if self.page_after is not None and self.page_before is not None:
            raise ValueError("Use only one pagination direction")
        return self


class _Wallet(_Input):
    wallet_id: str = Field(..., description="Wallet ID from list_wallets.")


class _WalletPage(_Page, _Wallet):
    pass


class ListWallets(_Page):
    operation: Literal["list_wallets"] = "list_wallets"
    search_name: str | None = None


class CreateWallet(_Input):
    operation: Literal["create_wallet"] = "create_wallet"
    name: str = Field(..., min_length=1, max_length=500)
    verification_data_access: Literal["webhook", "once", "15min"] | None = Field(None, description="Provider default is webhook. once and 15min enable fetching verification data through the API.")


class UpdateWallet(_Wallet):
    operation: Literal["update_wallet"] = "update_wallet"
    name: str = Field(..., min_length=1, max_length=500, description="New wallet name; only the name is changed.")


class ListCredentialTemplates(_WalletPage):
    operation: Literal["list_credential_templates"] = "list_credential_templates"


class GetCredentialTemplate(_Wallet):
    operation: Literal["get_credential_template"] = "get_credential_template"
    credential_template_id: str


class GetCredentialTemplateSchema(_Wallet):
    operation: Literal["get_credential_template_schema"] = "get_credential_template_schema"
    credential_template_id: str


class ArchiveCredentialTemplate(_Wallet):
    operation: Literal["archive_credential_template"] = "archive_credential_template"
    credential_template_id: str


class CreateCredentialTemplate(_Wallet):
    operation: Literal["create_credential_template"] = "create_credential_template"
    name: str = Field(..., min_length=1)
    vc_type: str = Field(..., min_length=1, description="SD-JWT VC type, for example UniversityCard. Sent as type.")
    attributes: dict[str, Any] = Field(..., description="Paradym attribute definitions keyed by claim name. Each definition declares type, name and optional required/alwaysDisclosed; supports nested attributes.")
    description: str | None = None
    revocable: bool = False


class ListPresentationTemplates(_WalletPage):
    operation: Literal["list_presentation_templates"] = "list_presentation_templates"


class GetPresentationTemplate(_Wallet):
    operation: Literal["get_presentation_template"] = "get_presentation_template"
    presentation_template_id: str


class ArchivePresentationTemplate(_Wallet):
    operation: Literal["archive_presentation_template"] = "archive_presentation_template"
    presentation_template_id: str


class CreatePresentationTemplate(_Wallet):
    operation: Literal["create_presentation_template"] = "create_presentation_template"
    name: str = Field(..., min_length=1)
    description: str | None = None
    credentials: list[dict[str, Any]] = Field(..., min_length=1, description="Paradym presentation credential definitions, including name, format, type, trustedIssuers and attributes.")


class ListIssuedCredentials(_WalletPage):
    operation: Literal["list_issued_credentials"] = "list_issued_credentials"


class IssueCredential(_Wallet):
    operation: Literal["issue_credential"] = "issue_credential"
    credential_template_id: str
    attributes: dict[str, Any] = Field(..., description="Claim values matching the template's JSON schema. Direct SD-JWT issuance supports scalar and object values.")


class ListIssuanceSessions(_WalletPage):
    operation: Literal["list_issuance_sessions"] = "list_issuance_sessions"


class GetIssuanceSession(_Wallet):
    operation: Literal["get_issuance_session"] = "get_issuance_session"
    issuance_id: str


class OfferCredential(_Input):
    credentialTemplateId: str = Field(..., min_length=1)
    attributes: dict[str, Any] | None = None


class CreateIssuanceOffer(_Wallet):
    operation: Literal["create_issuance_offer"] = "create_issuance_offer"
    credentials: list[OfferCredential] = Field(..., min_length=1, description="Template IDs and optional claim values for the credentials to offer.")
    expiration_in_minutes: int = Field(15, ge=1, le=10080)


class ListVerificationSessions(_WalletPage):
    operation: Literal["list_verification_sessions"] = "list_verification_sessions"


class GetVerificationSession(_Wallet):
    operation: Literal["get_verification_session"] = "get_verification_session"
    verification_id: str = Field(..., description="Verification session ID. Reading may consume data when wallet retention is once.")


class CreateVerificationRequest(_Wallet):
    operation: Literal["create_verification_request"] = "create_verification_request"
    presentation_template_id: str
    expiration_in_minutes: int = Field(15, ge=1, le=10080)
    require_response_encryption: bool = True


ParadymConfig = Annotated[Union[
    ListWallets, CreateWallet, UpdateWallet, ListCredentialTemplates, GetCredentialTemplate,
    GetCredentialTemplateSchema, ArchiveCredentialTemplate, CreateCredentialTemplate,
    ListPresentationTemplates, GetPresentationTemplate, ArchivePresentationTemplate,
    CreatePresentationTemplate, ListIssuedCredentials, IssueCredential, ListIssuanceSessions,
    GetIssuanceSession, CreateIssuanceOffer, ListVerificationSessions, GetVerificationSession,
    CreateVerificationRequest,
], Field(discriminator="operation")]


class ParadymFullConfig(NodeConfig[ParadymConfig, ParadymAPIKeyCredential]):
    pass


# The fixed table is also the reviewable mapping to the pinned contract.
ROUTES = {
    "list_wallets": ("GET", "/v1/wallets"),
    "create_wallet": ("POST", "/v1/wallets"),
    "update_wallet": ("PATCH", "/v1/wallets/{wallet_id}"),
    "list_credential_templates": ("GET", "/v1/wallets/{wallet_id}/templates/credentials/sd-jwt-vc"),
    "get_credential_template": ("GET", "/v1/wallets/{wallet_id}/templates/credentials/sd-jwt-vc/{credential_template_id}"),
    "get_credential_template_schema": ("GET", "/v1/wallets/{wallet_id}/templates/credentials/sd-jwt-vc/{credential_template_id}/json-schema"),
    "archive_credential_template": ("DELETE", "/v1/wallets/{wallet_id}/templates/credentials/sd-jwt-vc/{credential_template_id}"),
    "create_credential_template": ("POST", "/v1/wallets/{wallet_id}/templates/credentials/sd-jwt-vc"),
    "list_presentation_templates": ("GET", "/v1/wallets/{wallet_id}/templates/presentations"),
    "get_presentation_template": ("GET", "/v1/wallets/{wallet_id}/templates/presentations/{presentation_template_id}"),
    "archive_presentation_template": ("DELETE", "/v1/wallets/{wallet_id}/templates/presentations/{presentation_template_id}"),
    "create_presentation_template": ("POST", "/v1/wallets/{wallet_id}/templates/presentations"),
    "list_issued_credentials": ("GET", "/v1/wallets/{wallet_id}/issuance"),
    "issue_credential": ("POST", "/v1/wallets/{wallet_id}/issuance/sd-jwt-vc"),
    "list_issuance_sessions": ("GET", "/v1/wallets/{wallet_id}/openid4vc/issuance"),
    "get_issuance_session": ("GET", "/v1/wallets/{wallet_id}/openid4vc/issuance/{issuance_id}"),
    "create_issuance_offer": ("POST", "/v1/wallets/{wallet_id}/openid4vc/issuance/offer"),
    "list_verification_sessions": ("GET", "/v1/wallets/{wallet_id}/openid4vc/verification"),
    "get_verification_session": ("GET", "/v1/wallets/{wallet_id}/openid4vc/verification/{verification_id}"),
    "create_verification_request": ("POST", "/v1/wallets/{wallet_id}/openid4vc/verification/request"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k.replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class ParadymNode(WorkflowNode):
    integration_type = "automation-paradym"
    connection_evidence = ConnectionEvidence(noun="Paradym wallets", operation="list_wallets")

    @classmethod
    def get_config_model(cls):
        return ParadymFullConfig

    async def execute(self, inputs):
        cfg, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Paradym API key")
        method, template = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True)
        path = template.format(**values)  # IDs accept no path separators or controls.
        params, body = {}, None
        if isinstance(cfg, _Page):
            params["page[size]"] = cfg.page_size
            for name in ("after", "before"):
                value = getattr(cfg, "page_" + name)
                if value is not None:
                    params["page[" + name + "]"] = value
            if isinstance(cfg, ListWallets) and cfg.search_name is not None:
                params["search[name]"] = cfg.search_name
        elif isinstance(cfg, CreateWallet):
            body = {"name": cfg.name}
            if cfg.verification_data_access is not None:
                body["verificationDataAccess"] = cfg.verification_data_access
        elif isinstance(cfg, UpdateWallet):
            body = {"name": cfg.name}
        elif isinstance(cfg, CreateCredentialTemplate):
            body = {"name": cfg.name, "type": cfg.vc_type, "attributes": cfg.attributes, "revocable": cfg.revocable}
            if cfg.description is not None:
                body["description"] = cfg.description
        elif isinstance(cfg, CreatePresentationTemplate):
            body = {"name": cfg.name, "credentials": cfg.credentials}
            if cfg.description is not None:
                body["description"] = cfg.description
        elif isinstance(cfg, IssueCredential):
            body = {"credential": {"credentialTemplateId": cfg.credential_template_id, "attributes": cfg.attributes}}
        elif isinstance(cfg, CreateIssuanceOffer):
            body = {"credentials": [c.model_dump(exclude_none=True) for c in cfg.credentials], "expirationInMinutes": cfg.expiration_in_minutes}
        elif isinstance(cfg, CreateVerificationRequest):
            body = {"presentationTemplateId": cfg.presentation_template_id, "expirationInMinutes": cfg.expiration_in_minutes, "requireResponseEncryption": cfg.require_response_encryption}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"x-access-token": credential.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            except httpx.RequestError:
                raise ValueError("Paradym request could not be completed") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, excluding the supplied key.
            raise ValueError(f"Paradym HTTP {response.status_code}: " + str(_redact(response.text[:2000], credential.api_key)))
        if response.status_code == 204:
            return {"success": True}
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Paradym returned an invalid JSON response") from None
        if not isinstance(result, dict):
            raise ValueError("Paradym returned an unexpected JSON response")
        if "error" in result and result["error"] is not None and "id" not in result:
            raise ValueError("Paradym returned an error: " + str(_redact(result["error"], credential.api_key)))
        if isinstance(cfg, _Page) and not isinstance(result.get("data"), list):
            raise ValueError("Paradym returned a list without data")
        # Session status/error describe the credential exchange, not this HTTP request.
        # Keep all single-resource responses under data so those fields remain domain data.
        result = _redact(result, credential.api_key)
        return result if isinstance(cfg, _Page) else {"data": result}

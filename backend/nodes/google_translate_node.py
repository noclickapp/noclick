"""
Google Cloud Translation automation node.

Provides workflow integration with Google Cloud Translation across both editions:
- v3 (Advanced, OAuth / service-account Bearer token, project-scoped):
  translate text, detect language, supported languages, romanize text,
  translate document (inline), batch translate text (LRO), glossaries
  (create / list), and long-running-operation status.
- v2 (Basic, API key via ?key=): translate text, detect language,
  supported languages.

Authentication:
- OAuth 2.0 (Google) for v3 Advanced — scope cloud-translation. Bearer token.
- API key for v2 Basic — passed as the ?key= query parameter.

API base URLs:
- v3: https://translate.googleapis.com/v3
- v2: https://translation.googleapis.com/language/translate/v2
Documentation: https://docs.cloud.google.com/translate/docs/reference/rest

v3 requests are project- and location-scoped (projects/{id}/locations/{loc});
"global" handles most online ops while glossaries/batch require a region
(e.g. us-central1).
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
import uuid as uuid_module
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import bounded_seen_ids
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from nodes.scopes.google_cloud import GOOGLE_TRANSLATE_SCOPES
from utils.google_service_account import (
    BoundedTTLTokenCache,
    GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
    google_service_account_authority_key,
    normalize_google_service_account_private_key,
    require_google_service_account_token_uri,
)
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

GOOGLE_TRANSLATE_V3_BASE = "https://translate.googleapis.com/v3"
GOOGLE_TRANSLATE_V2_BASE = "https://translation.googleapis.com/language/translate/v2"

# Bound the persistent seen-operation set so it cannot grow without limit.
_MAX_SEEN_OPERATION_IDS = 10000


# ============================================================================
# Credential Schemas
# ============================================================================


class GoogleTranslateOAuthCredential(BaseModel):
    """
    OAuth credential for Google Cloud Translation v3 (Advanced).
    Tokens are obtained via the Google OAuth flow, not entered manually.
    """

    credential_type: Literal["google_translate_oauth"] = Field(
        "google_translate_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )
    project_id: Optional[str] = Field(
        None,
        title="GCP Project ID",
        description=(
            "Google Cloud project ID to run v3 Advanced operations under (required "
            "for v3 — it scopes the request and is billed for the translation)."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": [
                "https://www.googleapis.com/auth/cloud-translation",
            ],
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        }
    )


class GoogleTranslateApiKeyCredential(BaseModel):
    """API key credential for Google Cloud Translation v2 (Basic)."""

    credential_type: Literal["google_translate_api_key"] = Field(
        "google_translate_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "Google Cloud API key with the Cloud Translation API enabled. Works for "
            "v2 Basic operations only — v3 Advanced operations reject API keys "
            "(use an OAuth or service-account credential for v3)."
        ),
        json_schema_extra={"ui:widget": "password"},
    )
    project_id: Optional[str] = Field(
        None,
        title="GCP Project ID",
        description="Optional Google Cloud project ID (not required for v2 Basic).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
            "x-credential-instructions": (
                "API keys run v2 Basic operations only. v3 Advanced operations "
                "(romanize, document/batch translate, glossaries, operations) reject "
                "API keys — connect a Google account (OAuth) or add a service-account "
                "key for those."
            ),
        }
    )


class GoogleTranslateServiceAccountCredential(BaseModel):
    """Service-account credential for server-side v3 Advanced access.

    Signs a JWT with the service account's private key and exchanges it for a
    Google OAuth access token per run (cached until near expiry). The project is
    taken from the JSON key. This is the recommended server-to-server auth for
    v3; v2 Basic still uses an API key.
    """

    credential_type: Literal["google_translate_service_account"] = Field(
        "google_translate_service_account", json_schema_extra={"ui:hidden": True}
    )
    client_email: str = Field(
        ..., title="Client Email", description="service account client_email from the JSON key"
    )
    private_key: str = Field(
        ...,
        title="Private Key",
        description="The private_key PEM block from the JSON key",
        json_schema_extra={"ui:widget": "textarea"},
    )
    project_id: str = Field(
        ...,
        title="Project ID",
        description="GCP project id from the JSON key (v3 requests run under this project)",
    )
    private_key_id: Optional[str] = Field(
        None, title="Private Key ID", description="Optional private_key_id from the JSON key"
    )
    token_uri: str = Field(
        GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
        title="Token URI",
        description="OAuth 2.0 token endpoint for the service account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
            "x-credential-instructions": (
                "Create a service account with the 'Cloud Translation API User' role, "
                "download its JSON key, and paste client_email, private_key and project_id."
            ),
        }
    )


GoogleTranslateCredential = Union[
    GoogleTranslateOAuthCredential,
    GoogleTranslateServiceAccountCredential,
    GoogleTranslateApiKeyCredential,
]


_GOOGLE_TRANSLATE_SERVICE_ACCOUNT_SCOPES = (
    "https://www.googleapis.com/auth/cloud-translation",
)

# Authority-fingerprinted, bounded process-local access-token cache.
_sa_token_cache = BoundedTTLTokenCache()


async def _exchange_service_account_access_token(
    credentials: "GoogleTranslateServiceAccountCredential",
) -> str:
    """Sign a JWT with the SA key and exchange it for a cloud-translation token."""
    import jwt as _jwt

    token_uri = require_google_service_account_token_uri(credentials.token_uri)
    private_key = normalize_google_service_account_private_key(credentials.private_key)
    cache_key = google_service_account_authority_key(
        private_key=private_key,
        client_email=credentials.client_email,
        token_uri=token_uri,
        scopes=_GOOGLE_TRANSLATE_SERVICE_ACCOUNT_SCOPES,
        project_id=credentials.project_id,
        private_key_id=credentials.private_key_id,
    )
    now = time.time()
    cached = _sa_token_cache.get(cache_key, now=now)
    if cached is not None:
        return cached

    issued_at = int(now)
    claims = {
        "iss": credentials.client_email,
        "scope": " ".join(_GOOGLE_TRANSLATE_SERVICE_ACCOUNT_SCOPES),
        "aud": token_uri,
        "iat": issued_at,
        "exp": issued_at + 3600,
    }
    headers = {"alg": "RS256", "typ": "JWT"}
    if credentials.private_key_id:
        headers["kid"] = credentials.private_key_id
    assertion = _jwt.encode(
        claims, private_key, algorithm="RS256", headers=headers
    )
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        try:
            err = response.json()
        except Exception:
            err = response.text
        raise ValueError(f"Service account token exchange failed: {err}")
    token = response.json().get("access_token")
    if not token:
        raise ValueError("Service account token exchange returned no access_token")
    _sa_token_cache.put(cache_key, token, expires_at=issued_at + 3600, now=now)
    return token


# ============================================================================
# Operation Configs — v2 Basic (API key)
# ============================================================================


class GoogleTranslateV2TranslateConfig(BaseModel):
    """Translate text using the v2 Basic API (API key)."""

    operation: Literal["v2_translate_text"] = Field(
        "v2_translate_text",
        json_schema_extra={
            "const": "v2_translate_text",
            "ui:hidden": True,
            "x-category": "Translate (Basic)",
            "x-is-trigger": False,
            "x-display-name": "Translate Text (Basic)",
        },
        title="Translate Text (Basic)",
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to translate",
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_language: str = Field(
        ...,
        title="Target Language",
        description="ISO-639 language code to translate into (e.g. es, fr, de)",
    )
    source_language: Optional[str] = Field(
        None,
        title="Source Language",
        description="ISO-639 source language code. Auto-detected if omitted.",
    )
    format: str = Field(
        "text",
        title="Format",
        description="Whether the text is plain text or HTML",
        json_schema_extra={
            "enum": ["text", "html"],
            "enumNames": ["Plain text", "HTML"],
            "x-enum-searchable": True,
        },
    )


class GoogleTranslateV2DetectConfig(BaseModel):
    """Detect the source language of text using the v2 Basic API (API key)."""

    operation: Literal["v2_detect_language"] = Field(
        "v2_detect_language",
        json_schema_extra={
            "const": "v2_detect_language",
            "ui:hidden": True,
            "x-category": "Translate (Basic)",
            "x-is-trigger": False,
            "x-display-name": "Detect Language (Basic)",
        },
        title="Detect Language (Basic)",
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text whose language should be detected",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GoogleTranslateV2LanguagesConfig(BaseModel):
    """List supported languages using the v2 Basic API (API key)."""

    operation: Literal["v2_list_languages"] = Field(
        "v2_list_languages",
        json_schema_extra={
            "const": "v2_list_languages",
            "ui:hidden": True,
            "x-category": "Translate (Basic)",
            "x-is-trigger": False,
            "x-display-name": "List Languages (Basic)",
        },
        title="List Languages (Basic)",
    )
    target_language: Optional[str] = Field(
        None,
        title="Display Language",
        description="Language code to return language names in (e.g. en). Names omitted if blank.",
    )


# ============================================================================
# Operation Configs — v3 Advanced (OAuth / Bearer + project)
# ============================================================================


class _V3ProjectMixin(BaseModel):
    """v3 Advanced is project-scoped, but OAuth tokens carry no project and the
    OAuth connect UI exposes no field to enter one — so every v3 op inherits this
    node-level override. Service-account keys fall back to the project in the key."""

    project_id: Optional[str] = Field(
        None,
        title="GCP Project ID",
        description=(
            "Google Cloud project ID to run this v3 Advanced operation under. "
            "Required when using an OAuth credential (its token carries no "
            "project); service-account credentials fall back to the project in "
            "their key."
        ),
        json_schema_extra={"ui:placeholder": "my-gcp-project"},
    )


class GoogleTranslateV3TranslateConfig(_V3ProjectMixin):
    """Translate one or more strings with the v3 Advanced API."""

    operation: Literal["v3_translate_text"] = Field(
        "v3_translate_text",
        json_schema_extra={
            "const": "v3_translate_text",
            "ui:hidden": True,
            "x-category": "Translate",
            "x-is-trigger": False,
            "x-display-name": "Translate Text (v3)",
        },
        title="Translate Text",
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to translate (use newlines to translate multiple strings)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_language: str = Field(
        ...,
        title="Target Language",
        description="BCP-47 language code to translate into (e.g. es, fr-FR)",
    )
    source_language: Optional[str] = Field(
        None,
        title="Source Language",
        description="BCP-47 source language code. Auto-detected if omitted.",
    )
    mime_type: str = Field(
        "text/plain",
        title="MIME Type",
        description="Content type of the input text",
        json_schema_extra={
            "enum": ["text/plain", "text/html"],
            "enumNames": ["Plain text", "HTML"],
            "x-enum-searchable": True,
        },
    )
    location: str = Field(
        "global",
        title="Location",
        description="GCP location (use 'global' for online translation)",
    )


class GoogleTranslateV3DetectConfig(_V3ProjectMixin):
    """Detect the source language of input text (v3 Advanced)."""

    operation: Literal["v3_detect_language"] = Field(
        "v3_detect_language",
        json_schema_extra={
            "const": "v3_detect_language",
            "ui:hidden": True,
            "x-category": "Translate",
            "x-is-trigger": False,
            "x-display-name": "Detect Language (v3)",
        },
        title="Detect Language",
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text whose language should be detected",
        json_schema_extra={"ui:widget": "textarea"},
    )
    location: str = Field(
        "global", title="Location", description="GCP location (use 'global' for online detection)"
    )


class GoogleTranslateV3LanguagesConfig(_V3ProjectMixin):
    """List languages supported for translation/detection (v3 Advanced)."""

    operation: Literal["v3_supported_languages"] = Field(
        "v3_supported_languages",
        json_schema_extra={
            "const": "v3_supported_languages",
            "ui:hidden": True,
            "x-category": "Translate",
            "x-is-trigger": False,
            "x-display-name": "Get Supported Languages (v3)",
        },
        title="Get Supported Languages",
    )
    display_language: Optional[str] = Field(
        None,
        title="Display Language",
        description="Language code to return human-readable language names in (e.g. en)",
    )
    location: str = Field(
        "global", title="Location", description="GCP location"
    )


class GoogleTranslateRomanizeConfig(_V3ProjectMixin):
    """Transliterate non-Latin-script text into Latin (romanization)."""

    operation: Literal["v3_romanize_text"] = Field(
        "v3_romanize_text",
        json_schema_extra={
            "const": "v3_romanize_text",
            "ui:hidden": True,
            "x-category": "Translate",
            "x-is-trigger": False,
            "x-display-name": "Romanize Text (v3)",
        },
        title="Romanize Text",
    )
    text: str = Field(
        ...,
        title="Text",
        description="The text to romanize",
        json_schema_extra={"ui:widget": "textarea"},
    )
    source_language: str = Field(
        ...,
        title="Source Language",
        description="BCP-47 source language code of the text (e.g. hi, ja, ar)",
    )
    location: str = Field("global", title="Location", description="GCP location")


class GoogleTranslateTranslateDocumentConfig(_V3ProjectMixin):
    """Translate a single document inline, preserving formatting (v3 Advanced)."""

    operation: Literal["v3_translate_document"] = Field(
        "v3_translate_document",
        json_schema_extra={
            "const": "v3_translate_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Translate Document (v3)",
        },
        title="Translate Document",
    )
    document_content: str = Field(
        ...,
        title="Document Content (base64)",
        description="Base64-encoded document bytes to translate",
        json_schema_extra={"ui:widget": "textarea"},
    )
    document_mime_type: str = Field(
        "application/pdf",
        title="Document MIME Type",
        description="MIME type of the document (e.g. application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document)",
    )
    target_language: str = Field(
        ..., title="Target Language", description="BCP-47 language code to translate into"
    )
    source_language: Optional[str] = Field(
        None, title="Source Language", description="BCP-47 source language code. Auto-detected if omitted."
    )
    location: str = Field(
        "us-central1",
        title="Location",
        description="GCP region (document translation requires a regional location)",
    )


class GoogleTranslateBatchTranslateTextConfig(_V3ProjectMixin):
    """Async bulk text translation from/to Cloud Storage (returns an LRO)."""

    operation: Literal["v3_batch_translate_text"] = Field(
        "v3_batch_translate_text",
        json_schema_extra={
            "const": "v3_batch_translate_text",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Batch Translate Text (v3)",
        },
        title="Batch Translate Text",
    )
    source_language: str = Field(
        ..., title="Source Language", description="BCP-47 source language code"
    )
    target_languages: str = Field(
        ...,
        title="Target Languages",
        description="Comma-separated BCP-47 target language codes (e.g. es,fr,de)",
    )
    input_gcs_uri: str = Field(
        ...,
        title="Input GCS URI",
        description="Cloud Storage input URI (e.g. gs://bucket/input.tsv)",
        json_schema_extra={
            "ui:help": (
                "The Cloud Translation service agent must have read access to this "
                "bucket, or the job fails with PERMISSION_DENIED. Grant "
                "roles/storage.objectViewer to "
                "service-<project-number>@gcp-sa-translation.iam.gserviceaccount.com."
            )
        },
    )
    input_mime_type: str = Field(
        "text/plain",
        title="Input MIME Type",
        description="MIME type of the input files (text/plain or text/html)",
    )
    output_gcs_uri_prefix: str = Field(
        ...,
        title="Output GCS URI Prefix",
        description="Cloud Storage output prefix (e.g. gs://bucket/output/)",
        json_schema_extra={
            "ui:help": (
                "Must be empty. The Cloud Translation service agent needs "
                "roles/storage.objectAdmin on this bucket to write results."
            )
        },
    )
    location: str = Field(
        "us-central1", title="Location", description="GCP region (batch requires a regional location)"
    )


class GoogleTranslateCreateGlossaryConfig(_V3ProjectMixin):
    """Create a glossary for custom terminology (returns an LRO)."""

    operation: Literal["v3_create_glossary"] = Field(
        "v3_create_glossary",
        json_schema_extra={
            "const": "v3_create_glossary",
            "ui:hidden": True,
            "x-category": "Glossaries",
            "x-is-trigger": False,
            "x-display-name": "Create Glossary (v3)",
        },
        title="Create Glossary",
    )
    glossary_id: str = Field(
        ..., title="Glossary ID", description="Identifier for the new glossary"
    )
    source_language: str = Field(
        ..., title="Source Language", description="BCP-47 source language code"
    )
    target_language: str = Field(
        ..., title="Target Language", description="BCP-47 target language code"
    )
    input_gcs_uri: str = Field(
        ...,
        title="Input GCS URI",
        description="Cloud Storage URI of the glossary file (e.g. gs://bucket/glossary.csv)",
        json_schema_extra={
            "ui:help": (
                "The Cloud Translation service agent must have read access to this "
                "bucket, or the create job fails with PERMISSION_DENIED. Grant "
                "roles/storage.objectViewer to "
                "service-<project-number>@gcp-sa-translation.iam.gserviceaccount.com."
            )
        },
    )
    location: str = Field(
        "us-central1", title="Location", description="GCP region for the glossary"
    )


class GoogleTranslateListGlossariesConfig(_V3ProjectMixin):
    """List glossaries in a project/location."""

    operation: Literal["v3_list_glossaries"] = Field(
        "v3_list_glossaries",
        json_schema_extra={
            "const": "v3_list_glossaries",
            "ui:hidden": True,
            "x-category": "Glossaries",
            "x-is-trigger": False,
            "x-display-name": "List Glossaries (v3)",
        },
        title="List Glossaries",
    )
    location: str = Field("us-central1", title="Location", description="GCP region")
    page_size: Optional[str] = Field(
        "50", title="Page Size", description="Maximum number of glossaries to return"
    )


class GoogleTranslateGetOperationConfig(_V3ProjectMixin):
    """Poll the status of a long-running operation (batch/glossary jobs)."""

    operation: Literal["v3_get_operation"] = Field(
        "v3_get_operation",
        json_schema_extra={
            "const": "v3_get_operation",
            "ui:hidden": True,
            "x-category": "Operations",
            "x-is-trigger": False,
            "x-display-name": "Get Operation Status (v3)",
        },
        title="Get Operation Status",
    )
    operation_name: str = Field(
        ...,
        title="Operation Name",
        description="Full LRO name (projects/.../locations/.../operations/...) or just the operation id",
    )
    location: str = Field("us-central1", title="Location", description="GCP region")


# ============================================================================
# Trigger Config — poll long-running operations for newly completed jobs
# ============================================================================


class GoogleTranslateOnBatchCompletedConfig(_V3ProjectMixin):
    """Trigger when a long-running operation (batch translate, glossary, or
    custom-model job) newly reaches ``done=true``.

    Google Cloud Translation ships no provider webhooks; async jobs are LROs
    polled via ``operations.list``/``operations.get``. This trigger polls the
    project/location's operations on a schedule, emits operations that newly
    completed since the last poll, and dedupes by operation name."""

    operation: Literal["on_batch_completed"] = Field(
        "on_batch_completed",
        title="On Batch Operation Completed",
        description="Trigger when a batch/glossary/model job finishes",
        json_schema_extra={
            "const": "on_batch_completed",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Batch Operation Completed",
        },
    )
    location: str = Field(
        "us-central1",
        title="Location",
        description="GCP region whose operations to watch (e.g. us-central1)",
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll for newly completed operations",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    max_results: int = Field(
        25,
        title="Max Operations",
        description="Maximum number of operations to fetch per poll (1-100)",
        ge=1,
        le=100,
    )
    # Hidden internal fields for webhook/schedule management.
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


GoogleTranslateConfig = Annotated[
    Union[
        GoogleTranslateV3TranslateConfig,
        GoogleTranslateV3DetectConfig,
        GoogleTranslateV3LanguagesConfig,
        GoogleTranslateRomanizeConfig,
        GoogleTranslateTranslateDocumentConfig,
        GoogleTranslateBatchTranslateTextConfig,
        GoogleTranslateCreateGlossaryConfig,
        GoogleTranslateListGlossariesConfig,
        GoogleTranslateGetOperationConfig,
        GoogleTranslateV2TranslateConfig,
        GoogleTranslateV2DetectConfig,
        GoogleTranslateV2LanguagesConfig,
        # Trigger
        GoogleTranslateOnBatchCompletedConfig,
    ],
    Discriminator("operation"),
]


class GoogleTranslateNodeConfig(NodeConfig[GoogleTranslateConfig, GoogleTranslateCredential]):
    """Full configuration for the Google Translate node including credentials."""

    pass


# ============================================================================
# Request helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


async def _google_translate_request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make a Google Translation API request and return a structured result."""
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_obj = err.get("error", err) if isinstance(err, dict) else err
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else str(error_obj)
                    )
                except Exception:
                    message = response.text
                logger.error(f"[GoogleTranslateNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[GoogleTranslateNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# Operations that run against v3 Advanced (require OAuth Bearer + project id).
_V3_OPERATIONS = {
    "v3_translate_text",
    "v3_detect_language",
    "v3_supported_languages",
    "v3_romanize_text",
    "v3_translate_document",
    "v3_batch_translate_text",
    "v3_create_glossary",
    "v3_list_glossaries",
    "v3_get_operation",
    "on_batch_completed",
}


# ============================================================================
# Node Implementation
# ============================================================================


# Single-value language fields that get the searchable language dropdown
# (populated by load_field_options). target_languages (plural, comma-separated)
# is excluded — it holds a list, not one code.
_LANGUAGE_DROPDOWN_FIELDS = frozenset(
    {"target_language", "source_language", "display_language"}
)


class GoogleTranslateNode(WorkflowNode):
    """Google Cloud Translation automation node (v2 Basic + v3 Advanced)."""

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Inject the searchable language dropdown (x-dynamic-options) onto every
        language field across all operations, so the dropdown is wired without
        per-field boilerplate. Fields keep allow_custom so any ISO code can still
        be typed even before a credential is connected."""
        schema = super().get_config_schema()

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    for fname, fschema in props.items():
                        if (
                            fname in _LANGUAGE_DROPDOWN_FIELDS
                            and isinstance(fschema, dict)
                            and "x-dynamic-options" not in fschema
                            and not fschema.get("ui:hidden")
                        ):
                            fschema["x-dynamic-options"] = {
                                "field_name": fname,
                                "placeholder": "Select a language…",
                                "searchable": True,
                                "allow_custom": True,
                                "custom_placeholder": "Or type an ISO code (e.g. es)",
                            }
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
        return schema

    edit_examples = [
        "Translate text into Spanish",
        "Detect the language of an incoming message",
        "List the languages supported by Google Translate",
        "Romanize Japanese text into the Latin alphabet",
        "Translate a document while preserving its formatting",
    ]

    scope_registry = GOOGLE_TRANSLATE_SCOPES
    # Translate has no per-account data at all: the language list is identical
    # for every API key, so this verifies the key and claims nothing more.
    connection_evidence = ConnectionEvidence(
        field="target_language",
        noun="supported languages",
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return GoogleTranslateNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The batch-completed trigger is poll-based: the webhook is a wake-up
        signal, not data. Return None so execute() runs and polls operations.list.
        Other (non-trigger) operations have no webhook delivery path."""
        if config.get("operation") == "on_batch_completed":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """No operations newly completed on a scheduled poll -> skip downstream.
        Dedup is driven by the persistent seen-set in node state; emptiness is
        read off the poll output's operations list. See ``WorkflowNode``."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_batch_completed"
            and not output.get("operations")
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the webhook + polling schedule for the batch-completed
        trigger (same pattern as Gmail / CronTriggerNode)."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name != "webhook_url":
            return {"value": None}

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        webhook_id = webhook_data.get("webhook_id")
        webhook_url = webhook_data.get("webhook_url")

        schedule = {"frequency": "minutes", "interval": 5}
        if context and context.get("schedule"):
            schedule = context["schedule"]
        cron_expression = schedule_to_cron(schedule)
        logger.info(
            f"[GoogleTranslateNode] Trigger schedule {schedule} -> cron: {cron_expression}"
        )

        existing_schedule_id = context.get("schedule_id") if context else None
        schedule_id = existing_schedule_id
        next_run = None

        if is_cron_scheduler_enabled() and webhook_url:
            if existing_schedule_id:
                result = await update_schedule(
                    schedule_id=existing_schedule_id,
                    cron_expression=cron_expression,
                )
                if result.get("success"):
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to update schedule: {result['error']}")
                    existing_schedule_id = None

            if not existing_schedule_id:
                result = await create_schedule(
                    user_id=user_id,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    cron_expression=cron_expression,
                    webhook_url=webhook_url,
                    payload={"source": "google_translate_trigger", "node_id": node_id},
                )
                if "id" in result:
                    schedule_id = result["id"]
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to create schedule: {result['error']}")

        interval_ms = schedule_to_interval_ms(schedule)

        return {
            "values": {
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
                "schedule_id": schedule_id,
                "next_run": next_run,
                "interval_ms": interval_ms,
                "is_active": True,
            }
        }

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    # ------------------------------------------------------------------
    # Dynamic options (target/source language dropdowns)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate language dropdowns for every credential type via the v2 Basic
        ``/languages`` endpoint — it accepts an API key OR an OAuth/service-account
        Bearer token and needs no project, so it works even for an OAuth connection
        with no project set (v3's ``supportedLanguages`` is project-scoped and would
        fail there). ``credential_data`` arrives already loaded, decrypted and
        freshened by the workflow handler."""
        if field_name not in ("target_language", "source_language", "display_language"):
            return {"options": []}
        cred = credential_data or {}
        options: List[Dict[str, str]] = []

        # The v2 Basic /languages endpoint returns the full language list and
        # accepts EITHER an API key OR an OAuth/service-account Bearer token, and
        # (unlike v3) needs no project — so it populates the dropdown for every
        # credential type, including an OAuth connection with no project set.
        params: Dict[str, Any] = {"target": "en"}
        headers: Dict[str, str] = {}
        api_key = cred.get("api_key")
        if api_key:
            params["key"] = api_key
        elif cred.get("access_token"):
            headers["Authorization"] = f"Bearer {cred['access_token']}"
            if cred.get("project_id"):
                headers["x-goog-user-project"] = cred["project_id"]
        elif cred.get("client_email") and cred.get("private_key"):
            # Service account — mint a token from the JSON key.
            try:
                sa = GoogleTranslateServiceAccountCredential(**cred)
                token = await _exchange_service_account_access_token(sa)
            except Exception:
                return {"options": []}
            headers["Authorization"] = f"Bearer {token}"
            if cred.get("project_id"):
                headers["x-goog-user-project"] = cred["project_id"]
        else:
            return {"options": []}

        result = await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V2_BASE}/languages",
            params=params,
            headers=headers,
            action_name="v2_list_languages",
        )
        if result.get("status") == "success":
            for lang in (result.get("data") or {}).get("data", {}).get("languages", []):
                if isinstance(lang, dict) and lang.get("language"):
                    code = lang["language"]
                    options.append({"label": f"{lang.get('name') or code} ({code})", "value": code})
        return {"options": options}

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(self, credentials: GoogleTranslateOAuthCredential) -> str:
        """Return a valid v3 access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GoogleTranslateNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add a Google Translate API key (Basic) "
                "or connect your Google account (Advanced)."
            )

        is_v3 = op.operation in _V3_OPERATIONS

        if is_v3:
            if isinstance(credentials, GoogleTranslateOAuthCredential):
                access_token = await self._ensure_fresh_token(credentials)
            elif isinstance(credentials, GoogleTranslateServiceAccountCredential):
                access_token = await _exchange_service_account_access_token(credentials)
            elif isinstance(credentials, GoogleTranslateApiKeyCredential):
                raise ValueError(
                    "v3 Advanced operations require an OAuth or service-account "
                    "credential, not an API key. Connect a Google account or add a "
                    "service-account key for this operation."
                )
            else:
                raise ValueError("Unsupported credential type for v3 operation")

            project_id = (
                getattr(op, "project_id", None)
                or getattr(credentials, "project_id", None)
                or (self.node_data or {}).get("project_id")
            )
            if not project_id:
                raise ValueError(
                    "A GCP project ID is required for v3 Advanced operations. "
                    "Set the 'GCP Project ID' field on this operation (OAuth tokens "
                    "carry no project); service-account credentials use the project "
                    "from their key."
                )
            handler = self._V3_HANDLERS.get(op.operation)
            if not handler:
                raise ValueError(f"Unknown operation: {op.operation}")
            result = await handler(self, op, access_token, project_id)
        else:
            # v2 Basic accepts an API key (?key=) OR an OAuth / service-account
            # Bearer token — so any credential the user connected runs v2 ops.
            if isinstance(credentials, GoogleTranslateApiKeyCredential):
                auth = {"params": {"key": credentials.api_key}, "headers": {}}
            elif isinstance(credentials, GoogleTranslateOAuthCredential):
                auth = self._v2_bearer_auth(
                    await self._ensure_fresh_token(credentials), credentials.project_id
                )
            elif isinstance(credentials, GoogleTranslateServiceAccountCredential):
                auth = self._v2_bearer_auth(
                    await _exchange_service_account_access_token(credentials),
                    credentials.project_id,
                )
            else:
                raise ValueError("Unsupported credential type for v2 operation")
            handler = self._V2_HANDLERS.get(op.operation)
            if not handler:
                raise ValueError(f"Unknown operation: {op.operation}")
            result = await handler(self, op, auth)

        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # v3 helpers
    # ------------------------------------------------------------------
    def _v2_bearer_auth(self, access_token: str, project_id: Optional[str]) -> Dict[str, Any]:
        """v2 auth via an OAuth/service-account Bearer token (project sets the
        quota/billing project when present)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        if project_id:
            headers["x-goog-user-project"] = project_id
        return {"params": {}, "headers": headers}

    def _v3_parent(self, project_id: str, location: str) -> str:
        return f"projects/{project_id}/locations/{location}"

    def _v3_headers(self, access_token: str, project_id: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": project_id,
        }

    # ------------------------------------------------------------------
    # v3 handlers
    # ------------------------------------------------------------------
    async def _v3_translate_text(
        self, c: GoogleTranslateV3TranslateConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        body = {
            "contents": c.text.split("\n") if "\n" in c.text else [c.text],
            "targetLanguageCode": c.target_language,
            "sourceLanguageCode": c.source_language,
            "mimeType": c.mime_type,
        }
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}:translateText",
            headers=self._v3_headers(access_token, project_id),
            json_body=body,
            action_name="v3_translate_text",
        )

    async def _v3_detect_language(
        self, c: GoogleTranslateV3DetectConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}:detectLanguage",
            headers=self._v3_headers(access_token, project_id),
            json_body={"content": c.text},
            action_name="v3_detect_language",
        )

    async def _v3_supported_languages(
        self, c: GoogleTranslateV3LanguagesConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        params = {"displayLanguageCode": c.display_language} if c.display_language else None
        return await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}/supportedLanguages",
            headers=self._v3_headers(access_token, project_id),
            params=params,
            action_name="v3_supported_languages",
        )

    async def _v3_romanize_text(
        self, c: GoogleTranslateRomanizeConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        body = {
            "contents": [c.text],
            "sourceLanguageCode": c.source_language,
        }
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}:romanizeText",
            headers=self._v3_headers(access_token, project_id),
            json_body=body,
            action_name="v3_romanize_text",
        )

    async def _v3_translate_document(
        self, c: GoogleTranslateTranslateDocumentConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        body = {
            "targetLanguageCode": c.target_language,
            "sourceLanguageCode": c.source_language,
            "documentInputConfig": {
                "content": c.document_content,
                "mimeType": c.document_mime_type,
            },
        }
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}:translateDocument",
            headers=self._v3_headers(access_token, project_id),
            json_body=body,
            action_name="v3_translate_document",
        )

    async def _v3_batch_translate_text(
        self, c: GoogleTranslateBatchTranslateTextConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        body = {
            "sourceLanguageCode": c.source_language,
            "targetLanguageCodes": _comma_list(c.target_languages),
            "inputConfigs": [
                {
                    "gcsSource": {"inputUri": c.input_gcs_uri},
                    "mimeType": c.input_mime_type,
                }
            ],
            "outputConfig": {"gcsDestination": {"outputUriPrefix": c.output_gcs_uri_prefix}},
        }
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}:batchTranslateText",
            headers=self._v3_headers(access_token, project_id),
            json_body=body,
            action_name="v3_batch_translate_text",
        )

    async def _v3_create_glossary(
        self, c: GoogleTranslateCreateGlossaryConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        body = {
            "name": f"{parent}/glossaries/{c.glossary_id}",
            "languagePair": {
                "sourceLanguageCode": c.source_language,
                "targetLanguageCode": c.target_language,
            },
            "inputConfig": {"gcsSource": {"inputUri": c.input_gcs_uri}},
        }
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}/glossaries",
            headers=self._v3_headers(access_token, project_id),
            json_body=body,
            action_name="v3_create_glossary",
        )

    async def _v3_list_glossaries(
        self, c: GoogleTranslateListGlossariesConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        parent = self._v3_parent(project_id, c.location)
        return await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}/glossaries",
            headers=self._v3_headers(access_token, project_id),
            params={"pageSize": c.page_size},
            action_name="v3_list_glossaries",
        )

    async def _v3_get_operation(
        self, c: GoogleTranslateGetOperationConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        name = c.operation_name
        if not name.startswith("projects/"):
            name = f"{self._v3_parent(project_id, c.location)}/operations/{name}"
        return await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{name}",
            headers=self._v3_headers(access_token, project_id),
            action_name="v3_get_operation",
        )

    async def _on_batch_completed(
        self, c: GoogleTranslateOnBatchCompletedConfig, access_token: str, project_id: str
    ) -> Dict[str, Any]:
        """Poll operations.list for LROs that newly reached done=true (batch
        translate, glossary, model jobs). The first poll after the trigger is
        created *baselines* — it records the currently-completed operations as
        seen and emits nothing, so enabling the trigger never floods the workflow
        with every pre-existing batch/glossary/model job. Later polls emit only
        operations not seen before, deduping by operation name."""
        parent = self._v3_parent(project_id, c.location)
        # Cloud Translation's operations.list rejects a "done" filter (400), so we
        # fetch the most recent operations and filter to done=true client-side.
        result = await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V3_BASE}/{parent}/operations",
            headers=self._v3_headers(access_token, project_id),
            params={"pageSize": c.max_results},
            action_name="on_batch_completed",
        )
        if result.get("status") != "success":
            return result

        all_ops = (result.get("data") or {}).get("operations", []) or []
        done_ops = [
            op for op in all_ops if isinstance(op, dict) and op.get("done") and op.get("name")
        ]

        # Dedup cursor lives in persistent node state (scoped to workflow+node),
        # NOT in the config: the framework never writes trigger output back to the
        # config, so a config-held cursor would re-fire every completed op on every
        # poll. The seen-set write is a compare-and-swap (``_update_node_state``),
        # so an overlapping poll on another container that already emitted these
        # operations wins and this poll re-reads and emits nothing — no in-process
        # lock and no double-fire across containers.
        def mutator(state):
            seen_list = state.get("seen_operation_ids", [])
            is_first_poll = "seen_operation_ids" not in state
            seen = set(seen_list)
            done_names = [op["name"] for op in done_ops]

            if is_first_poll:
                # Baseline: record the current high-water mark, emit nothing.
                return {"seen_operation_ids": bounded_seen_ids([], done_names, _MAX_SEEN_OPERATION_IDS)}, []
            new_ops = [op for op in done_ops if op["name"] not in seen]
            if not new_ops:
                return None, []  # nothing new → no write
            all_seen = bounded_seen_ids(seen_list, done_names, _MAX_SEEN_OPERATION_IDS)
            return {"seen_operation_ids": all_seen}, new_ops

        # skip_result: on a transient state blip / lost contention, emit nothing
        # this tick (state untouched) instead of failing the scheduled run.
        new_ops = await self._update_node_state(mutator, skip_result=[])

        return {
            "status": "success",
            "action": "on_batch_completed",
            "operation": "on_batch_completed",
            "operations": new_ops,
            "new_count": len(new_ops),
            "location": c.location,
            "timestamp": time.time(),
            "timing_ms": result.get("timing_ms", {}),
        }

    # ------------------------------------------------------------------
    # v2 handlers (API key)
    # ------------------------------------------------------------------
    async def _v2_translate_text(
        self, c: GoogleTranslateV2TranslateConfig, auth: Dict[str, Any]
    ) -> Dict[str, Any]:
        body = {
            "q": c.text,
            "target": c.target_language,
            "source": c.source_language,
            "format": c.format,
        }
        return await _google_translate_request(
            "POST",
            GOOGLE_TRANSLATE_V2_BASE,
            params=auth["params"],
            headers=auth["headers"],
            json_body=body,
            action_name="v2_translate_text",
        )

    async def _v2_detect_language(
        self, c: GoogleTranslateV2DetectConfig, auth: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _google_translate_request(
            "POST",
            f"{GOOGLE_TRANSLATE_V2_BASE}/detect",
            params=auth["params"],
            headers=auth["headers"],
            json_body={"q": c.text},
            action_name="v2_detect_language",
        )

    async def _v2_list_languages(
        self, c: GoogleTranslateV2LanguagesConfig, auth: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = dict(auth["params"])
        if c.target_language:
            params["target"] = c.target_language
        return await _google_translate_request(
            "GET",
            f"{GOOGLE_TRANSLATE_V2_BASE}/languages",
            params=params,
            headers=auth["headers"],
            action_name="v2_list_languages",
        )

    # Handler dispatch tables (bound at call time via the explicit self arg).
    _V3_HANDLERS = {
        "v3_translate_text": _v3_translate_text,
        "v3_detect_language": _v3_detect_language,
        "v3_supported_languages": _v3_supported_languages,
        "v3_romanize_text": _v3_romanize_text,
        "v3_translate_document": _v3_translate_document,
        "v3_batch_translate_text": _v3_batch_translate_text,
        "v3_create_glossary": _v3_create_glossary,
        "v3_list_glossaries": _v3_list_glossaries,
        "v3_get_operation": _v3_get_operation,
        "on_batch_completed": _on_batch_completed,
    }
    _V2_HANDLERS = {
        "v2_translate_text": _v2_translate_text,
        "v2_detect_language": _v2_detect_language,
        "v2_list_languages": _v2_list_languages,
    }

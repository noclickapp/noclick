"""
HTTP Request automation node implementation.

Handles arbitrary HTTP requests in workflows, supporting GET, POST, PUT, PATCH, DELETE
methods with configurable headers, body, and authentication options.
"""

import re
import time
import json
import base64
import random
import asyncio
import logging
import mimetypes
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, Any, List, Optional, Union, Type, Literal, Annotated
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote
from pydantic import BaseModel, Field, Discriminator, field_validator, model_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.oauth_token_cache import (
    OAuthTokenCache,
    oauth_authority_digest,
    token_expiry_input,
)
from utils.ssrf import (
    SSRFError,
    assert_exact_url_origin,
    guarded_async_client,
    normalize_https_origin,
)

logger = logging.getLogger(__name__)


# ============================================================================
# HTTP Request Node Credential Schemas
# ============================================================================


class _OriginBoundHttpCredential(BaseModel):
    """A secret that may be sent to one explicitly approved API origin."""

    allowed_origin: str = Field(
        ...,
        min_length=1,
        title="Allowed Resource Origin",
        description=(
            "Exact HTTPS origin this credential may be sent to, for example "
            "https://api.example.com. Requests and redirects to any other "
            "origin are blocked."
        ),
        json_schema_extra={"ui:placeholder": "https://api.example.com"},
    )

    @field_validator("allowed_origin")
    @classmethod
    def _normalize_allowed_origin(cls, value: str) -> str:
        return normalize_https_origin(value, field_name="Allowed Resource Origin")


class BearerTokenCredential(_OriginBoundHttpCredential):
    """Bearer token authentication"""

    credential_type: Literal["http_bearer_token"] = Field(
        "http_bearer_token", json_schema_extra={"ui:hidden": True}
    )
    auth_type: Literal["bearer"] = Field(
        default="bearer", json_schema_extra={"ui:hidden": True}
    )
    token: str = Field(
        ...,
        min_length=1,
        title="Bearer Token",
        description="Token for Authorization header (Bearer <token>)",
        json_schema_extra={"ui:widget": "password"},
    )


class BasicAuthCredential(_OriginBoundHttpCredential):
    """HTTP Basic authentication"""

    credential_type: Literal["http_basic_auth"] = Field(
        "http_basic_auth", json_schema_extra={"ui:hidden": True}
    )
    auth_type: Literal["basic"] = Field(
        default="basic", json_schema_extra={"ui:hidden": True}
    )
    username: str = Field(
        ...,
        min_length=1,
        title="Username",
        description="Username for basic authentication",
    )
    password: str = Field(
        ...,
        min_length=1,
        title="Password",
        description="Password for basic authentication",
        json_schema_extra={"ui:widget": "password"},
    )


class ApiKeyCredential(_OriginBoundHttpCredential):
    """API Key authentication — sent as a request header or a query parameter.

    Also covers "custom header auth": set the name to any header an API expects
    (e.g. ``X-Auth-Token``) and keep the location as Header.
    """

    credential_type: Literal["http_api_key"] = Field(
        "http_api_key", json_schema_extra={"ui:hidden": True}
    )
    auth_type: Literal["api_key"] = Field(
        default="api_key", json_schema_extra={"ui:hidden": True}
    )
    location: str = Field(
        default="header",
        title="Send In",
        description="Where to put the API key on the request.",
        json_schema_extra={
            "enum": ["header", "query"],
            "enumNames": ["Request header", "Query parameter"],
        },
    )
    header_name: str = Field(
        default="X-API-Key",
        title="Header / Parameter Name",
        description="The name to send the key under — e.g. X-API-Key or Authorization for a header, or a query-parameter name like api_key.",
        json_schema_extra={"ui:placeholder": "X-API-Key"},
    )
    api_key: str = Field(
        ...,
        min_length=1,
        title="API Key",
        description="API key value",
        json_schema_extra={"ui:widget": "password"},
    )


class OAuth2ClientCredentials(_OriginBoundHttpCredential):
    """Generic OAuth2 client-credentials grant.

    Machine-to-machine auth: the node POSTs to the token URL to mint a short-
    lived access token and sends it as ``Authorization: Bearer``. No browser
    redirect, so it's a plain credential the user fills in (token URL + client
    id/secret + scope), not an OAuth connect flow.
    """

    credential_type: Literal["http_oauth2_client_credentials"] = Field(
        "http_oauth2_client_credentials", json_schema_extra={"ui:hidden": True}
    )
    auth_type: Literal["oauth2_client_credentials"] = Field(
        default="oauth2_client_credentials", json_schema_extra={"ui:hidden": True}
    )
    token_url: str = Field(
        ...,
        min_length=1,
        title="Token URL",
        description="OAuth2 token endpoint (grant_type=client_credentials).",
        json_schema_extra={"ui:placeholder": "https://auth.example.com/oauth/token"},
    )
    client_id: str = Field(..., min_length=1, title="Client ID")
    client_secret: str = Field(
        ...,
        min_length=1,
        title="Client Secret",
        json_schema_extra={"ui:widget": "password"},
    )
    scope: Optional[str] = Field(
        default=None, title="Scope", description="Space-separated scopes (optional)."
    )
    audience: Optional[str] = Field(
        default=None,
        title="Audience",
        description="Audience parameter, if your provider requires it (e.g. Auth0).",
    )
    send_credentials_in_body: str = Field(
        default="true",
        title="Send Client Credentials In",
        description="Where to put client_id/secret on the token request.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Request body", "Basic auth header"],
            "x-enum-searchable": True,
        },
    )

    @field_validator("token_url")
    @classmethod
    def _require_https_token_url(cls, value: str) -> str:
        raw = value.strip()
        try:
            token_url = httpx.URL(raw)
        except (TypeError, ValueError, httpx.InvalidURL) as e:
            raise ValueError("Token URL is invalid") from e
        if (
            not token_url.is_absolute_url
            or token_url.scheme != "https"
            or not token_url.host
            or bool(token_url.username)
            or bool(token_url.password)
            or bool(token_url.fragment)
        ):
            raise ValueError(
                "Token URL must be an absolute HTTPS URL without credentials or a fragment"
            )
        return str(token_url)


# Union of credential types - allows selecting one authentication method
HttpRequestCredential = Union[
    BearerTokenCredential,
    BasicAuthCredential,
    ApiKeyCredential,
    OAuth2ClientCredentials,
]


# ============================================================================
# HTTP Request Node Configuration Models
# ============================================================================
#
# Every HTTP method shares the same request surface (URL, headers, body, and
# behavioural options). To keep that surface defined in ONE place, the verb
# configs inherit from `_HttpRequestBaseConfig` and only pin the `operation`
# discriminator. `_HttpBodyMixin` adds the request body to the methods that
# conventionally carry one. The discriminated union below is keyed on
# `operation`, so the frontend operation picker and the agent-tool path keep
# working unchanged.


class HttpKeyValue(BaseModel):
    """One row in a headers / query-parameter editor.

    `value` supports `{{node.output.field}}` references (resolved upstream before
    parsing). `enabled` lets a row be toggled off without deleting it.
    """

    key: str = Field(default="", title="Name")
    value: str = Field(default="", title="Value")
    enabled: bool = Field(default=True)

    @field_validator("key", "value", mode="before")
    @classmethod
    def _coerce_none_to_str(cls, v: object) -> str:
        return "" if v is None else v


def _normalize_kv(v: object) -> object:
    """Coerce a headers/query-params value into a list of row dicts.

    Accepts the structured list (current shape), a JSON array string, and — for
    backward compatibility with the old raw-JSON-object headers field — a JSON
    object string or dict, which is migrated to `[{key, value, enabled}]`.
    Invalid JSON raises (fail loud), matching every other parse in this node.
    """
    if v is None:
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        v = json.loads(s)  # raises on invalid JSON
    if isinstance(v, dict):
        return [
            {"key": str(k), "value": "" if val is None else str(val), "enabled": True}
            for k, val in v.items()
        ]
    return v


class _HttpRequestBaseConfig(BaseModel):
    """Fields shared by every HTTP method."""

    url: str = Field(
        ...,
        min_length=1,
        title="URL",
        description="The URL to send the request to",
        json_schema_extra={"ui:placeholder": "https://api.example.com/v1/resource"},
    )
    query_params: Optional[List[HttpKeyValue]] = Field(
        default=None,
        title="Query Parameters",
        description="Query-string parameters appended to the URL (URL-encoded for you).",
        json_schema_extra={"ui:widget": "key_value"},
    )
    headers: Optional[List[HttpKeyValue]] = Field(
        default=None,
        title="Headers",
        description="Request headers. Drag in {{references}} on the value side.",
        json_schema_extra={"ui:widget": "key_value"},
    )
    body_type: str = Field(
        default="none",
        title="Body",
        description=(
            "Body encoding. For json or raw, provide body; for form_urlencoded, "
            "provide body_form. Raw requests may also set content_type_override."
        ),
        json_schema_extra={
            "enum": ["none", "json", "form_urlencoded", "raw"],
            "enumNames": ["None", "JSON", "Form", "Raw"],
            # The composite Body editor renders the type selector + the matching
            # editor, and writes the body / body_form / content_type_override
            # fields below (which are hidden from the form on their own).
            "ui:widget": "http_body",
        },
    )
    body: Optional[str] = Field(
        default=None,
        title="Request Body",
        description="Request body. Use {{nodeId.output.field}} to reference upstream data.",
        json_schema_extra={"ui:hidden": True, "x-agent-tool-visible": True},
    )
    body_form: Optional[List[HttpKeyValue]] = Field(
        default=None,
        title="Form Fields",
        description="Fields sent as application/x-www-form-urlencoded.",
        json_schema_extra={"ui:hidden": True, "x-agent-tool-visible": True},
    )
    content_type_override: Optional[str] = Field(
        default=None,
        title="Content-Type",
        description="Content-Type for the raw body (e.g. application/xml). Defaults to text/plain.",
        json_schema_extra={"ui:hidden": True, "x-agent-tool-visible": True},
    )

    @field_validator("query_params", "headers", "body_form", mode="before")
    @classmethod
    def _normalize_kv_fields(cls, v: object) -> object:
        return _normalize_kv(v)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_body(cls, data: object) -> object:
        """Configs saved before body_type existed stored a raw `body` string that
        was always sent as JSON-or-text. Classify it once so it keeps sending:
        valid JSON -> json, otherwise -> raw. Only fires when body_type is
        absent (i.e. a legacy config); new configs always carry body_type."""
        if isinstance(data, dict) and "body_type" not in data and data.get("body"):
            try:
                json.loads(data["body"])
                data["body_type"] = "json"
            except (json.JSONDecodeError, TypeError):
                data["body_type"] = "raw"
        return data

    never_error: str = Field(
        default="false",
        title="Continue on HTTP Error",
        description=(
            "By default a 4xx/5xx response (or a network/timeout failure) makes "
            "the node fail loudly. Enable this to return the error response as "
            "data instead, so the workflow can branch on it."
        ),
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Returns errors as data", "Fails the run"],
            "ui:widget": "toggle",
            "ui:category": "Options",
        },
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        title="Timeout (seconds)",
        description="How long to wait for the request before giving up.",
        json_schema_extra={"ui:category": "Options"},
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=10,
        title="Max Retries",
        description=(
            "Retry transient failures (network errors, 429 and 5xx) with "
            "exponential backoff, honoring Retry-After. Note: retries can "
            "re-submit non-idempotent requests (POST/PATCH)."
        ),
        json_schema_extra={"ui:category": "Options"},
    )
    follow_redirects: str = Field(
        default="true",
        title="Follow Redirects",
        description="Follow 3xx redirects to the new location automatically.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["On", "Off"],
            "ui:widget": "toggle",
            "ui:category": "Options",
        },
    )
    max_redirects: int = Field(
        default=10,
        ge=0,
        le=50,
        title="Max Redirects",
        description="Maximum redirects to follow (when Follow Redirects is on).",
        json_schema_extra={"ui:category": "Options"},
    )
    verify_ssl: str = Field(
        default="true",
        title="Verify SSL Certificate",
        description=(
            "Disable only for internal endpoints with self-signed certs. SSRF "
            "protection still applies regardless."
        ),
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["On", "Off"],
            "ui:widget": "toggle",
            "ui:category": "Options",
        },
    )
    response_format: str = Field(
        default="auto",
        title="Response Format",
        description="How to read the response body. Auto detects JSON / text / binary.",
        json_schema_extra={
            "enum": ["auto", "json", "text", "binary"],
            "enumNames": ["Auto", "JSON", "Text", "Binary"],
            "ui:widget": "segmented",
            "ui:category": "Options",
        },
    )
    full_response: str = Field(
        default="true",
        title="Include Full Response",
        description="On: return status code, headers and body. Off: return only the body.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Status + headers + body", "Body only"],
            "ui:widget": "toggle",
            "ui:category": "Options",
        },
    )

    @field_validator(
        "timeout_seconds", "max_retries", "max_redirects", mode="before"
    )
    @classmethod
    def _blank_int_to_default(cls, v: object, info) -> object:
        """A number field left blank in the UI arrives as "" — fall back to the
        field's default rather than failing validation."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return cls.model_fields[info.field_name].default
        return v


def _operation_field(operation_id: str, display_name: str):
    """Build the hidden `operation` discriminator field for a verb config."""
    return Field(
        default=operation_id,
        title=display_name,
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "HTTP Request",
            "x-is-trigger": False,
            "x-display-name": display_name,
        },
    )


class HttpGetConfig(_HttpRequestBaseConfig):
    """HTTP GET request configuration"""

    operation: Literal["send_http_get_request"] = _operation_field(
        "send_http_get_request", "Send Http Get Request"
    )


class HttpPostConfig(_HttpRequestBaseConfig):
    """HTTP POST request configuration"""

    operation: Literal["send_http_post_request"] = _operation_field(
        "send_http_post_request", "Send Http Post Request"
    )


class HttpPutConfig(_HttpRequestBaseConfig):
    """HTTP PUT request configuration"""

    operation: Literal["send_http_put_request"] = _operation_field(
        "send_http_put_request", "Send Http Put Request"
    )


class HttpPatchConfig(_HttpRequestBaseConfig):
    """HTTP PATCH request configuration"""

    operation: Literal["send_http_patch_request"] = _operation_field(
        "send_http_patch_request", "Send Http Patch Request"
    )


class HttpDeleteConfig(_HttpRequestBaseConfig):
    """HTTP DELETE request configuration"""

    operation: Literal["send_http_delete_request"] = _operation_field(
        "send_http_delete_request", "Send Http Delete Request"
    )


# Discriminated union uses 'operation' field to determine which config type to parse
HttpRequestConfig = Annotated[
    Union[
        HttpGetConfig, HttpPostConfig, HttpPutConfig, HttpPatchConfig, HttpDeleteConfig
    ],
    Discriminator("operation"),
]


class HttpRequestNodeConfig(NodeConfig[HttpRequestConfig, HttpRequestCredential]):
    """Full configuration for HTTP Request node including credentials"""

    pass


# Exception carrying the structured response of a failed HTTP request so the
# node fails loudly (default) while still surfacing the status/body for logs.
class HttpRequestFailed(Exception):
    def __init__(self, message: str, output: Dict[str, Any]):
        super().__init__(message)
        self.output = output


# ============================================================================
# HTTP Request Node Implementation
# ============================================================================


class HttpRequestNode(WorkflowNode):
    """
    HTTP Request automation node.

    Sends arbitrary HTTP requests to external APIs or services.
    Supports GET, POST, PUT, PATCH, DELETE methods with optional
    authentication (Bearer token, Basic auth, API key).
    """

    edit_examples = [
        "Send a GET request to the OpenWeather API with an API key",
        "POST JSON data to https://api.example.com/webhooks with basic auth",
        "Update a resource via PUT with a custom Authorization header",
        "Delete a record by ID using Bearer token authentication",
        "Fetch GitHub user repos via PATCH with custom headers",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for HTTP Request node"""
        return HttpRequestNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute HTTP request.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing HTTP response results
        """
        logger.info(f"[HttpRequestNode] Executing node {self.node_id}")

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[HttpRequestNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, HttpRequestNodeConfig):
            raise ValueError(
                f"[HttpRequestNode] Invalid config type: {type(node_config)}, expected HttpRequestNodeConfig"
            )

        # Extract the actual request config and credentials
        config = node_config.config
        credentials = node_config.credentials

        # Get method and URL from config. The UI operation is a stable node
        # action id, not the literal HTTP verb accepted by httpx.
        method = self._operation_to_http_method(config.operation)
        url = config.url

        # `url` is a required config field, but a templated URL
        # (`{{upstream.output.url}}`) can still resolve to an empty/invalid
        # string at runtime — keep a guard so that fails loudly with a clear
        # message instead of a confusing transport error.
        if not isinstance(url, str) or len(url.strip()) == 0:
            raise ValueError(
                "URL is required but resolved to an empty value. If the URL "
                "references an upstream node, check that node produced a value."
            )
        url = url.strip()

        never_error = self._is_true(getattr(config, "never_error", "false"))

        # Append structured query parameters to the URL (URL-encoded), keeping
        # any params already inline in the URL.
        url = self._apply_query_params(url, getattr(config, "query_params", None))

        # A saved secret is valid for exactly one resource origin. Enforce the
        # initial destination before reading/attaching the secret or minting an
        # OAuth token; _make_request repeats the check on every redirect hop.
        allowed_origin = credentials.allowed_origin if credentials else None
        if allowed_origin:
            assert_exact_url_origin(url, allowed_origin)

        verify_ssl = self._is_true(getattr(config, "verify_ssl", "true"))
        if credentials and not verify_ssl:
            raise SSRFError(
                "TLS certificate verification cannot be disabled for a credentialed request"
            )

        # API-key-in-query auth modifies the URL; remember the param name so it
        # can be redacted from logs and the echoed output.
        url, auth_query_param = self._apply_query_auth(url, credentials)

        # Build headers from the structured rows
        headers = self._build_headers(getattr(config, "headers", None))
        if credentials and any(name.lower() == "host" for name in headers):
            raise SSRFError(
                "Credentialed HTTP requests cannot override the Host header"
            )

        # Apply header-based authentication (Bearer / Basic / API-key-in-header)
        headers = self._apply_auth(headers, credentials)

        # OAuth2 client-credentials mints a Bearer token (async).
        headers = await self._apply_oauth2(
            headers,
            credentials,
            verify_ssl=verify_ssl,
        )

        # Build the request body from the selected body type
        body_kwargs, body_content_type = self._build_request_body(config)

        # Redacted URL for logging / output echo (masks the api-key query param).
        extra = (auth_query_param,) if auth_query_param else ()
        display_url = self._redact_url(url, extra_keys=extra)

        # Execute the request
        output = await self._make_request(
            method,
            url,
            headers,
            body_kwargs,
            body_content_type,
            display_url=display_url,
            never_error=never_error,
            timeout=float(getattr(config, "timeout_seconds", 30) or 30),
            max_retries=int(getattr(config, "max_retries", 0) or 0),
            follow_redirects=self._is_true(getattr(config, "follow_redirects", "true")),
            max_redirects=int(getattr(config, "max_redirects", 10) or 10),
            verify_ssl=verify_ssl,
            response_format=getattr(config, "response_format", "auto"),
            full_response=self._is_true(getattr(config, "full_response", "true")),
            allowed_origin=allowed_origin,
        )

        # Emit output to frontend
        await self.emit(output)

        return output

    @staticmethod
    def _is_true(value: Any) -> bool:
        """Coerce a string-enum boolean ("true"/"false") to a real bool."""
        return str(value).strip().lower() == "true"

    @staticmethod
    def _build_headers(rows: Optional[List[HttpKeyValue]]) -> Dict[str, str]:
        """Build a header dict from the enabled, named rows."""
        headers: Dict[str, str] = {}
        for row in rows or []:
            name = row.key.strip()
            if row.enabled and name:
                headers[name] = row.value
        return headers

    @staticmethod
    def _apply_query_params(url: str, rows: Optional[List[HttpKeyValue]]) -> str:
        """Append enabled, named query-parameter rows to *url* (URL-encoded).

        Params already present inline in the URL are preserved (appended to,
        never dropped).
        """
        params = [
            (row.key.strip(), row.value)
            for row in (rows or [])
            if row.enabled and row.key.strip()
        ]
        if not params:
            return url
        parts = urlsplit(url)
        merged = parse_qsl(parts.query, keep_blank_values=True) + params
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment)
        )

    @staticmethod
    def _operation_to_http_method(operation: str) -> str:
        """Translate operation ids into concrete HTTP verbs."""
        return {
            "send_http_get_request": "GET",
            "send_http_post_request": "POST",
            "send_http_put_request": "PUT",
            "send_http_patch_request": "PATCH",
            "send_http_delete_request": "DELETE",
        }.get(operation, operation)

    def _build_request_body(self, config: Any):
        """Build httpx body kwargs + an optional explicit Content-Type from the
        selected body type.

        Returns ``({}, None)`` when no body is sent. The chosen body type is the
        contract: a ``json`` body that isn't valid JSON fails loudly (no silent
        fallback to raw), and the Content-Type is set to match the type rather
        than being unconditionally ``application/json``.
        """
        body_type = getattr(config, "body_type", "none")

        if body_type == "json":
            raw = getattr(config, "body", None)
            if not raw or not raw.strip():
                return {}, None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"Request body is not valid JSON: {e}")
            return {"json": parsed}, None  # httpx sets application/json

        if body_type == "form_urlencoded":
            data = {
                row.key.strip(): row.value
                for row in (getattr(config, "body_form", None) or [])
                if row.enabled and row.key.strip()
            }
            if not data:
                return {}, None
            return {"data": data}, None  # httpx sets application/x-www-form-urlencoded

        if body_type == "raw":
            raw = getattr(config, "body", None)
            if not raw:
                return {}, None
            content_type = (
                getattr(config, "content_type_override", None) or ""
            ).strip() or "text/plain"
            return {"content": raw}, content_type

        return {}, None

    def _apply_auth(
        self, headers: Dict[str, str], credentials: Optional[HttpRequestCredential]
    ) -> Dict[str, str]:
        """Apply header-based authentication (Bearer / Basic / API-key-in-header)."""
        if not credentials:
            return headers

        if isinstance(credentials, BearerTokenCredential):
            headers["Authorization"] = f"Bearer {credentials.token}"
        elif isinstance(credentials, BasicAuthCredential):
            auth_string = f"{credentials.username}:{credentials.password}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif isinstance(credentials, ApiKeyCredential) and credentials.location != "query":
            headers[credentials.header_name] = credentials.api_key

        return headers

    @staticmethod
    def _apply_query_auth(
        url: str, credentials: Optional[HttpRequestCredential]
    ) -> "tuple[str, Optional[str]]":
        """Add an API key to the URL query string when configured for `query`.

        Returns (url, param_name) so the caller can redact the secret param.
        """
        if (
            isinstance(credentials, ApiKeyCredential)
            and credentials.location == "query"
            and credentials.api_key
        ):
            name = credentials.header_name.strip() or "api_key"
            parts = urlsplit(url)
            merged = parse_qsl(parts.query, keep_blank_values=True) + [
                (name, credentials.api_key)
            ]
            url = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment)
            )
            return url, name
        return url, None

    # Per-container cache of minted client-credentials tokens. Keys are digests
    # of every authority-bearing input, including the client secret.
    _OAUTH2_TOKEN_CACHE = OAuthTokenCache(refresh_skew_seconds=60)

    async def _apply_oauth2(
        self,
        headers: Dict[str, str],
        credentials: Optional[HttpRequestCredential],
        *,
        verify_ssl: bool = True,
    ) -> Dict[str, str]:
        """Mint and attach an OAuth2 client-credentials Bearer token."""
        if isinstance(credentials, OAuth2ClientCredentials):
            token = await self._fetch_oauth2_token(credentials, verify_ssl=verify_ssl)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _fetch_oauth2_token(
        self, cred: "OAuth2ClientCredentials", *, verify_ssl: bool = True
    ) -> str:
        """Fetch (or reuse a cached) client-credentials access token."""
        send_credentials_in_body = self._is_true(cred.send_credentials_in_body)
        cache_key = oauth_authority_digest(
            provider="generic-http-oauth2-client-credentials",
            token_url=cred.token_url,
            client_id=cred.client_id,
            client_secret=cred.client_secret,
            scope=cred.scope or "",
            audience=cred.audience or "",
            send_credentials_in_body=send_credentials_in_body,
            verify_ssl=verify_ssl,
        )
        cached = self._OAUTH2_TOKEN_CACHE.get(cache_key, now=time.monotonic())
        if cached:
            return cached

        data: Dict[str, str] = {"grant_type": "client_credentials"}
        if cred.scope:
            data["scope"] = cred.scope
        if cred.audience:
            data["audience"] = cred.audience
        auth = None
        if send_credentials_in_body:
            data["client_id"] = cred.client_id
            data["client_secret"] = cred.client_secret
        else:
            auth = (cred.client_id, cred.client_secret)

        async with guarded_async_client(verify=verify_ssl) as client:
            try:
                resp = await client.post(cred.token_url, data=data, auth=auth, timeout=30.0)
            except (httpx.TimeoutException, httpx.RequestError) as e:
                raise ValueError(f"OAuth2 token request failed: {e}") from e

        if resp.status_code >= 400:
            raise ValueError(
                f"OAuth2 token request failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"OAuth2 token response was not JSON: {e}") from e
        token = payload.get("access_token")
        if not token:
            raise ValueError("OAuth2 token response did not include an access_token")

        self._OAUTH2_TOKEN_CACHE.put(
            cache_key,
            token,
            expires_in=token_expiry_input(payload),
            now=time.monotonic(),
        )
        return token

    # Transient response statuses worth retrying.
    _RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
    _RETRY_BASE_DELAY = 0.5
    _MAX_RETRY_DELAY = 30.0

    # Refuse to inline a response body larger than this into workflow state.
    # Text/JSON go inline into workflow state, so keep that bounded. Binary
    # responses are stored as an R2 resource (not in state), so they get a much
    # larger cap.
    _MAX_INLINE_BYTES = 25 * 1024 * 1024
    _MAX_BINARY_BYTES = 100 * 1024 * 1024

    _AUTO_BINARY_HINTS = (
        "video/",
        "audio/",
        "image/",
        "application/octet-stream",
        "application/pdf",
        "application/zip",
    )

    @classmethod
    def _wants_binary(cls, response: httpx.Response, response_format: str) -> bool:
        """Whether the response should be treated as binary (stored as a resource)."""
        if response_format == "binary":
            return True
        if response_format == "auto":
            content_type = response.headers.get("content-type", "").lower()
            return any(hint in content_type for hint in cls._AUTO_BINARY_HINTS)
        return False  # text / json are never binary

    @classmethod
    def _parse_response_body(cls, response: httpx.Response, response_format: str) -> Any:
        """Decode a non-binary response body (binary is handled separately).

        - text: return text.
        - json: parse as JSON, failing loud if it isn't valid JSON.
        - auto (default): JSON when parseable, else text.
        """
        if response_format == "text":
            return response.text
        if response_format == "json":
            try:
                return response.json()
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    f"Response is not valid JSON (response_format=json): {e}"
                )
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return response.text

    async def _handle_binary_response(
        self, response: httpx.Response, display_url: str
    ) -> "tuple[Any, bool, bool]":
        """Store a binary response and return a usable file URL.

        Returns (response_value, is_file, is_base64). On success the value is a
        ``{url, mime_type, name, size_bytes}`` object — a public link downstream
        nodes (upload nodes, media blocks) and you can use directly. The bytes
        are stored in R2; the resource id stays internal. Falls back to base64
        only when there's no workflow context to store into (e.g. a context-less
        standalone run)."""
        content_type = (
            response.headers.get("content-type", "application/octet-stream")
            .split(";")[0]
            .strip()
            .lower()
            or "application/octet-stream"
        )
        if not (self.user_id and self.workflow_id):
            logger.warning(
                "[HttpRequestNode] binary response but no workflow context — returning base64"
            )
            return base64.b64encode(response.content).decode("utf-8"), False, True

        from utils.resource_store import create_resource_from_bytes

        ref = await create_resource_from_bytes(
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            organization_id=self.organization_id,
            body=response.content,
            content_type=content_type,
            filename=self._binary_filename(display_url, response, content_type),
        )
        logger.info(
            f"[HttpRequestNode] stored binary response ({ref['size_bytes']} bytes, "
            f"{content_type}) at {ref['url'] if 'url' in ref else ref['download_url']}"
        )
        file_value = {
            "url": ref["download_url"],
            "mime_type": ref["mime_type"],
            "name": ref["name"],
            "size_bytes": ref["size_bytes"],
        }
        return file_value, True, False

    @staticmethod
    def _binary_filename(url: str, response: httpx.Response, content_type: str) -> str:
        """Derive a filename from Content-Disposition, the URL path, or the MIME type."""
        cd = response.headers.get("content-disposition", "")
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
        if m and m.group(1).strip():
            return unquote(m.group(1).strip())
        name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        if name and "." in name:
            return name
        return f"download{mimetypes.guess_extension(content_type) or '.bin'}"

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        """Parse a Retry-After header (delta-seconds or HTTP-date) to seconds."""
        if not value:
            return None
        value = value.strip()
        if value.isdigit():
            return float(value)
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        return max(0.0, (when - datetime.now(when.tzinfo)).total_seconds())

    @classmethod
    def _retry_delay(cls, attempt: int, response: Optional[httpx.Response] = None) -> float:
        """Exponential backoff with jitter, capped, honoring Retry-After."""
        if response is not None:
            retry_after = cls._parse_retry_after(response.headers.get("retry-after"))
            if retry_after is not None:
                return min(retry_after, cls._MAX_RETRY_DELAY)
        backoff = min(cls._RETRY_BASE_DELAY * (2**attempt), cls._MAX_RETRY_DELAY)
        return backoff + random.uniform(0, backoff * 0.25)

    async def _send_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: Dict[str, str],
        body_kwargs: Dict[str, Any],
        timeout: float,
        max_retries: int,
    ) -> httpx.Response:
        """Send the request, retrying transient transport failures and 429/5xx
        responses with backoff. SSRF blocks (raised by the request hook) are not
        retried — they propagate immediately."""
        attempt = 0
        while True:
            try:
                response = await client.request(
                    method, url, headers=headers, timeout=timeout, **body_kwargs
                )
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt >= max_retries:
                    raise
                delay = self._retry_delay(attempt)
                logger.warning(
                    "[HttpRequestNode] transient failure, retrying in %.1fs "
                    "(attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            if response.status_code in self._RETRYABLE_STATUSES and attempt < max_retries:
                delay = self._retry_delay(attempt, response)
                logger.warning(
                    "[HttpRequestNode] HTTP %d, retrying in %.1fs (attempt %d/%d)",
                    response.status_code, delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            return response

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body_kwargs: Dict[str, Any],
        body_content_type: Optional[str] = None,
        *,
        display_url: Optional[str] = None,
        never_error: bool = False,
        timeout: float = 30.0,
        max_retries: int = 0,
        follow_redirects: bool = True,
        max_redirects: int = 10,
        verify_ssl: bool = True,
        response_format: str = "auto",
        full_response: bool = True,
        allowed_origin: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Make the HTTP request and return structured output.

        ``body_kwargs`` is the httpx body argument (``{"json": ...}`` /
        ``{"data": ...}`` / ``{"content": ...}`` / ``{}``) and
        ``body_content_type`` an explicit Content-Type to set (raw bodies only).
        ``display_url`` is the redacted URL used for logs and the echoed output
        (so an API key in the query string never lands in either).

        On a 4xx/5xx response or a transport failure the node fails loudly by
        default (raising). When ``never_error`` is set, the error is returned
        as data instead so the workflow can branch on it.
        """
        display_url = display_url or self._redact_url(url)
        logger.info(f"[HttpRequestNode] Making {method} request to {display_url}")

        # An explicit raw Content-Type is a default — a Content-Type the user set
        # in the Headers section wins.
        if body_content_type and not any(
            k.lower() == "content-type" for k in headers
        ):
            headers["Content-Type"] = body_content_type

        start_time = time.time()

        # The SSRF guard validates the target (and every redirect hop) before any
        # connection, so a tenant can't reach the metadata endpoint or internal
        # network. httpx itself strips Authorization on cross-origin redirects.
        client_kwargs: Dict[str, Any] = {
            "follow_redirects": follow_redirects,
            "verify": verify_ssl,
        }
        if follow_redirects:
            client_kwargs["max_redirects"] = max_redirects
        if allowed_origin:

            async def _enforce_credential_origin(request: httpx.Request) -> None:
                assert_exact_url_origin(str(request.url), allowed_origin)

            client_kwargs["event_hooks"] = {"request": [_enforce_credential_origin]}

        try:
            async with guarded_async_client(**client_kwargs) as client:
                response = await self._send_with_retries(
                    client, method, url, headers, body_kwargs, timeout, max_retries
                )

                elapsed_time = time.time() - start_time

                # Binary responses are stored as an R2 resource (small ref in
                # state); text/JSON go inline. Pick the cap accordingly and
                # refuse anything over it rather than blow up memory / state.
                wants_binary = self._wants_binary(response, response_format)
                cap = self._MAX_BINARY_BYTES if wants_binary else self._MAX_INLINE_BYTES
                if len(response.content) > cap:
                    limit_mb = cap // (1024 * 1024)
                    too_big = {
                        "type": "http_request",
                        "method": method,
                        "url": display_url,
                        "status_code": response.status_code,
                        "status": "error",
                        "error": (
                            f"Response body is too large to return "
                            f"({len(response.content)} bytes > {limit_mb} MB limit)."
                        ),
                        "response_headers": dict(response.headers),
                        "elapsed_ms": round(elapsed_time * 1000, 2),
                        "timestamp": time.time(),
                    }
                    if never_error:
                        return too_big
                    raise HttpRequestFailed(too_big["error"], too_big)

                if wants_binary:
                    response_body, is_file, is_base64_encoded = (
                        await self._handle_binary_response(response, display_url)
                    )
                else:
                    response_body = self._parse_response_body(response, response_format)
                    is_file, is_base64_encoded = False, False

                output = {
                    "type": "http_request",
                    "method": method,
                    "url": display_url,
                    "status_code": response.status_code,
                    "status": "success" if response.status_code < 400 else "error",
                    "response": response_body,
                    "response_headers": dict(response.headers),
                    "elapsed_ms": round(elapsed_time * 1000, 2),
                    "timestamp": time.time(),
                    "is_base64": is_base64_encoded,  # legacy: base64 only when no workflow context
                    "is_file": is_file,  # response is a {url, mime_type, name, size_bytes} file ref
                }

                if response.status_code >= 400:
                    output["error"] = (
                        f"HTTP {response.status_code}: {response.reason_phrase}"
                    )
                    if not never_error:
                        logger.warning(
                            f"[HttpRequestNode] Request returned error status: {response.status_code}"
                        )
                        raise HttpRequestFailed(
                            self._error_message(method, display_url, response, response_body),
                            output,
                        )
                else:
                    logger.info(
                        f"[HttpRequestNode] Request successful: {response.status_code}"
                    )
                    if not full_response:
                        # Body-only: return the JSON object directly, or wrap a
                        # non-dict body so downstream still gets a dict.
                        return (
                            response_body
                            if isinstance(response_body, dict)
                            else {"data": response_body}
                        )

                return output

        except HttpRequestFailed as e:
            # Loud failure for 4xx/5xx — surface the structured response too.
            if self.sio and self.sid and self.workflow_id:
                await self.emit(e.output)
            raise ValueError(str(e)) from e

        except (httpx.TimeoutException, httpx.RequestError) as e:
            elapsed_time = time.time() - start_time
            is_timeout = isinstance(e, httpx.TimeoutException)
            error_text = "Request timed out" if is_timeout else str(e)
            logger.error(f"[HttpRequestNode] Request failed: {e}")
            error_output = {
                "type": "http_request",
                "method": method,
                "url": display_url,
                "status": "error",
                "error": error_text,
                "elapsed_ms": round(elapsed_time * 1000, 2),
                "timestamp": time.time(),
            }
            if never_error:
                return error_output
            await self.emit(error_output)
            raise ValueError(
                f"HTTP {method} request to {display_url} failed: {error_text}"
            ) from e

    # Query-param keys whose values are masked before a URL is logged.
    _SECRET_QUERY_KEYS = (
        "key",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "password",
        "secret",
        "sig",
        "signature",
        "auth",
    )

    @classmethod
    def _redact_url(cls, url: str, extra_keys: tuple = ()) -> str:
        """Strip userinfo and mask secret-looking query values for logging.

        *extra_keys* names additional query params to mask (e.g. an API-key
        query param whose name doesn't match the generic secret patterns).
        """
        try:
            parts = urlsplit(url)
        except ValueError:
            return "<unparseable url>"
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        extra_lower = {k.lower() for k in extra_keys}
        query = parts.query
        if query:
            redacted_pairs = [
                (
                    k,
                    "***"
                    if k.lower() in extra_lower
                    or any(s in k.lower() for s in cls._SECRET_QUERY_KEYS)
                    else v,
                )
                for k, v in parse_qsl(query, keep_blank_values=True)
            ]
            query = urlencode(redacted_pairs, safe="*")
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))

    @staticmethod
    def _error_message(
        method: str, url: str, response: httpx.Response, response_body: Any
    ) -> str:
        """Build a concise, useful failure message for a 4xx/5xx response."""
        snippet = response_body
        if not isinstance(snippet, str):
            try:
                snippet = json.dumps(snippet, default=str)
            except (TypeError, ValueError):
                snippet = str(snippet)
        snippet = snippet.strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        base = (
            f"HTTP {response.status_code} {response.reason_phrase} "
            f"from {method} {url}"
        )
        return f"{base}: {snippet}" if snippet else base

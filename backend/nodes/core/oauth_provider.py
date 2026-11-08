"""Declarations and token transport for opt-in, standard OAuth2 providers.

Only public_metadata is emitted to the frontend. Environment values are read
at request time; neither secrets nor token/identity responses enter metadata.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote, urlsplit
from string import Formatter

import httpx
from pydantic import BaseModel, ConfigDict

from nodes.core.oauth_scopes import ScopeRegistry


class OAuthTokens(BaseModel):
    model_config = ConfigDict(extra="allow")
    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"


def read_field(payload: dict, path: str):
    value = payload
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@dataclass(frozen=True, kw_only=True)
class OAuthContextField:
    """Non-secret, provider-owned URL context. Patterns match the entire value.

    URL authorities must use host/origin fields; path fields are percent-encoded.
    Callback names may differ from the credential field (e.g. accounts-server).
    """

    source: Literal["input", "callback", "token"]
    pattern: str | None = None
    choices: tuple[str, ...] = ()
    kind: Literal["value", "host", "origin"] = "value"
    label: str | None = None
    callback_name: str | None = None

    def __post_init__(self):
        if self.source not in ("input", "callback", "token") or self.kind not in (
            "value",
            "host",
            "origin",
        ):
            raise ValueError("Invalid OAuth context field")
        if not self.pattern and not self.choices:
            raise ValueError("OAuth context needs an allowlist or pattern")
        if self.pattern:
            re.compile(self.pattern)

    def validate(self, value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise ValueError("Invalid OAuth context value")
        if self.choices and value not in self.choices:
            raise ValueError("OAuth context value is not allowed")
        if self.pattern and not re.fullmatch(self.pattern, value):
            raise ValueError("OAuth context value is not allowed")
        if self.kind in ("host", "origin"):
            url = urlsplit("https://" + value if self.kind == "host" else value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.port
                or url.path
                or url.query
                or url.fragment
                or url.hostname != url.netloc
                or len(url.hostname) > 253
                or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in url.hostname.split(".")
                )
            ):
                raise ValueError("OAuth context must be a public HTTPS host or origin")
        return value

    def public_metadata(self):
        return {
            "source": self.source,
            "pattern": self.pattern,
            "choices": list(self.choices),
            "kind": self.kind,
            "label": self.label,
            "callbackName": self.callback_name,
        }


@dataclass(frozen=True, kw_only=True)
class OAuthDeviceSpec:
    authorization_url: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class OAuthProviderSpec:
    provider: str
    authorize_url: str | None
    token_url: str
    scope_registry: ScopeRegistry
    client_id_env: str
    client_secret_env: str
    redirect_uri_env: str
    credential_type: str
    # A dotted field in the identity response. Missing identity fails connection.
    name_field: str
    identity_url: str | None = None
    pkce: bool = False
    token_auth: Literal["basic", "body", "none"] = "body"
    rotates_refresh_tokens: bool = False
    authorize_params: dict[str, str] = field(default_factory=dict)
    token_params: dict[str, str] = field(default_factory=dict)
    token_fields: tuple[str, ...] = ()

    context_fields: dict[str, OAuthContextField] = field(default_factory=dict)
    scope_separator: Literal[" ", ","] = " "
    token_format: Literal["form", "json"] = "form"
    refresh_url: str | None = None
    refresh_token_auth: Literal["basic", "body", "none"] | None = None
    token_grant_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)
    expires_at_field: str | None = None
    expires_at_unit: Literal["seconds", "milliseconds"] = "seconds"
    device: OAuthDeviceSpec | None = None

    def __post_init__(self):
        if not self.identity_url:
            raise ValueError("OAuth identity_url is required")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.provider):
            raise ValueError("Invalid OAuth provider id")
        if self.scope_registry.provider != self.provider:
            raise ValueError("OAuth scope registry must belong to the provider")
        if self.token_auth not in ("basic", "body", "none"):
            raise ValueError("Invalid OAuth token authentication")
        if not self.authorize_url and not self.device:
            raise ValueError("OAuth authorize_url or device authorization is required")
        if self.refresh_token_auth not in (None, "basic", "body", "none"):
            raise ValueError("Invalid refresh token authentication")
        allowed_grants = {
            "authorization_code": {
                "grant_type",
                "code",
                "redirect_uri",
                "code_verifier",
            },
            "refresh_token": {"grant_type", "refresh_token"},
        }
        for grant, fields in self.token_grant_fields.items():
            if (
                grant not in allowed_grants
                or set(fields) - allowed_grants[grant]
                or ("code" if grant == "authorization_code" else "refresh_token")
                not in fields
            ):
                raise ValueError("Invalid OAuth grant field selection")
        if (
            self.device
            and {"client_id", "client_secret", "scope", "grant_type", "device_code"}
            & self.device.params.keys()
        ):
            raise ValueError("Device parameters override OAuth protocol fields")
        if self.scope_separator not in (" ", ",") or self.token_format not in (
            "form",
            "json",
        ):
            raise ValueError("Invalid OAuth wire format")
        if self.expires_at_unit not in ("seconds", "milliseconds"):
            raise ValueError("Invalid OAuth expiry unit")
        if set(self.context_fields) & (
            set(OAuthTokens.model_fields)
            | {
                "name",
                "credential_type",
                "client_id",
                "client_secret",
                "provider",
                "scopes",
                "state",
                "nonce",
                "timestamp",
                "code",
                "code_verifier",
                "redirect_uri",
            }
        ):
            raise ValueError("OAuth context overrides reserved fields")
        for key in self.context_fields:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                raise ValueError("Invalid OAuth context name")
        for url in (
            self.authorize_url,
            self.token_url,
            self.identity_url,
            self.refresh_url,
            self.device.authorization_url if self.device else None,
        ):
            if url and not (
                url.startswith("https://")
                or any(
                    url.startswith("{" + key + "}/") and definition.kind == "origin"
                    for key, definition in self.context_fields.items()
                )
            ):
                raise ValueError("OAuth endpoints must use HTTPS")
            if url:
                self._validate_template(url)
        if self.device and any(
            v.source == "callback" for v in self.context_fields.values()
        ):
            raise ValueError("Device authorization cannot capture callback fields")
        for template, sources in (
            (self.authorize_url, {"input"}),
            (self.token_url, {"input", "callback"}),
            (self.device.authorization_url if self.device else None, {"input"}),
        ):
            for _, name, _, _ in Formatter().parse(template or ""):
                if name and self.context_fields[name].source not in sources:
                    raise ValueError(
                        "OAuth endpoint context is unavailable at this stage"
                    )
        for key, env in (
            ("id", self.client_id_env),
            ("secret", self.client_secret_env),
            ("redirect", self.redirect_uri_env),
        ):
            optional = self.device and (key == "redirect" or self.token_auth == "none")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env) and not (optional and not env):
                raise ValueError("Invalid OAuth environment variable name")
        reserved = {
            "client_id",
            "client_secret",
            "grant_type",
            "code",
            "redirect_uri",
            "refresh_token",
            "code_verifier",
        }
        if reserved & self.token_params.keys():
            raise ValueError("Token parameters override OAuth protocol fields")
        if {
            "client_id",
            "redirect_uri",
            "response_type",
            "scope",
            "state",
            "code_challenge",
            "code_challenge_method",
        } & self.authorize_params.keys():
            raise ValueError("Authorize parameters override OAuth protocol fields")
        if not self.name_field or not self.credential_type:
            raise ValueError("OAuth identity field and credential type are required")
        if set(self.token_fields) & set(OAuthTokens.model_fields):
            raise ValueError("Extra token fields override standard token fields")

    @property
    def scopes(self) -> list[str]:
        return sorted(self.scope_registry.declared_scopes())

    def public_metadata(self) -> dict:
        metadata = {
            "provider": self.provider,
            "authorizeUrl": self.authorize_url,
            "scopes": self.scopes,
            "pkce": self.pkce,
            "clientIdEnv": self.client_id_env,
            "clientSecretEnv": self.client_secret_env,
            "redirectUriEnv": self.redirect_uri_env,
            "authorizeParams": self.authorize_params,
            "credentialType": self.credential_type,
        }

        # Omit defaults to keep already-generated metadata byte-for-byte stable.
        if self.context_fields:
            metadata["contextFields"] = {
                k: v.public_metadata() for k, v in self.context_fields.items()
            }
        if self.scope_separator != " ":
            metadata["scopeSeparator"] = self.scope_separator
        if self.device:
            metadata["deviceFlow"] = True
        return metadata

    def _validate_template(self, template: str):
        for _, name, fmt, conversion in Formatter().parse(template):
            if name is not None and (
                name not in self.context_fields or fmt or conversion
            ):
                raise ValueError("Unknown OAuth URL context field")
        rendered = template
        for key, definition in self.context_fields.items():
            rendered = rendered.replace(
                "{" + key + "}",
                "https://provider.example"
                if definition.kind == "origin"
                else "provider.example",
            )
        parsed = urlsplit(rendered)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port
        ):
            raise ValueError("Invalid OAuth endpoint")
        authority = template.removeprefix("https://").split("/", 1)[0]
        for _, name, _, _ in Formatter().parse(authority):
            if name and self.context_fields[name].kind not in ("host", "origin"):
                raise ValueError("OAuth URL authority needs a host or origin field")

    def validate_context(
        self, context: dict | None, *, sources=None, complete=True
    ) -> dict[str, str]:
        context = context or {}
        fields = {
            k: v
            for k, v in self.context_fields.items()
            if sources is None or v.source in sources
        }
        if set(context) - set(fields):
            raise ValueError("Unknown OAuth context field")
        if complete and set(fields) - set(context):
            raise ValueError("Missing OAuth context field")
        return {k: fields[k].validate(v) for k, v in context.items()}

    def endpoint(self, template: str, context: dict | None = None) -> str:
        values = {
            k: self.context_fields[k].validate(v)
            for k, v in (context or {}).items()
            if k in self.context_fields
        }
        encoded = {
            k: (
                v
                if self.context_fields[k].kind in ("host", "origin")
                else quote(v, safe="")
            )
            for k, v in values.items()
            if k in self.context_fields
        }
        try:
            return template.format_map(encoded)
        except KeyError:
            raise ValueError("Missing OAuth URL context") from None

    def _client(self, template: str):
        if "{" in template:
            from utils.ssrf import guarded_async_client

            return guarded_async_client(timeout=30)
        return httpx.AsyncClient(timeout=30)

    @property
    def credential_fields(self):
        return tuple(dict.fromkeys((*self.token_fields, *self.context_fields)))

    def bind_refresh(self, credential: dict):
        async def refresh(refresh_token):
            context = self.validate_context(
                {k: credential[k] for k in self.context_fields if k in credential}
            )
            return await self.refresh(refresh_token, context=context)

        return refresh

    def granted_scopes(self, tokens: OAuthTokens, requested: list[str]):
        if set(requested) - set(self.scopes):
            raise ValueError("Unknown OAuth scope")
        granted = (
            [
                s
                for s in (
                    tokens.scope.replace(",", " ")
                    if self.scope_separator == ","
                    else tokens.scope
                ).split()
                if s
            ]
            if tokens.scope is not None
            else requested
        )
        if set(requested) - set(granted):
            raise ValueError("OAuth provider did not grant all requested scopes")
        return granted

    def token_request(self, grant: dict[str, str], *, context=None) -> dict:
        """The one request builder, also usable by credential-free probes."""
        token_auth = (
            (self.refresh_token_auth or self.token_auth)
            if grant.get("grant_type") == "refresh_token"
            else self.token_auth
        )
        grant_kind = grant.get("grant_type")
        if grant_kind in self.token_grant_fields:
            grant = {
                k: v
                for k, v in grant.items()
                if k in self.token_grant_fields[grant_kind]
            }
        client_id = os.environ[self.client_id_env] if self.client_id_env else None
        client_secret = (
            os.environ[self.client_secret_env] if token_auth != "none" else None
        )
        data = {**self.token_params, **grant}
        if token_auth == "body":
            data.update(client_id=client_id, client_secret=client_secret)
            auth = None
        elif token_auth == "basic":
            auth = httpx.BasicAuth(client_id, client_secret)
        else:
            if client_id:
                data["client_id"] = client_id
            auth = None
        return {
            "url": self.endpoint(
                self.refresh_url
                if grant_kind == "refresh_token" and self.refresh_url
                else self.token_url,
                context,
            ),
            ("json" if self.token_format == "json" else "data"): data,
            "auth": auth,
            "headers": {"Accept": "application/json"},
        }

    async def _tokens(
        self, grant: dict[str, str], *, context=None
    ) -> tuple[OAuthTokens, dict]:
        template = (
            self.refresh_url
            if grant.get("grant_type") == "refresh_token" and self.refresh_url
            else self.token_url
        )
        async with self._client(template) as client:
            response = await client.post(
                **self.token_request(
                    grant, **({"context": context} if self.context_fields else {})
                )
            )
        return self.parse_tokens(response, context=context)

    def parse_tokens(self, response: httpx.Response, *, context=None):
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Invalid OAuth token response")
        if response.is_error or payload.get("error"):
            # Never copy the upstream body (which may contain credentials) to
            # logs or callers. Retain the OAuth error code for refresh auditing.
            error = payload.get("error")
            safe_error = (
                error
                if isinstance(error, str) and re.fullmatch(r"[a-z_]+", error)
                else "token_request_failed"
            )
            raise ValueError(
                f"{self.provider} OAuth {safe_error} ({response.status_code})"
            )
        if not payload.get("access_token"):
            raise ValueError(f"{self.provider} response missing access_token")
        from nodes.core.oauth_refresh import require_rotated_refresh_token

        refresh_token = (
            require_rotated_refresh_token(payload, provider=self.provider)
            if self.rotates_refresh_tokens
            else payload.get("refresh_token")
        )
        expires_at = None
        if payload.get("expires_in") is not None:
            try:
                lifetime = int(payload["expires_in"])
            except (ValueError, TypeError):
                raise ValueError("Invalid OAuth token expiry") from None
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=lifetime)
            ).isoformat()
        if self.expires_at_field:
            try:
                timestamp = float(read_field(payload, self.expires_at_field))
                expires_at = datetime.fromtimestamp(
                    timestamp / (1000 if self.expires_at_unit == "milliseconds" else 1),
                    timezone.utc,
                ).isoformat()
            except (KeyError, ValueError, TypeError, OverflowError, OSError):
                raise ValueError("Invalid OAuth absolute token expiry") from None
        saved_context = dict(context or {})
        for key, definition in self.context_fields.items():
            if definition.source == "token" and key in payload:
                saved_context[key] = definition.validate(payload[key])
        if self.context_fields:
            saved_context = self.validate_context(saved_context)
        try:
            tokens = OAuthTokens(
                access_token=payload["access_token"],
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=payload.get("scope"),
                token_type=payload.get("token_type", "Bearer"),
                **{
                    **{
                        key: payload[key] for key in self.token_fields if key in payload
                    },
                    **saved_context,
                },
            )
        except ValueError:
            raise ValueError("Invalid OAuth token response fields") from None
        if self.scope_separator == "," and tokens.scope is not None:
            # The credential/refresh audit format is always space-delimited,
            # even when the provider uses commas on the wire.
            tokens.scope = " ".join(tokens.scope.replace(",", " ").split())
        return tokens, payload

    async def exchange(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        *,
        context=None,
    ) -> tuple[OAuthTokens, str]:
        if not self.authorize_url:
            raise ValueError("Provider uses device authorization")
        context = self.validate_context(context, sources={"input", "callback"})
        configured_redirect = os.environ.get(self.redirect_uri_env)
        if configured_redirect and redirect_uri != configured_redirect:
            raise ValueError("OAuth redirect URI does not match configured URI")
        grant = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if self.pkce:
            if not code_verifier or not re.fullmatch(
                r"[A-Za-z0-9._~-]{43,128}", code_verifier
            ):
                raise ValueError("OAuth PKCE verifier is required")
            grant["code_verifier"] = code_verifier
        # Existing declarations may specialize the original transport/identity
        # signatures. Only context-aware declarations opt into the new argument.
        tokens, _ = await self._tokens(
            grant, **({"context": context} if self.context_fields else {})
        )
        name = await self.account_name(
            tokens.access_token,
            **(
                {"context": {k: getattr(tokens, k) for k in self.context_fields}}
                if self.context_fields
                else {}
            ),
        )
        return tokens, name

    async def account_name(self, access_token: str, *, context=None) -> str:
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(
                self.endpoint(self.identity_url, context),
                headers={"Authorization": f"Bearer {access_token}"},
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{self.provider} returned no account name")
        return name

    async def refresh(self, refresh_token: str, *, context=None) -> OAuthTokens:
        tokens, _ = await self._tokens(
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            **({"context": context} if self.context_fields else {}),
        )
        return tokens

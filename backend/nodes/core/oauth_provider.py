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
        value = value[part]
    return value


@dataclass(frozen=True, kw_only=True)
class OAuthProviderSpec:
    provider: str
    authorize_url: str
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
    token_auth: Literal["basic", "body"] = "body"
    rotates_refresh_tokens: bool = False
    authorize_params: dict[str, str] = field(default_factory=dict)
    token_params: dict[str, str] = field(default_factory=dict)
    token_fields: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.identity_url:
            raise ValueError("OAuth identity_url is required")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.provider):
            raise ValueError("Invalid OAuth provider id")
        if self.scope_registry.provider != self.provider:
            raise ValueError("OAuth scope registry must belong to the provider")
        if self.token_auth not in ("basic", "body"):
            raise ValueError("Invalid OAuth token authentication")
        for url in (self.authorize_url, self.token_url, self.identity_url):
            if url and not url.startswith("https://"):
                raise ValueError("OAuth endpoints must use HTTPS")
        for env in (self.client_id_env, self.client_secret_env, self.redirect_uri_env):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env):
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
        return {
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

    def token_request(self, grant: dict[str, str]) -> dict:
        """The one request builder, also usable by credential-free probes."""
        client_id = os.environ[self.client_id_env]
        client_secret = os.environ[self.client_secret_env]
        data = {**self.token_params, **grant}
        if self.token_auth == "body":
            data.update(client_id=client_id, client_secret=client_secret)
            auth = None
        else:
            auth = httpx.BasicAuth(client_id, client_secret)
        return {
            "url": self.token_url,
            "data": data,
            "auth": auth,
            "headers": {"Accept": "application/json"},
        }

    async def _tokens(self, grant: dict[str, str]) -> tuple[OAuthTokens, dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(**self.token_request(grant))
        payload = response.json()
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
        try:
            tokens = OAuthTokens(
                access_token=payload["access_token"],
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=payload.get("scope"),
                token_type=payload.get("token_type", "Bearer"),
                **{key: payload[key] for key in self.token_fields if key in payload},
            )
        except ValueError:
            raise ValueError("Invalid OAuth token response fields") from None
        return tokens, payload

    async def exchange(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> tuple[OAuthTokens, str]:
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
        tokens, _ = await self._tokens(grant)
        name = await self.account_name(tokens.access_token)
        return tokens, name

    async def account_name(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.identity_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{self.provider} returned no account name")
        return name

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        tokens, _ = await self._tokens(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        return tokens

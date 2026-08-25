"""
Pydantic models for MCP OAuth 2.1 endpoints.

Follows RFC 7591 (Dynamic Client Registration), RFC 6749 (OAuth 2.0),
and RFC 7636 (PKCE) specifications as required by MCP protocol.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Discovery Metadata Models (RFC 8414, RFC 9728)
# =============================================================================


class ProtectedResourceMetadata(BaseModel):
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Returned at /.well-known/oauth-protected-resource
    """

    resource: str = Field(description="The protected resource identifier (MCP endpoint URL)")
    authorization_servers: list[str] = Field(
        description="List of authorization server URLs that can issue tokens for this resource"
    )
    scopes_supported: list[str] = Field(
        default=["mcp:tools"],
        description="Scopes available for this resource",
    )


class AuthorizationServerMetadata(BaseModel):
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Returned at /.well-known/oauth-authorization-server
    """

    model_config = ConfigDict(exclude_none=True)

    issuer: str = Field(description="Authorization server identifier")
    authorization_endpoint: str = Field(description="URL of authorization endpoint")
    token_endpoint: str = Field(description="URL of token endpoint")
    registration_endpoint: Optional[str] = Field(
        default=None, description="URL of dynamic client registration endpoint"
    )
    scopes_supported: list[str] = Field(default=["mcp:tools"])
    response_types_supported: list[str] = Field(default=["code"])
    grant_types_supported: list[str] = Field(
        default=["authorization_code", "refresh_token"]
    )
    token_endpoint_auth_methods_supported: list[str] = Field(default=["none", "client_secret_post"])
    code_challenge_methods_supported: list[str] = Field(default=["S256"])


# =============================================================================
# Dynamic Client Registration Models (RFC 7591)
# =============================================================================


class ClientRegistrationRequest(BaseModel):
    """
    Dynamic Client Registration request.

    MCP clients send this to register themselves before starting OAuth flow.
    """

    model_config = ConfigDict(extra="ignore")

    client_name: str = Field(description="Human-readable name of the client")
    redirect_uris: list[str] = Field(
        description="List of allowed redirect URIs for this client"
    )
    grant_types: list[str] = Field(
        default=["authorization_code"],
        description="OAuth grant types this client will use",
    )
    response_types: list[str] = Field(
        default=["code"],
        description="OAuth response types this client will use",
    )
    token_endpoint_auth_method: str = Field(
        default="none",
        description="Authentication method for token endpoint (public clients use 'none')",
    )
    # Optional metadata
    client_uri: Optional[str] = Field(
        default=None, description="URL of the client's home page"
    )
    logo_uri: Optional[str] = Field(
        default=None, description="URL of the client's logo"
    )


class ClientRegistrationResponse(BaseModel):
    """
    Dynamic Client Registration response.

    Returns the registered client information including generated client_id.
    """

    model_config = ConfigDict(exclude_none=True)

    client_id: str = Field(description="Unique identifier for the registered client")
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str] = ["code"]
    token_endpoint_auth_method: str
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    # Registration metadata
    client_id_issued_at: int = Field(
        description="Unix timestamp when client_id was issued"
    )


# =============================================================================
# Authorization Models (RFC 6749)
# =============================================================================


class AuthorizationRequest(BaseModel):
    """
    Authorization request parameters (query string).

    Parsed from /mcp/authorize?client_id=...&redirect_uri=...&...
    """

    client_id: str = Field(description="The registered client ID")
    redirect_uri: str = Field(description="URI to redirect after authorization")
    response_type: str = Field(default="code", description="Must be 'code'")
    scope: str = Field(default="mcp:tools", description="Requested scopes")
    state: str = Field(description="Opaque state value for CSRF protection")
    code_challenge: str = Field(description="PKCE code challenge (S256)")
    code_challenge_method: str = Field(default="S256", description="Must be 'S256'")

    @field_validator("response_type")
    @classmethod
    def validate_response_type(cls, v: str) -> str:
        if v != "code":
            raise ValueError("response_type must be 'code'")
        return v

    @field_validator("code_challenge_method")
    @classmethod
    def validate_code_challenge_method(cls, v: str) -> str:
        if v != "S256":
            raise ValueError("code_challenge_method must be 'S256'")
        return v


# =============================================================================
# Token Models (RFC 6749)
# =============================================================================


class TokenRequest(BaseModel):
    """
    Token exchange request (form data).

    Sent to /mcp/token to exchange authorization code for access token.
    """

    grant_type: str = Field(description="Must be 'authorization_code' or 'refresh_token'")
    code: Optional[str] = Field(default=None, description="Authorization code (for authorization_code grant)")
    redirect_uri: Optional[str] = Field(default=None, description="Must match original redirect_uri")
    client_id: str = Field(description="The registered client ID")
    code_verifier: Optional[str] = Field(default=None, description="PKCE code verifier (for authorization_code grant)")
    refresh_token: Optional[str] = Field(default=None, description="Refresh token (for refresh_token grant)")

    @field_validator("grant_type")
    @classmethod
    def validate_grant_type(cls, v: str) -> str:
        if v not in ("authorization_code", "refresh_token"):
            raise ValueError("grant_type must be 'authorization_code' or 'refresh_token'")
        return v


class TokenResponse(BaseModel):
    """
    Token response.

    Returned from /mcp/token with access token and optional refresh token.
    """

    model_config = ConfigDict(exclude_none=True)

    access_token: str = Field(description="The MCP access token (JWT)")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_in: int = Field(description="Token lifetime in seconds")
    scope: str = Field(description="Granted scopes")
    refresh_token: Optional[str] = Field(
        default=None, description="Refresh token for obtaining new access tokens"
    )


class TokenErrorResponse(BaseModel):
    """
    Token error response (RFC 6749 Section 5.2).
    """

    model_config = ConfigDict(exclude_none=True)

    error: str = Field(
        description="Error code: invalid_request, invalid_client, invalid_grant, "
        "unauthorized_client, unsupported_grant_type, invalid_scope"
    )
    error_description: Optional[str] = Field(
        default=None, description="Human-readable error description"
    )


# =============================================================================
# Internal Storage Models
# =============================================================================


class StoredClient(BaseModel):
    """
    Client registration stored in Redis.
    """

    client_id: str
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    token_endpoint_auth_method: str
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    created_at: datetime


class StoredAuthorizationCode(BaseModel):
    """
    Authorization code stored in Redis (short-lived, single-use).
    """

    code: str
    client_id: str
    user_id: str
    redirect_uri: str
    scope: str
    code_challenge: str
    created_at: datetime
    expires_at: datetime


class StoredRefreshToken(BaseModel):
    """
    Refresh token stored in Redis.
    """

    token: str
    client_id: str
    user_id: str
    scope: str
    created_at: datetime
    expires_at: datetime

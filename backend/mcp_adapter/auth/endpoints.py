"""
MCP OAuth 2.1 HTTP endpoints.

Implements the full OAuth 2.1 flow for MCP clients:
1. Discovery (/.well-known/*)
2. Dynamic Client Registration (/mcp/register)
3. Authorization (/mcp/authorize)
4. Token Exchange (/mcp/token)

The authorization endpoint redirects to the frontend consent page.
"""

import os
import hashlib
import base64
import secrets
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

from mcp_adapter.auth.models import (
    ProtectedResourceMetadata,
    AuthorizationServerMetadata,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    TokenRequest,
    TokenResponse,
    TokenErrorResponse,
    StoredClient,
)
from mcp_adapter.auth.storage import MCPOAuthStorage
from mcp_adapter.auth.tokens import issue_mcp_token, DEFAULT_TOKEN_EXPIRY_HOURS

logger = logging.getLogger(__name__)

# Environment configuration
def get_base_url() -> str:
    """Get the base URL for OAuth endpoints.

    Uses MCP_BASE_URL if set, otherwise derives from PORT env var.
    """
    if os.getenv("MCP_BASE_URL"):
        return os.getenv("MCP_BASE_URL")

    # Derive from PORT env var (default 8000)
    port = os.getenv("PORT", "8000")
    return f"http://localhost:{port}"


def get_frontend_url() -> str:
    """The frontend base URL for login redirects and every minted shareable
    link (bridge /b pages, credential provide, shared agent pages). In
    DEV_MODE the default is the local dev server because capability ids are
    scoped to the environment that minted them."""
    explicit = os.getenv("FRONTEND_URL") or os.getenv("VITE_PUBLIC_URL")
    if explicit:
        return explicit
    if os.getenv("DEV_MODE") == "1":
        return "http://localhost:5173"
    return "https://noclick.com"


def _get_base_url_from_request(request: Request) -> str:
    """Derive base URL from the incoming request, falling back to get_base_url()."""
    request_url = str(request.base_url).rstrip("/")
    explicit = os.getenv("MCP_BASE_URL")
    if explicit:
        # Only use MCP_BASE_URL if the request is coming through the expected host
        # (e.g., via Cloudflare proxy). For dev containers on different hostnames,
        # use the actual request URL so OAuth resource metadata matches.
        from urllib.parse import urlparse
        explicit_host = urlparse(explicit).hostname
        request_host = request.headers.get("host", "").split(":")[0]
        forwarded_host = request.headers.get("x-forwarded-host", "").split(":")[0]
        original_host = request.headers.get("x-noclick-original-host", "").split(":")[0]
        if explicit_host in (request_host, forwarded_host, original_host):
            return explicit
    # Use the request's own scheme + host so the URL matches whatever port the server runs on
    return request_url


# =============================================================================
# PKCE Utilities
# =============================================================================


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """
    Verify PKCE code_verifier against stored code_challenge.

    Uses S256 method: BASE64URL(SHA256(code_verifier)) == code_challenge

    Args:
        code_verifier: The plain text verifier from token request
        code_challenge: The challenge stored during authorization

    Returns:
        True if verification passes
    """
    # Compute SHA256 hash
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()

    # Base64url encode (no padding)
    computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return secrets.compare_digest(computed_challenge, code_challenge)


def redirect_uri_allowed(client: StoredClient, redirect_uri: str) -> bool:
    """Exact match, or same https origin as a registered redirect URI.

    ChatGPT reuses the client_id from its original DCR but rotates its
    callback path per connector/app version (connector_platform_oauth_redirect
    → /connector/oauth/{id}), so exact matching bricks every re-auth. PKCE is
    mandatory and DCR is open, so same-origin loses no real security: codes
    still only reach an origin the original registrant controls.
    """
    if redirect_uri in client.redirect_uris:
        return True
    presented = urllib.parse.urlsplit(redirect_uri)
    if presented.scheme != "https" or not presented.netloc:
        return False
    return any(
        registered.scheme == "https" and registered.netloc == presented.netloc
        for registered in map(urllib.parse.urlsplit, client.redirect_uris)
    )


def _oauth_redirect_url(redirect_uri: str, **params: str) -> str:
    """Append OAuth response parameters without allowing query injection."""
    parsed = urllib.parse.urlsplit(redirect_uri)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


# =============================================================================
# Consent Page HTML
# =============================================================================


def render_consent_page(
    client_name: str,
    client_uri: Optional[str],
    scopes: list[str],
    redirect_uri: str,
    state: str,
    code_challenge: str,
    client_id: str,
) -> str:
    """
    Render the OAuth consent page HTML.

    This is a simple, self-contained page that asks the user to approve
    the MCP client's access request.
    """
    scope_list = "".join(f"<li>{scope}</li>" for scope in scopes)
    client_link = (
        f'<a href="{client_uri}" target="_blank" rel="noopener">{client_name}</a>'
        if client_uri
        else client_name
    )

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorize {client_name} - NoClick</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #09090b;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: #09090b;
            border: 1px solid #27272a;
            border-radius: 16px;
            padding: 32px;
            max-width: 380px;
            width: 100%;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            margin-bottom: 32px;
        }}
        .logo {{
            width: 28px;
            height: 28px;
        }}
        .logo svg {{
            width: 100%;
            height: 100%;
        }}
        .logo-text {{
            font-size: 22px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: -0.03em;
        }}
        h1 {{
            font-size: 18px;
            font-weight: 500;
            color: #ffffff;
            text-align: center;
            margin-bottom: 6px;
            letter-spacing: -0.01em;
        }}
        .client-name {{
            color: #ffffff;
            font-weight: 600;
        }}
        .client-name a {{
            color: #ffffff;
            text-decoration: none;
            border-bottom: 1px solid #52525b;
            transition: border-color 0.15s;
        }}
        .client-name a:hover {{
            border-color: #a1a1aa;
        }}
        .description {{
            color: #71717a;
            text-align: center;
            margin-bottom: 24px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .scopes {{
            background: rgba(24, 24, 27, 0.6);
            border: 1px solid #27272a;
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 24px;
        }}
        .scopes-title {{
            font-size: 10px;
            font-weight: 600;
            color: #52525b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 10px;
        }}
        .scopes ul {{
            list-style: none;
        }}
        .scopes li {{
            display: flex;
            align-items: center;
            padding: 5px 0;
            color: #a1a1aa;
            font-size: 13px;
        }}
        .scopes li::before {{
            content: "";
            width: 14px;
            height: 14px;
            margin-right: 10px;
            background: #22c55e;
            border-radius: 50%;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='white'%3E%3Cpath d='M12.207 4.793a1 1 0 010 1.414l-5 5a1 1 0 01-1.414 0l-2-2a1 1 0 011.414-1.414L6.5 9.086l4.293-4.293a1 1 0 011.414 0z'/%3E%3C/svg%3E");
            background-size: 9px;
            background-repeat: no-repeat;
            background-position: center;
            flex-shrink: 0;
        }}
        .buttons {{
            display: flex;
            gap: 10px;
        }}
        button {{
            flex: 1;
            padding: 11px 18px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            border: none;
        }}
        .btn-approve {{
            background: #ffffff;
            color: #09090b;
        }}
        .btn-approve:hover {{
            background: #e4e4e7;
        }}
        .btn-deny {{
            background: transparent;
            color: #71717a;
            border: 1px solid #27272a;
        }}
        .btn-deny:hover {{
            background: #18181b;
            color: #a1a1aa;
            border-color: #3f3f46;
        }}
        .redirect-info {{
            margin-top: 20px;
            padding-top: 14px;
            border-top: 1px solid #18181b;
            font-size: 10px;
            color: #3f3f46;
            text-align: center;
            word-break: break-all;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 499 499" fill="none">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M4.364 1.16509C3.189 1.73709 1.727 3.30409 1.114 4.64909C0.308 6.41909 0 59.9921 0 198.624C0 390.154 0 390.154 3.046 393.2C9.504 399.658 4.522 403.973 94.475 314.025C175.509 232.996 175.509 232.996 204.493 261.993C233.477 290.99 233.477 290.99 162.871 361.745C102.884 421.858 91.862 433.343 89.586 438.106C78.436 461.434 90.073 488.305 114.86 496.469C123.494 499.312 135.857 498.314 144.627 494.067C151.009 490.975 156.536 485.712 222.013 420.379C292.525 350.02 292.525 350.02 361.013 418.533C398.681 456.214 431.171 488.21 433.214 489.634C439.38 493.931 449.244 497 456.889 497C487.231 497 506.795 466.17 494.427 437.846C491.837 431.914 487.084 426.915 421.598 361.247C351.54 290.994 351.54 290.994 420.637 221.747C495.936 146.285 493.567 149.014 496.126 134.785C499.652 115.168 487.889 95.7401 468.357 88.9211C459.622 85.8721 446.797 86.5141 438 90.4421C431.915 93.1591 427.065 97.7661 361.985 162.664C292.47 231.983 292.47 231.983 263.493 202.993C234.515 174.002 234.515 174.002 314.757 93.7361C403.441 5.02709 398.137 11.1831 392.11 3.96209C389.219 0.500089 389.219 0.500089 197.86 0.314089C67.242 0.186089 5.822 0.457089 4.364 1.16509Z" fill="#ffffff"/>
                </svg>
            </div>
            <span class="logo-text">NoClick</span>
        </div>

        <h1><span class="client-name">{client_link}</span> wants to connect</h1>
        <p class="description">
            Grant access to your NoClick tools and database
        </p>

        <div class="scopes">
            <div class="scopes-title">Permissions requested</div>
            <ul>
                {scope_list}
            </ul>
        </div>

        <form method="POST" action="/mcp/authorize/consent">
            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="state" value="{state}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="scope" value="{' '.join(scopes)}">

            <div class="buttons">
                <button type="submit" name="action" value="deny" class="btn-deny">Cancel</button>
                <button type="submit" name="action" value="approve" class="btn-approve">Allow</button>
            </div>
        </form>

        <div class="redirect-info">
            {redirect_uri}
        </div>
    </div>
</body>
</html>
"""


# =============================================================================
# Router Factory
# =============================================================================


def create_mcp_oauth_router(storage: Optional[MCPOAuthStorage] = None) -> APIRouter:
    """
    Create FastAPI router with all MCP OAuth endpoints.

    Args:
        storage: Optional storage instance (creates default if not provided)

    Returns:
        Configured APIRouter
    """
    router = APIRouter()
    oauth_storage = storage or MCPOAuthStorage()

    # =========================================================================
    # Discovery Endpoints
    # =========================================================================

    # Both root and path-suffixed discovery endpoints are needed:
    # - Root paths (3/26 MCP auth spec): /.well-known/oauth-protected-resource
    # - Path-suffixed (6/18 spec, RFC 9728): /.well-known/oauth-protected-resource/mcp

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource_metadata(request: Request) -> ProtectedResourceMetadata:
        """
        OAuth 2.0 Protected Resource Metadata (RFC 9728).

        MCP clients fetch this to discover the authorization server.
        """
        base_url = _get_base_url_from_request(request)
        return ProtectedResourceMetadata(
            resource=f"{base_url}/mcp",
            authorization_servers=[base_url],
            scopes_supported=["mcp:tools"],
        )

    @router.get("/.well-known/openid-configuration")
    @router.get("/.well-known/oauth-authorization-server")
    @router.get("/.well-known/oauth-authorization-server/mcp")
    async def authorization_server_metadata(request: Request) -> AuthorizationServerMetadata:
        """
        OAuth 2.0 Authorization Server Metadata (RFC 8414).

        MCP clients fetch this to discover OAuth endpoints.
        """
        base_url = _get_base_url_from_request(request)
        return AuthorizationServerMetadata(
            issuer=base_url,
            authorization_endpoint=f"{base_url}/mcp/authorize",
            token_endpoint=f"{base_url}/mcp/token",
            registration_endpoint=f"{base_url}/mcp/register",
            scopes_supported=["mcp:tools"],
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none", "client_secret_post"],
            code_challenge_methods_supported=["S256"],
        )

    # =========================================================================
    # Dynamic Client Registration (RFC 7591)
    # =========================================================================

    @router.post("/mcp/register")
    async def register_client(
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse:
        """
        Dynamic Client Registration endpoint.

        MCP clients call this to register before starting OAuth flow.
        Idempotent: returns existing client if same redirect_uris are registered again.
        """
        # Check for existing client with same redirect_uris (idempotent DCR)
        existing = await oauth_storage.find_client_by_redirect_uris(request.redirect_uris)
        if existing:
            logger.info(f"[MCP OAuth] Returning existing client: {existing.client_id} ({existing.client_name})")
            response = ClientRegistrationResponse(
                client_id=existing.client_id,
                client_name=existing.client_name,
                redirect_uris=existing.redirect_uris,
                grant_types=existing.grant_types,
                response_types=request.response_types,
                token_endpoint_auth_method=existing.token_endpoint_auth_method,
                client_uri=existing.client_uri,
                logo_uri=existing.logo_uri,
                client_id_issued_at=int(existing.created_at.timestamp()),
            )
            return JSONResponse(content=response.model_dump(exclude_none=True))

        # Deterministic client_id from redirect_uris ensures idempotent DCR
        client_id = oauth_storage.deterministic_client_id(request.redirect_uris)
        now = datetime.now(timezone.utc)

        # Store client — always use "none" internally since we're a public client,
        # but accept whatever the client sends (e.g. Claude.ai sends "client_secret_post")
        client = StoredClient(
            client_id=client_id,
            client_name=request.client_name,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
            client_uri=request.client_uri,
            logo_uri=request.logo_uri,
            created_at=now,
        )

        success = await oauth_storage.store_client(client)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to register client")

        logger.info(f"[MCP OAuth] Registered new client: {client_id} ({request.client_name})")

        response = ClientRegistrationResponse(
            client_id=client_id,
            client_name=request.client_name,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
            client_uri=request.client_uri,
            logo_uri=request.logo_uri,
            client_id_issued_at=int(now.timestamp()),
        )
        # Use exclude_none to omit null optional fields (RFC 7591 compliance)
        return JSONResponse(content=response.model_dump(exclude_none=True))

    # =========================================================================
    # Authorization Endpoint
    # =========================================================================

    @router.get("/mcp/authorize")
    async def authorize(
        request: Request,
        client_id: str = Query(...),
        redirect_uri: str = Query(...),
        response_type: str = Query(default="code"),
        scope: str = Query(default="mcp:tools"),
        state: str = Query(...),
        code_challenge: str = Query(...),
        code_challenge_method: str = Query(default="S256"),
    ):
        """
        Authorization endpoint - redirects to frontend consent page.

        The frontend handles authentication (Supabase session) and renders
        the consent UI. This avoids cross-domain cookie issues.
        """
        # Never redirect to a caller-provided URI until both the client and URI
        # have been validated. In particular, an unknown client cannot supply
        # an arbitrary open-redirect target for an error response.
        client = await oauth_storage.get_client(client_id)
        if not client:
            logger.warning(f"[MCP OAuth] Authorize: client not found: {client_id}")
            return HTMLResponse(
                content="<h1>Error: Invalid client</h1>",
                status_code=400,
            )

        if not redirect_uri_allowed(client, redirect_uri):
            logger.warning(f"[MCP OAuth] Authorize: redirect_uri mismatch: {redirect_uri} not in {client.redirect_uris}")
            return HTMLResponse(
                content="<h1>Error: Invalid redirect_uri</h1><p>The redirect URI is not registered for this client.</p>",
                status_code=400,
            )

        if response_type != "code":
            return RedirectResponse(
                _oauth_redirect_url(
                    redirect_uri,
                    error="unsupported_response_type",
                    state=state,
                )
            )

        if code_challenge_method != "S256":
            return RedirectResponse(
                _oauth_redirect_url(
                    redirect_uri,
                    error="invalid_request",
                    error_description="code_challenge_method must be S256",
                    state=state,
                )
            )

        # Redirect to frontend consent page (where Supabase session is available)
        frontend_url = get_frontend_url()
        params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "scope": scope,
            "client_name": client.client_name or "Unknown App",
        })
        # A different path from this endpoint on purpose: an installation that
        # serves the app and the backend on ONE origin (the single-container
        # image, and every one-click host) would otherwise have this redirect
        # point at itself.
        return RedirectResponse(
            f"{frontend_url}/mcp/consent?{params}",
            status_code=302,
        )

    @router.post("/mcp/authorize/consent")
    async def handle_consent(
        request: Request,
        client_id: str = Form(...),
        redirect_uri: str = Form(...),
        state: str = Form(...),
        code_challenge: str = Form(...),
        scope: str = Form(...),
        action: str = Form(...),
        access_token: str = Form(...),
    ):
        """
        Handle consent form submission.

        The frontend sends the Supabase access_token so we can identify the user
        without relying on cross-domain cookies.

        If approved, generates authorization code and returns redirect URL.
        If denied, returns redirect URL with error.

        Returns JSON with redirect_url instead of a 302 RedirectResponse
        because some reverse proxies do not preserve POST redirects with streamed
        request bodies. The frontend action performs the redirect.
        """
        # Validate registration before returning any browser-followed URL.
        client = await oauth_storage.get_client(client_id)
        if not client:
            return JSONResponse(
                content={"error": "Invalid client"},
                status_code=400,
            )

        if not redirect_uri_allowed(client, redirect_uri):
            return JSONResponse(
                content={"error": "Invalid redirect_uri"},
                status_code=400,
            )

        if action == "deny":
            return JSONResponse(
                content={
                    "redirect_url": _oauth_redirect_url(
                        redirect_uri, error="access_denied", state=state
                    )
                }
            )

        # Verify the Supabase access token to get user_id
        from utils.auth import verify_token

        try:
            token_data = await verify_token(access_token)
            user_id = token_data["sub"]
        except Exception as e:
            logger.error(f"[MCP OAuth] Failed to verify access token: {e}")
            return JSONResponse(
                content={
                    "redirect_url": _oauth_redirect_url(
                        redirect_uri,
                        error="access_denied",
                        error_description="authentication required",
                        state=state,
                    )
                }
            )

        # Generate authorization code
        code = await oauth_storage.store_authorization_code(
            client_id=client_id,
            user_id=user_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
        )

        if not code:
            return JSONResponse(
                content={
                    "redirect_url": _oauth_redirect_url(
                        redirect_uri, error="server_error", state=state
                    )
                }
            )

        logger.info(
            f"[MCP OAuth] User {user_id} authorized client {client_id}, "
            f"redirecting with code"
        )

        # Return redirect URL for the frontend to follow
        return JSONResponse(
            content={
                "redirect_url": _oauth_redirect_url(
                    redirect_uri, code=code, state=state
                )
            }
        )

    # =========================================================================
    # Token Endpoint
    # =========================================================================

    @router.post("/mcp/token")
    async def token_exchange(
        grant_type: str = Form(...),
        code: Optional[str] = Form(default=None),
        redirect_uri: Optional[str] = Form(default=None),
        client_id: str = Form(...),
        code_verifier: Optional[str] = Form(default=None),
        refresh_token: Optional[str] = Form(default=None),
        # Accept client_secret for clients using client_secret_post auth method
        # (e.g. Claude.ai). We ignore it since we're a public PKCE-based server.
        client_secret: Optional[str] = Form(default=None),
    ):
        """
        Token endpoint - exchanges authorization code or refresh token for access token.
        """
        if grant_type == "authorization_code":
            return await _handle_authorization_code_grant(
                oauth_storage, code, redirect_uri, client_id, code_verifier
            )
        elif grant_type == "refresh_token":
            return await _handle_refresh_token_grant(
                oauth_storage, refresh_token, client_id
            )
        else:
            return JSONResponse(
                status_code=400,
                content=TokenErrorResponse(
                    error="unsupported_grant_type",
                    error_description="grant_type must be 'authorization_code' or 'refresh_token'",
                ).model_dump(),
            )

    return router


async def _handle_authorization_code_grant(
    storage: MCPOAuthStorage,
    code: Optional[str],
    redirect_uri: Optional[str],
    client_id: str,
    code_verifier: Optional[str],
) -> JSONResponse:
    """Handle authorization_code grant type."""
    # Validate required parameters
    if not code or not redirect_uri or not code_verifier:
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_request",
                error_description="code, redirect_uri, and code_verifier are required",
            ).model_dump(),
        )

    # Consume authorization code (single-use)
    auth_code = await storage.consume_authorization_code(code)
    if not auth_code:
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="Authorization code is invalid or expired",
            ).model_dump(),
        )

    # Verify client_id matches
    if auth_code.client_id != client_id:
        logger.warning(
            f"[MCP OAuth] client_id mismatch: expected {auth_code.client_id}, got {client_id}"
        )
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="client_id does not match",
            ).model_dump(),
        )

    # Verify redirect_uri matches
    if auth_code.redirect_uri != redirect_uri:
        logger.warning(
            f"[MCP OAuth] redirect_uri mismatch: expected {auth_code.redirect_uri}"
        )
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="redirect_uri does not match",
            ).model_dump(),
        )

    # Verify PKCE
    if not verify_pkce(code_verifier, auth_code.code_challenge):
        logger.warning("[MCP OAuth] PKCE verification failed")
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="PKCE verification failed",
            ).model_dump(),
        )

    # Issue access token
    scopes = auth_code.scope.split()
    access_token = issue_mcp_token(
        user_id=auth_code.user_id,
        client_id=client_id,
        scopes=scopes,
    )

    # Issue refresh token
    refresh_token = await storage.store_refresh_token(
        client_id=client_id,
        user_id=auth_code.user_id,
        scope=auth_code.scope,
    )

    logger.info(
        f"[MCP OAuth] Issued tokens for user={auth_code.user_id}, client={client_id}"
    )

    return JSONResponse(
        content=TokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=DEFAULT_TOKEN_EXPIRY_HOURS * 3600,
            scope=auth_code.scope,
            refresh_token=refresh_token,
        ).model_dump(exclude_none=True),
    )


async def _handle_refresh_token_grant(
    storage: MCPOAuthStorage,
    refresh_token: Optional[str],
    client_id: str,
) -> JSONResponse:
    """Handle refresh_token grant type."""
    if not refresh_token:
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_request",
                error_description="refresh_token is required",
            ).model_dump(),
        )

    # Rotate refresh token (get old data, revoke old, issue new)
    result = await storage.rotate_refresh_token(refresh_token)
    if not result:
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="Refresh token is invalid or expired",
            ).model_dump(),
        )

    new_refresh_token, token_data = result

    # Verify client_id matches
    if token_data.client_id != client_id:
        # Revoke the newly issued token since client doesn't match
        await storage.revoke_refresh_token(new_refresh_token)
        return JSONResponse(
            status_code=400,
            content=TokenErrorResponse(
                error="invalid_grant",
                error_description="client_id does not match",
            ).model_dump(),
        )

    # Issue new access token
    scopes = token_data.scope.split()
    access_token = issue_mcp_token(
        user_id=token_data.user_id,
        client_id=client_id,
        scopes=scopes,
    )

    logger.info(
        f"[MCP OAuth] Refreshed tokens for user={token_data.user_id}, client={client_id}"
    )

    return JSONResponse(
        content=TokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=DEFAULT_TOKEN_EXPIRY_HOURS * 3600,
            scope=token_data.scope,
            refresh_token=new_refresh_token,
        ).model_dump(exclude_none=True),
    )

"""A vendor's remote MCP server with the MCP auth spec, served on loopback for tests.

Protected resource metadata (RFC 9728) behind a 401's ``WWW-Authenticate``,
authorization server metadata (RFC 8414), Dynamic Client Registration (RFC
7591), an authorization endpoint that signs the "person" in at once (a GET
answers a 302 with a code, as a browser that consented would be sent), a token
endpoint that checks PKCE S256, the resource indicator and the redirect URI and
rotates refresh tokens, and a Streamable HTTP MCP endpoint (the official SDK's
FastMCP) that answers only a live bearer token.

Knobs for the paths a real vendor takes: ``allowed_redirect_hosts`` refuses
any other redirect at authorize the way Canva's server does ("Invalid redirect
URI."); ``key`` makes it a server that takes a bearer key and publishes no OAuth;
``legacy`` serves the 2025-03-26 revision (no resource metadata: the server's
own origin is its authorization server); ``dcr=False`` with ``registrations``
preset is a server that admits only clients registered with the vendor (a
secret each); ``documents`` makes it a CIMD server.

Shapes live vendor servers take: ``anonymous`` answers a
client with no token (Shopify, Exa) while its metadata still names where a
person signs in; ``prm_path`` is where the resource metadata is served (None:
nowhere, as Trackdesk) and ``challenge_names`` the one the 401 names (ME-QR
names a path it doesn't serve), ``challenge_quoted=False`` names it unquoted
and ``info_document`` serves a server-info JSON at the path-specific well-known
URL (both Finnhub); ``client_auth_methods`` are the token endpoint
authentications it lists, a registration asking for another refused (Gong
takes only clients with a secret); ``refuse_registration`` refuses every
registration in those words (Kadoa, which wants a metadata document instead);
``sign_in_page`` shows a non-browser a 401 at authorize, where a browser is
sent on (Syncro).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import secrets
import socket
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import unquote, urlencode, urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp.server.fastmcp import Context, FastMCP

ACCOUNT = "ana@example.com"
WELL_KNOWN_PRM = "/.well-known/oauth-protected-resource"


def _unsigned_id_token(email: str) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'none'})}.{part({'email': email, 'sub': 'u-1'})}.sig"


@dataclass
class FakeMcpAuthServer:
    base: str = ""
    access_ttl: int = 3600
    allowed_redirect_hosts: Optional[Set[str]] = None
    key: Optional[str] = None
    legacy: bool = False
    #: Whether it takes self-registered clients (DCR); its metadata says so.
    dcr: bool = True
    #: Client ID Metadata Documents it can "fetch", by URL (as the app would serve them).
    documents: Optional[Dict[str, Dict]] = None
    anonymous: bool = False
    prm_path: Optional[str] = WELL_KNOWN_PRM + "/mcp"
    challenge_names: Optional[str] = None
    challenge_quoted: bool = True
    info_document: bool = False
    client_auth_methods: List[str] = field(default_factory=lambda: ["none", "client_secret_post"])
    refuse_registration: Optional[str] = None
    sign_in_page: bool = False
    registrations: Dict[str, Dict] = field(default_factory=dict)
    codes: Dict[str, Dict] = field(default_factory=dict)
    access_tokens: Dict[str, float] = field(default_factory=dict)
    refresh_tokens: Dict[str, str] = field(default_factory=dict)
    refreshes: int = 0
    calls: List[Dict] = field(default_factory=list)

    @property
    def mcp_url(self) -> str:
        return f"{self.base}/mcp"

    # -------------------------------------------------------------- auth

    def _challenge(self) -> Response:
        header = 'Bearer realm="OAuth", error="invalid_token"'
        named = self.challenge_names or self.prm_path
        if not self.key and not self.legacy and named:
            url = f"{self.base}{named}"
            header += f', resource_metadata="{url}"' if self.challenge_quoted else f", resource_metadata={url}"
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": header})

    def token_ok(self, authorization: str) -> bool:
        token = authorization.removeprefix("Bearer ").strip()
        if self.key:
            return token == self.key
        expires = self.access_tokens.get(token)
        return expires is not None and expires > time.time()

    async def resource_metadata(self, request: Request) -> Response:
        if self.key or self.legacy or request.url.path != self.prm_path:
            if self.info_document and request.url.path == WELL_KNOWN_PRM + "/mcp":
                return JSONResponse({"mcp": "/mcp", "name": "fake-vendor", "resource": WELL_KNOWN_PRM})
            return Response(status_code=404)
        return JSONResponse({"resource": self.mcp_url, "authorization_servers": [self.base],
                             "scopes_supported": ["designs:read", "designs:write"]})

    async def server_metadata(self, request: Request) -> Response:
        if self.key:
            return Response(status_code=404)
        metadata = {
            "issuer": self.base,
            "authorization_endpoint": f"{self.base}/authorize",
            "token_endpoint": f"{self.base}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": self.client_auth_methods,
            "code_challenge_methods_supported": ["S256"],
        }
        if self.dcr:
            metadata["registration_endpoint"] = f"{self.base}/register"
        if self.documents is not None:
            metadata["client_id_metadata_document_supported"] = True
        return JSONResponse(metadata)

    async def register(self, request: Request) -> Response:
        body = await request.json()
        method = body.get("token_endpoint_auth_method", "client_secret_basic")
        if self.refuse_registration or method not in self.client_auth_methods:
            refusal = self.refuse_registration or "token_endpoint_auth_method is unsupported"
            return JSONResponse({"error": "invalid_client_metadata", "error_description": refusal}, status_code=400)
        client_id = f"client-{len(self.registrations) + 1}"
        issued = {**body, "client_id": client_id}
        if method != "none":
            issued["client_secret"] = secrets.token_urlsafe(16)
        self.registrations[client_id] = issued
        return JSONResponse(issued, status_code=201)

    async def authorize(self, request: Request) -> Response:
        q = request.query_params
        if self.sign_in_page and "text/html" not in request.headers.get("accept", ""):
            return PlainTextResponse("You need to sign in or sign up before continuing.", status_code=401)
        client = self.registrations.get(q.get("client_id", "")) or (self.documents or {}).get(q.get("client_id", ""))
        redirect = q.get("redirect_uri", "")
        if client is None:
            return PlainTextResponse("Unknown client.", status_code=400)
        if redirect not in client.get("redirect_uris", []) or (
            self.allowed_redirect_hosts is not None and urlsplit(redirect).hostname not in self.allowed_redirect_hosts
        ):
            return PlainTextResponse("Invalid redirect URI.", status_code=400)
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge") or q.get("resource") != self.mcp_url:
            return PlainTextResponse("Bad request.", status_code=400)
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"client_id": q["client_id"], "redirect_uri": redirect,
                            "challenge": q["code_challenge"], "scope": q.get("scope", "")}
        return RedirectResponse(f"{redirect}?{urlencode({'code': code, 'state': q.get('state', '')})}", status_code=302)

    def _issue(self, scope: str, client_id: str) -> Dict:
        access, refresh = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
        self.access_tokens[access] = time.time() + self.access_ttl
        self.refresh_tokens[refresh] = client_id
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
                "expires_in": self.access_ttl, "scope": scope, "id_token": _unsigned_id_token(ACCOUNT)}

    def _client_of(self, request: Request, form: Dict) -> Optional[str]:
        """The client a token request is from, None when it fails to prove itself: a client issued a
        secret sends it the way it registered (in the body, or as HTTP Basic); a public one sends none."""
        basic = request.headers.get("authorization", "")
        if basic.startswith("Basic "):
            client_id, _, secret = (unquote(part) for part in base64.b64decode(basic[6:]).decode().partition(":"))
            given, method = secret, "client_secret_basic"
        else:
            client_id, given, method = form.get("client_id", ""), form.get("client_secret"), "client_secret_post"
        registered = self.registrations.get(client_id) or {}
        if not registered.get("client_secret"):
            return client_id
        expected = registered.get("token_endpoint_auth_method") or "client_secret_post"
        return client_id if method == expected and given == registered["client_secret"] else None

    async def token(self, request: Request) -> Response:
        form = dict(await request.form())
        client_id = self._client_of(request, form)
        if form.get("grant_type") == "authorization_code":
            grant = self.codes.pop(form.get("code", ""), None)
            if grant is not None and client_id is None:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (grant is None or grant["client_id"] != client_id or grant["redirect_uri"] != form.get("redirect_uri")
                    or grant["challenge"] != challenge or form.get("resource") != self.mcp_url):
                return JSONResponse({"error": "invalid_grant", "error_description": "The code is not valid."}, status_code=400)
            return JSONResponse(self._issue(grant["scope"], grant["client_id"]))
        if form.get("grant_type") == "refresh_token":
            granted_to = self.refresh_tokens.pop(form.get("refresh_token", ""), None)  # single use: rotated
            if granted_to is None or granted_to != client_id:
                return JSONResponse({"error": "invalid_grant", "error_description": "Refresh token revoked."}, status_code=400)
            self.refreshes += 1
            return JSONResponse(self._issue("", granted_to))
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    # --------------------------------------------------------------- MCP

    def build_app(self) -> Starlette:
        mcp = FastMCP("fake-vendor", stateless_http=True, json_response=True)
        server = self

        @mcp.tool(description="Find designs by a word in their title.")
        def search_designs(query: str, ctx: Context) -> str:
            server.calls.append({"tool": "search_designs", "query": query,
                                 "authorization": ctx.request_context.request.headers.get("authorization")})
            return json.dumps({"designs": [{"id": "D1", "title": f"{query} poster"}]})

        @mcp.tool(description="Who is signed in.")
        def whoami(ctx: Context) -> str:
            return ACCOUNT

        mcp_app = mcp.streamable_http_app()

        async def guarded(scope, receive, send):
            if scope["type"] == "http":
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                authorization = headers.get("authorization", "")
                if not (self.anonymous and not authorization) and not self.token_ok(authorization):
                    await self._challenge()(scope, receive, send)
                    return
            await mcp_app(scope, receive, send)

        return Starlette(
            routes=[
                Route(WELL_KNOWN_PRM, self.resource_metadata),
                Route(WELL_KNOWN_PRM + "/mcp", self.resource_metadata),
                Route("/.well-known/oauth-authorization-server", self.server_metadata),
                Route("/register", self.register, methods=["POST"]),
                Route("/authorize", self.authorize),
                Route("/token", self.token, methods=["POST"]),
                Mount("/", app=guarded),
            ],
            lifespan=lambda app: mcp.session_manager.run(),
        )


@contextlib.asynccontextmanager
async def serve(fake: FakeMcpAuthServer):
    """Run ``fake`` on an ephemeral loopback port for the duration of the block."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    fake.base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(fake.build_app(), log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield fake
    finally:
        server.should_exit = True
        await task

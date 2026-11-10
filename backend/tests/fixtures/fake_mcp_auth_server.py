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
from urllib.parse import urlencode, urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp.server.fastmcp import Context, FastMCP

ACCOUNT = "ana@example.com"


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
        if not self.key and not self.legacy:
            header += f', resource_metadata="{self.base}/.well-known/oauth-protected-resource/mcp"'
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": header})

    def token_ok(self, authorization: str) -> bool:
        token = authorization.removeprefix("Bearer ").strip()
        if self.key:
            return token == self.key
        expires = self.access_tokens.get(token)
        return expires is not None and expires > time.time()

    async def resource_metadata(self, request: Request) -> Response:
        if self.key or self.legacy:
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
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
        }
        if self.dcr:
            metadata["registration_endpoint"] = f"{self.base}/register"
        if self.documents is not None:
            metadata["client_id_metadata_document_supported"] = True
        return JSONResponse(metadata)

    async def register(self, request: Request) -> Response:
        body = await request.json()
        client_id = f"client-{len(self.registrations) + 1}"
        self.registrations[client_id] = body
        return JSONResponse({**body, "client_id": client_id}, status_code=201)

    async def authorize(self, request: Request) -> Response:
        q = request.query_params
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

    def _client_authenticated(self, client_id: str, form: Dict) -> bool:
        """A client issued a secret proves it (client_secret_post); a public one has none."""
        secret = (self.registrations.get(client_id) or {}).get("client_secret")
        return not secret or form.get("client_secret") == secret

    async def token(self, request: Request) -> Response:
        form = dict(await request.form())
        if form.get("grant_type") == "authorization_code":
            grant = self.codes.pop(form.get("code", ""), None)
            if grant is not None and not self._client_authenticated(grant["client_id"], form):
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (grant is None or grant["client_id"] != form.get("client_id") or grant["redirect_uri"] != form.get("redirect_uri")
                    or grant["challenge"] != challenge or form.get("resource") != self.mcp_url):
                return JSONResponse({"error": "invalid_grant", "error_description": "The code is not valid."}, status_code=400)
            return JSONResponse(self._issue(grant["scope"], grant["client_id"]))
        if form.get("grant_type") == "refresh_token":
            client_id = self.refresh_tokens.pop(form.get("refresh_token", ""), None)  # single use: rotated
            if client_id is None or client_id != form.get("client_id") or not self._client_authenticated(client_id, form):
                return JSONResponse({"error": "invalid_grant", "error_description": "Refresh token revoked."}, status_code=400)
            self.refreshes += 1
            return JSONResponse(self._issue("", client_id))
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
                if not self.token_ok(headers.get("authorization", "")):
                    await self._challenge()(scope, receive, send)
                    return
            await mcp_app(scope, receive, send)

        return Starlette(
            routes=[
                Route("/.well-known/oauth-protected-resource/mcp", self.resource_metadata),
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

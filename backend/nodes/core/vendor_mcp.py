"""An integration connected through its vendor's own MCP server.

Many services run a remote MCP server that any MCP client can sign a person
into through the MCP auth spec (protected resource metadata, authorization
server metadata, a client registration, then OAuth 2.1 with PKCE). That server
is a second way into the integration: the only one while the vendor hasn't
approved NoClick's OAuth app, and the one way in for an app with no OAuth at
all. An integration declares it in its own file, as one more credential class
in its node's union::

    NotionMcpCredential = mcp_credential("notion", "https://mcp.notion.com/mcp", app="Notion")
    NotionCredential = Union[NotionOAuthCredential, NotionIntegrationTokenCredential, NotionMcpCredential]

A server that admits only clients registered with the vendor names NoClick's app
there (``client_env``, as Canva's Connect API route does).

The credential class IS the declaration: everything that reads a node's ways in
(the generated schema, NodeCredentials, Connections, provide links,
``credential_classes_for_node``) reads the union, so the method appears on every
surface with nothing registered elsewhere. Its schema says ``x-credential-type:
"mcp"`` and names the server (``x-mcp-server``).

What such a credential does: an agent wired to the node gets the server's live
tools (``tools/list``) in place of the node's REST operations
(``nodes.agent.node_op_tools.build_node_mcp_tools``), each call made with the
person's token through ``call_tool``. A workflow step and a trigger still need
the integration's own sign-in: ``refusal_for_step`` says so. Connecting it is
``nodes.oauth.mcp_connect``; its proof is a successful ``tools/list``.

The server a call reaches is always the DECLARED one, never a URL a credential
carries: a blob naming another server is refused, so nobody can point a
person's token somewhere else.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: The credential schema's ``x-credential-type`` for a vendor MCP way in.
MCP_METHOD = "mcp"

#: How long the connect-time proof may take before it says "cannot judge".
EVIDENCE_TIMEOUT_S = 20.0
#: Tool names shown as the proof.
EVIDENCE_SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class McpServer:
    """A vendor's remote MCP server, as an integration declares it."""

    url: str
    #: The app as a person names it ("Canva").
    app: str
    transport: Literal["shttp", "sse"] = "shttp"
    #: A server that lets in only clients registered with the vendor: the env stem of
    #: NoClick's app there (``<STEM>_CLIENT_ID`` / ``<STEM>_CLIENT_SECRET``, set like any
    #: OAuth app's: a secret hosted, Settings -> Self-hosted on an instance). None: the
    #: client registers itself (DCR) or names its metadata document (CIMD).
    client_env: Optional[str] = None

    def registered_client(self) -> Optional[Tuple[str, Optional[str]]]:
        """NoClick's (client id, secret) at the vendor, when the declaration names one and it is set."""
        if not self.client_env:
            return None
        client_id = os.environ.get(f"{self.client_env}_CLIENT_ID")
        return (client_id, os.environ.get(f"{self.client_env}_CLIENT_SECRET")) if client_id else None


_HIDDEN = {"ui:hidden": True}


class McpCredential(BaseModel):
    """What connecting through a vendor's MCP server stores. Never typed in: the
    connect flow writes every field (``mcp_server_url`` is linked, so the
    typed-in connect seam refuses a blob naming it)."""

    linked_fields: ClassVar[Tuple[str, ...]] = ("mcp_server_url",)
    mcp_server: ClassVar[McpServer]

    mcp_server_url: str = Field(..., title="MCP server", json_schema_extra=_HIDDEN)
    access_token: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    refresh_token: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    expires_at: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    token_type: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    scope: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    token_endpoint: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    client_id: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    client_secret: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    resource_url: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    #: A server that asks for a bearer key rather than a sign-in.
    api_key: Optional[str] = Field(None, json_schema_extra=_HIDDEN)
    #: Who signed in, when the sign-in said.
    account: Optional[str] = Field(None, json_schema_extra=_HIDDEN)


# credential_type -> the class mcp_credential made for it.
_DECLARED: Dict[str, Type[McpCredential]] = {}


def mcp_credential(
    provider: str,
    url: str,
    *,
    app: str,
    transport: Literal["shttp", "sse"] = "shttp",
    client_env: Optional[str] = None,
) -> Type[McpCredential]:
    """The credential class for ``provider`` connected through the MCP server at
    ``url``: credential type ``<provider>_mcp``, put in the node's union.
    ``client_env`` names NoClick's app registered with the vendor, for a server
    that takes no self-registered client (``McpServer.client_env``)."""
    if not re.fullmatch(r"[a-z0-9_]+", provider):
        raise ValueError(f"provider must be a lowercase slug, got {provider!r}")
    credential_type = f"{provider}_mcp"
    if credential_type in _DECLARED:
        return _DECLARED[credential_type]
    server = McpServer(url=url, app=app, transport=transport, client_env=client_env)
    name = "".join(part.capitalize() for part in provider.split("_")) + "McpCredential"
    cls = type(
        name,
        (McpCredential,),
        {
            "__module__": __name__,
            "__doc__": f"{app} connected through {app}'s MCP server: agents get its tools.",
            "__annotations__": {"credential_type": Literal[credential_type]},  # type: ignore[valid-type]
            "credential_type": Field(credential_type, json_schema_extra=_HIDDEN),
            "mcp_server": server,
            "model_config": ConfigDict(
                title=f"{app} MCP",
                json_schema_extra={
                    "x-credential-type": MCP_METHOD,
                    "x-mcp-server": url,
                    "x-mcp-transport": transport,
                },
            ),
        },
    )
    _DECLARED[credential_type] = cls
    return cls


def mcp_credential_class(credential_type: Optional[str]) -> Optional[Type[McpCredential]]:
    """The declared class for a vendor-MCP credential type, else None."""
    return _DECLARED.get(credential_type or "")


def server_of(credential_type: Optional[str]) -> Optional[McpServer]:
    cls = mcp_credential_class(credential_type)
    return cls.mcp_server if cls is not None else None


def node_mcp_credential(node_cls: Any) -> Optional[Type[McpCredential]]:
    """The vendor-MCP credential class in a node's union, if it declares one."""
    from nodes.core.credential_connect import credential_classes_for_node

    return next((c for c in credential_classes_for_node(node_cls) if issubclass(c, McpCredential)), None)


def node_type_of(credential_type: Optional[str]) -> Optional[str]:
    """The node whose union holds this vendor-MCP credential type."""
    if mcp_credential_class(credential_type) is None:
        return None
    from nodes.core.credential_connect import resolve_credential_class

    resolved = resolve_credential_class(credential_type)
    return resolved[0] if resolved else None


def is_mcp_credential(credential: Any) -> bool:
    """A credential (a parsed model or a decrypted blob) made through a vendor MCP connect."""
    if isinstance(credential, McpCredential):
        return True
    return isinstance(credential, dict) and mcp_credential_class(credential.get("credential_type")) is not None


def refusal_for_step(credential: Any) -> Optional[str]:
    """Why a workflow step (or a trigger) can't run with this credential, or None.
    The node's operations call the vendor's own API, which an MCP token isn't for."""
    if not isinstance(credential, McpCredential):
        return None
    app = credential.mcp_server.app
    return (
        f"This {app} account is connected through {app}'s MCP server, which gives agents {app}'s tools. "
        f"A workflow step calls {app}'s own API: connect {app} with its own sign-in or key to run it, "
        f"or wire this node into an agent to use its MCP tools."
    )


# --------------------------------------------------------------- the server


def _declared(credential_type: str, credential: Dict[str, Any]) -> McpServer:
    server = server_of(credential_type)
    if server is None:
        raise ValueError(f"{credential_type} is not a vendor MCP credential")
    stored = credential.get("mcp_server_url")
    if stored and stored.rstrip("/") != server.url.rstrip("/"):
        raise ValueError(
            f"This account was connected to {stored}, but {server.app}'s MCP server is now {server.url}. "
            f"Connect {server.app} through MCP again."
        )
    return server


def client_secret_for(server: McpServer, credential: Dict[str, Any]) -> Optional[str]:
    """The secret a token request authenticates with: the one a registration issued
    (kept with the credential), else NoClick's registered app's, read where it's
    configured so a rotated secret never strands a credential."""
    if credential.get("client_secret"):
        return credential["client_secret"]
    registered = server.registered_client()
    return registered[1] if registered and registered[0] == credential.get("client_id") else None


def server_config(server: McpServer, credential: Dict[str, Any]) -> Dict[str, Any]:
    """The ``coder.openai_agent.mcp`` server config for a call with this credential:
    its sign-in's token, else its key, as the bearer."""
    return {
        "url": server.url,
        "transport_type": server.transport,
        "access_token": credential.get("access_token") or credential.get("api_key"),
    }


async def fresh_credential(
    credential: Dict[str, Any],
    *,
    credential_id: Optional[str],
    user_id: Optional[str],
    pool=None,
    caller_path: str = "execute",
) -> Dict[str, Any]:
    """The credential with a live access token: an expiring one is refreshed
    through the one refresh choke point (lock, re-read, rotate, persist).
    Mutates and returns ``credential``."""
    if not (credential.get("refresh_token") and credential.get("token_endpoint") and credential.get("client_id")):
        return credential
    from nodes.core.oauth_refresh import ensure_fresh_oauth_token
    from nodes.oauth import mcp_oauth

    server = server_of(credential.get("credential_type"))
    secret = client_secret_for(server, credential) if server else credential.get("client_secret")

    async def refresh(refresh_token: str):
        tokens = await mcp_oauth.refresh_access_token(
            refresh_token,
            token_endpoint=credential["token_endpoint"],
            client_id=credential["client_id"],
            resource_url=credential.get("resource_url"),
            client_secret=secret,
        )
        return SimpleNamespace(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at.isoformat() if tokens.expires_at else None,
            scope=tokens.scope,
            token_type=tokens.token_type,
        )

    await ensure_fresh_oauth_token(
        pool=pool,
        credential_id=credential_id,
        user_id=user_id,
        credential=credential,
        refresh=refresh,
        provider=credential.get("credential_type") or "mcp",
        caller_path=caller_path,
    )
    return credential


async def list_tools(credential_type: str, credential: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The server's live tools, as the person's token sees them."""
    from coder.openai_agent.mcp import discover_tools

    server = _declared(credential_type, credential)
    return await discover_tools(server_config(server, credential))


async def call_tool(
    credential_type: str, credential: Dict[str, Any], tool: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """One tool call with the person's token: ``{success, result}`` or ``{success: False, error}``."""
    from coder.openai_agent.mcp import call_tool as mcp_call_tool

    server = _declared(credential_type, credential)
    return await mcp_call_tool(server_config(server, credential), tool, arguments or {})


# ----------------------------------------------------------------- evidence


def _status_of(error: BaseException) -> Optional[int]:
    """The HTTP status an MCP client error carries, searching exception groups."""
    stack = [error]
    while stack:
        e = stack.pop()
        response = getattr(e, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
        stack.extend(getattr(e, "exceptions", ()) or ())
        if e.__cause__ is not None:
            stack.append(e.__cause__)
    return None


async def evidence(credential_type: str, credential: Dict[str, Any]):
    """Proof the account works: the server listed its tools for this token.
    A 401/403 is the server refusing the token (``reachable=False``); anything
    else that fails is "cannot judge"."""
    from nodes.core.connection_evidence import EvidenceResult, EvidenceSample

    result = EvidenceResult(noun="tools", account_label=credential.get("account"))
    try:
        tools = await asyncio.wait_for(list_tools(credential_type, credential), timeout=EVIDENCE_TIMEOUT_S)
    except ValueError as e:
        result.reachable = False
        result.error = str(e)
        return result
    except Exception as e:  # noqa: BLE001 — a probe never breaks a connect
        status = _status_of(e)
        if status in (401, 403):
            result.reachable = False
            result.error = f"{server_of(credential_type).app}'s MCP server refused this account (HTTP {status})."
        else:
            logger.info("[vendor_mcp] %s tools/list could not be judged: %r", credential_type, e)
        return result
    result.reachable = True
    result.samples = [EvidenceSample(label=t["name"]) for t in tools[:EVIDENCE_SAMPLE_LIMIT]]
    if len(tools) > EVIDENCE_SAMPLE_LIMIT:
        result.total = len(tools)
    return result


async def stored_evidence(
    *,
    credential_id: Optional[str],
    credential_data: Optional[Dict[str, Any]],
    user_id: str,
    pool=None,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
):
    """``evidence`` for a credential ``collect_evidence`` was handed, freshened first
    (an expired token would read as refused); None when it isn't a vendor-MCP one,
    so the node's own probe runs. Never raises."""
    from nodes.core.connection_evidence import EvidenceResult
    from nodes.core.oauth_refresh import OAuthRefreshError

    loaded = credential_data
    if loaded is None and credential_id:
        from utils.credentials import resolve_credential_with_owner_fallback

        loaded = await resolve_credential_with_owner_fallback(
            credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id,
        )
    if not loaded or not is_mcp_credential(loaded):
        return None
    credential_type = loaded["credential_type"]
    try:
        fresh = await fresh_credential(
            dict(loaded), credential_id=credential_id, user_id=user_id, pool=pool, caller_path="connection_evidence",
        )
    except OAuthRefreshError as e:
        return EvidenceResult(noun="tools", reachable=None if e.transient else False, error=None if e.transient else str(e))
    return await evidence(credential_type, fresh)


def account_from_tokens(token_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Who signed in, when the token response says cheaply: an OpenID ``id_token``'s
    email or name (read for display only, never trusted), else a plain field."""
    if not isinstance(token_data, dict):
        return None
    id_token = token_data.get("id_token")
    if isinstance(id_token, str) and id_token.count(".") == 2:
        try:
            payload = id_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            for key in ("email", "preferred_username", "name"):
                if isinstance(claims.get(key), str) and claims[key].strip():
                    return claims[key].strip()
        except (ValueError, json.JSONDecodeError):
            pass
    for key in ("email", "account", "user", "workspace_name", "team_name"):
        value = token_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

"""
HTTP API routes for external credential provision.
Allows external users (no NoClick account required) to provide credentials
via a token-based link received by email.
"""

import inspect
import logging
from typing import Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from repositories.organization import PRIMARY_ORG_SQL
from utils.async_helpers import spawn
from utils.database_pool import get_native_pool
from utils.encryption import get_encryption
from utils.email import send_credential_fulfilled_email
from utils.shopify_routes import install_router as shopify_install_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credential-request", tags=["credential-request"])

# Public-app OAuth exchanges create a credential, so they share this existing
# authenticated API front door instead of adding another root-level backend
# prefix that self-hosted gateways would have to discover independently.
router.include_router(shopify_install_router)

MAX_PROVISION_ATTEMPTS = 5

# ---------------------------------------------------------------------------
# OAuth provider registry — auto-discovered from node schemas and module conventions
# ---------------------------------------------------------------------------

# Lazy cache: set of OAuth provider keys discovered from x-oauth-provider in node schemas
_oauth_providers_cache: set[str] | None = None
# Lazy cache: provider → bool indicating whether PKCE is required
_pkce_cache: dict[str, bool] = {}


def _discover_oauth_providers() -> set[str]:
    """Discover OAuth provider keys from node schema ``x-oauth-provider`` metadata."""
    global _oauth_providers_cache
    if _oauth_providers_cache is not None:
        return _oauth_providers_cache

    providers: set[str] = set()
    try:
        from nodes.core.registry import NODE_REGISTRY
        for node_class in NODE_REGISTRY.values():
            try:
                schema = node_class.get_config_schema()
                for defn in schema.get('$defs', {}).values():
                    provider = defn.get('x-oauth-provider')
                    if provider:
                        providers.add(provider)
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Failed to discover OAuth providers: {e}")

    _oauth_providers_cache = providers
    return providers


def _is_pkce_provider(provider: str) -> bool:
    """Check if an OAuth provider requires PKCE by inspecting its exchange function signature.

    A provider requires PKCE if ``exchange_code_for_tokens`` has a ``code_verifier``
    parameter with no default value (i.e. it's required, not Optional).
    """
    if provider in _pkce_cache:
        return _pkce_cache[provider]
    try:
        import importlib
        mod = importlib.import_module(f'nodes.oauth.{provider}_oauth')
        sig = inspect.signature(mod.exchange_code_for_tokens)
        param = sig.parameters.get('code_verifier')
        result = param is not None and param.default is inspect.Parameter.empty
    except Exception:
        result = False
    _pkce_cache[provider] = result
    return result


def _get_oauth_provider(credential_type: str) -> Optional[str]:
    """Return the provider key if this credential_type is OAuth, else None."""
    if 'oauth' not in credential_type:
        return None
    for provider in _discover_oauth_providers():
        if credential_type.startswith(provider):
            return provider
    return None


def _is_oauth_type(credential_type: str) -> bool:
    return _get_oauth_provider(credential_type) is not None


async def _exchange_oauth_code(
    provider: str,
    code: str,
    redirect_uri: str,
    scopes: list[str],
    code_verifier: Optional[str] = None,
) -> dict[str, Any]:
    """Exchange an OAuth code for tokens and return credential_data dict."""
    import importlib

    mod = importlib.import_module(f'nodes.oauth.{provider}_oauth')
    exchange_fn = mod.exchange_code_for_tokens

    kwargs: dict[str, Any] = {'code': code, 'redirect_uri': redirect_uri}
    if _is_pkce_provider(provider) and code_verifier:
        kwargs['code_verifier'] = code_verifier

    result = await exchange_fn(**kwargs)

    # All providers return (tokens, user_info) tuple
    tokens, user_info = result

    # Build credential_data from the tokens object's attributes
    credential_data: dict[str, Any] = {}
    for attr in ['access_token', 'refresh_token', 'expires_at', 'scope', 'token_type']:
        val = getattr(tokens, attr, None)
        if val is not None:
            credential_data[attr] = val

    # Include user info email if available
    email = getattr(user_info, 'email', None) or getattr(user_info, 'name', None)
    if email:
        credential_data['email'] = email

    return credential_data


# ---------------------------------------------------------------------------
# Credential field registry — maps credential_type → field definitions
# Built lazily from node JSON schemas so the provision page renders correct fields.
# ---------------------------------------------------------------------------

# Lazy-loaded caches built from node JSON schemas.
# _credential_fields_cache: credential_type → field definitions (non-OAuth only)
# _credential_siblings_cache: credential_type → list of all sibling credential methods
# _credential_methods_cache: credential_type → its own full method dict (single source
#   for the provide page, so even a no-sibling OAuth type carries scopes + connect flags)
_credential_fields_cache: dict[str, list[dict]] | None = None
_credential_siblings_cache: dict[str, list[dict]] | None = None
_credential_methods_cache: dict[str, dict] | None = None


def _resolve_credential_type(title: str, defn: dict) -> str | None:
    """Resolve the credential_type string from a schema definition.

    Reads the ``credential_type.const`` value auto-generated by Pydantic from
    the ``Literal["..."]`` field on each credential model.
    """
    return defn.get('properties', {}).get('credential_type', {}).get('const')


def _method_kind(defn: dict) -> str:
    """UI dispatch kind for a credential method, from its `x-credential-type` discriminator.
    Generic: a new kind flows through as-is with no per-kind code here."""
    xct = defn.get('x-credential-type')
    if xct == 'oauth':
        return 'oauth'
    if xct == 'qr_scan':
        return 'qr_scan'
    return 'api_key'


def _extract_fields_from_schema(defn: dict) -> list[dict]:
    """Extract renderable field definitions from a credential JSON schema definition."""
    properties = defn.get('properties', {})
    required = set(defn.get('required', []))
    fields: list[dict] = []
    for name, prop in properties.items():
        # Skip internal discriminator field
        if name == 'credential_type':
            continue
        # Skip UI-hidden fields — managed by the credential's flow, not typed by the
        # user (e.g. qr_scan's connection_id is auto-filled after the scan).
        if prop.get('ui:hidden'):
            continue
        # Skip optional metadata fields (like email on OAuth tokens)
        prop_any_of = prop.get('anyOf')
        is_optional = prop_any_of and any(
            e.get('type') == 'null' for e in prop_any_of
        )
        if is_optional and name not in required:
            continue
        fields.append({
            'name': name,
            'label': prop.get('title', name),
            'type': 'password' if prop.get('ui:widget') == 'password' else 'text',
            'placeholder': prop.get('placeholder', ''),
            'required': name in required,
        })
    return fields


def _method_dict_from_defn(title: str, defn: dict) -> Optional[dict]:
    """Build one CredentialMethod dict from a credential's JSON schema definition.
    The SINGLE place method metadata is derived, so a credential exposes the same
    fields / OAuth scopes / connect requirements whether it's rendered as a sibling
    tab or as the only method. Returns None if the defn has no credential_type."""
    cred_type = _resolve_credential_type(title, defn)
    if not cred_type:
        return None
    is_oauth = defn.get('x-credential-type') == 'oauth'
    provider = _get_oauth_provider(cred_type) if is_oauth else None
    raw_label = title.replace('Credential', '').strip()
    raw_desc = defn.get('description', '')
    short_desc = raw_desc.split('\n')[0].strip() if raw_desc else ''
    # credential_url: prefer definition-level, fall back to first field-level.
    cred_url = defn.get('x-credential-url')
    if not cred_url:
        for prop in defn.get('properties', {}).values():
            cred_url = prop.get('x-credential-url')
            if cred_url and cred_url.startswith('http'):
                break
            cred_url = None
    return {
        'credential_type': cred_type,
        'label': raw_label,
        'description': short_desc,
        'credential_url': cred_url,
        'is_oauth': is_oauth,
        'oauth_provider': provider,
        'oauth_scopes': defn.get('x-oauth-scopes', []) if is_oauth else [],
        'requires_pkce': _is_pkce_provider(provider) if provider else False,
        'credential_fields': [] if is_oauth else _extract_fields_from_schema(defn),
        'method_kind': _method_kind(defn),
        # OAuth connect requirements — mirror the FE's schema reads so the provide link
        # collects the SAME pre-connect inputs the in-app UI does.
        'supports_custom_client': bool(defn.get('x-oauth-supports-custom-client')) if is_oauth else False,
        'requires_custom_client': bool(defn.get('x-oauth-requires-custom-client')) if is_oauth else False,
        'oauth_redirect_uri': defn.get('x-oauth-redirect-uri') if is_oauth else None,
        'oauth_user_scopes': defn.get('x-oauth-user-scopes', []) if is_oauth else [],
    }


def _build_caches() -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, dict]]:
    """Build field, sibling, and per-type method caches from node JSON schemas.

    Returns (fields_cache, siblings_cache, methods_cache).
    """
    fields_cache: dict[str, list[dict]] = {}
    siblings_cache: dict[str, list[dict]] = {}
    methods_cache: dict[str, dict] = {}
    try:
        from nodes.core.registry import NODE_REGISTRY

        seen_types: set[str] = set()
        for node_class in NODE_REGISTRY.values():
            try:
                schema = node_class.get_config_schema()
                defs = schema.get('$defs', {})

                # --- Build field + per-type method cache entries ---
                for title, defn in defs.items():
                    cred_type = _resolve_credential_type(title, defn)
                    if not cred_type or cred_type in seen_types:
                        continue
                    seen_types.add(cred_type)
                    if defn.get('x-credential-type') != 'oauth':
                        fields_cache[cred_type] = _extract_fields_from_schema(defn)
                    method = _method_dict_from_defn(title, defn)
                    if method:
                        methods_cache[cred_type] = method

                # --- Build sibling groups from the credentials anyOf union ---
                cred_prop = schema.get('properties', {}).get('credentials', {})
                any_of = cred_prop.get('anyOf', [])
                refs = [e for e in any_of if '$ref' in e]
                if len(refs) <= 1:
                    continue  # no siblings to map

                sibling_methods: list[dict] = []
                for ref in refs:
                    title = ref['$ref'].split('/')[-1]
                    defn = defs.get(title, {})
                    # x-credential-hidden methods (e.g. OAuth pending provider app
                    # approval) are hidden in-app — don't offer them here either.
                    if defn.get('x-credential-hidden'):
                        continue
                    method = _method_dict_from_defn(title, defn)
                    if method:
                        sibling_methods.append(method)

                # Map every credential_type in this group to the full list
                for method in sibling_methods:
                    siblings_cache[method['credential_type']] = sibling_methods
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Failed to build credential caches: {e}")
    return fields_cache, siblings_cache, methods_cache


def _ensure_caches() -> None:
    global _credential_fields_cache, _credential_siblings_cache, _credential_methods_cache
    if _credential_fields_cache is None:
        _credential_fields_cache, _credential_siblings_cache, _credential_methods_cache = _build_caches()


def _get_credential_fields(credential_type: str) -> list[dict]:
    """Get field definitions for a credential type. Returns empty list for OAuth types."""
    _ensure_caches()
    return (_credential_fields_cache or {}).get(credential_type, [])


def _get_sibling_methods(credential_type: str) -> list[dict]:
    """Get all auth methods for the same service (sibling credential types)."""
    _ensure_caches()
    return (_credential_siblings_cache or {}).get(credential_type, [])


def _get_credential_method(credential_type: str) -> Optional[dict]:
    """Get the credential's own method dict (single-method / no-sibling case)."""
    _ensure_caches()
    return (_credential_methods_cache or {}).get(credential_type)


# ---------------------------------------------------------------------------
# AI-agent LLM credentials (agent_<provider>) — not tied to a node schema, so
# their fields are resolved from the provider's required env vars instead.
# ---------------------------------------------------------------------------

_ENV_LABEL_ACRONYMS = {"API", "ID", "JWT", "AWS", "HF", "NLP", "AI", "URL", "PSE", "NIM"}


def _format_env_var_label(env_var: str) -> str:
    """Human label for a credential env var, e.g. ANTHROPIC_API_KEY → 'Anthropic API Key'."""
    return " ".join(
        w if w in _ENV_LABEL_ACRONYMS else w.capitalize()
        for w in env_var.split("_")
    )


def _get_agent_provider(credential_type: str) -> Optional[str]:
    """Provider key for an AI-agent LLM API-key credential (``agent_<provider>``),
    or None. OAuth agent aliases (``agent_*_oauth``) are excluded — a device-code /
    PKCE flow can't be completed through the simple provide form."""
    if not credential_type.startswith("agent_") or "oauth" in credential_type:
        return None
    return credential_type[len("agent_"):]


def _agent_credential_fields(credential_type: str) -> Optional[list[dict]]:
    """Renderable field(s) for an ``agent_<provider>`` credential, derived from the
    provider's required env vars. None if not an agent API-key type OR the provider
    has no operator-key form. Field names ARE the env vars so the provided
    values slot straight into the ``{credentials: {...}}`` blob the agent runtime reads."""
    provider = _get_agent_provider(credential_type)
    if not provider or provider in AGENT_OAUTH_ONLY_PROVIDERS:
        return None
    from nodes.agent.config.providers import get_provider_credentials
    env_vars, _ = get_provider_credentials(f"{provider}/")
    return [
        {
            "name": env_var,
            "label": _format_env_var_label(env_var),
            "type": "password" if any(k in env_var for k in ("KEY", "TOKEN", "SECRET", "JWT")) else "text",
            "placeholder": "",
            "required": True,
        }
        for env_var in env_vars
    ]


def _agent_oauth_method(oauth_type: str) -> dict:
    """A CredentialMethod dict for an agent OAuth sign-in (device-code / PKCE).
    ``agent_oauth_kind`` tells the FE to render the sign-in flow instead of a field."""
    flow = AGENT_OAUTH_FLOWS[oauth_type]
    return {
        "credential_type": oauth_type,
        "label": flow.label,
        "description": "",
        "credential_url": None,
        "is_oauth": True,
        "oauth_provider": None,
        "oauth_scopes": [],
        "requires_pkce": flow.kind == "pkce",
        "credential_fields": [],
        "agent_oauth_kind": flow.kind,
        "method_kind": "agent_oauth",
    }


def _agent_methods(credential_type: str) -> Optional[list[dict]]:
    """Auth methods offered for an agent credential request: the provider's API-key
    field(s) and/or an OAuth sign-in. None when ``credential_type`` isn't an agent type."""
    provider = _get_agent_provider(credential_type)
    methods: list[dict] = []
    if provider:
        api_fields = _agent_credential_fields(credential_type)
        if api_fields:
            methods.append({
                "credential_type": credential_type,
                "label": f"{provider.replace('_', ' ').title()} API Key",
                "description": "",
                "credential_url": None,
                "is_oauth": False,
                "oauth_provider": None,
                "oauth_scopes": [],
                "requires_pkce": False,
                "credential_fields": api_fields,
                "agent_oauth_kind": None,
                "method_kind": "api_key",
            })
        oauth_type = AGENT_PROVIDER_OAUTH_TYPE.get(provider)
        if oauth_type:
            methods.append(_agent_oauth_method(oauth_type))
    elif get_agent_oauth_flow(credential_type):
        # Request was made directly for an OAuth agent type.
        methods.append(_agent_oauth_method(credential_type))
    return methods or None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CredentialField(BaseModel):
    name: str
    label: str
    type: str  # "text" or "password"
    placeholder: str = ''
    required: bool = True


class CredentialMethod(BaseModel):
    """One auth method among potentially several for the same service."""
    credential_type: str
    label: str
    description: str = ''
    credential_url: Optional[str] = None
    is_oauth: bool
    oauth_provider: Optional[str] = None
    oauth_scopes: list[str] = []
    oauth_user_scopes: list[str] = []
    requires_pkce: bool = False
    credential_fields: list[CredentialField] = []
    # Set for agent CLI sign-in methods: 'device_code' | 'pkce'. Tells the FE to
    # run the device-code / PKCE flow (via the agent-oauth endpoints) instead of a
    # redirect OAuth or an API-key field.
    agent_oauth_kind: Optional[str] = None
    # UI dispatch kind: 'api_key' | 'oauth' | 'agent_oauth' | 'qr_scan'. The FE registry
    # picks the component from this; generic pass-through so new kinds need no FE/BE branch.
    method_kind: str = 'api_key'
    # OAuth pre-connect requirements — the provide page collects the SAME inputs as the
    # in-app UI (BYOO custom client, Slack-style user scopes). Provider-intrinsic inputs
    # (Shopify store / Zendesk subdomain / Atlassian site) are FE-derived from the provider.
    supports_custom_client: bool = False
    requires_custom_client: bool = False
    oauth_redirect_uri: Optional[str] = None


class CredentialRequestDetails(BaseModel):
    credential_type: str
    requester_name: str
    requester_email: str
    message: Optional[str] = None
    is_oauth: bool
    oauth_provider: Optional[str] = None
    oauth_scopes: list[str] = []
    oauth_user_scopes: list[str] = []
    requires_pkce: bool = False
    supports_custom_client: bool = False
    requires_custom_client: bool = False
    credential_fields: list[CredentialField] = []
    # All available auth methods for this service (populated when > 1 method exists)
    available_methods: list[CredentialMethod] = []
    status: str
    expires_at: str


class ProvideCredentialBody(BaseModel):
    # Optional override: use a sibling credential type instead of the originally requested one
    credential_type: Optional[str] = None
    # For API key credentials
    credential_data: Optional[dict[str, str]] = None
    # For OAuth credentials
    oauth_code: Optional[str] = None
    redirect_uri: Optional[str] = None
    scopes: Optional[list[str]] = None
    code_verifier: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# Optional harness sign-in support is resolved once here because
# _agent_methods() runs on EVERY
# credential-provide page — a function-level import made the whole public page
# 500 with ModuleNotFoundError, not just the agent-OAuth part of it.
#
# Absent means "this build offers no agent OAuth sign-ins", which is the honest
# answer: the API-key path is unaffected and is what a self-hosted install uses.
try:
    from nodes.agent.harness_oauth_flows import (  # noqa: F401
        AGENT_OAUTH_FLOWS,
        AGENT_OAUTH_ONLY_PROVIDERS,
        AGENT_PROVIDER_OAUTH_TYPE,
        OAuthFlowError,
        get_agent_oauth_flow,
    )

    AGENT_OAUTH_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in the open build
    AGENT_OAUTH_FLOWS: dict = {}
    AGENT_OAUTH_ONLY_PROVIDERS: frozenset = frozenset()
    AGENT_PROVIDER_OAUTH_TYPE: dict = {}

    class OAuthFlowError(Exception):
        """Placeholder so except-clauses still bind where flows don't ship."""

    def get_agent_oauth_flow(*_args, **_kwargs):
        return None

    AGENT_OAUTH_AVAILABLE = False


@router.get("/{token}")
async def get_credential_request(token: str) -> CredentialRequestDetails:
    """Get credential request details by token. Public — no auth required."""
    pool = get_native_pool()
    row = await pool.fetchrow(
        """
        SELECT cr.id, cr.credential_type, cr.message, cr.status, cr.expires_at,
               cr.provision_attempts,
               u.raw_user_meta_data->>'name' as requester_name,
               u.email as requester_email
        FROM credential_requests cr
        JOIN auth.users u ON u.id = cr.requester_id
        WHERE cr.token = $1
        """,
        token,
    )

    if not row:
        raise HTTPException(status_code=404, detail="Credential request not found")

    if row['status'] != 'pending':
        raise HTTPException(status_code=410, detail=f"This credential request has already been {row['status']}")

    if row['expires_at'] and row['expires_at'].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This credential request has expired")

    if row['provision_attempts'] >= MAX_PROVISION_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many provision attempts for this request")

    cred_type = row['credential_type']
    provider = _get_oauth_provider(cred_type)
    fields = _get_credential_fields(cred_type) if not provider else []
    # agent_<provider> LLM credentials aren't node-schema-backed; resolve their
    # API-key field(s) from the provider's required env vars.
    if not provider and not fields:
        fields = _agent_credential_fields(cred_type) or []

    # Build available_methods: node-schema siblings, agent API-key + OAuth methods, or —
    # for a single node-schema credential — its own method (so its OAuth scopes + connect
    # requirements still reach the provide page instead of an empty methods list).
    siblings = _get_sibling_methods(cred_type)
    agent_methods = _agent_methods(cred_type)
    if siblings:
        method_dicts = siblings
    elif agent_methods:
        method_dicts = agent_methods
    else:
        single = _get_credential_method(cred_type)
        method_dicts = [single] if single else []
    available = [
        CredentialMethod(
            credential_type=m['credential_type'],
            label=m['label'],
            description=m.get('description', ''),
            credential_url=m.get('credential_url'),
            is_oauth=m['is_oauth'],
            oauth_provider=m.get('oauth_provider'),
            oauth_scopes=m.get('oauth_scopes', []),
            oauth_user_scopes=m.get('oauth_user_scopes', []),
            requires_pkce=m.get('requires_pkce', False),
            credential_fields=[CredentialField(**f) for f in m.get('credential_fields', [])],
            agent_oauth_kind=m.get('agent_oauth_kind'),
            method_kind=m.get('method_kind', 'api_key'),
            supports_custom_client=m.get('supports_custom_client', False),
            requires_custom_client=m.get('requires_custom_client', False),
            oauth_redirect_uri=m.get('oauth_redirect_uri'),
        )
        for m in method_dicts
    ]

    # Top-level OAuth metadata for the requested type (drives the FE fallback method when
    # available_methods is empty). Read from the requested type's own method dict.
    own = next((m for m in method_dicts if m['credential_type'] == cred_type), None)

    return CredentialRequestDetails(
        credential_type=cred_type,
        requester_name=row['requester_name'] or row['requester_email'].split('@')[0],
        requester_email=row['requester_email'],
        message=row['message'],
        is_oauth=provider is not None,
        oauth_provider=provider,
        oauth_scopes=own.get('oauth_scopes', []) if own else [],
        requires_pkce=_is_pkce_provider(provider) if provider else False,
        supports_custom_client=own.get('supports_custom_client', False) if own else False,
        requires_custom_client=own.get('requires_custom_client', False) if own else False,
        oauth_user_scopes=own.get('oauth_user_scopes', []) if own else [],
        credential_fields=[CredentialField(**f) for f in fields],
        available_methods=available,
        status=row['status'],
        expires_at=row['expires_at'].isoformat() if row['expires_at'] else '',
    )


async def _store_and_fulfill(
    pool, row, credential_type: str,
    credential_data: dict, credential_name: str, metadata: dict,
) -> dict[str, str]:
    """Encrypt + store an already-built credential, atomically fulfil the request,
    share to the requester when the provider has an account, and notify. Shared by
    the API-key / redirect-OAuth provide path and the agent-OAuth completion."""
    encrypted = get_encryption().encrypt_credential(credential_data)

    # If the provider already has a NoClick account they own the credential
    # (can revoke) and the requester gets edit access via a share.
    provider_user = await pool.fetchrow(
        "SELECT id FROM auth.users WHERE LOWER(email) = LOWER($1)",
        row['target_email'],
    )
    credential_owner_id = str(provider_user['id']) if provider_user else str(row['requester_id'])

    org_context_row = await pool.fetchrow(PRIMARY_ORG_SQL, credential_owner_id)
    cred_org_id = str(org_context_row['organization_id']) if org_context_row else None

    cred_row = await pool.fetchrow(
        """
        INSERT INTO credentials (owner_id, organization_id, name, credential_type, credential, metadata, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        RETURNING id
        """,
        credential_owner_id, cred_org_id, credential_name, credential_type, encrypted, metadata,
    )
    if not cred_row:
        raise HTTPException(status_code=500, detail="Failed to store credential")
    credential_id = str(cred_row['id'])

    # Atomically claim fulfillment. The status guard (not the initial read) owns the
    # double-submit race: a concurrent provide that lost gets 0 rows, and we remove
    # the credential it just created.
    claimed = await pool.fetchval(
        """
        UPDATE credential_requests
        SET status = 'fulfilled', credential_id = $1, fulfilled_at = NOW()
        WHERE id = $2 AND status = 'pending'
        RETURNING id
        """,
        credential_id, str(row['id']),
    )
    if not claimed:
        await pool.execute("DELETE FROM credentials WHERE id = $1", credential_id)
        raise HTTPException(status_code=410, detail="This credential request has already been fulfilled")

    if provider_user:
        await pool.execute(
            """
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('credential', $1, 'user', $2, 'edit', $3)
            ON CONFLICT DO NOTHING
            """,
            credential_id, str(row['requester_id']), credential_owner_id,
        )

    try:
        await send_credential_fulfilled_email(
            to_email=row['requester_email'],
            provider_email=row['target_email'],
            credential_type=credential_type,
        )
    except Exception as e:
        logger.warning(f"Failed to send fulfillment notification: {e}")

    logger.info(
        f"Credential request {row['id']} fulfilled: type={credential_type}, "
        f"requester={row['requester_id']}, provider={row['target_email']}"
    )
    return {"status": "success", "message": "Credential provided successfully", "credential_id": credential_id}


@router.post("/{token}/provide")
async def provide_credential(token: str, body: ProvideCredentialBody) -> dict[str, str]:
    """Submit a credential for a request. Public — no auth required."""
    pool = get_native_pool()

    # Fetch and validate the request. No row lock here — the fulfilled-status
    # CAS below owns the double-submit race; a lock on this single-statement
    # read would release immediately anyway.
    row = await pool.fetchrow(
        """
        SELECT cr.id, cr.requester_id, cr.credential_type, cr.status, cr.expires_at,
               cr.provision_attempts, cr.target_email,
               u.email as requester_email,
               u.raw_user_meta_data->>'name' as requester_name
        FROM credential_requests cr
        JOIN auth.users u ON u.id = cr.requester_id
        WHERE cr.token = $1
        """,
        token,
    )

    if not row:
        raise HTTPException(status_code=404, detail="Credential request not found")

    if row['status'] != 'pending':
        raise HTTPException(status_code=410, detail=f"This credential request has already been {row['status']}")

    if row['expires_at'] and row['expires_at'].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This credential request has expired")

    if row['provision_attempts'] >= MAX_PROVISION_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many provision attempts for this request")

    # Deliberate fire-and-forget: attempt counter must not block the provision flow.
    spawn(pool.execute(
        "UPDATE credential_requests SET provision_attempts = provision_attempts + 1 WHERE id = $1",
        str(row['id']),
    ), name="credential-request-attempt-counter")

    # Allow the provider to choose a sibling credential type (e.g. API key instead of OAuth)
    credential_type = row['credential_type']
    if body.credential_type and body.credential_type != credential_type:
        siblings = _get_sibling_methods(credential_type)
        sibling_types = {m['credential_type'] for m in siblings}
        if body.credential_type not in sibling_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credential type override: {body.credential_type}",
            )
        credential_type = body.credential_type

    provider = _get_oauth_provider(credential_type)

    try:
        if provider:
            # OAuth credential
            if not body.oauth_code or not body.redirect_uri:
                raise HTTPException(status_code=400, detail="OAuth credentials require oauth_code and redirect_uri")

            credential_data = await _exchange_oauth_code(
                provider=provider,
                code=body.oauth_code,
                redirect_uri=body.redirect_uri,
                scopes=body.scopes or [],
                code_verifier=body.code_verifier,
            )
            credential_name = credential_data.get('email', f'{provider.title()} Account')
            metadata = {
                'provider': provider,
                'email': credential_data.get('email'),
                'scopes': body.scopes or [],
                'provided_by': row['target_email'],
            }
        else:
            # API key / manual credential
            if not body.credential_data:
                raise HTTPException(status_code=400, detail="API key credentials require credential_data")

            # "(provided by …)" only when we know who — copy-link requests carry no email.
            provided_by = row['target_email']
            by_suffix = f" (provided by {provided_by})" if provided_by else ""
            agent_provider = _get_agent_provider(credential_type)
            if agent_provider:
                # Agent LLM credentials nest their env vars under `credentials` and
                # carry `provider` so the runtime + agent form resolve them correctly.
                credential_data = {'credentials': body.credential_data}
                credential_name = f"{agent_provider.title()} API Key{by_suffix}"
                metadata = {'provider': agent_provider, 'provided_by': provided_by}
            else:
                credential_data = body.credential_data
                credential_name = f"{credential_type}{by_suffix}"
                metadata = {'provided_by': provided_by}

        return await _store_and_fulfill(pool, row, credential_type, credential_data, credential_name, metadata)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Token exchange failed for request {row['id']}: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to exchange OAuth code: {e}")
    except Exception as e:
        logger.error(f"Failed to provision credential for request {row['id']}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to store credential")


# ---------------------------------------------------------------------------
# Agent CLI OAuth sign-in (device-code / PKCE) over the public request link
# ---------------------------------------------------------------------------

class AgentOAuthStartBody(BaseModel):
    credential_type: str


class AgentOAuthCompleteBody(BaseModel):
    credential_type: str
    poll: dict[str, Any] = {}


async def _load_active_request(token: str, pool):
    """Load a credential_requests row and assert it's still fulfillable. Selects the
    columns ``_store_and_fulfill`` needs. Raises 404/410 like the provide endpoint."""
    row = await pool.fetchrow(
        """
        SELECT cr.id, cr.requester_id, cr.credential_type, cr.status, cr.expires_at,
               cr.target_email, u.email as requester_email
        FROM credential_requests cr
        JOIN auth.users u ON u.id = cr.requester_id
        WHERE cr.token = $1
        """,
        token,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Credential request not found")
    if row['status'] != 'pending':
        raise HTTPException(status_code=410, detail=f"This credential request has already been {row['status']}")
    if row['expires_at'] and row['expires_at'].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This credential request has expired")
    return row


def _resolve_agent_oauth_flow(row_credential_type: str, requested_type: str):
    """Return the flow for ``requested_type`` iff it's a legitimate OAuth method for the
    request — the request's own type, or the OAuth sibling of its agent provider. Blocks
    a request for provider X from minting an unrelated credential."""
    flow = get_agent_oauth_flow(requested_type)
    if not flow:
        raise HTTPException(status_code=400, detail=f"Not an agent OAuth credential type: {requested_type}")
    if requested_type == row_credential_type:
        return flow
    provider = _get_agent_provider(row_credential_type)
    if provider and AGENT_PROVIDER_OAUTH_TYPE.get(provider) == requested_type:
        return flow
    raise HTTPException(status_code=400, detail="This OAuth method is not valid for this request")


@router.post("/{token}/agent-oauth/start")
async def agent_oauth_start(token: str, body: AgentOAuthStartBody) -> dict[str, Any]:
    """Begin an agent CLI OAuth sign-in (device-code / PKCE). Public — no auth.
    Returns display data (verification URL + code, or an authorize URL) plus opaque
    ``poll`` state the client echoes back to ``/complete``."""
    if not AGENT_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=404,
            detail="Agent subscription sign-in is not available on this instance. "
                   "Provide an API key for this provider instead.",
        )
    pool = get_native_pool()
    row = await _load_active_request(token, pool)
    flow = _resolve_agent_oauth_flow(row['credential_type'], body.credential_type)
    try:
        result = await flow.start()
    except OAuthFlowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[agent_oauth_start] {body.credential_type} failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to start sign-in with the provider")
    return {"kind": flow.kind, "label": flow.label, "display": result["display"], "poll": result["poll"]}


@router.post("/{token}/agent-oauth/complete")
async def agent_oauth_complete(token: str, body: AgentOAuthCompleteBody) -> dict[str, Any]:
    """Poll (device-code) or exchange (PKCE) an agent OAuth sign-in. On completion,
    stores the minted credential for the requester and fulfils the request. Public."""
    if not AGENT_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=404,
            detail="Agent subscription sign-in is not available on this instance. "
                   "Provide an API key for this provider instead.",
        )
    pool = get_native_pool()
    row = await _load_active_request(token, pool)
    flow = _resolve_agent_oauth_flow(row['credential_type'], body.credential_type)
    try:
        result = await flow.complete(body.poll or {})
    except OAuthFlowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[agent_oauth_complete] {body.credential_type} failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Sign-in with the provider failed")

    status = result.get("status")
    if status in ("pending", "slow_down"):
        return {"status": status}
    if status != "completed":
        raise HTTPException(status_code=502, detail="Unexpected sign-in state")

    metadata = {**flow.metadata, "provided_by": row['target_email']}
    return await _store_and_fulfill(
        pool, row, flow.credential_type, result["credential_data"], flow.credential_name, metadata,
    )


# ---------------------------------------------------------------------------
# WhatsApp QR scan sign-in over the public request link
#
# Unlike API-key / OAuth methods, a QR credential is minted server-side by the
# shared utils.whatsapp_qr core (which owns reservation and unique-index binding
# safety). The connection binds to the REQUESTER; the external scanner never
# needs an account. These endpoints
# resolve the requester from the token and delegate to that one audited core.
# ---------------------------------------------------------------------------

class QRStatusBody(BaseModel):
    connection_id: str


# /qr/start mints/reserves a connection on the SHARED paid WAHooks account and is public
# (the external scanner has no account), so unlike the API-key /provide path it can't lean
# on provision_attempts. Bound each token's start rate so a leaked link can't hold shared
# connections hostage or exhaust the pool. Generous vs. legitimate retries (a QR expires
# after ~2 min of polling); fail-open on Redis errors. /qr/status polling is intentionally
# uncapped (it's idempotent and binding-guarded).
QR_START_MAX = 20
QR_START_WINDOW_S = 3600


async def _qr_start_over_limit(token: str) -> bool:
    """True = this token has exceeded its /qr/start budget (caller returns 429)."""
    from utils.redis_client import get_shared_redis
    client = get_shared_redis()
    if client is None:
        return False
    key = f"credreq:qrstart:{token}"
    try:
        # SET NX EX then INCR: the window key is created WITH its TTL atomically, so a
        # crash can't orphan a TTL-less counter.
        await client.set(key, 0, ex=QR_START_WINDOW_S, nx=True)
        count = await client.incr(key)
        return count > QR_START_MAX
    except Exception as e:
        logger.warning("[credreq] QR start rate check failed: %s", e)
        return False


def _assert_qr_request(credential_type: str) -> None:
    if credential_type != "whatsapp_qr":
        raise HTTPException(status_code=400, detail="This request is not a WhatsApp QR credential")


async def _requester_effective_tier(pool, requester_id) -> str:
    """Community credential requests are uncapped by billing tier."""
    del pool, requester_id
    return "free"


async def _rollback_qr_credential(pool, credential_id: str) -> None:
    """Undo a QR credential minted for a request that turned out already fulfilled."""
    await pool.execute("DELETE FROM credentials WHERE id = $1", credential_id)


async def _claim_qr_fulfillment(pool, row, credential_id: str) -> bool:
    """CAS-claim the request as fulfilled with an already-created QR credential
    (owned by the requester) and notify. Returns False if the request was already
    fulfilled — the caller rolls back the orphaned credential."""
    claimed = await pool.fetchval(
        """
        UPDATE credential_requests
        SET status = 'fulfilled', credential_id = $1, fulfilled_at = NOW()
        WHERE id = $2 AND status = 'pending'
        RETURNING id
        """,
        credential_id, str(row["id"]),
    )
    if not claimed:
        return False
    if row["target_email"]:
        try:
            await send_credential_fulfilled_email(
                to_email=row["requester_email"],
                provider_email=row["target_email"],
                credential_type="whatsapp_qr",
            )
        except Exception as e:
            logger.warning(f"Failed to send fulfillment notification: {e}")
    logger.info(f"Credential request {row['id']} fulfilled via WhatsApp QR: credential={credential_id}")
    return True


@router.post("/{token}/qr/start")
async def qr_start(token: str) -> dict[str, Any]:
    """Create a scannable WhatsApp connection for a QR credential request, bound
    to the requester. Public — no auth. Returns ``{connection_id, qr_code}``."""
    pool = get_native_pool()
    row = await _load_active_request(token, pool)
    _assert_qr_request(row["credential_type"])
    if await _qr_start_over_limit(token):
        raise HTTPException(status_code=429, detail="Too many QR attempts for this request. Please try again later.")
    from utils.whatsapp_qr import start_qr_connection
    result = await start_qr_connection(pool, owner_id=str(row["requester_id"]))
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("message") or "Failed to start WhatsApp connection")
    return result


@router.post("/{token}/qr/status")
async def qr_status(token: str, body: QRStatusBody) -> dict[str, Any]:
    """Poll a WhatsApp QR connection. On connect, mints the credential for the
    requester (via the shared core) and fulfils the request. Public — no auth."""
    pool = get_native_pool()
    row = await _load_active_request(token, pool)
    _assert_qr_request(row["credential_type"])
    from utils.whatsapp_qr import finalize_qr_connection
    tier = await _requester_effective_tier(pool, row["requester_id"])
    result = await finalize_qr_connection(
        pool, owner_id=str(row["requester_id"]), connection_id=body.connection_id,
        user_tier=tier, encryption=get_encryption(),
    )
    if result.get("status") == "connected" and result.get("credential_id"):
        claimed = await _claim_qr_fulfillment(pool, row, result["credential_id"])
        if not claimed and result.get("created"):
            await _rollback_qr_credential(pool, result["credential_id"])
            raise HTTPException(status_code=410, detail="This credential request has already been fulfilled")
    return result

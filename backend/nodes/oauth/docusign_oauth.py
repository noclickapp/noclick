"""Docusign production OAuth declaration and default eSignature account discovery.

Endpoints and account fields: https://developers.docusign.com/platform/auth/confidential-authcode-get-token
https://developers.docusign.com/platform/auth/reference/user-info
"""
from urllib.parse import urlparse

import httpx

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.docusign import DOCUSIGN_SCOPES


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="docusign",
    authorize_url="https://account.docusign.com/oauth/auth",
    token_url="https://account.docusign.com/oauth/token",
    identity_url="https://account.docusign.com/oauth/userinfo",
    name_field="name",
    scope_registry=DOCUSIGN_SCOPES,
    client_id_env="DOCUSIGN_CLIENT_ID",
    client_secret_env="DOCUSIGN_CLIENT_SECRET",
    redirect_uri_env="DOCUSIGN_REDIRECT_URI",
    credential_type="docusign_oauth",
    pkce=True,
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh


def validate_base_uri(value: str) -> str:
    """Account discovery must never turn an OAuth response into an SSRF target."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or not (host == "docusign.net" or host.endswith(".docusign.net"))):
        raise ValueError("Docusign returned an invalid account API base URI")
    return f"https://{host}"



async def resolve_account(credential: dict) -> dict:
    """Resolve a token-only generic credential once, retaining its account fields."""
    if credential.get("account_id") and credential.get("base_uri"):
        credential["base_uri"] = validate_base_uri(credential["base_uri"])
        return credential
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            OAUTH_PROVIDER.identity_url,
            headers={"Authorization": f"Bearer {credential['access_token']}"},
        )
    if response.is_error:
        raise ValueError(f"Docusign account discovery failed ({response.status_code})")
    profile = response.json()
    accounts = profile.get("accounts") or []
    account = next((item for item in accounts
                    if item.get("account_id") == credential["account_id"]), None) if credential.get("account_id") else next(
        (item for item in accounts if item.get("is_default") is True), None
    )
    if not account or not account.get("account_id"):
        raise ValueError("Docusign user has no matching default eSignature account")
    credential.update(
        account_id=account["account_id"],
        base_uri=validate_base_uri(account.get("base_uri") or ""),
        account_name=account.get("account_name"),
        email=profile.get("email"),
    )
    return credential

"""SAP Concur's supplied-client refresh grant and regional token pair.

Only refresh is implemented. No login, client-credentials mint or principal
inference is performed; the node validates and saves the returned pair.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from utils.ssrf import SSRFError, guarded_async_client


def make_refresh(data):
    async def refresh(refresh_token):
        from nodes.sap_concur_node import credential, origin, secret
        current = credential(data)
        if refresh_token != current.get("refresh_token") or not current.get("client_id") or not current.get("client_secret"):
            raise RuntimeError("SAP Concur current refresh client is unavailable")
        url = origin(current["geolocation"]) + "/oauth2/v0/token"
        safe_request = httpx.Request("POST", url)
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
                response = await client.post(url, data={"grant_type": "refresh_token", "refresh_token": refresh_token,
                    "client_id": current["client_id"], "client_secret": current["client_secret"]}, headers={"Accept": "application/json"})
        except SSRFError:
            raise RuntimeError("SAP Concur regional token endpoint was refused") from None
        except httpx.RequestError as exc:
            raise type(exc)("SAP Concur token endpoint could not be reached", request=safe_request) from None
        if response.status_code != 200:
            code = None
            if len(response.content) <= 65536:
                try:
                    body = response.json()
                    code = body.get("error") if isinstance(body, dict) else None
                except ValueError:
                    pass
            if response.status_code in {400, 401} and isinstance(code, str) and code in {"invalid_grant", "invalid_refresh_token", "token_revoked"}:
                raise ValueError("SAP Concur refresh refused: " + code)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError("SAP Concur token response was not accepted", request=safe_request,
                    response=httpx.Response(response.status_code, request=safe_request))
            raise RuntimeError("SAP Concur token response or client configuration was not accepted")
        try:
            if len(response.content) > 65536:
                raise ValueError()
            body = response.json()
            if not isinstance(body, dict) or body.get("token_type") != "Bearer" or not isinstance(body.get("scope"), str):
                raise ValueError()
            lifetime = body.get("expires_in")
            if isinstance(lifetime, str) and lifetime.isascii() and lifetime.isdecimal():
                lifetime = int(lifetime)
            if type(lifetime) is not int or not 1 <= lifetime <= 86400:
                raise ValueError()
            access, successor = secret(body.get("access_token")), secret(body.get("refresh_token"))
            location = origin(body.get("geolocation"))
            # Validate the whole successor before returning it to the common CAS.
            expires = (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()
            checked = credential({**current, "access_token": access, "refresh_token": successor,
                "expires_at": expires, "geolocation": location, "scope": body["scope"], "token_type": "Bearer"})
            return SimpleNamespace(**{k: checked[k] for k in ("access_token", "refresh_token", "expires_at", "geolocation", "scope", "token_type")})
        except (ValueError, TypeError, KeyError, OverflowError):
            # A malformed successful mint may have consumed a refresh token.
            # It does not establish that the saved grant is invalid or valid.
            raise RuntimeError("SAP Concur token response was unreadable; grant validity is unverified") from None
    return refresh

"""Live Page/app authorization for Facebook's managed callback path."""

from dataclasses import dataclass, field
import asyncio
from functools import partial
import hashlib
import hmac
import os
from time import time
from urllib.parse import urlsplit

import httpx

from utils.facebook_events import FB_WEBHOOK_FIELDS, facebook_page_id
from utils.meta_subscriptions import (
    MetaAuthorizationDenied, graph_request, read_edge, read_subscribed_fields, registration_lease,
)

GRAPH_API_VERSION = "v25.0"
FB_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


@dataclass(frozen=True)
class FacebookWebhookApp:
    app_id: str
    app_secret: str = field(repr=False)
    callback_url: str


def require_facebook_webhook_configuration():
    app_id = facebook_page_id(os.environ.get("FACEBOOK_WEBHOOK_APP_ID"))
    secret = os.environ.get("FACEBOOK_WEBHOOK_APP_SECRET") or ""
    verify = os.environ.get("FACEBOOK_WEBHOOK_VERIFY_TOKEN") or ""
    base = urlsplit(os.environ.get("APP_WEBHOOK_BASE_URL") or "")
    if not app_id or not secret.strip() or not verify.strip():
        raise ValueError("Facebook managed callbacks require the configured app ID, signing secret and verification token.")
    if (base.scheme != "https" or not base.hostname or base.username or base.password
            or base.query or base.fragment or base.path not in ("", "/")):
        raise ValueError("APP_WEBHOOK_BASE_URL must be a public HTTPS origin")
    return FacebookWebhookApp(app_id, secret, (os.environ["APP_WEBHOOK_BASE_URL"].rstrip("/") + "/webhook/app/facebook"))


def required_event_fields(operation):
    fields = {name for name, _ in FB_WEBHOOK_FIELDS}
    if operation == "on_any_facebook_event":
        return fields
    if isinstance(operation, str) and operation.startswith("on_") and operation[3:] in fields:
        return {operation[3:]}
    raise ValueError("Unknown Facebook trigger operation.")


def _request(client, token, app):
    proof = hmac.new(app.app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    async def request(method, path, *, params=None, data=None):
        return await graph_request(
            client, method, path, base=FB_API_BASE, label="Facebook",
            params={**(params or {}), "appsecret_proof": proof}, data=data,
        )
    return request


async def authorize_page(credential, page_id, app, event_fields):
    """Return an ephemeral derived Page token; never cache a Page access grant."""
    try:
        async with asyncio.timeout(45):
            return await _authorize_page(credential, page_id, app, event_fields)
    except TimeoutError:
        raise ValueError("Facebook Page authorization timed out; retry verification.") from None


async def managed_page_options(credential):
    app = require_facebook_webhook_configuration()
    token = (credential or {}).get("access_token")
    if (credential or {}).get("credential_type") != "facebook_oauth" or not isinstance(token, str) or not token.strip():
        raise ValueError("Connect a Facebook OAuth account to select a managed Page.")
    try:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {token}"}) as client:
                pages = await read_edge(_request(client, token, app), "me/accounts", fields="id,name", label="Facebook", max_pages=50)
    except TimeoutError:
        raise ValueError("Facebook Page listing timed out; retry loading Pages.") from None
    if any(not facebook_page_id(page.get("id")) for page in pages):
        raise ValueError("Facebook returned invalid Page identities; retry loading Pages.")
    return {"options": [{"value": str(page["id"]), "label": str(page.get("name") or page["id"])} for page in pages]}


async def _authorize_page(credential, page_id, app, event_fields):
    user = facebook_page_id((credential or {}).get("facebook_user_id"))
    token = (credential or {}).get("access_token")
    if ((credential or {}).get("credential_type") != "facebook_oauth" or not user
            or not isinstance(token, str) or not token.strip() or not facebook_page_id(page_id)):
        raise MetaAuthorizationDenied("Connect a valid Facebook OAuth account and select its Page.")
    # The debugger's app/user identity, not caller-provided scopes, binds the token.
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {app.app_id}|{app.app_secret}"}) as client:
        inspected = await graph_request(client, "GET", "debug_token", base=FB_API_BASE,
                                        label="Facebook", params={"input_token": token})
    details = inspected.get("data")
    if (not isinstance(details, dict) or details.get("is_valid") is not True
            or facebook_page_id(details.get("app_id")) != app.app_id
            or facebook_page_id(details.get("user_id")) != user or details.get("type") != "USER"):
        raise MetaAuthorizationDenied("Facebook token is invalid or belongs to another app/account; reconnect it.")
    for key in ("expires_at", "data_access_expires_at"):
        expiry = details.get(key)
        if (not isinstance(expiry, int) or isinstance(expiry, bool) or expiry < 0
                or (expiry != 0 and expiry <= time())):
            raise MetaAuthorizationDenied("Facebook token or data access has expired; reconnect it.")
    required = {"pages_show_list", "pages_manage_metadata"}
    if event_fields & {"feed", "mention", "ratings"}:
        required |= {"pages_read_engagement", "pages_read_user_content"}
    if event_fields - {"feed", "mention", "ratings"}:
        required.add("pages_messaging")
    scopes = details.get("scopes")
    if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes) or not required.issubset(scopes):
        raise MetaAuthorizationDenied("Facebook authorization is missing required Page permissions; reconnect it.")
    granular = details.get("granular_scopes", [])
    if not isinstance(granular, list) or any(not isinstance(grant, dict) for grant in granular):
        raise ValueError("Facebook returned invalid permission target data; retry verification.")
    for grant in granular:
        if grant.get("scope") in required and "target_ids" in grant:
            targets = grant["target_ids"]
            if not isinstance(targets, list) or page_id not in [facebook_page_id(target) for target in targets]:
                raise MetaAuthorizationDenied("Facebook permission no longer includes the selected Page; reconnect it.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {token}"}) as client:
        rows = await read_edge(_request(client, token, app), "me/accounts", fields="id,access_token,tasks", label="Facebook", max_pages=50)
    matches = [row for row in rows if facebook_page_id(row.get("id")) == page_id]
    if len(matches) != 1:
        raise MetaAuthorizationDenied("The selected Page is not uniquely authorized by this Facebook account.")
    page_token, tasks = matches[0].get("access_token"), matches[0].get("tasks")
    if (not isinstance(page_token, str) or not page_token.strip() or not isinstance(tasks, list)
            or not {"MANAGE", "PROFILE_PLUS_MANAGE", "PROFILE_PLUS_FULL_CONTROL"}.intersection(str(task) for task in tasks)):
        raise MetaAuthorizationDenied("The selected Page does not grant management access to this account.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {page_token}"}) as client:
        identity = await _request(client, page_token, app)("GET", "me", params={"fields": "id"})
        if facebook_page_id(identity.get("id")) != page_id:
            raise MetaAuthorizationDenied("Facebook's Page token identity does not match the selected Page.")
    return page_token


async def ensure_page_subscription(credential, config):
    app = require_facebook_webhook_configuration()
    page_id = facebook_page_id((config or {}).get("page_id"))
    if not page_id or (config or {}).get("callback_mode") != "managed" or config.get("disabled") in (True, "true"):
        raise ValueError("Select a Page on an enabled managed Facebook trigger.")
    fields = required_event_fields(config.get("operation"))
    page_token = await authorize_page(credential, page_id, app, fields)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {app.app_id}|{app.app_secret}"}) as client:
        request = partial(graph_request, client, base=FB_API_BASE, label="Facebook")
        app_rows = await read_edge(request, f"{app.app_id}/subscriptions", fields="object,callback_url,active,fields", label="Facebook")
        matching = [row for row in app_rows if row.get("object") == "page"]
        if len(matching) != 1 or matching[0].get("active") is not True or matching[0].get("callback_url") != app.callback_url:
            raise ValueError("Facebook's app-level Page callback is not active at the configured URL; an app administrator must complete callback setup.")
        app_fields = matching[0].get("fields")
        if (not isinstance(app_fields, list) or any(not isinstance(item, dict) for item in app_fields)
                or not fields.issubset({item.get("name") for item in app_fields if isinstance(item.get("name"), str)})):
            raise ValueError("Facebook's app-level callback does not subscribe to every selected event field; an app administrator must complete callback setup.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {page_token}"}) as client:
        request = _request(client, page_token, app)
        read = partial(read_subscribed_fields, request, page_id, {app.app_id}, label="Facebook", require_matching_if_nonempty=False)
        async with registration_lease(page_id, app.app_id, provider="facebook", label="Facebook") as check_owner:
            current = await read()
            wanted = current | fields
            if wanted != current:
                await check_owner()
                result = await request("POST", f"{page_id}/subscribed_apps", data={"subscribed_fields": ",".join(sorted(wanted))})
                if result.get("success") is not True:
                    raise ValueError("Facebook did not confirm the subscription update; remote fields may have changed; no workflow subscription was saved.")
                try:
                    verified = await read()
                except ValueError:
                    raise ValueError("Facebook accepted the subscription update but readback could not be verified; remote fields may have changed; no workflow subscription was saved.") from None
                if not wanted.issubset(verified):
                    raise ValueError("Facebook readback did not confirm every subscribed field; no workflow subscription was saved.")
    return page_id

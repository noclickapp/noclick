"""Facebook Login authorization and callbacks for cross-account Instagram mentions."""

from functools import partial

import httpx

from utils.credential_loader import load_credential
from utils.facebook_subscriptions import (
    FB_API_BASE, _request, authorize_page, require_facebook_webhook_configuration,
)
from utils.facebook_webhooks import verify_facebook_webhook
from utils.instagram_webhooks import (
    INSTAGRAM_WEBHOOK_ADAPTER, instagram_account_id, instagram_event_guard,
    instagram_live_scope_filter, parse_instagram_webhook,
)
from utils.meta_subscriptions import (
    MetaAuthorizationDenied, graph_request, read_edge, read_subscribed_fields, registration_lease,
)

PROVIDER = "instagram_facebook"


async def authorize_instagram_facebook(credential):
    app = require_facebook_webhook_configuration()
    account = instagram_account_id((credential or {}).get("instagram_user_id"))
    page = instagram_account_id((credential or {}).get("facebook_page_id"))
    token = (credential or {}).get("access_token")
    if ((credential or {}).get("credential_type") != "instagram_oauth" or not account or not page
            or not isinstance(token, str) or not token.strip()):
        raise MetaAuthorizationDenied("Connect Instagram with Facebook Login and select its linked Page to receive mentions.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {token}"}) as client:
        identity = await _request(client, token, app)("GET", "me", params={"fields": "id"})
    page_token = await authorize_page(
        {**credential, "credential_type": "facebook_oauth", "facebook_user_id": identity.get("id")},
        page, app, set(), permission_targets={
            "instagram_basic": account, "instagram_manage_comments": account,
            "pages_read_engagement": page,
        },
    )
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"Authorization": f"Bearer {page_token}"}) as client:
        linked = await _request(client, page_token, app)(
            "GET", page, params={"fields": "instagram_business_account{id}"},
        )
    if instagram_account_id((linked.get("instagram_business_account") or {}).get("id")) != account:
        raise MetaAuthorizationDenied("The Facebook Page is no longer linked to the selected Instagram account; reconnect it.")
    return app, page, page_token


async def ensure_instagram_facebook_subscription(credential):
    app, page, page_token = await authorize_instagram_facebook(credential)
    callback = app.callback_url.removesuffix("/facebook") + "/instagram_facebook"
    async with httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bearer {app.app_id}|{app.app_secret}"}) as client:
        rows = await read_edge(
            partial(graph_request, client, base=FB_API_BASE, label="Instagram"),
            f"{app.app_id}/subscriptions", fields="object,callback_url,active,fields", label="Instagram",
        )
    rows = [row for row in rows if row.get("object") == "instagram"]
    if (len(rows) != 1 or rows[0].get("active") is not True or rows[0].get("callback_url") != callback
            or not isinstance(rows[0].get("fields"), list)
            or "mentions" not in {field.get("name") for field in rows[0]["fields"] if isinstance(field, dict)}):
        raise ValueError("An app administrator must enable the Facebook Login Instagram mentions callback at the configured URL.")
    async with httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bearer {page_token}"}) as client:
        request = _request(client, page_token, app)
        read = partial(read_subscribed_fields, request, page, {app.app_id}, label="Instagram", require_matching_if_nonempty=False)
        # The Page subscription activates all app-level Instagram fields. Its
        # field enum uses `feed`; `mentions` is an Instagram app field only.
        async with registration_lease(page, app.app_id, provider="facebook", label="Instagram") as check_owner:
            current = await read()
            if not current:
                await check_owner()
                result = await request("POST", f"{page}/subscribed_apps", data={"subscribed_fields": "feed"})
                if result.get("success") is not True or "feed" not in await read():
                    raise ValueError("Instagram Page subscription was not verified; no workflow subscription was saved.")
    return credential["instagram_user_id"]


async def instagram_facebook_live_scope_filter(pool, sub, payload, trigger_node):
    if payload.get("event_type") != "mentions":
        return "Facebook Login Instagram callbacks support the mention trigger"
    reason = await instagram_live_scope_filter(
        pool, sub, payload, trigger_node, provider=PROVIDER, credential_type="instagram_oauth",
    )
    if reason:
        return reason
    credential = await load_credential(pool, str(sub["user_id"]), str(sub["credential_id"]), raise_on_error=True)
    from nodes.instagram_node import InstagramNode

    credential = await InstagramNode.freshen_credential(
        credential, pool=pool, user_id=str(sub["user_id"]), credential_id=str(sub["credential_id"]),
    )
    try:
        app, page, token = await authorize_instagram_facebook(credential)
        async with httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bearer {token}"}) as client:
            fields = await read_subscribed_fields(
                _request(client, token, app), page, {app.app_id}, label="Instagram", require_matching_if_nonempty=False,
            )
        if not fields:
            return "Instagram's linked Page is no longer subscribed"
    except MetaAuthorizationDenied:
        return "Instagram Facebook Login authorization is no longer available"
    return None


INSTAGRAM_FACEBOOK_WEBHOOK_ADAPTER = {
    **INSTAGRAM_WEBHOOK_ADAPTER,
    "verify": verify_facebook_webhook,
    "parse": lambda body: [event for event in parse_instagram_webhook(body) if event[1] == "mentions"],
    "event_guard": partial(instagram_event_guard, provider=PROVIDER),
    "subscription_guard": partial(instagram_event_guard, provider=PROVIDER),
    "live_scope_filter": instagram_facebook_live_scope_filter,
}

"""Discover Instagram accounts available through a Facebook Login grant."""

import re

from utils.meta_subscriptions import graph_request, read_edge


async def discover_instagram_accounts(client, user_token, *, base):
    """Return all accessible accounts, or a concrete, token-free diagnostic."""
    async def request(method, path, *, params):
        return await graph_request(
            client, method, path, base=base, label="Facebook Pages",
            purpose="account discovery", params=params,
            headers={"Authorization": f"Bearer {user_token}"},
        )

    pages = await read_edge(
        request, "me/accounts", label="Facebook Page list",
        fields=("id,name,access_token,tasks,instagram_business_account{id,username},"
                "connected_instagram_account{id,username}"),
    )
    if not pages:
        return [], (
            "Facebook returned no Pages for this login. Reconnect using the personal "
            "Facebook profile that has access to the Page linked to your Instagram "
            "professional account, and include that Page in Facebook's consent screen. "
            "If the Page is managed in a business portfolio, check that the profile "
            "has been assigned access to the Page."
        )

    accounts, seen_ids, failed_pages, missing_tokens = [], set(), [], []
    for page in pages:
        page_id = page.get("id")
        if not isinstance(page_id, str) or not re.fullmatch(r"[1-9][0-9]{0,31}", page_id):
            raise ValueError("Facebook Page list returned an invalid Page ID; reconnect and retry.")
        ig_account = page.get("instagram_business_account") or page.get("connected_instagram_account")
        page_data = page
        if not ig_account:
            page_token = page.get("access_token")
            if not page_token:
                missing_tokens.append(page_id)
                continue
            try:
                page_data = await graph_request(
                    client, "GET", page_id, base=base, label=f"Facebook Page {page_id}",
                    purpose="Instagram account lookup",
                    params={"fields": "instagram_business_account{id,username},connected_instagram_account{id,username},name"},
                    headers={"Authorization": f"Bearer {page_token}"},
                )
            except ValueError as exc:
                # Preserve the failed lookup as an error, rather than telling the
                # user that the Page definitely has no linked Instagram account.
                failed_pages.append(str(exc))
                continue
            ig_account = page_data.get("instagram_business_account") or page_data.get("connected_instagram_account")
        if not ig_account:
            continue
        if not isinstance(ig_account, dict) or not isinstance(ig_account.get("id"), str):
            raise ValueError(f"Facebook Page {page_id} returned invalid Instagram account data; retry.")
        ig_id = ig_account["id"]
        if not ig_id or ig_id in seen_ids:
            continue
        seen_ids.add(ig_id)
        accounts.append({
            "instagram_user_id": ig_id,
            "instagram_username": ig_account.get("username"),
            "facebook_page_id": page_id,
            "facebook_page_name": page_data.get("name") or page.get("name"),
        })

    if accounts:
        return accounts, None
    detail = f"Facebook returned {len(pages)} Page(s) (IDs: {', '.join(p['id'] for p in pages)}). "
    if failed_pages or missing_tokens:
        detail += "Instagram account discovery could not be completed. "
        if failed_pages:
            detail += " ".join(failed_pages) + " "
        if missing_tokens:
            detail += f"Facebook did not grant Page access tokens for: {', '.join(missing_tokens)}. "
        detail += "Check the profile's Page access and reconnect with the linked Page selected."
    else:
        detail += (
            "No linked Instagram Business or Creator account was returned. "
            "Check the Page's Linked accounts settings, confirm the Instagram account "
            "is professional, and include both the Page and Instagram account when reconnecting."
        )
    return [], detail

"""Enrich signed mention events with comment/caption text, author identity and media."""

MENTIONED_COMMENT_FIELDS = (
    "id,text,timestamp,media{id,caption,media_type,media_url,permalink,timestamp,"
    "thumbnail_url,children{id,media_type,media_url,thumbnail_url}}"
)
# Mentioned Media exposes fewer fields than the regular Media endpoint.
MENTIONED_MEDIA_FIELDS = "id,caption,media_type,media_url,timestamp,username"


async def enrich_mention(node, credentials, payload):
    from utils.instagram_webhooks import instagram_account_id, mentions_username

    account_id = credentials.instagram_user_id
    if instagram_account_id(payload.get("account_id")) != account_id:
        raise ValueError("Instagram event belongs to a different connected account")
    value = payload["data"]
    kind = value.get("mention_type")
    if kind not in ("comment", "caption"):
        raise ValueError("Instagram webhook has an invalid mention type")
    object_id = instagram_account_id(value.get("comment_id" if kind == "comment" else "media_id"))
    media_id = instagram_account_id(value.get("media_id"))
    if not object_id or not media_id:
        raise ValueError("Instagram webhook is missing a valid comment or media ID")
    username = credentials.instagram_username
    # Full comment notifications also include ordinary comments on owned media.
    # The live scope guard filters these first; recheck at execution in case the
    # account changed while queued. ID-only mentions are confirmed by the API.
    if isinstance(value.get("text"), str):
        if not username:
            profile = await node._make_request(
                "GET", f"/{account_id}", credentials,
                params={"fields": "username"}, action_name="on_mention",
            )
            if profile["status"] == "error":
                return profile
            username = profile["data"].get("username")
        if not username:
            raise ValueError("Instagram did not return the connected account's username")
        if not mentions_username(value["text"], username):
            return node.no_event_output("on_mention", "This event does not mention the connected account.")
    # Instagram Login reads the object IDs in the signed notification directly.
    # The mentioned_comment/mentioned_media user expansions belong to Facebook
    # Login and fail with "nonexisting field" on graph.instagram.com.
    fields = MENTIONED_COMMENT_FIELDS + ",from" if kind == "comment" else MENTIONED_MEDIA_FIELDS
    result = await node._make_request(
        "GET", f"/{object_id}", credentials,
        params={"fields": fields}, action_name="on_mention",
    )
    if result["status"] == "error":
        return result
    comment = None
    if kind == "comment":
        comment = result["data"]
        if not isinstance(comment, dict) or instagram_account_id(comment.get("id")) != object_id:
            raise ValueError("Instagram did not return the mentioned comment")
        media = comment.get("media")
        author = value.get("from") or comment.get("from")
        author = author if isinstance(author, dict) else None
        text = comment.get("text")
    else:
        media = result["data"]
        author = {"username": media["username"]} if isinstance(media, dict) and media.get("username") else None
        text = media.get("caption") if isinstance(media, dict) else None
    if not isinstance(media, dict) or instagram_account_id(media.get("id")) != media_id:
        raise ValueError("Instagram did not return media for the mention")
    if author and (
        instagram_account_id(author.get("id")) == account_id
        or (username and str(author.get("username") or "").casefold() == username.casefold())
    ):
        return node.no_event_output("on_mention", "This mention was written by the connected account.")
    # Preserve the original webhook text when available. Mentioned Media strips
    # @ from other accounts' captions; never reconstruct text Meta didn't send.
    if isinstance(value.get("text"), str):
        text = value["text"]
    children = (media.get("children") or {}).get("data", [])
    media_urls = list(dict.fromkeys(
        item["media_url"] for item in [media, *children] if item.get("media_url")
    ))
    return {
        **result,
        "type": "instagram",
        "account_id": account_id,
        "event_type": "mentions",
        "event_id": payload["event_id"],
        "timestamp": payload.get("timestamp"),
        "data": {
            "account_id": account_id,
            "event_id": payload["event_id"],
            "mention_type": kind,
            "mentioned_username": username,
            "comment_id": object_id if comment else None,
            "media_id": media_id,
            "text": text,
            "author": author,
            "author_available": bool(author and (author.get("id") or author.get("username"))),
            "comment": {**comment, "from": author} if comment else None,
            "media": media,
            "media_urls": media_urls,
            "media_url_available": bool(media_urls),
            "received_at": payload.get("timestamp"),
        },
    }

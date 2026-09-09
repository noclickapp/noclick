"""Validate and normalize native Reddit JSON without changing authored text."""
import asyncio
from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlencode, urlsplit

ORIGIN = "https://www.reddit.com"


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Missing or invalid Reddit timestamp")
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def require(data, *fields):
    missing = [key for key in fields if data.get(key) is None]
    if missing:
        raise ValueError("Incomplete Reddit data: " + ", ".join(missing))


def permalink(path):
    if not isinstance(path, str) or not path.startswith("/r/"):
        raise ValueError("Invalid Reddit permalink")
    return ORIGIN + path


def media(data):
    photos, videos, assets = [], [], []
    metadata = data.get("media_metadata") or {}
    for item in (data.get("gallery_data") or {}).get("items", []):
        entry = metadata.get(item.get("media_id"), {})
        source = entry.get("s") or {}
        if source.get("u"):
            photos.append(unescape(source["u"]))
        for key in ("mp4", "gif"):
            if source.get(key):
                videos.append(unescape(source[key]))
        assets.append(
            {"type": "gallery", "media_id": item.get("media_id"), "metadata": entry}
        )
    destination = data.get("url") or ""
    if not photos and re.search(
        r"\.(?:png|jpe?g|webp|gif)$", urlsplit(destination).path, re.I
    ):
        photos.append(unescape(destination))
    for field in ("media", "secure_media"):
        entry = data.get(field)
        if not isinstance(entry, dict):
            continue
        video = entry.get("reddit_video") or {}
        if video.get("fallback_url"):
            videos.append(unescape(video["fallback_url"]))
        assets.append({"type": field, "metadata": entry})
    # Crossposts can carry their playable assets on the original post.
    for parent in data.get("crosspost_parent_list") or []:
        parent_photos, parent_videos, parent_assets = media(
            {k: v for k, v in parent.items() if k != "crosspost_parent_list"}
        )
        photos.extend(parent_photos)
        videos.extend(parent_videos)
        assets.extend(parent_assets)
    return list(dict.fromkeys(photos)), list(dict.fromkeys(videos)), assets


def normalize_post(data, community, scraped_at):
    require(
        data,
        "id",
        "title",
        "author",
        "subreddit",
        "selftext",
        "permalink",
        "created_utc",
        "score",
        "num_comments",
    )
    require(
        community, "display_name", "subscribers", "description", "public_description"
    )
    if not isinstance(data["id"], str) or not re.fullmatch(r"[a-z0-9]+", data["id"]):
        raise ValueError("Invalid Reddit post identity")
    if (
        any(
            not isinstance(data[key], str)
            for key in ("title", "author", "subreddit", "selftext")
        )
        or not data["title"]
    ):
        raise ValueError("Invalid Reddit post text")
    if not all(isinstance(community[k], str) for k in ("display_name", "description", "public_description")):
        raise ValueError("Invalid Reddit community metadata")
    if not _integer(community["subscribers"]) or community["subscribers"] < 0:
        raise ValueError("Invalid Reddit community member count")
    if data["subreddit"].casefold() != community["display_name"].casefold():
        raise ValueError("Post belongs to a different community")
    if not re.match(
        rf"^/r/{re.escape(data['subreddit'])}/comments/{re.escape(data['id'])}/",
        data["permalink"], re.I,
    ):
        raise ValueError("Reddit post permalink does not match its identity")
    if data["selftext"] and not isinstance(data.get("selftext_html"), str):
        raise ValueError("Post body HTML is missing")
    if data["selftext"] and not data["selftext_html"]:
        raise ValueError("Post body HTML is missing")
    if (
        not _integer(data["num_comments"])
        or data["num_comments"] < 0
        or isinstance(data["score"], bool)
        or not isinstance(data["score"], (int, float))
    ):
        raise ValueError("Invalid Reddit engagement counts")
    created = timestamp(data["created_utc"])
    edited = data.get("edited")
    photos, videos, assets = media(data)
    return {
        "post_id": data["id"],
        "title": data["title"],
        "url": permalink(data["permalink"]),
        "author": data["author"],
        "subreddit": data["subreddit"],
        "body": data["selftext"],
        "content_html": data.get("selftext_html") or "",
        "published_at": created,
        "updated_at": timestamp(edited)
        if isinstance(edited, (int, float)) and not isinstance(edited, bool)
        else created,
        "scraped_at": scraped_at,
        "score": data["score"],
        "num_comments": data["num_comments"],
        "tag": data.get("link_flair_text"),
        "content_url": data.get("url"),
        "photos": photos,
        "videos": videos,
        "media_assets": assets,
        "community_url": ORIGIN + "/r/" + community["display_name"] + "/",
        "community_description": community["description"]
        or community["public_description"],
        "community_members_num": community["subscribers"],
        "related_posts": None,
    }


def normalize_comments(children, limit, post_id):
    seen = set()

    def visit(things, parent_id):
        result = []
        for thing in things:
            if len(seen) >= limit:
                break
            if thing.get("kind") != "t1":
                continue
            data = thing["data"]
            require(
                data,
                "id",
                "parent_id",
                "author",
                "body",
                "body_html",
                "created_utc",
                "score",
                "permalink",
            )
            if data["parent_id"] != parent_id or data.get("link_id") != "t3_" + post_id:
                raise ValueError("Reddit returned a comment attached to the wrong post or parent")
            if not all(isinstance(data[k], str) for k in ("id", "author", "body", "body_html")):
                raise ValueError("Invalid Reddit comment text")
            if not _integer(data["score"]):
                raise ValueError("Invalid comment score")
            if data["id"] in seen:
                continue
            seen.add(data["id"])
            replies = data.get("replies")
            nested = (
                replies.get("data", {}).get("children", [])
                if isinstance(replies, dict)
                else []
            )
            result.append(
                {
                    "comment_id": data["id"],
                    "parent_id": data["parent_id"],
                    "author": data["author"],
                    "body": data["body"],
                    "content_html": data.get("body_html"),
                    "created_at": timestamp(data["created_utc"]),
                    "score": data["score"],
                    "url": permalink(data["permalink"]),
                    "replies": visit(nested, "t1_" + data["id"]),
                    "reply_count": None,
                }
            )
        return result

    roots = visit(children, "t3_" + post_id)
    return roots, len(seen)


def listing_children(value, kind):
    if (
        not isinstance(value, dict)
        or value.get("kind") != "Listing"
        or not isinstance(value.get("data"), dict)
    ):
        raise ValueError("Missing Reddit listing envelope")
    children = value["data"].get("children")
    if not isinstance(children, list) or any(
        not isinstance(c, dict) or not isinstance(c.get("data"), dict) for c in children
    ):
        raise ValueError("Malformed Reddit listing children")
    allowed = {kind, "more"} if kind == "t1" else {kind}
    if any(c.get("kind") not in allowed for c in children):
        raise ValueError("Unexpected record type in Reddit listing")
    return children


def comment_coverage(children):
    returned, deferred = 0, 0
    for thing in children:
        if thing.get("kind") == "more":
            deferred += len(thing["data"].get("children") or [])
        elif thing.get("kind") == "t1":
            returned += 1
            replies = thing["data"].get("replies")
            if replies:
                nested, more = comment_coverage(listing_children(replies, "t1"))
                returned += nested
                deferred += more
    return returned, deferred


def build_reddit_input(config):
    subreddit = config.subreddit.strip().removeprefix("r/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", subreddit):
        raise ValueError("Enter one subreddit name, without a URL or query parameters.")
    sort = config.sort or "hot"
    period = config.time if sort in {"top", "controversial"} else None
    limit = max(1, min(config.limit or 25, 100))
    comments = (config.max_comments or 10) if config.fetch_comments == "true" else 0
    params = {"raw_json": 1, "limit": limit, "sr_detail": 1}
    if period:
        params["t"] = period
    url = f"{ORIGIN}/r/{subreddit}/{sort}.json?" + urlencode(params)
    return url, subreddit, sort, period, limit, comments


def normalize_reddit_result(value, *, subreddit, sort, period, limit, comments_limit):
    posts = []
    seen = set()
    now = datetime.now(timezone.utc).isoformat()
    children = listing_children(value, "t3")
    if len(children) > limit:
        raise ValueError("Reddit scraper exceeded the requested post limit")
    for item in children:
        data = item["data"]
        post = normalize_post(data, data.get("sr_detail") or {}, now)
        if post["subreddit"].casefold() != subreddit.casefold():
            raise ValueError("Reddit scraper returned a different subreddit")
        if post["post_id"] not in seen:
            posts.append(post)
            seen.add(post["post_id"])
    if sort == "new":
        posts.sort(key=lambda p: p["published_at"], reverse=True)
    elif sort == "top":
        posts.sort(key=lambda p: p["score"], reverse=True)
    return {
        "posts": posts, "count": len(posts), "subreddit": subreddit, "sort": sort,
        "time_period": period, "source": "decodo", "comments_fetched": bool(comments_limit),
        "coverage": {"requested_posts": limit, "requested_count_met": len(posts) >= limit,
                     "next_cursor": value["data"].get("after")},
    }


def attach_comments(post, thread, limit):
    if not isinstance(thread, list) or len(thread) != 2:
        raise ValueError("Reddit returned an invalid comment thread")
    parents = listing_children(thread[0], "t3")
    if len(parents) != 1 or parents[0]["data"].get("id") != post["post_id"]:
        raise ValueError("Reddit returned a comment thread for the wrong post")
    children = listing_children(thread[1], "t1")
    available, deferred = comment_coverage(children)
    comments, count = normalize_comments(children, limit, post["post_id"])
    post.update(
        comments=comments, comment_count=count, comments_limit=limit, comments_are_sampled=True,
        comment_coverage={"returned_by_reddit": available, "returned_to_caller": count,
                          "deferred_comment_ids": deferred},
    )


async def fetch_subreddit(client, request):
    url, subreddit, sort, period, limit, comments_limit = request
    value = await client.fetch_json(url)
    output = normalize_reddit_result(
        value, subreddit=subreddit, sort=sort, period=period, limit=limit, comments_limit=comments_limit,
    )
    if comments_limit:
        async def enrich(post):
            params = urlencode({"raw_json": 1, "limit": comments_limit, "depth": 10})
            url = f"{ORIGIN}/r/{subreddit}/comments/{post['post_id']}.json?{params}"
            attach_comments(post, await client.fetch_json(url), comments_limit)

        tasks = [asyncio.create_task(enrich(post)) for post in output["posts"]]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            # Close every pending paid read before the runner settles usage or exits.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    return output

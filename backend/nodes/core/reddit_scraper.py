"""Input and output contract for the public Reddit scraper (verified live)."""

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

REDDIT_ACTOR = "harshmaur/reddit-scraper"
REDDIT_ACTOR_BUILD = "0.0.392"


def build_reddit_input(config):
    subreddit = config.subreddit.strip().removeprefix("r/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", subreddit):
        raise ValueError("Enter one subreddit name, without a URL or query parameters.")
    sort = config.sort or "hot"
    period = config.time if sort in {"top", "controversial"} else None
    limit = max(1, min(config.limit or 25, 100))
    comments = (config.max_comments or 10) if config.fetch_comments == "true" else 0
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/"
    if period:
        url += "?" + urlencode({"t": period})
    return (
        {
            "startUrls": [{"url": url}],
            "maxPostsCount": limit,
            "crawlCommentsPerPost": bool(comments),
            "maxCommentsPerPost": comments,
            "maxCommentsCount": 0,
            "maxCommunitiesCount": 1,
            "includeNSFW": True,
            "aiAnalysis": False,
            "customLabels": {},
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
        subreddit,
        sort,
        period,
        limit,
        comments,
    )


def _require(item: dict, fields: tuple[str, ...]) -> None:
    missing = [key for key in fields if item.get(key) is None]
    if missing:
        raise ValueError(
            f"Reddit scraper returned an incomplete record: missing {', '.join(missing)}"
        )


def _date(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Reddit scraper returned a timestamp without a timezone")
    return value


def normalize_reddit_result(
    items: list[dict],
    community_items: list[dict],
    *,
    subreddit: str,
    sort: str,
    period: str | None,
    limit: int,
    comments_limit: int,
) -> dict[str, Any]:
    communities = [
        x
        for x in community_items
        if x.get("dataType") == "community" and x.get("name", "").casefold() == subreddit.casefold()
    ]
    if len(communities) != 1:
        raise ValueError(f"Reddit scraper did not return community metadata for r/{subreddit}")
    community = communities[0]
    _require(community, ("membersCount", "description", "publicDescription"))
    posts = {}
    for item in items:
        if item.get("dataType") != "post":
            continue
        _require(
            item,
            (
                "id",
                "title",
                "body",
                "postUrl",
                "authorName",
                "createdAt",
                "score",
                "commentsCount",
                "parsedCommunityName",
            ),
        )
        if item["body"]:
            _require(item, ("bodyHtml",))
        post_id = item["id"].removeprefix("t3_")
        if (
            not post_id
            or not item["title"]
            or not item["postUrl"].startswith("https://www.reddit.com/")
            or item["parsedCommunityName"].casefold() != subreddit.casefold()
        ):
            raise ValueError("Reddit scraper returned a post with an invalid identity or subreddit")
        if (
            not isinstance(item["commentsCount"], int)
            or item["commentsCount"] < 0
            or not isinstance(item["score"], (int, float))
        ):
            raise ValueError("Reddit scraper returned invalid engagement counts")
        if (
            item.get("bodyLength") is not None
            and len(item["body"].encode("utf-16-le")) // 2 != item["bodyLength"]
        ):
            raise ValueError("Reddit scraper returned truncated post text")
        posts[post_id] = {
            "post_id": post_id,
            "title": item["title"],
            "url": item["postUrl"],
            "author": item["authorName"],
            "subreddit": item["parsedCommunityName"],
            "body": item["body"],
            "content_html": item.get("bodyHtml") or "",
            "published_at": _date(item["createdAt"]),
            "updated_at": item.get("editedAt") or item["createdAt"],
            "scraped_at": item.get("crawledAt"),
            "score": item["score"],
            "num_comments": item["commentsCount"],
            "tag": item.get("flair"),
            "content_url": item.get("contentUrl"),
            "photos": (item.get("galleryImages") or [])
            if item.get("mediaType") == "gallery"
            else (
                [item["contentUrl"]]
                if item.get("mediaType") == "image" and item.get("contentUrl")
                else item.get("images") or []
            ),
            "videos": [item["videoUrl"]] if item.get("videoUrl") else [],
            "media_assets": item.get("mediaAssets") or [],
            "community_url": f"https://www.reddit.com/r/{subreddit}/",
            "community_description": community["description"] or community["publicDescription"],
            "community_members_num": community["membersCount"],
            # Reddit does not expose related-post recommendations in this dataset.
            "related_posts": None,
        }
    if len(posts) > limit:
        raise ValueError("Reddit scraper exceeded the requested post limit")

    if comments_limit:
        comments_by_post: dict[str, dict] = {pid: {} for pid in posts}
        for item in items:
            if item.get("dataType") != "comment":
                continue
            _require(
                item,
                (
                    "id",
                    "postId",
                    "parentId",
                    "body",
                    "authorName",
                    "url",
                    "commentCreatedAt",
                    "score",
                ),
            )
            pid = item["postId"].removeprefix("t3_")
            if pid not in posts:
                raise ValueError("Reddit scraper returned a comment without its post")
            cid = item["id"].removeprefix("t1_")
            comments_by_post[pid][cid] = {
                "comment_id": cid,
                "parent_id": item["parentId"],
                "author": item["authorName"],
                "body": item["body"],
                "content_html": item.get("bodyHtml"),
                "created_at": _date(item["commentCreatedAt"]),
                "score": item["score"],
                "url": item["url"],
                "replies": [],
                "reply_count": None,
            }
        for pid, comments in comments_by_post.items():
            if len(comments) > comments_limit:
                raise ValueError("Reddit scraper exceeded the requested comment limit")
            roots = []
            for cid, comment in comments.items():
                parent_id = comment["parent_id"]
                parent = (
                    comments.get(parent_id.removeprefix("t1_"))
                    if parent_id.startswith("t1_")
                    else None
                )
                # Keep orphaned replies visible; sampling may omit their parent.
                if parent is not None:
                    ancestors = {cid}
                    cursor = parent
                    while cursor is not None:
                        if cursor["comment_id"] in ancestors:
                            raise ValueError("Reddit scraper returned cyclic comment replies")
                        ancestors.add(cursor["comment_id"])
                        cursor = comments.get(cursor["parent_id"].removeprefix("t1_"))
                    parent["replies"].append(comment)
                else:
                    roots.append(comment)
            posts[pid].update(
                comments=roots,
                comment_count=len(comments),
                comments_limit=comments_limit,
                comments_are_sampled=True,
            )

    result = list(posts.values())
    if sort == "new":
        result.sort(
            key=lambda p: datetime.fromisoformat(p["published_at"].replace("Z", "+00:00")),
            reverse=True,
        )
    elif sort == "top":
        result.sort(key=lambda p: p["score"], reverse=True)
    return {
        "posts": result,
        "count": len(result),
        "subreddit": subreddit,
        "sort": sort,
        "time_period": period,
        "source": "apify",
        "comments_fetched": bool(comments_limit),
    }

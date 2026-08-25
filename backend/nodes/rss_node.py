"""
RSS Feed automation node implementation.

Comprehensive RSS feed integration supporting 80+ operations across multiple services:
- Direct RSS/Atom Feed Parsing: Parse any public or password-protected feed
- Miniflux API: Self-hosted RSS reader with full API (feeds, entries, categories, OPML)
- Feedly API: Cloud RSS service (streams, subscriptions, articles, search)
- FreshRSS API: Google Reader API compatible (subscriptions, streams, tags)
- RSS.app API: RSS feed generation and management service

Supports all major authentication methods: API tokens, OAuth, basic auth, API keys
"""

import asyncio
import time
import logging
import hashlib
import json
from typing import Dict, Any, Optional, Union, Type, Literal, List, Annotated
from datetime import datetime, timezone
from pydantic import (
    BaseModel,
    Field,
    Discriminator,
    ConfigDict,
    field_validator,
    model_validator,
)
import httpx
import feedparser
from urllib.parse import urlencode, urljoin, urlsplit

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import bounded_seen_ids
from utils.ssrf import assert_exact_url_origin, guarded_async_client

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================


def generate_fever_api_key(username: str, password: str) -> str:
    """Generate the protocol-defined Fever API key.

    The Fever API wire format requires ``MD5(username:password)``.  This value
    is sent to a server that already owns the credential; it is not password
    storage or a general-purpose security hash.
    """
    return hashlib.md5(
        f"{username}:{password}".encode(), usedforsecurity=False
    ).hexdigest()


def _canonical_https_origin(value: str) -> str:
    """Validate an arbitrary credential-bound HTTPS origin."""
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as e:
        raise ValueError("Allowed Feed Origin must be a valid HTTPS origin") from e
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.path not in ("", "/")
        or bool(parts.query)
        or bool(parts.fragment)
    ):
        raise ValueError("Allowed Feed Origin must be a canonical HTTPS origin")
    return f"https://{parts.hostname.lower().rstrip('.')}"


async def parse_rss_feed_direct(
    feed_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    api_key: Optional[str] = None,
    custom_headers: Optional[Dict[str, str]] = None,
    allowed_origin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse RSS/Atom feed directly using feedparser.

    Args:
        feed_url: URL of the RSS/Atom feed
        username: Optional basic auth username
        password: Optional basic auth password
        api_key: Optional API key for authorization header
        custom_headers: Optional custom headers

    Returns:
        Parsed feed data
    """
    try:
        # Prepare request arguments. Authenticated RSS credentials are bound to
        # one origin so selecting an existing credential cannot turn an
        # arbitrary feed URL into a credential-exfiltration sink.
        has_credentials = bool(
            (username and password) or api_key or custom_headers
        )
        if has_credentials:
            if not allowed_origin:
                raise ValueError(
                    "Authenticated RSS credentials require an Allowed Feed Origin"
                )
            allowed_origin = _canonical_https_origin(allowed_origin)
            assert_exact_url_origin(feed_url, allowed_origin)

        kwargs = {}

        # Add authentication if provided
        if username and password:
            kwargs["auth"] = httpx.BasicAuth(username, password)

        # Build headers
        headers = custom_headers.copy() if custom_headers else {}
        if any(str(name).strip().lower() == "host" for name in headers):
            raise ValueError("Authenticated RSS custom headers must not override Host")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # Set a standard User-Agent so servers don't reject the request
        if "User-Agent" not in headers:
            headers["User-Agent"] = "Mozilla/5.0 (compatible; NoClick RSS Reader/1.0)"

        kwargs["headers"] = headers

        # Public feeds may follow guarded redirects freely. Authenticated feeds
        # follow redirects manually and only within the credential-bound origin,
        # so custom secret headers can never survive a cross-origin hop.
        async with guarded_async_client(follow_redirects=not has_credentials) as client:
            if has_credentials:
                current_url = feed_url
                for redirect_count in range(6):
                    response = await client.get(current_url, timeout=30.0, **kwargs)
                    if response.status_code not in (301, 302, 303, 307, 308):
                        break
                    location = response.headers.get("location")
                    if not location:
                        break
                    if redirect_count == 5:
                        raise ValueError("RSS feed exceeded the redirect limit")
                    next_url = urljoin(str(response.url), location)
                    assert_exact_url_origin(next_url, allowed_origin)
                    current_url = next_url
            else:
                response = await client.get(feed_url, timeout=30.0, **kwargs)
            response.raise_for_status()

            # Parse with feedparser. The parse is CPU-bound XML (expat via
            # xml.sax) and blocked the loop up to 2.8s on real feeds, so it
            # runs off-thread — the fetch above already yields.
            feed = await asyncio.to_thread(feedparser.parse, response.text)

            # Extract feed metadata
            feed_info = {
                "title": feed.feed.get("title", ""),
                "link": feed.feed.get("link", ""),
                "description": feed.feed.get("description", ""),
                "language": feed.feed.get("language", ""),
                "updated": feed.feed.get("updated", ""),
                "author": feed.feed.get("author", ""),
                "image_url": feed.feed.get("image", {}).get("href", ""),
            }

            # Extract entries
            entries = []
            for entry in feed.entries:
                entry_data = {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "description": entry.get("description", "")
                    or entry.get("summary", ""),
                    "author": entry.get("author", ""),
                    "published": entry.get("published", ""),
                    "updated": entry.get("updated", ""),
                    "id": entry.get("id", ""),
                    "guid": entry.get("guid", ""),
                    "categories": [
                        tag.get("term", "") for tag in entry.get("tags", [])
                    ],
                    "content": entry.get("content", [{}])[0].get("value", "")
                    if entry.get("content")
                    else "",
                }
                entries.append(entry_data)

            return {
                "feed": feed_info,
                "entries": entries,
                "entry_count": len(entries),
                "feed_version": feed.version,
                "bozo": feed.bozo,  # True if feed is malformed
            }

    except Exception as e:
        raise ValueError(f"Failed to parse RSS feed: {str(e)}")


def _parse_feed_urls(feed_url: Any) -> List[str]:
    """Normalize feed_url to a list of URL strings.

    Accepts any of:
    - Single URL string: "https://example.com/feed.xml"
    - Comma-separated:   "https://url1.com, https://url2.com"
    - JSON array string: '["https://url1.com", "https://url2.com"]'
    - Python list:       ["https://url1.com", "https://url2.com"]
    - Reference result:  anything the above formats can produce after template resolution
    """
    if feed_url is None:
        return []
    if isinstance(feed_url, list):
        return [str(u).strip() for u in feed_url if str(u).strip()]
    s = str(feed_url).strip()
    if not s:
        return []
    # JSON array
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(u).strip() for u in parsed if str(u).strip()]
        except (json.JSONDecodeError, ValueError):
            pass
    # Comma-separated
    if "," in s:
        return [u.strip() for u in s.split(",") if u.strip()]
    # Single URL
    return [s]


# ============================================================================
# RSS Node Credential Schemas
# ============================================================================


class RSSDirectCredential(BaseModel):
    """
    Credential for parsing RSS/Atom feeds directly.

    Use this for:
    - Public RSS feeds (no credentials needed)
    - Password-protected feeds (with basic auth)
    - Feeds requiring API keys in headers
    """

    credential_type: Literal["direct"] = Field(
        "direct", title="Type", json_schema_extra={"const": "direct", "ui:hidden": True}
    )
    username: Optional[str] = Field(
        None, title="Username (Optional)", description="For Basic Auth protected feeds"
    )
    password: Optional[str] = Field(
        None,
        title="Password (Optional)",
        description="For Basic Auth protected feeds",
        json_schema_extra={"ui:widget": "password"},
    )
    api_key: Optional[str] = Field(
        None,
        title="API Key (Optional)",
        description="For feeds requiring bearer token authentication",
        json_schema_extra={"ui:widget": "password"},
    )
    custom_headers: Optional[Dict[str, str]] = Field(
        None,
        title="Custom Headers (Optional)",
        description="Additional headers as JSON object (e.g., {'X-API-Key': 'value'})",
        json_schema_extra={"ui:widget": "textarea"},
    )
    allowed_origin: Optional[str] = Field(
        None,
        title="Allowed Feed Origin",
        description=(
            "Required when authentication is configured. Credentials are sent only "
            "to this exact HTTPS origin (for example https://feeds.example.com)."
        ),
        json_schema_extra={"placeholder": "https://feeds.example.com"},
    )

    @field_validator("allowed_origin")
    @classmethod
    def validate_allowed_origin(cls, value: Optional[str]) -> Optional[str]:
        return _canonical_https_origin(value) if value else None

    @model_validator(mode="after")
    def require_origin_for_secrets(self):
        has_secrets = bool(
            (self.username and self.password) or self.api_key or self.custom_headers
        )
        if has_secrets and not self.allowed_origin:
            raise ValueError(
                "Allowed Feed Origin is required for authenticated RSS credentials"
            )
        return self


class RSSMinifluxCredential(BaseModel):
    """
    Miniflux API credential.

    Miniflux is a minimalist and opinionated feed reader.
    Create API token at: https://your-miniflux-url/keys
    """

    credential_type: Literal["miniflux"] = Field(
        "miniflux",
        title="Type",
        json_schema_extra={"const": "miniflux", "ui:hidden": True},
    )
    server_url: str = Field(
        ...,
        title="Miniflux Server URL",
        description="Your Miniflux instance URL (e.g., https://miniflux.example.com)",
        json_schema_extra={"placeholder": "https://miniflux.example.com"},
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="API token from Miniflux Settings > API Keys",
        json_schema_extra={
            "ui:widget": "password",
            "x-credential-url": "Settings > API Keys",
        },
    )


class RSSFeedlyCredential(BaseModel):
    """
    Feedly API credential.

    Get your developer access token from: https://feedly.com/i/team/developer
    Note: Enterprise accounts support OAuth 2.0
    """

    credential_type: Literal["feedly"] = Field(
        "feedly", title="Type", json_schema_extra={"const": "feedly", "ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Developer Access Token",
        description="Personal access token from Feedly Developer settings",
        json_schema_extra={
            "ui:widget": "password",
            "x-credential-url": "https://feedly.com/i/team/developer",
        },
    )


class RSSFreshRSSCredential(BaseModel):
    """
    FreshRSS API credential (Google Reader API compatible).

    FreshRSS is a self-hosted RSS aggregator.
    Enable API access in: Profile > Authentication > Allow API access
    """

    credential_type: Literal["freshrss"] = Field(
        "freshrss",
        title="Type",
        json_schema_extra={"const": "freshrss", "ui:hidden": True},
    )
    server_url: str = Field(
        ...,
        title="FreshRSS Server URL",
        description="Your FreshRSS instance URL (e.g., https://freshrss.example.com)",
        json_schema_extra={"placeholder": "https://freshrss.example.com"},
    )
    username: str = Field(..., title="Username", description="Your FreshRSS username")
    api_password: str = Field(
        ...,
        title="API Password",
        description="API password from Profile settings (not your login password)",
        json_schema_extra={
            "ui:widget": "password",
            "x-credential-url": "Profile > API Password",
        },
    )


class RSSAppCredential(BaseModel):
    """
    RSS.app API credential.

    RSS.app is a service for generating and managing RSS feeds.
    Get API keys from: https://rss.app/dashboard
    """

    credential_type: Literal["rss_app"] = Field(
        "rss_app",
        title="Type",
        json_schema_extra={"const": "rss_app", "ui:hidden": True},
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your RSS.app API key",
        json_schema_extra={
            "ui:widget": "password",
            "x-credential-url": "https://rss.app/dashboard",
        },
    )
    secret_key: str = Field(
        ...,
        title="Secret Key",
        description="Your RSS.app secret key",
        json_schema_extra={"ui:widget": "password"},
    )


# RSS credential type - Union of all credential types
RSSCredential = Union[
    RSSDirectCredential,
    RSSMinifluxCredential,
    RSSFeedlyCredential,
    RSSFreshRSSCredential,
    RSSAppCredential,
]


# ============================================================================
# Direct Feed Parsing Operations (2 operations)
# ============================================================================


class RSSParseFeedConfig(BaseModel):
    """Parse an RSS or Atom feed from a URL."""

    model_config = ConfigDict(title="Parse RSS Feed")

    operation: Literal["parse_rss_atom_feed"] = Field(
        "parse_rss_atom_feed",
        json_schema_extra={
            "const": "parse_rss_atom_feed",
            "ui:hidden": True,
            "x-category": "Generic Feed",
            "x-is-trigger": False,
            "x-display-name": "Parse Rss Atom Feed",
        },
        title="Parse Rss Atom Feed",
    )
    feed_url: str = Field(
        "",
        title="Feed URL(s)",
        description="URL of the RSS/Atom feed to parse. Accepts a single URL, comma-separated URLs, a JSON array, or a reference like {{nodeId.url}} or {{nodeId.rss_feeds}} that resolves to any of these formats.",
        json_schema_extra={"placeholder": "https://example.com/feed.xml"},
    )

    @field_validator("feed_url", mode="before")
    @classmethod
    def normalize_feed_url(cls, v: Any) -> str:
        """Coerce lists or other types to string for storage."""
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return json.dumps(v)
        return str(v)

    use_credentials: bool = Field(
        False,
        title="Use Credentials",
        description="Enable if the feed requires authentication",
    )
    only_new_items: str = Field(
        "false",
        title="Only New Items",
        description="Only return items not seen in previous executions. Useful for cron-triggered workflows to avoid processing duplicates.",
        json_schema_extra={
            "ui:category": "filtering",
            "enum": ["true", "false"],
            "enumNames": ["Yes — only new items", "No — all items"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Miniflux Operations (30+ operations)
# ============================================================================


class MinifluxDiscoverFeedConfig(BaseModel):
    """Discover RSS feeds from a website URL."""

    model_config = ConfigDict(title="Miniflux Discover Feed")

    operation: Literal["discover_rss_feeds_from_website"] = Field(
        "discover_rss_feeds_from_website",
        json_schema_extra={
            "const": "discover_rss_feeds_from_website",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Discover Rss Feeds from Website",
        },
        title="Discover Rss Feeds from Website",
    )
    website_url: str = Field(
        ...,
        title="Website URL",
        description="URL of the website to discover feeds from",
        json_schema_extra={"placeholder": "https://example.com"},
    )


class MinifluxCreateFeedConfig(BaseModel):
    """Create a new feed subscription in Miniflux."""

    model_config = ConfigDict(title="Miniflux Create Feed")

    operation: Literal["create_miniflux_feed_subscription"] = Field(
        "create_miniflux_feed_subscription",
        json_schema_extra={
            "const": "create_miniflux_feed_subscription",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Create Miniflux Feed Subscription",
        },
        title="Create Miniflux Feed Subscription",
    )
    feed_url: str = Field(
        ...,
        title="Feed URL",
        description="URL of the RSS/Atom feed to subscribe to",
        json_schema_extra={"placeholder": "https://example.com/feed.xml"},
    )
    category_id: Optional[int] = Field(
        None, title="Category ID (Optional)", description="Category to add the feed to"
    )


class MinifluxGetFeedsConfig(BaseModel):
    """Get all feeds from Miniflux."""

    model_config = ConfigDict(title="Miniflux Get Feeds")

    operation: Literal["get_miniflux_feeds"] = Field(
        "get_miniflux_feeds",
        json_schema_extra={
            "const": "get_miniflux_feeds",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Feeds",
        },
        title="Get Miniflux Feeds",
    )


class MinifluxGetFeedConfig(BaseModel):
    """Get a specific feed by ID."""

    model_config = ConfigDict(title="Miniflux Get Feed")

    operation: Literal["get_miniflux_feed"] = Field(
        "get_miniflux_feed",
        json_schema_extra={
            "const": "get_miniflux_feed",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Feed",
        },
        title="Get Miniflux Feed",
    )
    feed_id: int = Field(..., title="Feed ID", description="ID of the feed to retrieve")


class MinifluxUpdateFeedConfig(BaseModel):
    """Update feed settings."""

    model_config = ConfigDict(title="Miniflux Update Feed")

    operation: Literal["update_miniflux_feed_settings"] = Field(
        "update_miniflux_feed_settings",
        json_schema_extra={
            "const": "update_miniflux_feed_settings",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Update Miniflux Feed Settings",
        },
        title="Update Miniflux Feed Settings",
    )
    feed_id: int = Field(..., title="Feed ID", description="ID of the feed to update")
    title: Optional[str] = Field(
        None, title="Title (Optional)", description="New title for the feed"
    )
    category_id: Optional[int] = Field(
        None, title="Category ID (Optional)", description="Move feed to this category"
    )


class MinifluxDeleteFeedConfig(BaseModel):
    """Delete a feed subscription."""

    model_config = ConfigDict(title="Miniflux Delete Feed")

    operation: Literal["delete_miniflux_feed_subscription"] = Field(
        "delete_miniflux_feed_subscription",
        json_schema_extra={
            "const": "delete_miniflux_feed_subscription",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Delete Miniflux Feed Subscription",
        },
        title="Delete Miniflux Feed Subscription",
    )
    feed_id: int = Field(..., title="Feed ID", description="ID of the feed to delete")


class MinifluxRefreshFeedConfig(BaseModel):
    """Refresh a specific feed to fetch new entries."""

    model_config = ConfigDict(title="Miniflux Refresh Feed")

    operation: Literal["refresh_miniflux_feed"] = Field(
        "refresh_miniflux_feed",
        json_schema_extra={
            "const": "refresh_miniflux_feed",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Refresh Miniflux Feed",
        },
        title="Refresh Miniflux Feed",
    )
    feed_id: int = Field(..., title="Feed ID", description="ID of the feed to refresh")


class MinifluxRefreshAllFeedsConfig(BaseModel):
    """Refresh all feeds to fetch new entries."""

    model_config = ConfigDict(title="Miniflux Refresh All Feeds")

    operation: Literal["refresh_all_miniflux_feeds"] = Field(
        "refresh_all_miniflux_feeds",
        json_schema_extra={
            "const": "refresh_all_miniflux_feeds",
            "ui:hidden": True,
            "x-category": "Miniflux Account",
            "x-is-trigger": False,
            "x-display-name": "Refresh All Miniflux Feeds",
        },
        title="Refresh All Miniflux Feeds",
    )


class MinifluxGetEntriesConfig(BaseModel):
    """Get entries with filtering options."""

    model_config = ConfigDict(title="Miniflux Get Entries")

    operation: Literal["get_miniflux_entries"] = Field(
        "get_miniflux_entries",
        json_schema_extra={
            "const": "get_miniflux_entries",
            "ui:hidden": True,
            "x-category": "Miniflux Entry",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Entries",
        },
        title="Get Miniflux Entries",
    )
    status: Optional[Literal["unread", "read", "removed"]] = Field(
        None,
        title="Status Filter (Optional)",
        description="Filter entries by read status",
    )
    limit: int = Field(
        100,
        title="Limit",
        description="Maximum number of entries to return",
        ge=1,
        le=1000,
    )
    offset: int = Field(
        0, title="Offset", description="Number of entries to skip for pagination", ge=0
    )
    starred: Optional[bool] = Field(
        None,
        title="Starred Only (Optional)",
        description="Filter to show only starred/bookmarked entries",
    )


class MinifluxGetFeedEntriesConfig(BaseModel):
    """Get entries from a specific feed."""

    model_config = ConfigDict(title="Miniflux Get Feed Entries")

    operation: Literal["get_miniflux_feed_entries"] = Field(
        "get_miniflux_feed_entries",
        json_schema_extra={
            "const": "get_miniflux_feed_entries",
            "ui:hidden": True,
            "x-category": "Miniflux Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Feed Entries",
        },
        title="Get Miniflux Feed Entries",
    )
    feed_id: int = Field(..., title="Feed ID", description="ID of the feed")
    limit: int = Field(
        100,
        title="Limit",
        description="Maximum number of entries to return",
        ge=1,
        le=1000,
    )


class MinifluxGetEntryConfig(BaseModel):
    """Get a specific entry by ID."""

    model_config = ConfigDict(title="Miniflux Get Entry")

    operation: Literal["get_miniflux_entry"] = Field(
        "get_miniflux_entry",
        json_schema_extra={
            "const": "get_miniflux_entry",
            "ui:hidden": True,
            "x-category": "Miniflux Entry",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Entry",
        },
        title="Get Miniflux Entry",
    )
    entry_id: int = Field(
        ..., title="Entry ID", description="ID of the entry to retrieve"
    )


class MinifluxToggleBookmarkConfig(BaseModel):
    """Toggle bookmark/starred status of an entry."""

    model_config = ConfigDict(title="Miniflux Toggle Bookmark")

    operation: Literal["toggle_miniflux_entry_bookmark"] = Field(
        "toggle_miniflux_entry_bookmark",
        json_schema_extra={
            "const": "toggle_miniflux_entry_bookmark",
            "ui:hidden": True,
            "x-category": "Miniflux Entry",
            "x-is-trigger": False,
            "x-display-name": "Toggle Miniflux Entry Bookmark",
        },
        title="Toggle Miniflux Entry Bookmark",
    )
    entry_id: int = Field(
        ..., title="Entry ID", description="ID of the entry to bookmark/unbookmark"
    )


class MinifluxMarkEntriesReadConfig(BaseModel):
    """Mark specific entries as read."""

    model_config = ConfigDict(title="Miniflux Mark Entries as Read")

    operation: Literal["mark_miniflux_entries_read"] = Field(
        "mark_miniflux_entries_read",
        json_schema_extra={
            "const": "mark_miniflux_entries_read",
            "ui:hidden": True,
            "x-category": "Miniflux Entry",
            "x-is-trigger": False,
            "x-display-name": "Mark Miniflux Entries Read",
        },
        title="Mark Miniflux Entries Read",
    )
    entry_ids: List[int] = Field(
        ...,
        title="Entry IDs",
        description="List of entry IDs to mark as read",
        min_length=1,
    )


class MinifluxMarkAllReadConfig(BaseModel):
    """Mark all entries as read."""

    model_config = ConfigDict(title="Miniflux Mark All as Read")

    operation: Literal["mark_all_miniflux_entries_read"] = Field(
        "mark_all_miniflux_entries_read",
        json_schema_extra={
            "const": "mark_all_miniflux_entries_read",
            "ui:hidden": True,
            "x-category": "Miniflux Entry",
            "x-is-trigger": False,
            "x-display-name": "Mark All Miniflux Entries Read",
        },
        title="Mark All Miniflux Entries Read",
    )


class MinifluxCreateCategoryConfig(BaseModel):
    """Create a new category."""

    model_config = ConfigDict(title="Miniflux Create Category")

    operation: Literal["create_miniflux_category"] = Field(
        "create_miniflux_category",
        json_schema_extra={
            "const": "create_miniflux_category",
            "ui:hidden": True,
            "x-category": "Miniflux Category",
            "x-is-trigger": False,
            "x-display-name": "Create Miniflux Category",
        },
        title="Create Miniflux Category",
    )
    title: str = Field(
        ..., title="Category Title", description="Name of the category", min_length=1
    )


class MinifluxGetCategoriesConfig(BaseModel):
    """Get all categories."""

    model_config = ConfigDict(title="Miniflux Get Categories")

    operation: Literal["get_miniflux_categories"] = Field(
        "get_miniflux_categories",
        json_schema_extra={
            "const": "get_miniflux_categories",
            "ui:hidden": True,
            "x-category": "Miniflux Category",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Categories",
        },
        title="Get Miniflux Categories",
    )


class MinifluxUpdateCategoryConfig(BaseModel):
    """Update a category."""

    model_config = ConfigDict(title="Miniflux Update Category")

    operation: Literal["update_miniflux_category"] = Field(
        "update_miniflux_category",
        json_schema_extra={
            "const": "update_miniflux_category",
            "ui:hidden": True,
            "x-category": "Miniflux Category",
            "x-is-trigger": False,
            "x-display-name": "Update Miniflux Category",
        },
        title="Update Miniflux Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="ID of the category to update"
    )
    title: str = Field(
        ..., title="New Title", description="New name for the category", min_length=1
    )


class MinifluxDeleteCategoryConfig(BaseModel):
    """Delete a category."""

    model_config = ConfigDict(title="Miniflux Delete Category")

    operation: Literal["delete_miniflux_category"] = Field(
        "delete_miniflux_category",
        json_schema_extra={
            "const": "delete_miniflux_category",
            "ui:hidden": True,
            "x-category": "Miniflux Category",
            "x-is-trigger": False,
            "x-display-name": "Delete Miniflux Category",
        },
        title="Delete Miniflux Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="ID of the category to delete"
    )


class MinifluxExportOPMLConfig(BaseModel):
    """Export all subscriptions as OPML."""

    model_config = ConfigDict(title="Miniflux Export OPML")

    operation: Literal["export_miniflux_subscriptions_as_opml"] = Field(
        "export_miniflux_subscriptions_as_opml",
        json_schema_extra={
            "const": "export_miniflux_subscriptions_as_opml",
            "ui:hidden": True,
            "x-category": "Miniflux Account",
            "x-is-trigger": False,
            "x-display-name": "Export Miniflux Subscriptions As Opml",
        },
        title="Export Miniflux Subscriptions As Opml",
    )


class MinifluxImportOPMLConfig(BaseModel):
    """Import subscriptions from OPML file content."""

    model_config = ConfigDict(title="Miniflux Import OPML")

    operation: Literal["import_miniflux_subscriptions_from_opml"] = Field(
        "import_miniflux_subscriptions_from_opml",
        json_schema_extra={
            "const": "import_miniflux_subscriptions_from_opml",
            "ui:hidden": True,
            "x-category": "Miniflux Account",
            "x-is-trigger": False,
            "x-display-name": "Import Miniflux Subscriptions from Opml",
        },
        title="Import Miniflux Subscriptions from Opml",
    )
    opml_content: str = Field(
        ...,
        title="OPML Content",
        description="OPML XML file content to import",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MinifluxGetCurrentUserConfig(BaseModel):
    """Get current user information."""

    operation: Literal["get_miniflux_current_user"] = Field(
        "get_miniflux_current_user",
        json_schema_extra={
            "const": "get_miniflux_current_user",
            "ui:hidden": True,
            "x-category": "Miniflux Account",
            "x-is-trigger": False,
            "x-display-name": "Get Miniflux Current User",
        },
        title="Get Miniflux Current User",
    )


class MinifluxCreateAPIKeyConfig(BaseModel):
    """Create a new API key."""

    operation: Literal["create_miniflux_api_key"] = Field(
        "create_miniflux_api_key",
        json_schema_extra={
            "const": "create_miniflux_api_key",
            "ui:hidden": True,
            "x-category": "Miniflux Account",
            "x-is-trigger": False,
            "x-display-name": "Create Miniflux Api Key",
        },
        title="Create Miniflux Api Key",
    )
    label: str = Field(
        ...,
        title="API Key Label",
        description="Description for the API key",
        min_length=1,
    )


# ============================================================================
# Feedly Operations (20+ operations)
# ============================================================================


class FeedlyGetStreamContentsConfig(BaseModel):
    """Get articles from a Feedly stream."""

    model_config = ConfigDict(title="Feedly Get Stream Contents")

    operation: Literal["get_feedly_stream_articles"] = Field(
        "get_feedly_stream_articles",
        json_schema_extra={
            "const": "get_feedly_stream_articles",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Feedly Stream Articles",
        },
        title="Get Feedly Stream Articles",
    )
    stream_id: str = Field(
        ...,
        title="Stream ID",
        description="Stream ID (e.g., feed/https://example.com/feed.xml, user/xxx/category/tech)",
        json_schema_extra={"placeholder": "feed/https://example.com/feed.xml"},
    )
    count: int = Field(
        20, title="Count", description="Number of articles to retrieve", ge=1, le=1000
    )
    unread_only: bool = Field(
        False, title="Unread Only", description="Return only unread articles"
    )


class FeedlySearchFeedsConfig(BaseModel):
    """Search for feeds by query."""

    operation: Literal["search_feedly_feeds"] = Field(
        "search_feedly_feeds",
        json_schema_extra={
            "const": "search_feedly_feeds",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Search Feedly Feeds",
        },
        title="Search Feedly Feeds",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Search term or URL to find feeds",
        min_length=1,
    )
    count: int = Field(
        20, title="Count", description="Number of results to return", ge=1, le=100
    )


class FeedlyGetSubscriptionsConfig(BaseModel):
    """Get all feed subscriptions."""

    model_config = ConfigDict(title="Feedly Get Subscriptions")

    operation: Literal["get_feedly_subscriptions"] = Field(
        "get_feedly_subscriptions",
        json_schema_extra={
            "const": "get_feedly_subscriptions",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Feedly Subscriptions",
        },
        title="Get Feedly Subscriptions",
    )


class FeedlySubscribeFeedConfig(BaseModel):
    """Subscribe to a feed."""

    model_config = ConfigDict(title="Feedly Subscribe to Feed")

    operation: Literal["subscribe_to_feedly_feed"] = Field(
        "subscribe_to_feedly_feed",
        json_schema_extra={
            "const": "subscribe_to_feedly_feed",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Subscribe to Feedly Feed",
        },
        title="Subscribe to Feedly Feed",
    )
    feed_id: str = Field(
        ...,
        title="Feed ID",
        description="Feed ID to subscribe to (e.g., feed/https://example.com/feed.xml)",
        json_schema_extra={"placeholder": "feed/https://example.com/feed.xml"},
    )
    title: Optional[str] = Field(
        None, title="Title (Optional)", description="Custom title for the subscription"
    )
    categories: Optional[List[str]] = Field(
        None,
        title="Categories (Optional)",
        description="Category names to add the feed to",
    )


class FeedlyUnsubscribeFeedConfig(BaseModel):
    """Unsubscribe from a feed."""

    model_config = ConfigDict(title="Feedly Unsubscribe from Feed")

    operation: Literal["unsubscribe_from_feedly_feed"] = Field(
        "unsubscribe_from_feedly_feed",
        json_schema_extra={
            "const": "unsubscribe_from_feedly_feed",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Unsubscribe from Feedly Feed",
        },
        title="Unsubscribe from Feedly Feed",
    )
    feed_id: str = Field(
        ..., title="Feed ID", description="Feed ID to unsubscribe from"
    )


class FeedlyGetArticleConfig(BaseModel):
    """Get a specific article by ID."""

    operation: Literal["get_feedly_article"] = Field(
        "get_feedly_article",
        json_schema_extra={
            "const": "get_feedly_article",
            "ui:hidden": True,
            "x-category": "Feedly Article",
            "x-is-trigger": False,
            "x-display-name": "Get Feedly Article",
        },
        title="Get Feedly Article",
    )
    entry_id: str = Field(..., title="Entry ID", description="Article entry ID")


class FeedlyMarkArticlesReadConfig(BaseModel):
    """Mark articles as read."""

    operation: Literal["mark_feedly_articles_read"] = Field(
        "mark_feedly_articles_read",
        json_schema_extra={
            "const": "mark_feedly_articles_read",
            "ui:hidden": True,
            "x-category": "Feedly Feed and Subscription",
            "x-is-trigger": False,
            "x-display-name": "Mark Feedly Articles Read",
        },
        title="Mark Feedly Articles Read",
    )
    entry_ids: List[str] = Field(
        ...,
        title="Entry IDs",
        description="List of article IDs to mark as read",
        min_length=1,
    )


class FeedlyGetProfileConfig(BaseModel):
    """Get user profile information."""

    operation: Literal["get_feedly_user_profile"] = Field(
        "get_feedly_user_profile",
        json_schema_extra={
            "const": "get_feedly_user_profile",
            "ui:hidden": True,
            "x-category": "Feedly User",
            "x-is-trigger": False,
            "x-display-name": "Get Feedly User Profile",
        },
        title="Get Feedly User Profile",
    )


class FeedlyGetTagsConfig(BaseModel):
    """Get all user tags."""

    model_config = ConfigDict(title="Feedly Get Tags")

    operation: Literal["get_feedly_user_tags"] = Field(
        "get_feedly_user_tags",
        json_schema_extra={
            "const": "get_feedly_user_tags",
            "ui:hidden": True,
            "x-category": "Feedly User",
            "x-is-trigger": False,
            "x-display-name": "Get Feedly User Tags",
        },
        title="Get Feedly User Tags",
    )


class FeedlyTagEntryConfig(BaseModel):
    """Add tags to an article."""

    operation: Literal["add_tags_to_feedly_article"] = Field(
        "add_tags_to_feedly_article",
        json_schema_extra={
            "const": "add_tags_to_feedly_article",
            "ui:hidden": True,
            "x-category": "Feedly Article",
            "x-is-trigger": False,
            "x-display-name": "Add Tags to Feedly Article",
        },
        title="Add Tags to Feedly Article",
    )
    entry_id: str = Field(..., title="Entry ID", description="Article entry ID to tag")
    tags: List[str] = Field(
        ..., title="Tags", description="Tag names to add", min_length=1
    )


class FeedlySearchContentConfig(BaseModel):
    """Search articles in Feedly."""

    operation: Literal["search_feedly_articles"] = Field(
        "search_feedly_articles",
        json_schema_extra={
            "const": "search_feedly_articles",
            "ui:hidden": True,
            "x-category": "Feedly Article",
            "x-is-trigger": False,
            "x-display-name": "Search Feedly Articles",
        },
        title="Search Feedly Articles",
    )
    query: str = Field(
        ..., title="Search Query", description="Search keywords", min_length=1
    )
    count: int = Field(20, title="Count", description="Number of results", ge=1, le=100)


# ============================================================================
# FreshRSS Operations (15+ operations)
# ============================================================================


class FreshRSSGetSubscriptionsConfig(BaseModel):
    """Get all feed subscriptions."""

    model_config = ConfigDict(title="FreshRSS Get Subscriptions")

    operation: Literal["get_freshrss_subscriptions"] = Field(
        "get_freshrss_subscriptions",
        json_schema_extra={
            "const": "get_freshrss_subscriptions",
            "ui:hidden": True,
            "x-category": "FreshRSS Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Freshrss Subscriptions",
        },
        title="Get Freshrss Subscriptions",
    )


class FreshRSSSubscribeFeedConfig(BaseModel):
    """Subscribe to a feed."""

    operation: Literal["subscribe_to_freshrss_feed"] = Field(
        "subscribe_to_freshrss_feed",
        json_schema_extra={
            "const": "subscribe_to_freshrss_feed",
            "ui:hidden": True,
            "x-category": "FreshRSS Subscription",
            "x-is-trigger": False,
            "x-display-name": "Subscribe to Freshrss Feed",
        },
        title="Subscribe to Freshrss Feed",
    )
    feed_url: str = Field(
        ...,
        title="Feed URL",
        description="URL of the feed to subscribe to",
        json_schema_extra={"placeholder": "https://example.com/feed.xml"},
    )


class FreshRSSUnsubscribeFeedConfig(BaseModel):
    """Unsubscribe from a feed."""

    operation: Literal["unsubscribe_from_freshrss_feed"] = Field(
        "unsubscribe_from_freshrss_feed",
        json_schema_extra={
            "const": "unsubscribe_from_freshrss_feed",
            "ui:hidden": True,
            "x-category": "FreshRSS Subscription",
            "x-is-trigger": False,
            "x-display-name": "Unsubscribe from Freshrss Feed",
        },
        title="Unsubscribe from Freshrss Feed",
    )
    feed_id: str = Field(
        ..., title="Feed ID", description="Feed ID to unsubscribe from"
    )


class FreshRSSGetUnreadCountConfig(BaseModel):
    """Get unread article counts."""

    operation: Literal["get_freshrss_unread_counts"] = Field(
        "get_freshrss_unread_counts",
        json_schema_extra={
            "const": "get_freshrss_unread_counts",
            "ui:hidden": True,
            "x-category": "FreshRSS Article",
            "x-is-trigger": False,
            "x-display-name": "Get Freshrss Unread Counts",
        },
        title="Get Freshrss Unread Counts",
    )


class FreshRSSGetStreamContentsConfig(BaseModel):
    """Get articles from a stream."""

    operation: Literal["get_freshrss_stream_articles"] = Field(
        "get_freshrss_stream_articles",
        json_schema_extra={
            "const": "get_freshrss_stream_articles",
            "ui:hidden": True,
            "x-category": "FreshRSS Article",
            "x-is-trigger": False,
            "x-display-name": "Get Freshrss Stream Articles",
        },
        title="Get Freshrss Stream Articles",
    )
    stream_id: str = Field(
        "user/-/state/com.google/reading-list",
        title="Stream ID",
        description="Stream ID (user/-/state/com.google/reading-list for all, feed/... for specific feed)",
    )
    count: int = Field(
        20, title="Count", description="Number of articles to retrieve", ge=1, le=1000
    )
    exclude_read: bool = Field(
        False, title="Exclude Read", description="Only return unread articles"
    )


class FreshRSSMarkAsReadConfig(BaseModel):
    """Mark articles as read."""

    operation: Literal["mark_freshrss_articles_read"] = Field(
        "mark_freshrss_articles_read",
        json_schema_extra={
            "const": "mark_freshrss_articles_read",
            "ui:hidden": True,
            "x-category": "FreshRSS Article",
            "x-is-trigger": False,
            "x-display-name": "Mark Freshrss Articles Read",
        },
        title="Mark Freshrss Articles Read",
    )
    item_ids: List[str] = Field(
        ...,
        title="Item IDs",
        description="List of item IDs to mark as read",
        min_length=1,
    )


class FreshRSSGetTagsConfig(BaseModel):
    """Get all tags/labels."""

    model_config = ConfigDict(title="FreshRSS Get Tags")

    operation: Literal["get_freshrss_tags"] = Field(
        "get_freshrss_tags",
        json_schema_extra={
            "const": "get_freshrss_tags",
            "ui:hidden": True,
            "x-category": "FreshRSS Tag",
            "x-is-trigger": False,
            "x-display-name": "Get Freshrss Tags",
        },
        title="Get Freshrss Tags",
    )


# ============================================================================
# RSS.app Operations (10+ operations)
# ============================================================================


class RSSAppCreateFeedConfig(BaseModel):
    """Create a new RSS feed from a URL."""

    model_config = ConfigDict(title="RSS.app Create Feed")

    operation: Literal["create_rssapp_feed"] = Field(
        "create_rssapp_feed",
        json_schema_extra={
            "const": "create_rssapp_feed",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "Create Rssapp Feed",
        },
        title="Create Rssapp Feed",
    )
    url: str = Field(
        ...,
        title="Source URL",
        description="URL to generate RSS feed from",
        json_schema_extra={"placeholder": "https://example.com"},
    )
    name: Optional[str] = Field(
        None, title="Feed Name (Optional)", description="Custom name for the feed"
    )


class RSSAppGetFeedConfig(BaseModel):
    """Get a specific feed by ID."""

    model_config = ConfigDict(title="RSS.app Get Feed")

    operation: Literal["get_rssapp_feed"] = Field(
        "get_rssapp_feed",
        json_schema_extra={
            "const": "get_rssapp_feed",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Rssapp Feed",
        },
        title="Get Rssapp Feed",
    )
    feed_id: str = Field(..., title="Feed ID", description="ID of the feed to retrieve")


class RSSAppListFeedsConfig(BaseModel):
    """List all feeds."""

    model_config = ConfigDict(title="RSS.app List Feeds")

    operation: Literal["list_rssapp_feeds"] = Field(
        "list_rssapp_feeds",
        json_schema_extra={
            "const": "list_rssapp_feeds",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "List Rssapp Feeds",
        },
        title="List Rssapp Feeds",
    )
    limit: int = Field(
        50, title="Limit", description="Number of feeds to return", ge=1, le=100
    )
    offset: int = Field(0, title="Offset", description="Number of feeds to skip", ge=0)


class RSSAppUpdateFeedConfig(BaseModel):
    """Update a feed."""

    model_config = ConfigDict(title="RSS.app Update Feed")

    operation: Literal["update_rssapp_feed"] = Field(
        "update_rssapp_feed",
        json_schema_extra={
            "const": "update_rssapp_feed",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "Update Rssapp Feed",
        },
        title="Update Rssapp Feed",
    )
    feed_id: str = Field(..., title="Feed ID", description="ID of the feed to update")
    name: Optional[str] = Field(
        None, title="New Name (Optional)", description="New name for the feed"
    )


class RSSAppDeleteFeedConfig(BaseModel):
    """Delete a feed."""

    model_config = ConfigDict(title="RSS.app Delete Feed")

    operation: Literal["delete_rssapp_feed"] = Field(
        "delete_rssapp_feed",
        json_schema_extra={
            "const": "delete_rssapp_feed",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "Delete Rssapp Feed",
        },
        title="Delete Rssapp Feed",
    )
    feed_id: str = Field(..., title="Feed ID", description="ID of the feed to delete")


class RSSAppGetFeedItemsConfig(BaseModel):
    """Get items from a feed."""

    operation: Literal["get_rssapp_feed_items"] = Field(
        "get_rssapp_feed_items",
        json_schema_extra={
            "const": "get_rssapp_feed_items",
            "ui:hidden": True,
            "x-category": "RSSApp Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Rssapp Feed Items",
        },
        title="Get Rssapp Feed Items",
    )
    feed_id: str = Field(..., title="Feed ID", description="ID of the feed")
    limit: int = Field(
        20, title="Limit", description="Number of items to return", ge=1, le=100
    )


# ============================================================================
# Combined Configuration Union
# ============================================================================

RSSConfig = Annotated[
    Union[
        # Direct Feed Parsing (1 operation)
        RSSParseFeedConfig,
        # Miniflux Operations (23 operations)
        MinifluxDiscoverFeedConfig,
        MinifluxCreateFeedConfig,
        MinifluxGetFeedsConfig,
        MinifluxGetFeedConfig,
        MinifluxUpdateFeedConfig,
        MinifluxDeleteFeedConfig,
        MinifluxRefreshFeedConfig,
        MinifluxRefreshAllFeedsConfig,
        MinifluxGetEntriesConfig,
        MinifluxGetFeedEntriesConfig,
        MinifluxGetEntryConfig,
        MinifluxToggleBookmarkConfig,
        MinifluxMarkEntriesReadConfig,
        MinifluxMarkAllReadConfig,
        MinifluxCreateCategoryConfig,
        MinifluxGetCategoriesConfig,
        MinifluxUpdateCategoryConfig,
        MinifluxDeleteCategoryConfig,
        MinifluxExportOPMLConfig,
        MinifluxImportOPMLConfig,
        MinifluxGetCurrentUserConfig,
        MinifluxCreateAPIKeyConfig,
        # Feedly Operations (11 operations)
        FeedlyGetStreamContentsConfig,
        FeedlySearchFeedsConfig,
        FeedlyGetSubscriptionsConfig,
        FeedlySubscribeFeedConfig,
        FeedlyUnsubscribeFeedConfig,
        FeedlyGetArticleConfig,
        FeedlyMarkArticlesReadConfig,
        FeedlyGetProfileConfig,
        FeedlyGetTagsConfig,
        FeedlyTagEntryConfig,
        FeedlySearchContentConfig,
        # FreshRSS Operations (7 operations)
        FreshRSSGetSubscriptionsConfig,
        FreshRSSSubscribeFeedConfig,
        FreshRSSUnsubscribeFeedConfig,
        FreshRSSGetUnreadCountConfig,
        FreshRSSGetStreamContentsConfig,
        FreshRSSMarkAsReadConfig,
        FreshRSSGetTagsConfig,
        # RSS.app Operations (6 operations)
        RSSAppCreateFeedConfig,
        RSSAppGetFeedConfig,
        RSSAppListFeedsConfig,
        RSSAppUpdateFeedConfig,
        RSSAppDeleteFeedConfig,
        RSSAppGetFeedItemsConfig,
    ],
    Discriminator("operation"),
]


class RSSNodeConfig(NodeConfig[RSSConfig, RSSCredential]):
    """Full configuration for RSS node including credentials"""

    pass


# ============================================================================
# RSS Node Implementation
# ============================================================================


class RSSNode(WorkflowNode):
    """RSS workflow node implementation"""

    edit_examples = [
        "Parse a feed from TechCrunch and only return new articles",
        "Get all feeds from Miniflux and list them by creation date",
        "Subscribe to a Feedly stream for AI news and retrieve recent articles",
        "Export all RSS subscriptions from Miniflux as OPML backup",
        "Mark unread entries as read in FreshRSS from this month",
        "Create new RSS feeds from multiple URLs in Miniflux",
        "Get trending topics from RSS feeds and search by tags",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return RSSNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the RSS node"""
        logger.info(f"[RSSNode] Executing node {self.node_id}")
        start_time = time.time()

        # Get config
        node_config = self.config
        if not node_config or not isinstance(node_config, RSSNodeConfig):
            raise ValueError(
                f"[RSSNode] Configuration is required for node {self.node_id}"
            )

        config = node_config.config
        credentials = node_config.credentials
        action = config.operation

        try:
            # Provider routing. Op renames stripped the per-provider prefix
            # (`feedly_*`, `miniflux_*`, etc.) from many op names, so prefix
            # matching no longer works. Substring routing on the new names is
            # safe (no cross-provider collisions); `discover_rss_feeds_from_website`
            # is the one renamed miniflux op without "miniflux" in its new name.
            MINIFLUX_EXTRAS = {"discover_rss_feeds_from_website"}

            if action == "parse_rss_atom_feed":
                output = await self._parse_feed(config, credentials)

            elif "miniflux" in action or action in MINIFLUX_EXTRAS:
                if not credentials or not isinstance(
                    credentials, RSSMinifluxCredential
                ):
                    raise ValueError("Miniflux credentials required for this operation")
                output = await self._execute_miniflux(config, credentials)

            elif "feedly" in action:
                if not credentials or not isinstance(credentials, RSSFeedlyCredential):
                    raise ValueError("Feedly credentials required for this operation")
                output = await self._execute_feedly(config, credentials)

            elif "freshrss" in action:
                if not credentials or not isinstance(
                    credentials, RSSFreshRSSCredential
                ):
                    raise ValueError("FreshRSS credentials required for this operation")
                output = await self._execute_freshrss(config, credentials)

            elif "rssapp" in action:
                if not credentials or not isinstance(credentials, RSSAppCredential):
                    raise ValueError("RSS.app credentials required for this operation")
                output = await self._execute_rssapp(config, credentials)

            else:
                raise ValueError(f"Unknown action: {action}")

            # Add timing and metadata
            timing_ms = (time.time() - start_time) * 1000
            output.update(
                {
                    "type": "rss",
                    "action": action,
                    "status": "success",
                    "timing_ms": round(timing_ms, 2),
                    "timestamp": time.time(),
                }
            )

            return output

        except Exception as e:
            timing_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            logger.error(f"[RSSNode] Error in action {action}: {error_msg}")
            return {
                "type": "rss",
                "action": action,
                "status": "error",
                "error": error_msg,
                "timing_ms": round(timing_ms, 2),
                "timestamp": time.time(),
            }

    # ========================================================================
    # Direct Feed Parsing
    # ========================================================================

    async def _parse_feed(
        self, config: RSSParseFeedConfig, credentials: Optional[RSSCredential]
    ) -> Dict[str, Any]:
        """Parse RSS/Atom feed directly. Supports multiple feed URLs — results are merged."""
        kwargs = {}

        if (
            config.use_credentials
            and credentials
            and isinstance(credentials, RSSDirectCredential)
        ):
            if credentials.username and credentials.password:
                kwargs["username"] = credentials.username
                kwargs["password"] = credentials.password
            if credentials.api_key:
                kwargs["api_key"] = credentials.api_key
            if credentials.custom_headers:
                kwargs["custom_headers"] = credentials.custom_headers
            kwargs["allowed_origin"] = credentials.allowed_origin

        feed_urls = _parse_feed_urls(config.feed_url)
        if not feed_urls:
            raise ValueError("No valid feed URL(s) provided")
        if len(feed_urls) == 1:
            result = await parse_rss_feed_direct(feed_urls[0], **kwargs)
        else:
            # Merge entries from all feeds
            all_entries: list = []
            result = {}
            for url in feed_urls:
                feed_result = await parse_rss_feed_direct(url, **kwargs)
                all_entries.extend(feed_result.get("entries", []))
                if not result:
                    result = feed_result
            result["entries"] = all_entries
            result["entry_count"] = len(all_entries)

        # Apply "only new items" filtering if enabled
        if str(config.only_new_items).lower() == "true":
            result = await self._filter_new_items(result)

        return result

    async def _filter_new_items(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Filter feed entries to only those not seen on a previous run.

        RSS "only new items" is an ON-DEMAND ACTION, not a scheduled trigger, so
        it deliberately does NOT baseline: the first run returns ALL current
        entries (there's no prior run to diff against, and a user asking for
        "new items" expects the feed the first time). Later runs return only
        entries whose id hasn't been seen. The seen-set is compare-and-swapped in
        node state (``_update_node_state``), so overlapping runs on different
        containers can't clobber each other's set — replacing the old in-process
        lock, which only serialized within a single process.
        """
        entries = result.get("entries", [])
        if not entries:
            return result

        # Unique identifier per entry (prefer id/guid, fallback to link+title hash).
        def get_entry_id(entry: Dict[str, Any]) -> str:
            if entry.get("id"):
                return str(entry["id"])
            if entry.get("guid"):
                return str(entry["guid"])
            link = entry.get("link", "")
            title = entry.get("title", "")
            return hashlib.md5(f"{link}:{title}".encode()).hexdigest()

        # Compute ids once (pure) so the mutator is re-runnable on CAS retry.
        entry_ids = [(get_entry_id(e), e) for e in entries]

        def mutator(state):
            seen_list = state.get("seen_item_ids", [])
            seen_ids = set(seen_list)
            new_entries = []
            new_ids = set()
            for eid, entry in entry_ids:
                if eid not in seen_ids:
                    new_entries.append(entry)
                    new_ids.add(eid)
            if not new_ids:
                return None, ([], len(seen_ids))
            # Order-preserving, bounded: this poll's ids move to the end, so
            # truncation drops the least-recently-seen items, not arbitrary ones.
            all_seen = bounded_seen_ids(seen_list, [eid for eid, _ in entry_ids])
            return {"seen_item_ids": all_seen}, (new_entries, len(seen_ids))

        new_entries, prev_seen_count = await self._update_node_state(
            mutator, skip_result=([], 0)
        )

        logger.info(
            f"[RSSNode] Filtered to {len(new_entries)} new items (from {len(entries)} total, {prev_seen_count} previously seen)"
        )

        return {
            **result,
            "entries": new_entries,
            "entry_count": len(new_entries),
            "total_in_feed": len(entries),
            "filtered_count": len(entries) - len(new_entries),
        }

    # ========================================================================
    # Miniflux Operations
    # ========================================================================

    async def _execute_miniflux(
        self, config, credentials: RSSMinifluxCredential
    ) -> Dict[str, Any]:
        """Execute Miniflux API operations."""
        base_url = credentials.server_url.rstrip("/")
        headers = {"X-Auth-Token": credentials.api_token}

        async with guarded_async_client() as client:
            if isinstance(config, MinifluxDiscoverFeedConfig):
                response = await client.post(
                    f"{base_url}/v1/discover",
                    headers=headers,
                    json={"url": config.website_url},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"feeds": response.json()}

            elif isinstance(config, MinifluxCreateFeedConfig):
                payload = {"feed_url": config.feed_url}
                if config.category_id:
                    payload["category_id"] = config.category_id
                response = await client.post(
                    f"{base_url}/v1/feeds", headers=headers, json=payload, timeout=30.0
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, MinifluxGetFeedsConfig):
                response = await client.get(
                    f"{base_url}/v1/feeds", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                feeds = response.json()
                return {"feeds": feeds, "count": len(feeds)}

            elif isinstance(config, MinifluxGetFeedConfig):
                response = await client.get(
                    f"{base_url}/v1/feeds/{config.feed_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, MinifluxUpdateFeedConfig):
                payload = {}
                if config.title:
                    payload["title"] = config.title
                if config.category_id:
                    payload["category_id"] = config.category_id
                response = await client.put(
                    f"{base_url}/v1/feeds/{config.feed_id}",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, MinifluxDeleteFeedConfig):
                response = await client.delete(
                    f"{base_url}/v1/feeds/{config.feed_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"deleted": True, "feed_id": config.feed_id}

            elif isinstance(config, MinifluxRefreshFeedConfig):
                response = await client.put(
                    f"{base_url}/v1/feeds/{config.feed_id}/refresh",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"refreshed": True, "feed_id": config.feed_id}

            elif isinstance(config, MinifluxRefreshAllFeedsConfig):
                response = await client.put(
                    f"{base_url}/v1/feeds/refresh", headers=headers, timeout=60.0
                )
                response.raise_for_status()
                return {"refreshed": True, "all_feeds": True}

            elif isinstance(config, MinifluxGetEntriesConfig):
                params = {"limit": config.limit, "offset": config.offset}
                if config.status:
                    params["status"] = config.status
                if config.starred is not None:
                    params["starred"] = str(config.starred).lower()
                response = await client.get(
                    f"{base_url}/v1/entries",
                    headers=headers,
                    params=params,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "entries": data.get("entries", []),
                    "total": data.get("total", 0),
                }

            elif isinstance(config, MinifluxGetFeedEntriesConfig):
                response = await client.get(
                    f"{base_url}/v1/feeds/{config.feed_id}/entries",
                    headers=headers,
                    params={"limit": config.limit},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "entries": data.get("entries", []),
                    "total": data.get("total", 0),
                }

            elif isinstance(config, MinifluxGetEntryConfig):
                response = await client.get(
                    f"{base_url}/v1/entries/{config.entry_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"entry": response.json()}

            elif isinstance(config, MinifluxToggleBookmarkConfig):
                response = await client.put(
                    f"{base_url}/v1/entries/{config.entry_id}/bookmark",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"toggled": True, "entry_id": config.entry_id}

            elif isinstance(config, MinifluxMarkEntriesReadConfig):
                response = await client.put(
                    f"{base_url}/v1/entries",
                    headers=headers,
                    json={"entry_ids": config.entry_ids, "status": "read"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"marked_read": True, "count": len(config.entry_ids)}

            elif isinstance(config, MinifluxMarkAllReadConfig):
                response = await client.put(
                    f"{base_url}/v1/mark-all-as-read", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"marked_all_read": True}

            elif isinstance(config, MinifluxCreateCategoryConfig):
                response = await client.post(
                    f"{base_url}/v1/categories",
                    headers=headers,
                    json={"title": config.title},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"category": response.json()}

            elif isinstance(config, MinifluxGetCategoriesConfig):
                response = await client.get(
                    f"{base_url}/v1/categories", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                categories = response.json()
                return {"categories": categories, "count": len(categories)}

            elif isinstance(config, MinifluxUpdateCategoryConfig):
                response = await client.put(
                    f"{base_url}/v1/categories/{config.category_id}",
                    headers=headers,
                    json={"title": config.title},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"category": response.json()}

            elif isinstance(config, MinifluxDeleteCategoryConfig):
                response = await client.delete(
                    f"{base_url}/v1/categories/{config.category_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"deleted": True, "category_id": config.category_id}

            elif isinstance(config, MinifluxExportOPMLConfig):
                response = await client.get(
                    f"{base_url}/v1/export", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"opml": response.text}

            elif isinstance(config, MinifluxImportOPMLConfig):
                response = await client.post(
                    f"{base_url}/v1/import",
                    headers=headers,
                    files={
                        "file": ("import.opml", config.opml_content, "application/xml")
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                return {
                    "imported": True,
                    "message": response.json().get("message", "Import successful"),
                }

            elif isinstance(config, MinifluxGetCurrentUserConfig):
                response = await client.get(
                    f"{base_url}/v1/me", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"user": response.json()}

            elif isinstance(config, MinifluxCreateAPIKeyConfig):
                response = await client.post(
                    f"{base_url}/v1/me/api-keys",
                    headers=headers,
                    json={"label": config.label},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"api_key": response.json()}

    # ========================================================================
    # Feedly Operations
    # ========================================================================

    async def _execute_feedly(
        self, config, credentials: RSSFeedlyCredential
    ) -> Dict[str, Any]:
        """Execute Feedly API operations."""
        base_url = "https://cloud.feedly.com/v3"
        headers = {"Authorization": f"Bearer {credentials.access_token}"}

        async with httpx.AsyncClient() as client:
            if isinstance(config, FeedlyGetStreamContentsConfig):
                params = {"count": config.count}
                if config.unread_only:
                    params["unreadOnly"] = "true"
                response = await client.get(
                    f"{base_url}/streams/contents",
                    headers=headers,
                    params={"streamId": config.stream_id, **params},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "items": data.get("items", []),
                    "continuation": data.get("continuation"),
                    "count": len(data.get("items", [])),
                }

            elif isinstance(config, FeedlySearchFeedsConfig):
                response = await client.get(
                    f"{base_url}/search/feeds",
                    headers=headers,
                    params={"query": config.query, "count": config.count},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "results": data.get("results", []),
                    "count": len(data.get("results", [])),
                }

            elif isinstance(config, FeedlyGetSubscriptionsConfig):
                response = await client.get(
                    f"{base_url}/subscriptions", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                subscriptions = response.json()
                return {"subscriptions": subscriptions, "count": len(subscriptions)}

            elif isinstance(config, FeedlySubscribeFeedConfig):
                payload = {"id": config.feed_id}
                if config.title:
                    payload["title"] = config.title
                if config.categories:
                    payload["categories"] = [
                        {"label": cat} for cat in config.categories
                    ]
                response = await client.post(
                    f"{base_url}/subscriptions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"subscription": response.json()}

            elif isinstance(config, FeedlyUnsubscribeFeedConfig):
                response = await client.delete(
                    f"{base_url}/subscriptions/{config.feed_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"unsubscribed": True, "feed_id": config.feed_id}

            elif isinstance(config, FeedlyGetArticleConfig):
                response = await client.get(
                    f"{base_url}/entries/{config.entry_id}",
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"article": response.json()}

            elif isinstance(config, FeedlyMarkArticlesReadConfig):
                response = await client.post(
                    f"{base_url}/markers",
                    headers=headers,
                    json={
                        "action": "markAsRead",
                        "type": "entries",
                        "entryIds": config.entry_ids,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"marked_read": True, "count": len(config.entry_ids)}

            elif isinstance(config, FeedlyGetProfileConfig):
                response = await client.get(
                    f"{base_url}/profile", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"profile": response.json()}

            elif isinstance(config, FeedlyGetTagsConfig):
                response = await client.get(
                    f"{base_url}/tags", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                tags = response.json()
                return {"tags": tags, "count": len(tags)}

            elif isinstance(config, FeedlyTagEntryConfig):
                # Feedly doesn't have a direct tag entry endpoint
                # Instead, we'd use the markers API to add to a tag stream
                return {
                    "message": "Tagging in Feedly requires using tag streams",
                    "entry_id": config.entry_id,
                    "tags": config.tags,
                }

            elif isinstance(config, FeedlySearchContentConfig):
                response = await client.get(
                    f"{base_url}/search/contents",
                    headers=headers,
                    params={"query": config.query, "count": config.count},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "results": data.get("items", []),
                    "count": len(data.get("items", [])),
                }

    # ========================================================================
    # FreshRSS Operations
    # ========================================================================

    async def _execute_freshrss(
        self, config, credentials: RSSFreshRSSCredential
    ) -> Dict[str, Any]:
        """Execute FreshRSS API operations using Google Reader API compatibility."""
        base_url = credentials.server_url.rstrip("/") + "/api/greader.php"

        # Generate auth token
        api_key = generate_fever_api_key(credentials.username, credentials.api_password)

        # Authenticate and get session token
        async with guarded_async_client() as client:
            # Login to get Auth token
            auth_response = await client.post(
                base_url + "/accounts/ClientLogin",
                data={
                    "Email": credentials.username,
                    "Passwd": credentials.api_password,
                },
                timeout=30.0,
            )
            auth_response.raise_for_status()

            # Extract Auth token from response
            auth_token = None
            for line in auth_response.text.split("\n"):
                if line.startswith("Auth="):
                    auth_token = line.split("=", 1)[1]
                    break

            if not auth_token:
                raise ValueError("Failed to get authentication token from FreshRSS")

            headers = {"Authorization": f"GoogleLogin auth={auth_token}"}

            if isinstance(config, FreshRSSGetSubscriptionsConfig):
                response = await client.get(
                    base_url + "/subscription/list", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                subs = data.get("subscriptions", [])
                return {"subscriptions": subs, "count": len(subs)}

            elif isinstance(config, FreshRSSSubscribeFeedConfig):
                response = await client.post(
                    base_url + "/subscription/edit",
                    headers=headers,
                    data={"s": f"feed/{config.feed_url}", "ac": "subscribe"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"subscribed": True, "feed_url": config.feed_url}

            elif isinstance(config, FreshRSSUnsubscribeFeedConfig):
                response = await client.post(
                    base_url + "/subscription/edit",
                    headers=headers,
                    data={"s": config.feed_id, "ac": "unsubscribe"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"unsubscribed": True, "feed_id": config.feed_id}

            elif isinstance(config, FreshRSSGetUnreadCountConfig):
                response = await client.get(
                    base_url + "/unread-count", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return {"unread_counts": data.get("unreadcounts", [])}

            elif isinstance(config, FreshRSSGetStreamContentsConfig):
                params = {"s": config.stream_id, "n": config.count}
                if config.exclude_read:
                    params["xt"] = "user/-/state/com.google/read"
                response = await client.get(
                    base_url + "/stream/contents",
                    headers=headers,
                    params=params,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "items": data.get("items", []),
                    "continuation": data.get("continuation"),
                    "count": len(data.get("items", [])),
                }

            elif isinstance(config, FreshRSSMarkAsReadConfig):
                response = await client.post(
                    base_url + "/edit-tag",
                    headers=headers,
                    data={"i": config.item_ids, "a": "user/-/state/com.google/read"},
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"marked_read": True, "count": len(config.item_ids)}

            elif isinstance(config, FreshRSSGetTagsConfig):
                response = await client.get(
                    base_url + "/tag/list", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                tags = data.get("tags", [])
                return {"tags": tags, "count": len(tags)}

    # ========================================================================
    # RSS.app Operations
    # ========================================================================

    async def _execute_rssapp(
        self, config, credentials: RSSAppCredential
    ) -> Dict[str, Any]:
        """Execute RSS.app API operations."""
        base_url = "https://api.rss.app/v1"
        headers = {
            "X-API-Key": credentials.api_key,
            "X-Secret-Key": credentials.secret_key,
        }

        async with httpx.AsyncClient() as client:
            if isinstance(config, RSSAppCreateFeedConfig):
                payload = {"url": config.url}
                if config.name:
                    payload["name"] = config.name
                response = await client.post(
                    f"{base_url}/feeds", headers=headers, json=payload, timeout=30.0
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, RSSAppGetFeedConfig):
                response = await client.get(
                    f"{base_url}/feeds/{config.feed_id}", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, RSSAppListFeedsConfig):
                response = await client.get(
                    f"{base_url}/feeds",
                    headers=headers,
                    params={"limit": config.limit, "offset": config.offset},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {"feeds": data.get("feeds", []), "total": data.get("total", 0)}

            elif isinstance(config, RSSAppUpdateFeedConfig):
                payload = {}
                if config.name:
                    payload["name"] = config.name
                response = await client.patch(
                    f"{base_url}/feeds/{config.feed_id}",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                return {"feed": response.json()}

            elif isinstance(config, RSSAppDeleteFeedConfig):
                response = await client.delete(
                    f"{base_url}/feeds/{config.feed_id}", headers=headers, timeout=30.0
                )
                response.raise_for_status()
                return {"deleted": True, "feed_id": config.feed_id}

            elif isinstance(config, RSSAppGetFeedItemsConfig):
                response = await client.get(
                    f"{base_url}/feeds/{config.feed_id}/items",
                    headers=headers,
                    params={"limit": config.limit},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "items": data.get("items", []),
                    "count": len(data.get("items", [])),
                }

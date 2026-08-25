"""
Hacker News automation node implementation.

Provides comprehensive access to Hacker News data through two APIs:

1. Official Firebase API (https://hacker-news.firebaseio.com/v0):
   - Fetch items (stories, comments, polls, jobs) by ID
   - Get user profiles and submission history
   - List top, new, best, ask, show, and job stories
   - Get max item ID and recent updates

2. Algolia Search API (http://hn.algolia.com/api/v1):
   - Search stories, comments, and all content
   - Sort by relevance or date
   - Advanced filtering by tags and numeric fields

No authentication required - both APIs are public with no rate limits.

API Documentation:
- Firebase: https://github.com/HackerNews/API
- Algolia: https://hn.algolia.com/api
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# Base URLs for Hacker News APIs
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


# ============================================================================
# Hacker News Node Configuration Models
# ============================================================================


class HNGetItemConfig(BaseModel):
    """Config for fetching a single item (story, comment, job, poll) by ID"""

    operation: Literal["fetch_item_by_id"] = Field(
        default="fetch_item_by_id",
        json_schema_extra={
            "const": "fetch_item_by_id",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Fetch Item by Id",
        },
        title="Fetch Item by Id",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        title="Item ID",
        description="The numeric ID of the item to fetch (story, comment, job, or poll)",
        json_schema_extra={"placeholder": "8863"},
    )


class HNGetUserConfig(BaseModel):
    """Config for fetching a user profile by username"""

    operation: Literal["fetch_user_profile"] = Field(
        default="fetch_user_profile",
        json_schema_extra={
            "const": "fetch_user_profile",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Fetch User Profile",
        },
        title="Fetch User Profile",
    )
    username: str = Field(
        ...,
        min_length=1,
        title="Username",
        description="The case-sensitive username to look up",
        json_schema_extra={"placeholder": "pg"},
    )


class HNGetTopStoriesConfig(BaseModel):
    """Config for fetching top stories"""

    operation: Literal["fetch_top_stories"] = Field(
        default="fetch_top_stories",
        json_schema_extra={
            "const": "fetch_top_stories",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Top Stories",
        },
        title="Fetch Top Stories",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=500,
        title="Limit",
        description="Maximum number of stories to return (1-500)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full story details. If false, returns only IDs (faster).",
    )


class HNGetNewStoriesConfig(BaseModel):
    """Config for fetching newest stories"""

    operation: Literal["fetch_newest_stories"] = Field(
        default="fetch_newest_stories",
        json_schema_extra={
            "const": "fetch_newest_stories",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Newest Stories",
        },
        title="Fetch Newest Stories",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=500,
        title="Limit",
        description="Maximum number of stories to return (1-500)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full story details. If false, returns only IDs (faster).",
    )


class HNGetBestStoriesConfig(BaseModel):
    """Config for fetching best stories"""

    operation: Literal["fetch_best_stories"] = Field(
        default="fetch_best_stories",
        json_schema_extra={
            "const": "fetch_best_stories",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Best Stories",
        },
        title="Fetch Best Stories",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=500,
        title="Limit",
        description="Maximum number of stories to return (1-500)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full story details. If false, returns only IDs (faster).",
    )


class HNGetAskStoriesConfig(BaseModel):
    """Config for fetching Ask HN stories"""

    operation: Literal["fetch_ask_hn_stories"] = Field(
        default="fetch_ask_hn_stories",
        json_schema_extra={
            "const": "fetch_ask_hn_stories",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ask Hn Stories",
        },
        title="Fetch Ask Hn Stories",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=200,
        title="Limit",
        description="Maximum number of stories to return (1-200)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full story details. If false, returns only IDs (faster).",
    )


class HNGetShowStoriesConfig(BaseModel):
    """Config for fetching Show HN stories"""

    operation: Literal["fetch_show_hn_stories"] = Field(
        default="fetch_show_hn_stories",
        json_schema_extra={
            "const": "fetch_show_hn_stories",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Show Hn Stories",
        },
        title="Fetch Show Hn Stories",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=200,
        title="Limit",
        description="Maximum number of stories to return (1-200)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full story details. If false, returns only IDs (faster).",
    )


class HNGetJobStoriesConfig(BaseModel):
    """Config for fetching job postings"""

    operation: Literal["fetch_job_postings"] = Field(
        default="fetch_job_postings",
        json_schema_extra={
            "const": "fetch_job_postings",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Fetch Job Postings",
        },
        title="Fetch Job Postings",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=200,
        title="Limit",
        description="Maximum number of jobs to return (1-200)",
    )
    fetch_details: bool = Field(
        default=True,
        title="Fetch Full Details",
        description="If true, fetches full job details. If false, returns only IDs (faster).",
    )


class HNGetMaxItemConfig(BaseModel):
    """Config for fetching the current largest item ID"""

    operation: Literal["fetch_largest_item_id"] = Field(
        default="fetch_largest_item_id",
        json_schema_extra={
            "const": "fetch_largest_item_id",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Fetch Largest Item Id",
        },
        title="Fetch Largest Item Id",
    )


class HNGetUpdatesConfig(BaseModel):
    """Config for fetching changed items and profiles"""

    operation: Literal["fetch_changed_items_and_profiles"] = Field(
        default="fetch_changed_items_and_profiles",
        json_schema_extra={
            "const": "fetch_changed_items_and_profiles",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Fetch Changed Items and Profiles",
        },
        title="Fetch Changed Items and Profiles",
    )


class HNSearchConfig(BaseModel):
    """Config for Algolia search (sorted by relevance, then points, then comments)"""

    operation: Literal["search_by_relevance"] = Field(
        default="search_by_relevance",
        json_schema_extra={
            "const": "search_by_relevance",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search by Relevance",
        },
        title="Search by Relevance",
    )
    query: str = Field(
        default="",
        title="Search Query",
        description="Search query string (leave empty to get all items with specified tags)",
    )
    tags: Optional[str] = Field(
        None,
        title="Tags Filter",
        description="Filter by tags (e.g., 'story', 'ask_hn', 'show_hn', 'poll', 'comment', 'author_pg', 'story_8863'). ANDed by default, ORed if in parenthesis.",
    )
    page: int = Field(
        default=0,
        ge=0,
        title="Page Number",
        description="Page number for pagination (0-indexed)",
    )
    hits_per_page: int = Field(
        default=20,
        ge=1,
        le=1000,
        title="Results Per Page",
        description="Number of results per page (1-1000)",
    )
    numeric_filters: Optional[str] = Field(
        None,
        title="Numeric Filters",
        description="Numeric filters (e.g., 'created_at_i>1234567890' or 'points>100,num_comments<50')",
    )


class HNSearchByDateConfig(BaseModel):
    """Config for Algolia search sorted by date (most recent first)"""

    operation: Literal["search_by_recent_date"] = Field(
        default="search_by_recent_date",
        json_schema_extra={
            "const": "search_by_recent_date",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search by Recent Date",
        },
        title="Search by Recent Date",
    )
    query: str = Field(
        default="",
        title="Search Query",
        description="Search query string (leave empty to get all items with specified tags)",
    )
    tags: Optional[str] = Field(
        None,
        title="Tags Filter",
        description="Filter by tags (e.g., 'story', 'ask_hn', 'show_hn', 'poll', 'comment', 'author_pg', 'story_8863'). ANDed by default, ORed if in parenthesis.",
    )
    page: int = Field(
        default=0,
        ge=0,
        title="Page Number",
        description="Page number for pagination (0-indexed)",
    )
    hits_per_page: int = Field(
        default=20,
        ge=1,
        le=1000,
        title="Results Per Page",
        description="Number of results per page (1-1000)",
    )
    numeric_filters: Optional[str] = Field(
        None,
        title="Numeric Filters",
        description="Numeric filters (e.g., 'created_at_i>1234567890' or 'points>100,num_comments<50')",
    )


# Union of all operation configs
# Union of all operation configs
# Using Discriminator to ensure Pydantic only validates the matching config type
# based on the 'operation' field, preventing validation against all 12 union members
HackerNewsConfig = Annotated[
    Union[
        HNGetItemConfig,
        HNGetUserConfig,
        HNGetTopStoriesConfig,
        HNGetNewStoriesConfig,
        HNGetBestStoriesConfig,
        HNGetAskStoriesConfig,
        HNGetShowStoriesConfig,
        HNGetJobStoriesConfig,
        HNGetMaxItemConfig,
        HNGetUpdatesConfig,
        HNSearchConfig,
        HNSearchByDateConfig,
    ],
    Discriminator("operation"),
]


class HackerNewsNodeConfig(NodeConfig[HackerNewsConfig, None]):
    """Full configuration for Hacker News node (no credentials needed - public API)"""

    pass


# ============================================================================
# Hacker News Node Implementation
# ============================================================================


class HackerNewsNode(WorkflowNode):
    """
    Hacker News automation node.

    Provides access to both the official Hacker News Firebase API and Algolia Search API.

    Firebase API: Fetch items, users, story lists, updates, and max item ID.
    Algolia API: Search stories, comments, and all content by relevance or date.

    No authentication required - both APIs are public with no rate limits.
    """

    edit_examples = [
        "Get top 25 stories and fetch full details for each",
        "Search for posts tagged with PostgreSQL sorted by date",
        "Retrieve user profile and find all their recent submissions",
        "Get current job postings list with job details and permalinks",
        "Search for 'machine learning' comments and fetch 100 results",
        "Query Show HN stories with score > 100 from last 30 days",
        "Fetch Ask HN best posts and get replies to a specific comment",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Hacker News node"""
        return HackerNewsNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Hacker News API request.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing Hacker News data
        """
        logger.info(f"[HackerNewsNode] Executing node {self.node_id}")

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[HackerNewsNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, HackerNewsNodeConfig):
            raise ValueError(
                f"[HackerNewsNode] Invalid config type: {type(node_config)}, expected HackerNewsNodeConfig"
            )

        # Extract the operation config
        config = node_config.config

        # Route to appropriate handler based on operation type
        if isinstance(config, HNGetItemConfig):
            output = await self._get_item(config)
        elif isinstance(config, HNGetUserConfig):
            output = await self._get_user(config)
        elif isinstance(config, HNGetTopStoriesConfig):
            output = await self._get_stories(
                "topstories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetNewStoriesConfig):
            output = await self._get_stories(
                "newstories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetBestStoriesConfig):
            output = await self._get_stories(
                "beststories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetAskStoriesConfig):
            output = await self._get_stories(
                "askstories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetShowStoriesConfig):
            output = await self._get_stories(
                "showstories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetJobStoriesConfig):
            output = await self._get_stories(
                "jobstories", config.limit, config.fetch_details
            )
        elif isinstance(config, HNGetMaxItemConfig):
            output = await self._get_max_item()
        elif isinstance(config, HNGetUpdatesConfig):
            output = await self._get_updates()
        elif isinstance(config, HNSearchConfig):
            output = await self._search(config, sort_by_date=False)
        elif isinstance(config, HNSearchByDateConfig):
            output = await self._search(config, sort_by_date=True)
        else:
            raise ValueError(f"[HackerNewsNode] Unknown operation type: {type(config)}")

        # Emit output to frontend
        await self.emit(output)

        return output

    async def _fetch_json(self, url: str) -> Any:
        """Fetch JSON from URL with error handling"""
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()

    async def _get_item(self, config: HNGetItemConfig) -> Dict[str, Any]:
        """Fetch a single item by ID"""
        logger.info(f"[HackerNewsNode] Fetching item {config.item_id}")
        start_time = time.time()

        try:
            url = f"{HN_API_BASE}/item/{config.item_id}.json"
            item = await self._fetch_json(url)

            if item is None:
                return {
                    "type": "hackernews",
                    "operation": "fetch_item_by_id",
                    "status": "error",
                    "error": f"Item {config.item_id} not found",
                    "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": time.time(),
                }

            return {
                "type": "hackernews",
                "operation": "fetch_item_by_id",
                "status": "success",
                "item": item,
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error fetching item: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_item_by_id",
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error fetching item: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_item_by_id",
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

    async def _get_user(self, config: HNGetUserConfig) -> Dict[str, Any]:
        """Fetch a user profile by username"""
        logger.info(f"[HackerNewsNode] Fetching user {config.username}")
        start_time = time.time()

        try:
            url = f"{HN_API_BASE}/user/{config.username}.json"
            user = await self._fetch_json(url)

            if user is None:
                return {
                    "type": "hackernews",
                    "operation": "fetch_user_profile",
                    "status": "error",
                    "error": f"User '{config.username}' not found",
                    "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": time.time(),
                }

            return {
                "type": "hackernews",
                "operation": "fetch_user_profile",
                "status": "success",
                "user": user,
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error fetching user: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_user_profile",
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error fetching user: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_user_profile",
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

    async def _get_stories(
        self, endpoint: str, limit: int, fetch_details: bool
    ) -> Dict[str, Any]:
        """Fetch story list and optionally full details"""
        operation_name = endpoint.replace("stories", "_stories")
        logger.info(
            f"[HackerNewsNode] Fetching {endpoint} (limit={limit}, details={fetch_details})"
        )
        start_time = time.time()

        try:
            # Fetch list of story IDs
            url = f"{HN_API_BASE}/{endpoint}.json"
            story_ids = await self._fetch_json(url)

            if not story_ids:
                return {
                    "type": "hackernews",
                    "operation": operation_name,
                    "status": "success",
                    "stories": [],
                    "count": 0,
                    "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": time.time(),
                }

            # Apply limit
            story_ids = story_ids[:limit]

            if not fetch_details:
                # Return just IDs
                return {
                    "type": "hackernews",
                    "operation": operation_name,
                    "status": "success",
                    "story_ids": story_ids,
                    "count": len(story_ids),
                    "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": time.time(),
                }

            # Fetch full details for each story (in parallel)
            stories = await self._fetch_items_parallel(story_ids)

            return {
                "type": "hackernews",
                "operation": operation_name,
                "status": "success",
                "stories": stories,
                "count": len(stories),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error fetching {endpoint}: {e}")
            return {
                "type": "hackernews",
                "operation": operation_name,
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error fetching {endpoint}: {e}")
            return {
                "type": "hackernews",
                "operation": operation_name,
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

    async def _fetch_items_parallel(
        self, item_ids: List[int], max_concurrent: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch multiple items in parallel with concurrency limit"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(item_id: int) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    url = f"{HN_API_BASE}/item/{item_id}.json"
                    return await self._fetch_json(url)
                except Exception as e:
                    logger.warning(
                        f"[HackerNewsNode] Failed to fetch item {item_id}: {e}"
                    )
                    return None

        # Fetch all items in parallel
        results = await asyncio.gather(*[fetch_with_semaphore(id) for id in item_ids])

        # Filter out None values (failed fetches)
        return [item for item in results if item is not None]

    async def _get_max_item(self) -> Dict[str, Any]:
        """Get the current largest item ID"""
        logger.info(f"[HackerNewsNode] Fetching max item ID")
        start_time = time.time()

        try:
            url = f"{HN_API_BASE}/maxitem.json"
            max_item_id = await self._fetch_json(url)

            return {
                "type": "hackernews",
                "operation": "fetch_largest_item_id",
                "status": "success",
                "max_item_id": max_item_id,
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error fetching max item: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_largest_item_id",
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error fetching max item: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_largest_item_id",
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

    async def _get_updates(self) -> Dict[str, Any]:
        """Get changed items and profiles"""
        logger.info(f"[HackerNewsNode] Fetching updates")
        start_time = time.time()

        try:
            url = f"{HN_API_BASE}/updates.json"
            updates = await self._fetch_json(url)

            return {
                "type": "hackernews",
                "operation": "fetch_changed_items_and_profiles",
                "status": "success",
                "updates": updates,
                "item_count": len(updates.get("items", [])) if updates else 0,
                "profile_count": len(updates.get("profiles", [])) if updates else 0,
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error fetching updates: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_changed_items_and_profiles",
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error fetching updates: {e}")
            return {
                "type": "hackernews",
                "operation": "fetch_changed_items_and_profiles",
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

    async def _search(
        self, config: Union[HNSearchConfig, HNSearchByDateConfig], sort_by_date: bool
    ) -> Dict[str, Any]:
        """Search Hacker News using Algolia API"""
        operation = "search_by_recent_date" if sort_by_date else "search_by_relevance"
        endpoint = "search_by_date" if sort_by_date else "search"

        logger.info(
            f"[HackerNewsNode] Algolia {operation} (query='{config.query}', tags={config.tags}, page={config.page})"
        )
        start_time = time.time()

        try:
            # Build query parameters
            params: Dict[str, Any] = {
                "query": config.query,
                "page": config.page,
                "hitsPerPage": config.hits_per_page,
            }

            if config.tags:
                params["tags"] = config.tags

            if config.numeric_filters:
                params["numericFilters"] = config.numeric_filters

            # Make request to Algolia API
            url = f"{HN_ALGOLIA_BASE}/{endpoint}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=30.0)
                response.raise_for_status()
                result = response.json()

            return {
                "type": "hackernews",
                "operation": operation,
                "status": "success",
                "hits": result.get("hits", []),
                "nb_hits": result.get("nbHits", 0),
                "nb_pages": result.get("nbPages", 0),
                "page": result.get("page", 0),
                "hits_per_page": result.get("hitsPerPage", 0),
                "query": config.query,
                "tags": config.tags,
                "processing_time_ms": result.get("processingTimeMS", 0),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[HackerNewsNode] HTTP error during Algolia {operation}: {e}")
            return {
                "type": "hackernews",
                "operation": operation,
                "status": "error",
                "error": f"HTTP {e.response.status_code}: {str(e)}",
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"[HackerNewsNode] Error during Algolia {operation}: {e}")
            return {
                "type": "hackernews",
                "operation": operation,
                "status": "error",
                "error": str(e),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": time.time(),
            }

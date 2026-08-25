"""
Integration tests for Hacker News Node.

Tests all 12 operations against the real Hacker News APIs:
- Firebase API (10 operations)
- Algolia Search API (2 operations)

No authentication required - both APIs are public.
These tests verify actual API behavior and response formats.
"""

import pytest

from nodes.hackernews_node import (
    HackerNewsNode,
    HackerNewsNodeConfig,
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
)


# ============================================================================
# Test Fixtures
# ============================================================================


def create_node(config) -> HackerNewsNode:
    """Create a HackerNewsNode instance with the given config."""
    node_config = HackerNewsNodeConfig(config=config, credentials=None)
    node = HackerNewsNode(
        node_id="test-node",
        node_type="automation-hackernews",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Firebase API Integration Tests
# ============================================================================


class TestFirebaseAPIIntegration:
    """Integration tests for Firebase API operations."""

    @pytest.mark.asyncio
    async def test_get_item_famous_story(self):
        """Test fetching the famous Dropbox YC story."""
        config = HNGetItemConfig(item_id="8863")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "fetch_item_by_id"
        assert result["item"]["id"] == 8863
        assert "Dropbox" in result["item"]["title"]
        assert result["item"]["type"] == "story"

    @pytest.mark.asyncio
    async def test_get_user_pg(self):
        """Test fetching Paul Graham's user profile."""
        config = HNGetUserConfig(username="pg")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "fetch_user_profile"
        assert result["user"]["id"] == "pg"
        assert result["user"]["karma"] > 0
        assert "created" in result["user"]

    @pytest.mark.asyncio
    async def test_get_top_stories(self):
        """Test fetching top stories."""
        config = HNGetTopStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "top_stories"
        assert len(result["story_ids"]) == 5
        assert result["count"] == 5
        # All IDs should be positive integers
        assert all(isinstance(id, int) and id > 0 for id in result["story_ids"])

    @pytest.mark.asyncio
    async def test_get_top_stories_with_details(self):
        """Test fetching top stories with full details."""
        config = HNGetTopStoriesConfig(limit=3, fetch_details=True)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "top_stories"
        assert len(result["stories"]) > 0  # Should get at least some stories
        assert result["count"] > 0
        # Verify each story has expected fields
        for story in result["stories"]:
            assert "id" in story
            assert "type" in story

    @pytest.mark.asyncio
    async def test_get_new_stories(self):
        """Test fetching new stories."""
        config = HNGetNewStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "new_stories"
        assert len(result["story_ids"]) == 5

    @pytest.mark.asyncio
    async def test_get_best_stories(self):
        """Test fetching best stories."""
        config = HNGetBestStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "best_stories"
        assert len(result["story_ids"]) == 5

    @pytest.mark.asyncio
    async def test_get_ask_stories(self):
        """Test fetching Ask HN stories."""
        config = HNGetAskStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "ask_stories"
        assert len(result["story_ids"]) == 5

    @pytest.mark.asyncio
    async def test_get_show_stories(self):
        """Test fetching Show HN stories."""
        config = HNGetShowStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "show_stories"
        assert len(result["story_ids"]) == 5

    @pytest.mark.asyncio
    async def test_get_job_stories(self):
        """Test fetching job postings."""
        config = HNGetJobStoriesConfig(limit=5, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "job_stories"
        # Job stories might be fewer than requested if there aren't many active
        assert len(result["story_ids"]) > 0

    @pytest.mark.asyncio
    async def test_get_max_item(self):
        """Test fetching the current largest item ID."""
        config = HNGetMaxItemConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "fetch_largest_item_id"
        assert isinstance(result["max_item_id"], int)
        # Max item should be a very large number (millions)
        assert result["max_item_id"] > 1000000

    @pytest.mark.asyncio
    async def test_get_updates(self):
        """Test fetching changed items and profiles."""
        config = HNGetUpdatesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "fetch_changed_items_and_profiles"
        assert "updates" in result
        assert "items" in result["updates"]
        assert "profiles" in result["updates"]
        assert result["item_count"] > 0
        # Profile count might be 0 if no profiles changed recently
        assert result["profile_count"] >= 0


# ============================================================================
# Algolia Search API Integration Tests
# ============================================================================


class TestAlgoliaAPIIntegration:
    """Integration tests for Algolia Search API operations."""

    @pytest.mark.asyncio
    async def test_search_python(self):
        """Test searching for Python-related content."""
        config = HNSearchConfig(query="python", tags="story", page=0, hits_per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "search_by_relevance"
        assert len(result["hits"]) > 0  # Should find Python stories
        assert result["nb_hits"] > 0
        assert result["query"] == "python"
        # Verify hits have expected Algolia fields
        for hit in result["hits"]:
            assert "objectID" in hit

    @pytest.mark.asyncio
    async def test_search_by_date_recent_ask_hn(self):
        """Test searching for recent Ask HN posts sorted by date."""
        config = HNSearchByDateConfig(query="", tags="ask_hn", page=0, hits_per_page=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "search_by_recent_date"
        assert len(result["hits"]) > 0
        # Verify hits are sorted by date (most recent first)
        if len(result["hits"]) >= 2:
            first_hit = result["hits"][0]
            second_hit = result["hits"][1]
            if "created_at_i" in first_hit and "created_at_i" in second_hit:
                assert first_hit["created_at_i"] >= second_hit["created_at_i"]

    @pytest.mark.asyncio
    async def test_search_with_numeric_filters(self):
        """Test searching with numeric filters for recent stories.

        The Algolia HN index only permits filtering on ``created_at_i``
        (Unix timestamp) via numericFilters; ``points`` and ``num_comments``
        were removed from numericAttributesForFiltering by Algolia.
        """
        config = HNSearchConfig(
            query="",
            tags="story",
            numeric_filters="created_at_i>1700000000",  # stories after Nov 2023
            page=0,
            hits_per_page=5,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "search_by_relevance"
        assert len(result["hits"]) > 0
        for hit in result["hits"]:
            if "created_at_i" in hit:
                assert hit["created_at_i"] > 1700000000

    @pytest.mark.asyncio
    async def test_search_show_hn(self):
        """Test searching Show HN posts."""
        config = HNSearchConfig(query="", tags="show_hn", page=0, hits_per_page=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "search_by_relevance"
        assert len(result["hits"]) > 0
        assert result["nb_hits"] > 0

    @pytest.mark.asyncio
    async def test_search_pagination(self):
        """Test search pagination."""
        config = HNSearchConfig(
            query="javascript", tags="story", page=1, hits_per_page=10  # Get page 2
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "search_by_relevance"
        assert result["page"] == 1
        assert len(result["hits"]) > 0


# ============================================================================
# Error Handling Integration Tests
# ============================================================================


class TestErrorHandlingIntegration:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_nonexistent_item(self):
        """Test fetching a non-existent item."""
        # Use a very high ID that likely doesn't exist yet
        config = HNGetItemConfig(item_id="999999999")
        node = create_node(config)

        result = await node.execute({})

        # Should handle gracefully
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_nonexistent_user(self):
        """Test fetching a non-existent user."""
        config = HNGetUserConfig(username="thisuserdoesnotexist123456789")
        node = create_node(config)

        result = await node.execute({})

        # Should handle gracefully
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()


# ============================================================================
# Performance and Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and performance."""

    @pytest.mark.asyncio
    async def test_large_limit(self):
        """Test fetching with maximum allowed limit."""
        config = HNGetTopStoriesConfig(limit=500, fetch_details=False)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["story_ids"]) == 500

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Test search with empty query (should return all items with tag)."""
        config = HNSearchConfig(query="", tags="story", page=0, hits_per_page=20)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["hits"]) > 0
        # Empty query with tags should still return results
        assert result["nb_hits"] > 0

    @pytest.mark.asyncio
    async def test_parallel_story_fetching(self):
        """Test fetching stories with details (parallel item fetching)."""
        config = HNGetTopStoriesConfig(limit=10, fetch_details=True)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        # Should successfully fetch multiple stories in parallel
        assert len(result["stories"]) > 0
        assert result["elapsed_ms"] < 10000  # Should complete within 10 seconds

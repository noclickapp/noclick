"""
Mock tests for Hacker News Node.

Tests all 12 operations using mocked responses:
- Firebase API (10): get_item, get_user, 6 story lists, max_item, updates
- Algolia API (2): search, search_by_date

No real API calls are made - all responses are simulated.
This allows tests to run in CI without dependencies and without making real requests.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

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
# Mock Response Factory
# ============================================================================


def mock_json_response(data):
    """Create a mock httpx response with JSON data."""
    mock_response = MagicMock()
    mock_response.json.return_value = data
    return mock_response


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
# Firebase API Tests
# ============================================================================


class TestFirebaseAPI:
    """Test Firebase API operations."""

    @pytest.mark.asyncio
    async def test_get_item(self):
        """Test fetching a single item by ID."""
        config = HNGetItemConfig(item_id="8863")
        node = create_node(config)

        mock_item = {
            "id": 8863,
            "type": "story",
            "by": "dhouston",
            "time": 1175714200,
            "title": "My YC app: Dropbox - Throw away your USB drive",
            "url": "http://www.getdropbox.com/u/2/screencast.html",
            "score": 111,
            "descendants": 71,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_item)
            result = await node.execute({})

        assert result["operation"] == "fetch_item_by_id"
        assert result["status"] == "success"
        assert result["item"]["id"] == 8863
        assert (
            result["item"]["title"] == "My YC app: Dropbox - Throw away your USB drive"
        )

    @pytest.mark.asyncio
    async def test_get_user(self):
        """Test fetching a user profile."""
        config = HNGetUserConfig(username="pg")
        node = create_node(config)

        mock_user = {
            "id": "pg",
            "created": 1160418092,
            "karma": 155111,
            "about": "Bug fixer.",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_user)
            result = await node.execute({})

        assert result["operation"] == "fetch_user_profile"
        assert result["status"] == "success"
        assert result["user"]["id"] == "pg"
        assert result["user"]["karma"] == 155111

    @pytest.mark.asyncio
    async def test_get_top_stories_with_details(self):
        """Test fetching top stories with full details."""
        config = HNGetTopStoriesConfig(limit=2, fetch_details=True)
        node = create_node(config)

        mock_story_ids = [8863, 8864]
        mock_story_1 = {"id": 8863, "title": "Story 1", "score": 100}
        mock_story_2 = {"id": 8864, "title": "Story 2", "score": 90}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # First call returns story IDs
            # Subsequent calls return individual stories
            mock_get.side_effect = [
                mock_json_response(mock_story_ids),
                mock_json_response(mock_story_1),
                mock_json_response(mock_story_2),
            ]
            result = await node.execute({})

        assert result["operation"] == "top_stories"
        assert result["status"] == "success"
        assert len(result["stories"]) == 2
        assert result["stories"][0]["id"] == 8863
        assert result["stories"][1]["id"] == 8864

    @pytest.mark.asyncio
    async def test_get_top_stories_ids_only(self):
        """Test fetching top stories without details (IDs only)."""
        config = HNGetTopStoriesConfig(limit=3, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [8863, 8864, 8865]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "top_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [8863, 8864, 8865]
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_get_new_stories(self):
        """Test fetching new stories."""
        config = HNGetNewStoriesConfig(limit=2, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [9001, 9002]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "new_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [9001, 9002]

    @pytest.mark.asyncio
    async def test_get_best_stories(self):
        """Test fetching best stories."""
        config = HNGetBestStoriesConfig(limit=2, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [8001, 8002]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "best_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [8001, 8002]

    @pytest.mark.asyncio
    async def test_get_ask_stories(self):
        """Test fetching Ask HN stories."""
        config = HNGetAskStoriesConfig(limit=2, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [7001, 7002]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "ask_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [7001, 7002]

    @pytest.mark.asyncio
    async def test_get_show_stories(self):
        """Test fetching Show HN stories."""
        config = HNGetShowStoriesConfig(limit=2, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [6001, 6002]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "show_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [6001, 6002]

    @pytest.mark.asyncio
    async def test_get_job_stories(self):
        """Test fetching job postings."""
        config = HNGetJobStoriesConfig(limit=2, fetch_details=False)
        node = create_node(config)

        mock_story_ids = [5001, 5002]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_story_ids)
            result = await node.execute({})

        assert result["operation"] == "job_stories"
        assert result["status"] == "success"
        assert result["story_ids"] == [5001, 5002]

    @pytest.mark.asyncio
    async def test_get_max_item(self):
        """Test fetching the current largest item ID."""
        config = HNGetMaxItemConfig()
        node = create_node(config)

        mock_max_id = 38599119

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_max_id)
            result = await node.execute({})

        assert result["operation"] == "fetch_largest_item_id"
        assert result["status"] == "success"
        assert result["max_item_id"] == 38599119

    @pytest.mark.asyncio
    async def test_get_updates(self):
        """Test fetching changed items and profiles."""
        config = HNGetUpdatesConfig()
        node = create_node(config)

        mock_updates = {"items": [8863, 8864, 8865], "profiles": ["jl", "pg", "sama"]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_updates)
            result = await node.execute({})

        assert result["operation"] == "fetch_changed_items_and_profiles"
        assert result["status"] == "success"
        assert result["item_count"] == 3
        assert result["profile_count"] == 3
        assert result["updates"]["items"] == [8863, 8864, 8865]


# ============================================================================
# Algolia Search API Tests
# ============================================================================


class TestAlgoliaAPI:
    """Test Algolia Search API operations."""

    @pytest.mark.asyncio
    async def test_search_by_relevance(self):
        """Test Algolia search sorted by relevance."""
        config = HNSearchConfig(query="python", tags="story", page=0, hits_per_page=2)
        node = create_node(config)

        mock_response = {
            "hits": [
                {"objectID": "1", "title": "Python 3.12 Released", "points": 500},
                {"objectID": "2", "title": "Learning Python", "points": 300},
            ],
            "nbHits": 12345,
            "nbPages": 6173,
            "page": 0,
            "hitsPerPage": 2,
            "processingTimeMS": 2,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_response)
            result = await node.execute({})

        assert result["operation"] == "search_by_relevance"
        assert result["status"] == "success"
        assert len(result["hits"]) == 2
        assert result["nb_hits"] == 12345
        assert result["query"] == "python"
        assert result["tags"] == "story"

    @pytest.mark.asyncio
    async def test_search_by_date(self):
        """Test Algolia search sorted by date."""
        config = HNSearchByDateConfig(query="", tags="ask_hn", page=0, hits_per_page=3)
        node = create_node(config)

        mock_response = {
            "hits": [
                {
                    "objectID": "3",
                    "title": "Ask HN: Best resources?",
                    "created_at_i": 1700000000,
                },
                {
                    "objectID": "4",
                    "title": "Ask HN: Career advice?",
                    "created_at_i": 1699999999,
                },
                {
                    "objectID": "5",
                    "title": "Ask HN: Learning path?",
                    "created_at_i": 1699999998,
                },
            ],
            "nbHits": 54321,
            "nbPages": 18107,
            "page": 0,
            "hitsPerPage": 3,
            "processingTimeMS": 1,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_response)
            result = await node.execute({})

        assert result["operation"] == "search_by_recent_date"
        assert result["status"] == "success"
        assert len(result["hits"]) == 3
        assert result["nb_hits"] == 54321
        assert result["tags"] == "ask_hn"

    @pytest.mark.asyncio
    async def test_search_with_numeric_filters(self):
        """Test Algolia search with numeric filters."""
        config = HNSearchConfig(
            query="startup",
            numeric_filters="points>100,created_at_i>1609459200",
            page=0,
            hits_per_page=5,
        )
        node = create_node(config)

        mock_response = {
            "hits": [{"objectID": "6", "title": "YC Startup School", "points": 250}],
            "nbHits": 1234,
            "nbPages": 247,
            "page": 0,
            "hitsPerPage": 5,
            "processingTimeMS": 3,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(mock_response)
            result = await node.execute({})

        assert result["operation"] == "search_by_relevance"
        assert result["status"] == "success"
        assert len(result["hits"]) == 1
        assert result["hits"][0]["points"] == 250


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_item_not_found(self):
        """Test handling of non-existent item."""
        config = HNGetItemConfig(item_id="99999999")
        node = create_node(config)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(None)
            result = await node.execute({})

        assert result["operation"] == "fetch_item_by_id"
        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        """Test handling of non-existent user."""
        config = HNGetUserConfig(username="nonexistentuser99999")
        node = create_node(config)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_json_response(None)
            result = await node.execute({})

        assert result["operation"] == "fetch_user_profile"
        assert result["status"] == "error"
        assert "not found" in result["error"]

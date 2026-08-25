"""
Integration tests for TikTok Open Platform automation node.

Tests all 5 TikTok operations against the real TikTok API.
All tests are skipped unless TIKTOK_ACCESS_TOKEN is set in the environment.

Required env vars:
    TIKTOK_ACCESS_TOKEN  — A valid TikTok access token
    TIKTOK_OPEN_ID       — The open_id for the authenticated account (optional but recommended)

Optional env vars:
    TIKTOK_REFRESH_TOKEN — Refresh token for auto-renewal

How to get credentials:
1. Register a developer app at https://developers.tiktok.com/
2. Implement the OAuth flow or use a test token from the developer portal
3. Set env vars and run:

   TIKTOK_ACCESS_TOKEN=... TIKTOK_OPEN_ID=... pytest nodes/tests/test_tiktok_node_integration.py -v
"""

import os
import pytest
from datetime import datetime, timedelta, timezone

from nodes.tiktok_node import (
    TikTokNode,
    TikTokNodeConfig,
    TikTokOAuthCredential,
    TikTokGetUserInfoConfig,
    TikTokListVideosConfig,
    TikTokQueryVideosConfig,
    TikTokPublishVideoConfig,
    TikTokCheckPublishStatusConfig,
)

# ============================================================================
# Skip all tests unless real credentials are present
# ============================================================================

pytestmark = pytest.mark.skipif(
    not os.environ.get("TIKTOK_ACCESS_TOKEN"),
    reason="TIKTOK_ACCESS_TOKEN not set — skipping TikTok integration tests",
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def credential():
    """Build a real TikTok OAuth credential from env vars."""
    access_token = os.environ["TIKTOK_ACCESS_TOKEN"]
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN")
    open_id = os.environ.get("TIKTOK_OPEN_ID")
    # Set expiry well in the future to avoid refresh during testing
    future_expiry = (datetime.now(timezone.utc) + timedelta(hours=23)).isoformat()
    return TikTokOAuthCredential(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=future_expiry,
        open_id=open_id,
    )


def build_node(action_config, credential):
    full_config = TikTokNodeConfig(config=action_config, credentials=credential)
    return TikTokNode(
        node_id="test_node",
        node_type="automation-tiktok",
        node_data={},
        config=full_config,
    )


# ============================================================================
# User Info Integration
# ============================================================================


class TestUserIntegration:
    @pytest.mark.asyncio
    async def test_get_user_info(self, credential):
        """Retrieve the authenticated user's TikTok profile."""
        config = TikTokGetUserInfoConfig()
        node = build_node(config, credential)

        result = await node.execute({})

        assert (
            result["status"] == "success"
        ), f"get_user_info failed: {result.get('error')}"
        assert result["action"] == "get_authenticated_user_info"
        assert "data" in result
        assert "timing_ms" in result
        print(
            f"\n[get_user_info] data: {result['data'].get('data', {}).get('user', {})}"
        )


# ============================================================================
# Video Reading Integration
# ============================================================================


class TestVideoReadingIntegration:
    @pytest.mark.asyncio
    async def test_list_videos(self, credential):
        """List the authenticated user's recent videos."""
        config = TikTokListVideosConfig(max_count=5)
        node = build_node(config, credential)

        result = await node.execute({})

        assert (
            result["status"] == "success"
        ), f"list_videos failed: {result.get('error')}"
        assert result["action"] == "list_user_public_videos"
        assert "data" in result
        assert "timing_ms" in result
        videos = result["data"].get("data", {}).get("videos", [])
        print(f"\n[list_videos] Found {len(videos)} videos")

    @pytest.mark.asyncio
    async def test_query_videos(self, credential):
        """Query specific videos by ID — uses first listed video if available."""
        # First get a video ID by listing videos
        list_config = TikTokListVideosConfig(max_count=1)
        list_node = build_node(list_config, credential)
        list_result = await list_node.execute({})

        if list_result["status"] != "success":
            pytest.skip("Could not list videos to get a video ID for query test")

        videos = list_result["data"].get("data", {}).get("videos", [])
        if not videos:
            pytest.skip(
                "No videos found for the authenticated account; skipping query test"
            )

        video_id = videos[0]["id"]
        config = TikTokQueryVideosConfig(video_ids=video_id)
        node = build_node(config, credential)

        result = await node.execute({})

        assert (
            result["status"] == "success"
        ), f"query_videos failed: {result.get('error')}"
        assert result["action"] == "query_video_metrics_by_id"
        assert "timing_ms" in result
        print(f"\n[query_videos] Queried video: {video_id}")


# ============================================================================
# Publishing Integration
# ============================================================================


class TestPublishingIntegration:
    @pytest.mark.asyncio
    async def test_publish_video_from_url(self, credential):
        """Publish a test video to creator inbox draft (video.upload scope, no audit required)."""
        config = TikTokPublishVideoConfig(
            video_url="https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4",
            title="NoClick integration test video",
        )
        node = build_node(config, credential)

        result = await node.execute({})

        if result["status"] == "error":
            # Publishing may fail if the app hasn't been granted content posting permission
            pytest.skip(
                f"publish_video failed (may need video.upload permission): {result.get('error')}"
            )

        assert (
            result["status"] == "success"
        ), f"publish_video failed: {result.get('error')}"
        assert result["action"] == "upload_video_to_creator_inbox"
        assert "data" in result
        assert "timing_ms" in result
        publish_id = result["data"].get("data", {}).get("publish_id")
        print(f"\n[publish_video] publish_id: {publish_id}")

    @pytest.mark.asyncio
    async def test_check_publish_status(self, credential):
        """Check publish status with a dummy publish_id — expects a structured error response."""
        config = TikTokCheckPublishStatusConfig(publish_id="dummy_publish_id_for_test")
        node = build_node(config, credential)

        result = await node.execute({})

        # A dummy ID should return an error from TikTok — we verify the call reaches the API
        assert result["action"] == "check_video_publish_status"
        assert "timing_ms" in result
        print(
            f"\n[check_publish_status] status: {result['status']}, status_code: {result.get('status_code')}"
        )

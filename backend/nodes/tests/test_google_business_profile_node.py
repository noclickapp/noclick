"""
Unit tests for Google Business Profile (GBP) node — all 26 operations.
All API calls are mocked; no live network traffic.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.google_business_profile_node import (
    GoogleBusinessProfileNode,
    GoogleBusinessProfileNodeConfig,
    GoogleBusinessProfileOAuthCredential,
    GBPListLocationsConfig,
    GBPGetLocationConfig,
    GBPUpdateLocationConfig,
    GBPGetLocationAttributesConfig,
    GBPUpdateLocationAttributesConfig,
    GBPListReviewsConfig,
    GBPGetReviewConfig,
    GBPReplyToReviewConfig,
    GBPDeleteReviewReplyConfig,
    GBPListLocalPostsConfig,
    GBPGetLocalPostConfig,
    GBPCreateLocalPostConfig,
    GBPUpdateLocalPostConfig,
    GBPDeleteLocalPostConfig,
    GBPGetLocalPostInsightsConfig,
    GBPListMediaConfig,
    GBPGetMediaConfig,
    GBPCreateMediaConfig,
    GBPDeleteMediaConfig,
    GBPListCustomerMediaConfig,
    GBPGetPerformanceConfig,
    GBPGetSearchKeywordsConfig,
    GBPListPlaceActionLinksConfig,
    GBPCreatePlaceActionLinkConfig,
    GBPUpdatePlaceActionLinkConfig,
    GBPDeletePlaceActionLinkConfig,
)

# ============================================================================
# Fixtures
# ============================================================================

ACCOUNT_ID = "accounts/123456"
LOCATION_ID = "locations/loc1"
REVIEW_NAME = "accounts/123456/locations/loc1/reviews/rev1"
POST_NAME = "accounts/123456/locations/loc1/localPosts/post1"
MEDIA_NAME = "accounts/123456/locations/loc1/media/media1"
LINK_NAME = "locations/loc1/placeActionLinks/link1"


@pytest.fixture
def creds():
    return GoogleBusinessProfileOAuthCredential(
        access_token="tok",
        refresh_token="ref",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


def _resp(data: dict, status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    r.text = json.dumps(data)
    r.raise_for_status = MagicMock()
    return r


def make_node(config, credentials) -> GoogleBusinessProfileNode:
    return GoogleBusinessProfileNode(
        node_id="n",
        node_type="automation-google-business-profile",
        node_data={},
        config=GoogleBusinessProfileNodeConfig(config=config, credentials=credentials),
        sio=None, sid=None, workflow_id="wf",
    )


def patch_token():
    return patch(
        "nodes.google_business_profile_node.GoogleBusinessProfileNode._ensure_fresh_token",
        new=AsyncMock(return_value="tok"),
    )


# ============================================================================
# Location — list
# ============================================================================

class TestListLocations:
    @pytest.mark.asyncio
    async def test_success(self, creds):
        node = make_node(GBPListLocationsConfig(account_id=ACCOUNT_ID), creds)
        mock_resp = _resp({"locations": [
            {"name": "locations/loc1", "title": "Store A",
             "storefrontAddress": {"addressLines": ["1 Main St"], "locality": "SF", "administrativeArea": "CA", "postalCode": "94101"},
             "websiteUri": "https://a.com", "phoneNumbers": {"primaryPhone": "+14155551234"}},
        ]})
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            result = await node.execute({})
        assert result["count"] == 1
        assert result["locations"][0]["title"] == "Store A"
        assert result["locations"][0]["phone"] == "+14155551234"

    @pytest.mark.asyncio
    async def test_pagination(self, creds):
        node = make_node(GBPListLocationsConfig(account_id=ACCOUNT_ID), creds)
        p1 = _resp({"locations": [{"name": "locations/l1", "title": "A", "storefrontAddress": {}}], "nextPageToken": "t2"})
        p2 = _resp({"locations": [{"name": "locations/l2", "title": "B", "storefrontAddress": {}}]})
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(side_effect=[p1, p2])
            result = await node.execute({})
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_empty(self, creds):
        node = make_node(GBPListLocationsConfig(account_id=ACCOUNT_ID), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp({"locations": []}))
            result = await node.execute({})
        assert result["count"] == 0


# ============================================================================
# Location — get
# ============================================================================

class TestGetLocation:
    @pytest.mark.asyncio
    async def test_success(self, creds):
        node = make_node(GBPGetLocationConfig(location_id=LOCATION_ID), creds)
        payload = {"name": LOCATION_ID, "title": "My Store", "websiteUri": "https://example.com"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["title"] == "My Store"


# ============================================================================
# Location — update
# ============================================================================

class TestUpdateLocation:
    @pytest.mark.asyncio
    async def test_update_title_and_phone(self, creds):
        node = make_node(GBPUpdateLocationConfig(
            location_id=LOCATION_ID, title="New Name", primary_phone="+14155550001"
        ), creds)
        updated = {"name": LOCATION_ID, "title": "New Name"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.patch = AsyncMock(return_value=_resp(updated))
            result = await node.execute({})
        assert result["status"] == "updated"
        assert "title" in result["updated_fields"]
        assert "phoneNumbers.primaryPhone" in result["updated_fields"]

    @pytest.mark.asyncio
    async def test_no_fields_raises(self, creds):
        node = make_node(GBPUpdateLocationConfig(location_id=LOCATION_ID), creds)
        with patch_token():
            with pytest.raises(ValueError, match="At least one field"):
                await node.execute({})


# ============================================================================
# Location — attributes
# ============================================================================

class TestLocationAttributes:
    @pytest.mark.asyncio
    async def test_get_attributes(self, creds):
        node = make_node(GBPGetLocationAttributesConfig(location_id=LOCATION_ID), creds)
        payload = {"name": f"{LOCATION_ID}/attributes", "attributes": [{"name": "attributes/has_wifi"}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert "attributes" in result

    @pytest.mark.asyncio
    async def test_update_attributes(self, creds):
        attrs_json = '[{"name":"attributes/has_wifi","valueType":"BOOL","values":[true]}]'
        node = make_node(GBPUpdateLocationAttributesConfig(location_id=LOCATION_ID, attributes=attrs_json), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.patch = AsyncMock(return_value=_resp({"name": f"{LOCATION_ID}/attributes"}))
            result = await node.execute({})
        assert result["status"] == "updated"

    @pytest.mark.asyncio
    async def test_invalid_json_attributes_raises(self, creds):
        node = make_node(GBPUpdateLocationAttributesConfig(location_id=LOCATION_ID, attributes="not json"), creds)
        with patch_token():
            with pytest.raises(ValueError, match="not valid JSON"):
                await node.execute({})


# ============================================================================
# Reviews — list
# ============================================================================

class TestListReviews:
    @pytest.mark.asyncio
    async def test_success(self, creds):
        node = make_node(GBPListReviewsConfig(account_id=ACCOUNT_ID, location_id=LOCATION_ID), creds)
        payload = {
            "reviews": [
                {"name": REVIEW_NAME, "reviewer": {"displayName": "Alice"},
                 "starRating": "FIVE", "comment": "Great!", "createTime": "2026-01-01T00:00:00Z",
                 "updateTime": "2026-01-01T00:00:00Z", "reviewReply": {"comment": "Thanks!"}},
            ],
            "totalReviewCount": 10, "averageRating": 4.8,
        }
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 1
        assert result["reviews"][0]["reviewer_name"] == "Alice"
        assert result["reviews"][0]["reply"] == "Thanks!"

    @pytest.mark.asyncio
    async def test_anonymous_reviewer(self, creds):
        node = make_node(GBPListReviewsConfig(account_id=ACCOUNT_ID, location_id=LOCATION_ID), creds)
        payload = {"reviews": [{"name": REVIEW_NAME, "reviewer": {}, "starRating": "ONE", "comment": "Bad",
                                "createTime": "2026-01-01T00:00:00Z", "updateTime": "2026-01-01T00:00:00Z"}],
                   "totalReviewCount": 1, "averageRating": 1.0}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["reviews"][0]["reviewer_name"] == "Anonymous"


# ============================================================================
# Reviews — get
# ============================================================================

class TestGetReview:
    @pytest.mark.asyncio
    async def test_full_resource_name(self, creds):
        node = make_node(GBPGetReviewConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID, review_id=REVIEW_NAME
        ), creds)
        payload = {"name": REVIEW_NAME, "starRating": "FOUR", "comment": "Good"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["starRating"] == "FOUR"

    @pytest.mark.asyncio
    async def test_short_review_id(self, creds):
        node = make_node(GBPGetReviewConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID, review_id="rev1"
        ), creds)
        payload = {"name": REVIEW_NAME, "starRating": "THREE"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_get = AsyncMock(return_value=_resp(payload))
            m.return_value.__aenter__.return_value.get = mock_get
            await node.execute({})
        url = mock_get.call_args.args[0]
        assert "rev1" in url


# ============================================================================
# Reviews — reply
# ============================================================================

class TestReplyToReview:
    @pytest.mark.asyncio
    async def test_reply(self, creds):
        node = make_node(GBPReplyToReviewConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            review_id=REVIEW_NAME, reply_text="Thank you for your feedback!",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.put = AsyncMock(return_value=_resp({"comment": "Thank you!"}))
            result = await node.execute({})
        assert result["status"] == "replied"

    @pytest.mark.asyncio
    async def test_delete_reply(self, creds):
        node = make_node(GBPDeleteReviewReplyConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID, review_id=REVIEW_NAME,
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.delete = AsyncMock(return_value=_resp({}))
            result = await node.execute({})
        assert result["status"] == "deleted"


# ============================================================================
# Local Posts
# ============================================================================

class TestLocalPosts:
    @pytest.mark.asyncio
    async def test_list(self, creds):
        node = make_node(GBPListLocalPostsConfig(account_id=ACCOUNT_ID, location_id=LOCATION_ID), creds)
        payload = {"localPosts": [{"name": POST_NAME, "summary": "Check out our sale!", "topicType": "STANDARD"}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 1
        assert result["posts"][0]["name"] == POST_NAME

    @pytest.mark.asyncio
    async def test_get(self, creds):
        node = make_node(GBPGetLocalPostConfig(local_post_name=POST_NAME), creds)
        payload = {"name": POST_NAME, "summary": "Sale ends Sunday", "state": "LIVE"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["summary"] == "Sale ends Sunday"

    @pytest.mark.asyncio
    async def test_create_standard(self, creds):
        node = make_node(GBPCreateLocalPostConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            topic_type="STANDARD", summary="Weekend special!",
            call_to_action_type="LEARN_MORE", call_to_action_url="https://example.com",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_post = AsyncMock(return_value=_resp({"name": POST_NAME, "summary": "Weekend special!"}))
            m.return_value.__aenter__.return_value.post = mock_post
            result = await node.execute({})
        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert body["topicType"] == "STANDARD"
        assert body["callToAction"]["actionType"] == "LEARN_MORE"

    @pytest.mark.asyncio
    async def test_create_event(self, creds):
        node = make_node(GBPCreateLocalPostConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            topic_type="EVENT", summary="Grand opening!",
            event_title="Grand Opening", event_start="2026-08-01", event_end="2026-08-03",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_post = AsyncMock(return_value=_resp({"name": POST_NAME}))
            m.return_value.__aenter__.return_value.post = mock_post
            await node.execute({})
        body = mock_post.call_args.kwargs["json"]
        assert body["event"]["title"] == "Grand Opening"
        assert body["event"]["schedule"]["startDate"]["year"] == 2026

    @pytest.mark.asyncio
    async def test_create_offer(self, creds):
        node = make_node(GBPCreateLocalPostConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            topic_type="OFFER", summary="20% off this weekend",
            offer_coupon_code="SAVE20", offer_redeem_url="https://example.com/offer",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_post = AsyncMock(return_value=_resp({"name": POST_NAME}))
            m.return_value.__aenter__.return_value.post = mock_post
            await node.execute({})
        body = mock_post.call_args.kwargs["json"]
        assert body["offer"]["couponCode"] == "SAVE20"

    @pytest.mark.asyncio
    async def test_update(self, creds):
        node = make_node(GBPUpdateLocalPostConfig(
            local_post_name=POST_NAME, summary="Updated text",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_patch = AsyncMock(return_value=_resp({"name": POST_NAME, "summary": "Updated text"}))
            m.return_value.__aenter__.return_value.patch = mock_patch
            result = await node.execute({})
        assert result["status"] == "updated"
        params = mock_patch.call_args.kwargs["params"]
        assert "summary" in params["updateMask"]

    @pytest.mark.asyncio
    async def test_update_no_fields_raises(self, creds):
        node = make_node(GBPUpdateLocalPostConfig(local_post_name=POST_NAME), creds)
        with patch_token():
            with pytest.raises(ValueError, match="At least one field"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_delete(self, creds):
        node = make_node(GBPDeleteLocalPostConfig(local_post_name=POST_NAME), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.delete = AsyncMock(return_value=_resp({}))
            result = await node.execute({})
        assert result["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_insights(self, creds):
        node = make_node(GBPGetLocalPostInsightsConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            local_post_names=POST_NAME,
            start_date="2026-06-01", end_date="2026-07-01",
        ), creds)
        payload = {"localPostMetrics": [{"localPostName": POST_NAME, "metricValues": []}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.post = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert "localPostMetrics" in result

    @pytest.mark.asyncio
    async def test_insights_empty_names_raises(self, creds):
        node = make_node(GBPGetLocalPostInsightsConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID, local_post_names="  ",
        ), creds)
        with patch_token():
            with pytest.raises(ValueError, match="At least one"):
                await node.execute({})


# ============================================================================
# Media
# ============================================================================

class TestMedia:
    @pytest.mark.asyncio
    async def test_list(self, creds):
        node = make_node(GBPListMediaConfig(account_id=ACCOUNT_ID, location_id=LOCATION_ID), creds)
        payload = {"mediaItems": [{"name": MEDIA_NAME, "mediaFormat": "PHOTO", "googleUrl": "https://lh3.googleusercontent.com/abc"}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get(self, creds):
        node = make_node(GBPGetMediaConfig(media_item_name=MEDIA_NAME), creds)
        payload = {"name": MEDIA_NAME, "mediaFormat": "PHOTO", "googleUrl": "https://lh3.googleusercontent.com/abc"}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["mediaFormat"] == "PHOTO"

    @pytest.mark.asyncio
    async def test_create(self, creds):
        node = make_node(GBPCreateMediaConfig(
            account_id=ACCOUNT_ID, location_id=LOCATION_ID,
            source_url="https://example.com/photo.jpg",
            media_format="PHOTO", category="EXTERIOR",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_post = AsyncMock(return_value=_resp({"name": MEDIA_NAME}))
            m.return_value.__aenter__.return_value.post = mock_post
            result = await node.execute({})
        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert body["mediaFormat"] == "PHOTO"
        assert body["locationAssociation"]["category"] == "EXTERIOR"
        assert body["sourceUrl"] == "https://example.com/photo.jpg"

    @pytest.mark.asyncio
    async def test_delete(self, creds):
        node = make_node(GBPDeleteMediaConfig(media_item_name=MEDIA_NAME), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.delete = AsyncMock(return_value=_resp({}))
            result = await node.execute({})
        assert result["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_list_customer_media(self, creds):
        node = make_node(GBPListCustomerMediaConfig(account_id=ACCOUNT_ID, location_id=LOCATION_ID), creds)
        payload = {"mediaItems": [{"name": f"{MEDIA_NAME}/customers/c1", "mediaFormat": "PHOTO"}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 1


# ============================================================================
# Analytics
# ============================================================================

class TestAnalytics:
    @pytest.mark.asyncio
    async def test_performance_metrics(self, creds):
        node = make_node(GBPGetPerformanceConfig(
            location_id=LOCATION_ID, start_date="2026-06-01", end_date="2026-06-07",
            daily_metrics="WEBSITE_CLICKS,CALL_CLICKS",
        ), creds)
        payload = {"multiDailyMetricTimeSeries": [
            {"dailyMetric": "WEBSITE_CLICKS", "dailyMetricTimeSeries": {"timeSeries": {"datedValues": [
                {"date": {"year": 2026, "month": 6, "day": 1}, "value": 15},
            ]}}},
            {"dailyMetric": "CALL_CLICKS", "dailyMetricTimeSeries": {"timeSeries": {"datedValues": [
                {"date": {"year": 2026, "month": 6, "day": 1}, "value": 3},
            ]}}},
        ]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["rows"][0]["WEBSITE_CLICKS"] == 15
        assert result["rows"][0]["CALL_CLICKS"] == 3

    @pytest.mark.asyncio
    async def test_search_keywords(self, creds):
        node = make_node(GBPGetSearchKeywordsConfig(location_id=LOCATION_ID, year="2026", month="5"), creds)
        payload = {"searchKeywordsCounts": [
            {"searchKeyword": "pizza place", "insightsValue": {"value": 500}},
            {"searchKeyword": "best pizza", "insightsValue": {"value": 200}},
        ]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 2
        assert result["keywords"][0]["keyword"] == "pizza place"
        assert result["period"] == "2026-05"


# ============================================================================
# Place Action Links
# ============================================================================

class TestPlaceActionLinks:
    @pytest.mark.asyncio
    async def test_list(self, creds):
        node = make_node(GBPListPlaceActionLinksConfig(location_id=LOCATION_ID), creds)
        payload = {"placeActionLinks": [{"name": LINK_NAME, "uri": "https://book.example.com", "placeActionType": "APPOINTMENT"}]}
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await node.execute({})
        assert result["count"] == 1
        assert result["place_action_links"][0]["uri"] == "https://book.example.com"

    @pytest.mark.asyncio
    async def test_create(self, creds):
        node = make_node(GBPCreatePlaceActionLinkConfig(
            location_id=LOCATION_ID, uri="https://book.example.com",
            place_action_type="APPOINTMENT", is_preferred="true",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_post = AsyncMock(return_value=_resp({"name": LINK_NAME, "uri": "https://book.example.com"}))
            m.return_value.__aenter__.return_value.post = mock_post
            result = await node.execute({})
        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert body["placeActionType"] == "APPOINTMENT"
        assert body["isPreferred"] is True

    @pytest.mark.asyncio
    async def test_update(self, creds):
        node = make_node(GBPUpdatePlaceActionLinkConfig(
            place_action_link_name=LINK_NAME, uri="https://newbook.example.com",
        ), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            mock_patch = AsyncMock(return_value=_resp({"name": LINK_NAME, "uri": "https://newbook.example.com"}))
            m.return_value.__aenter__.return_value.patch = mock_patch
            result = await node.execute({})
        assert result["status"] == "updated"
        params = mock_patch.call_args.kwargs["params"]
        assert "uri" in params["updateMask"]

    @pytest.mark.asyncio
    async def test_update_no_fields_raises(self, creds):
        node = make_node(GBPUpdatePlaceActionLinkConfig(place_action_link_name=LINK_NAME), creds)
        with patch_token():
            with pytest.raises(ValueError, match="At least one field"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_delete(self, creds):
        node = make_node(GBPDeletePlaceActionLinkConfig(place_action_link_name=LINK_NAME), creds)
        with patch_token(), patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.delete = AsyncMock(return_value=_resp({}))
            result = await node.execute({})
        assert result["status"] == "deleted"


# ============================================================================
# No credentials guard
# ============================================================================

class TestCredentials:
    @pytest.mark.asyncio
    async def test_no_credentials(self):
        config = GoogleBusinessProfileNodeConfig(
            config=GBPListLocationsConfig(account_id=ACCOUNT_ID), credentials=None
        )
        node = GoogleBusinessProfileNode(
            node_id="n", node_type="automation-google-business-profile",
            node_data={}, config=config, sio=None, sid=None, workflow_id="wf",
        )
        result = await node.execute({})
        assert "error" in result


# ============================================================================
# Schema smoke test
# ============================================================================

def test_schema_has_all_26_operations():
    schema = GoogleBusinessProfileNode.get_config_schema()
    text = json.dumps(schema)
    ops = [
        "list_business_profile_locations", "get_location", "update_location",
        "get_location_attributes", "update_location_attributes",
        "list_location_reviews", "get_review", "reply_to_review", "delete_review_reply",
        "list_local_posts", "get_local_post", "create_local_post",
        "update_local_post", "delete_local_post", "get_local_post_insights",
        "list_media", "get_media", "create_media", "delete_media", "list_customer_media",
        "fetch_location_performance_metrics", "fetch_location_search_keywords",
        "list_place_action_links", "create_place_action_link",
        "update_place_action_link", "delete_place_action_link",
    ]
    for op in ops:
        assert op in text, f"Operation '{op}' missing from schema"


def test_config_model():
    assert GoogleBusinessProfileNode.get_config_model() is GoogleBusinessProfileNodeConfig


# ============================================================================
# Load field options
# ============================================================================

class TestLoadFieldOptions:
    @pytest.mark.asyncio
    async def test_account_options(self):
        cred_data = {"access_token": "tok", "expires_at": "2099-12-31T23:59:59Z"}
        payload = {"accounts": [
            {"name": "accounts/111", "accountName": "Main Account"},
            {"name": "accounts/222", "accountName": "Agency"},
        ]}
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await GoogleBusinessProfileNode.load_field_options("account_id", cred_data)
        assert len(result["options"]) == 2
        assert result["options"][0]["value"] == "accounts/111"

    @pytest.mark.asyncio
    async def test_location_options(self):
        cred_data = {"access_token": "tok", "expires_at": "2099-12-31T23:59:59Z"}
        payload = {"locations": [
            {"name": "locations/loc1", "title": "Store A",
             "storefrontAddress": {"locality": "SF", "administrativeArea": "CA"}},
        ]}
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=_resp(payload))
            result = await GoogleBusinessProfileNode.load_field_options(
                "location_id", cred_data, context={"account_id": "accounts/111"}
            )
        assert result["options"][0]["value"] == "locations/loc1"
        assert "Store A" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_location_without_account_empty(self):
        result = await GoogleBusinessProfileNode.load_field_options(
            "location_id", {"access_token": "tok", "expires_at": "2099-12-31T23:59:59Z"}
        )
        assert result["options"] == []

    @pytest.mark.asyncio
    async def test_unknown_field_empty(self):
        result = await GoogleBusinessProfileNode.load_field_options(
            "no_such_field", {"access_token": "tok", "expires_at": "2099-12-31T23:59:59Z"}
        )
        assert result["options"] == []

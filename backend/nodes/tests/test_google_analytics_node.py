"""
Unit tests for Google Analytics 4 (GA4) node.

Tests the GA4 node functionality with mocked API responses.
All 3 operations are tested: run_report, run_realtime_report, get_metadata.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from nodes.google_analytics_node import (
    GoogleAnalyticsNode,
    GoogleAnalyticsNodeConfig,
    GoogleAnalyticsOAuthCredential,
    GoogleAnalyticsRunReportConfig,
    GoogleAnalyticsRealtimeReportConfig,
    GoogleAnalyticsGetMetadataConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return GoogleAnalyticsOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create_response(status_code: int, json_data: dict):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data
        response.text = json.dumps(json_data)
        response.content = json.dumps(json_data).encode()
        response.raise_for_status = MagicMock()
        return response

    return _create_response


def create_node(config, credentials) -> GoogleAnalyticsNode:
    """Create a GoogleAnalyticsNode instance with the given config."""
    node_config = GoogleAnalyticsNodeConfig(config=config, credentials=credentials)
    return GoogleAnalyticsNode(
        node_id="test-node",
        node_type="automation-google-analytics",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


# ============================================================================
# Run Report Operation Tests
# ============================================================================


class TestRunReportOperation:
    """Test GA4 run_report operation."""

    @pytest.mark.asyncio
    async def test_run_report_success(self, mock_credentials, mock_httpx_response):
        """Test running a basic GA4 report."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            start_date="30daysAgo",
            end_date="today",
            dimensions="date",
            metrics="sessions,totalUsers,screenPageViews",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [
                    {"name": "sessions"},
                    {"name": "totalUsers"},
                    {"name": "screenPageViews"},
                ],
                "rows": [
                    {
                        "dimensionValues": [{"value": "20260301"}],
                        "metricValues": [
                            {"value": "150"},
                            {"value": "120"},
                            {"value": "450"},
                        ],
                    },
                    {
                        "dimensionValues": [{"value": "20260302"}],
                        "metricValues": [
                            {"value": "175"},
                            {"value": "140"},
                            {"value": "520"},
                        ],
                    },
                ],
                "rowCount": 2,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["row_count"] == 2
            assert result["headers"] == [
                "date",
                "sessions",
                "totalUsers",
                "screenPageViews",
            ]
            assert len(result["rows"]) == 2
            assert result["rows"][0]["date"] == "20260301"
            assert result["rows"][0]["sessions"] == "150"
            assert result["rows"][1]["totalUsers"] == "140"

    @pytest.mark.asyncio
    async def test_run_report_with_multiple_dimensions(
        self, mock_credentials, mock_httpx_response
    ):
        """Test report with multiple dimensions."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            start_date="2026-03-01",
            end_date="2026-03-15",
            dimensions="date, sessionSource, sessionMedium",
            metrics="sessions,conversions",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [
                    {"name": "date"},
                    {"name": "sessionSource"},
                    {"name": "sessionMedium"},
                ],
                "metricHeaders": [{"name": "sessions"}, {"name": "conversions"}],
                "rows": [
                    {
                        "dimensionValues": [
                            {"value": "20260301"},
                            {"value": "google"},
                            {"value": "organic"},
                        ],
                        "metricValues": [{"value": "85"}, {"value": "12"}],
                    },
                ],
                "rowCount": 1,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["row_count"] == 1
            assert "sessionSource" in result["headers"]
            assert result["rows"][0]["sessionSource"] == "google"
            assert result["rows"][0]["sessionMedium"] == "organic"
            assert result["metadata"]["dimension_headers"] == [
                "date",
                "sessionSource",
                "sessionMedium",
            ]
            assert result["metadata"]["metric_headers"] == ["sessions", "conversions"]

    @pytest.mark.asyncio
    async def test_run_report_with_comparison_dates(
        self, mock_credentials, mock_httpx_response
    ):
        """Test report with comparison date range for MoM analysis."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            start_date="2026-03-01",
            end_date="2026-03-31",
            compare_start_date="2026-02-01",
            compare_end_date="2026-02-28",
            dimensions="date",
            metrics="sessions",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [
                    {
                        "dimensionValues": [{"value": "20260301"}],
                        "metricValues": [{"value": "200"}],
                    },
                ],
                "rowCount": 1,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            # Verify the API was called with two date ranges
            call_args = mock_post.call_args
            request_body = call_args.kwargs["json"]
            assert len(request_body["dateRanges"]) == 2
            assert request_body["dateRanges"][0]["startDate"] == "2026-03-01"
            assert request_body["dateRanges"][1]["startDate"] == "2026-02-01"

    @pytest.mark.asyncio
    async def test_run_report_with_dimension_filter(
        self, mock_credentials, mock_httpx_response
    ):
        """Test report with dimension filter applied."""
        dim_filter = json.dumps(
            {"filter": {"fieldName": "country", "stringFilter": {"value": "US"}}}
        )
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date,country",
            metrics="sessions",
            dimension_filter=dim_filter,
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}, {"name": "country"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [],
                "rowCount": 0,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            call_args = mock_post.call_args
            request_body = call_args.kwargs["json"]
            assert "dimensionFilter" in request_body

    @pytest.mark.asyncio
    async def test_run_report_invalid_dimension_filter(self, mock_credentials):
        """Test report with invalid JSON dimension filter returns error."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
            dimension_filter="not valid json{{{",
        )
        node = create_node(config, mock_credentials)

        result = await node.execute({})

        assert "error" in result
        assert "dimension_filter" in result["error"]

    @pytest.mark.asyncio
    async def test_run_report_invalid_metric_filter(self, mock_credentials):
        """Test report with invalid JSON metric filter returns error."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
            metric_filter="bad json",
        )
        node = create_node(config, mock_credentials)

        result = await node.execute({})

        assert "error" in result
        assert "metric_filter" in result["error"]

    @pytest.mark.asyncio
    async def test_run_report_empty_result(self, mock_credentials, mock_httpx_response):
        """Test report that returns no rows."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [],
                "rowCount": 0,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["row_count"] == 0
            assert result["rows"] == []
            assert result["headers"] == ["date", "sessions"]

    @pytest.mark.asyncio
    async def test_run_report_custom_limit(self, mock_credentials, mock_httpx_response):
        """Test report with custom row limit."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
            limit="50",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await node.execute({})

            call_args = mock_post.call_args
            assert call_args.kwargs["json"]["limit"] == 50


# ============================================================================
# Realtime Report Operation Tests
# ============================================================================


class TestRealtimeReportOperation:
    """Test GA4 run_realtime_report operation."""

    @pytest.mark.asyncio
    async def test_realtime_report_success(self, mock_credentials, mock_httpx_response):
        """Test running a realtime report."""
        config = GoogleAnalyticsRealtimeReportConfig(
            property_id="123456789",
            dimensions="unifiedScreenName",
            metrics="activeUsers",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "unifiedScreenName"}],
                "metricHeaders": [{"name": "activeUsers"}],
                "rows": [
                    {
                        "dimensionValues": [{"value": "/home"}],
                        "metricValues": [{"value": "42"}],
                    },
                    {
                        "dimensionValues": [{"value": "/pricing"}],
                        "metricValues": [{"value": "15"}],
                    },
                ],
                "rowCount": 2,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["row_count"] == 2
            assert result["rows"][0]["unifiedScreenName"] == "/home"
            assert result["rows"][0]["activeUsers"] == "42"

    @pytest.mark.asyncio
    async def test_realtime_report_multiple_metrics(
        self, mock_credentials, mock_httpx_response
    ):
        """Test realtime report with multiple metrics."""
        config = GoogleAnalyticsRealtimeReportConfig(
            property_id="123456789",
            dimensions="country, city",
            metrics="activeUsers, screenPageViews",
            limit="10",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "country"}, {"name": "city"}],
                "metricHeaders": [{"name": "activeUsers"}, {"name": "screenPageViews"}],
                "rows": [
                    {
                        "dimensionValues": [{"value": "US"}, {"value": "New York"}],
                        "metricValues": [{"value": "25"}, {"value": "80"}],
                    },
                ],
                "rowCount": 1,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["rows"][0]["country"] == "US"
            assert result["rows"][0]["city"] == "New York"
            # Verify limit was passed
            call_args = mock_post.call_args
            assert call_args.kwargs["json"]["limit"] == 10


# ============================================================================
# Get Metadata Operation Tests
# ============================================================================


class TestGetMetadataOperation:
    """Test GA4 get_metadata operation."""

    @pytest.mark.asyncio
    async def test_get_metadata_success(self, mock_credentials, mock_httpx_response):
        """Test listing available dimensions and metrics."""
        config = GoogleAnalyticsGetMetadataConfig(property_id="123456789")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensions": [
                    {"apiName": "date", "uiName": "Date", "category": "Time"},
                    {"apiName": "city", "uiName": "City", "category": "Geography"},
                    {
                        "apiName": "sessionSource",
                        "uiName": "Session source",
                        "category": "Traffic source",
                    },
                ],
                "metrics": [
                    {
                        "apiName": "sessions",
                        "uiName": "Sessions",
                        "category": "Session",
                    },
                    {
                        "apiName": "totalUsers",
                        "uiName": "Total users",
                        "category": "User",
                    },
                    {
                        "apiName": "conversions",
                        "uiName": "Conversions",
                        "category": "Event",
                    },
                ],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert len(result["dimensions"]) == 3
            assert len(result["metrics"]) == 3
            assert result["dimensions"][0]["api_name"] == "date"
            assert result["dimensions"][0]["display_name"] == "Date"
            assert result["dimensions"][0]["category"] == "Time"
            assert result["metrics"][2]["api_name"] == "conversions"


# ============================================================================
# Credential and Edge Case Tests
# ============================================================================


class TestCredentialHandling:
    """Test credential validation and token refresh."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_error(self):
        """Test that missing credentials returns an error."""
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
        )
        node_config = GoogleAnalyticsNodeConfig(config=config, credentials=None)
        node = GoogleAnalyticsNode(
            node_id="test-node",
            node_type="automation-google-analytics",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        result = await node.execute({})

        assert "error" in result
        assert "credentials" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_expired_token_triggers_refresh(self, mock_httpx_response):
        """Test that expired tokens are refreshed before API call."""
        credentials = GoogleAnalyticsOAuthCredential(
            access_token="expired_token",
            refresh_token="mock_refresh_token",
            expires_at="2020-01-01T00:00:00Z",  # Already expired
            email="test@example.com",
        )
        config = GoogleAnalyticsRunReportConfig(
            property_id="123456789",
            dimensions="date",
            metrics="sessions",
        )
        node = create_node(config, credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "dimensionHeaders": [{"name": "date"}],
                "metricHeaders": [{"name": "sessions"}],
                "rows": [],
            },
        )

        with patch(
            "nodes.oauth.google_oauth.refresh_access_token", new_callable=AsyncMock
        ) as mock_refresh, patch("httpx.AsyncClient") as mock_client:
            mock_refresh.return_value = MagicMock(access_token="new_access_token")
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await node.execute({})

            mock_refresh.assert_called_once_with("mock_refresh_token")


# ============================================================================
# Load Field Options Tests
# ============================================================================


class TestLoadFieldOptions:
    """Test dynamic field option loading."""

    @pytest.mark.asyncio
    async def test_list_properties(self, mock_httpx_response):
        """Test loading GA4 property options."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "accountSummaries": [
                    {
                        "displayName": "Test Account",
                        "propertySummaries": [
                            {
                                "property": "properties/123456",
                                "displayName": "Main Website",
                            },
                            {"property": "properties/789012", "displayName": "Blog"},
                        ],
                    },
                    {
                        "displayName": "Client Account",
                        "propertySummaries": [
                            {
                                "property": "properties/345678",
                                "displayName": "Client Site",
                            },
                        ],
                    },
                ],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleAnalyticsNode.load_field_options(
                "property_id", credential_data
            )

            assert len(result["options"]) == 3
            assert result["options"][0]["value"] == "123456"
            assert "Main Website" in result["options"][0]["label"]
            assert "Test Account" in result["options"][0]["label"]
            assert result["options"][2]["value"] == "345678"

    @pytest.mark.asyncio
    async def test_list_properties_with_pagination(self, mock_httpx_response):
        """Test property listing returns next_page_token."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "accountSummaries": [
                    {
                        "displayName": "Account",
                        "propertySummaries": [
                            {"property": "properties/111", "displayName": "Site 1"},
                        ],
                    },
                ],
                "nextPageToken": "page2_token",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleAnalyticsNode.load_field_options(
                "property_id", credential_data
            )

            assert result["next_page_token"] == "page2_token"

    @pytest.mark.asyncio
    async def test_unknown_field_returns_empty(self):
        """Test that unknown field names return empty options."""
        result = await GoogleAnalyticsNode.load_field_options(
            "unknown_field",
            {"access_token": "token", "expires_at": "2099-12-31T23:59:59Z"},
        )

        assert result["options"] == []

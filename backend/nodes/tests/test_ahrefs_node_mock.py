"""
Mock tests for the Ahrefs API v3 node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Site Explorer: overview, domain rating, backlinks, broken backlinks, refdomains,
  anchors, organic keywords, organic competitors, top pages, paid pages,
  best by external links, linked domains, metrics history
- Keywords Explorer: overview, volume history, volume by country, matching terms,
  related terms, search suggestions
- SERP overview, batch analysis
- Site Audit: projects, page explorer
- Rank Tracker: overview
- Management: list projects, add keywords, add competitors
- Subscription: limits and usage
- Public: crawler IP ranges
- Error handling: API errors, missing credentials
- Dynamic options: project dropdowns
"""

import json
from pathlib import Path

import httpx
import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.ahrefs_node import (
    AhrefsNode,
    AhrefsNodeConfig,
    AhrefsAPIKeyCredential,
    AhrefsSiteOverviewConfig,
    AhrefsDomainRatingConfig,
    AhrefsBacklinksConfig,
    AhrefsBrokenBacklinksConfig,
    AhrefsRefDomainsConfig,
    AhrefsAnchorsConfig,
    AhrefsOrganicKeywordsConfig,
    AhrefsOrganicCompetitorsConfig,
    AhrefsTopPagesConfig,
    AhrefsPaidPagesConfig,
    AhrefsBestByExternalLinksConfig,
    AhrefsLinkedDomainsConfig,
    AhrefsMetricsHistoryConfig,
    AhrefsKeywordsOverviewConfig,
    AhrefsVolumeHistoryConfig,
    AhrefsVolumeByCountryConfig,
    AhrefsMatchingTermsConfig,
    AhrefsRelatedTermsConfig,
    AhrefsSearchSuggestionsConfig,
    AhrefsSerpOverviewConfig,
    AhrefsBatchAnalysisConfig,
    AhrefsSiteAuditProjectsConfig,
    AhrefsSiteAuditPageExplorerConfig,
    AhrefsRankTrackerOverviewConfig,
    AhrefsListProjectsConfig,
    AhrefsAddKeywordsConfig,
    AhrefsAddCompetitorsConfig,
    AhrefsLimitsAndUsageConfig,
    AhrefsCrawlerIpRangesConfig,
)


@pytest.fixture
def api_key_credentials():
    return AhrefsAPIKeyCredential(api_key="ahrefs_test_key_12345")


def create_ahrefs_node(config):
    return AhrefsNode(
        node_id="test-ahrefs-node",
        node_type="automation-ahrefs",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(config_obj, json_data, api_key_credentials, status_code=200):
    config = AhrefsNodeConfig(config=config_obj, credentials=api_key_credentials)
    node = create_ahrefs_node(config)
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# These bodies are copied verbatim from the provider's reference pages; each
# fixture records its source URL. Exercise the real HTTP serialization as well
# as the parser, so a mock cannot hide an unsupported method or body shape.
DOCUMENTED_RESPONSES = json.loads(
    (Path(__file__).parent / "fixtures/ahrefs/responses.json").read_text()
)


async def _run_documented(config_obj, credentials):
    requests = []

    def transport(request):
        requests.append(request)
        path = request.url.path.removeprefix("/v3/")
        return httpx.Response(200, json=DOCUMENTED_RESPONSES[path]["body"])

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(transport))

    node = create_ahrefs_node(AhrefsNodeConfig(config=config_obj, credentials=credentials))
    with patch("nodes.ahrefs_node.httpx.AsyncClient", side_effect=client):
        result = await node.execute({})
    assert result["status"] == "success"
    return result, requests


class TestAhrefsConformanceRegressions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [None, "", " \t ", "ad"])
    async def test_volume_country_filter_omits_blank_values(self, value, api_key_credentials):
        _, requests = await _run_documented(
            AhrefsVolumeByCountryConfig(keyword="ahrefs", countries=value), api_key_credentials,
        )
        request, = requests
        if value == "ad":
            assert request.url.params["countries"] == "ad"
        else:
            assert "countries" not in request.url.params

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [None, "", " \t ", "ae"])
    async def test_serp_filters_omit_blank_values(self, value, api_key_credentials):
        serp_type = "organic" if value == "ae" else value
        _, requests = await _run_documented(
            AhrefsSerpOverviewConfig(
                keyword="ahrefs", country="ad", select="country,position",
                comparison_countries=value, type=serp_type,
            ), api_key_credentials,
        )
        request, = requests
        if value == "ae":
            assert request.url.params["comparison_countries"] == "ae"
            assert request.url.params["type"] == "organic"
        else:
            assert "comparison_countries" not in request.url.params
            assert "type" not in request.url.params

    @pytest.mark.asyncio
    async def test_overview_combines_documented_endpoints(self, api_key_credentials):
        result, requests = await _run_documented(
            AhrefsSiteOverviewConfig(target="ahrefs.com", date="2023-05-18"),
            api_key_credentials,
        )
        assert [r.url.path for r in requests] == [
            "/v3/site-explorer/metrics", "/v3/site-explorer/domain-rating",
            "/v3/site-explorer/backlinks-stats",
        ]
        assert all(r.method == "GET" and r.url.params["date"] == "2023-05-18" for r in requests)
        assert result["data"]["metrics"]["org_traffic"] == 0
        assert result["data"]["metrics"]["live_refdomains"] == 0
        assert result["data"]["domain_rating"]["domain_rating"] == 0

    @pytest.mark.asyncio
    async def test_batch_posts_target_objects_and_field_array(self, api_key_credentials):
        _, requests = await _run_documented(
            AhrefsBatchAnalysisConfig(targets="ahrefs.com, yep.com"), api_key_credentials,
        )
        request, = requests
        assert request.method == "POST"
        assert not request.url.query
        body = json.loads(request.content)
        assert body["targets"] == [
            {"url": "ahrefs.com", "mode": "subdomains", "protocol": "both"},
            {"url": "yep.com", "mode": "subdomains", "protocol": "both"},
        ]
        assert body["select"] == ["url", "domain_rating", "org_traffic", "refdomains", "backlinks"]

    @pytest.mark.asyncio
    async def test_keywords_put_uses_query_project_and_locations(self, api_key_credentials):
        _, requests = await _run_documented(
            AhrefsAddKeywordsConfig(project_id="123", keywords="ahrefs, yep", country="us"),
            api_key_credentials,
        )
        request, = requests
        assert request.method == "PUT"
        assert request.url.path == "/v3/management/project-keywords"
        assert request.url.params["project_id"] == "123"
        assert json.loads(request.content) == {
            "keywords": [{"keyword": "ahrefs"}, {"keyword": "yep"}],
            "locations": [{"country": "us"}],
        }

    @pytest.mark.asyncio
    async def test_competitors_post_uses_target_objects(self, api_key_credentials):
        _, requests = await _run_documented(
            AhrefsAddCompetitorsConfig(project_id="123", competitors="yep.com", mode="domain"),
            api_key_credentials,
        )
        request, = requests
        assert request.method == "POST"
        assert request.url.path == "/v3/management/project-competitors"
        assert request.url.params["project_id"] == "123"
        assert json.loads(request.content) == {"competitors": [{"url": "yep.com", "mode": "domain"}]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("config", [
        AhrefsOrganicKeywordsConfig(target="ahrefs.com", date="2023-05-18"),
        AhrefsOrganicCompetitorsConfig(target="ahrefs.com", date="2023-05-18"),
        AhrefsTopPagesConfig(target="ahrefs.com", date="2023-05-18"),
        AhrefsPaidPagesConfig(target="ahrefs.com", date="2023-05-18"),
        AhrefsMatchingTermsConfig(keywords="ahrefs"),
        AhrefsRelatedTermsConfig(keywords="ahrefs"),
        AhrefsSearchSuggestionsConfig(keywords="ahrefs"),
        AhrefsRankTrackerOverviewConfig(project_id="123", date="2023-05-18"),
        AhrefsBestByExternalLinksConfig(target="ahrefs.com"),
        AhrefsLinkedDomainsConfig(target="ahrefs.com"),
    ])
    async def test_required_parameters_and_corrected_routes(self, config, api_key_credentials):
        node = create_ahrefs_node(AhrefsNodeConfig(config=config, credentials=api_key_credentials))
        with patch("nodes.ahrefs_node._ahrefs_request", new=AsyncMock(
            return_value={"status": "success"},
        )) as send:
            await node.execute({})
        request = send.await_args.kwargs
        assert request["params"]["select"]
        if hasattr(config, "date"):
            assert str(request["params"]["date"]) == "2023-05-18"
        if config.operation == "rank_tracker_overview":
            assert request["params"]["device"] == "desktop"
        if config.operation == "best_by_external_links":
            assert send.await_args.args[2] == "/site-explorer/pages-by-backlinks"
        if config.operation == "linked_domains":
            assert send.await_args.args[2] == "/site-explorer/linkeddomains"


# ============================================================================
# Site Explorer
# ============================================================================


class TestAhrefsSiteExplorerMock:
    @pytest.mark.asyncio
    async def test_site_overview(self, api_key_credentials):
        result = await _run(
            AhrefsSiteOverviewConfig(date="2023-05-18", target="ahrefs.com"),
            {"metrics": {"domain_rating": 92, "backlinks": 100}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "site_overview"
        assert result["data"]["metrics"]["domain_rating"] == 92

    @pytest.mark.asyncio
    async def test_domain_rating(self, api_key_credentials):
        result = await _run(
            AhrefsDomainRatingConfig(date="2023-05-18", target="ahrefs.com"),
            {"domain_rating": {"domain_rating": 92}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "domain_rating"

    @pytest.mark.asyncio
    async def test_backlinks(self, api_key_credentials):
        result = await _run(
            AhrefsBacklinksConfig(target="ahrefs.com", limit="10"),
            {"backlinks": [{"url_from": "a.com"}, {"url_from": "b.com"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "backlinks"
        assert len(result["data"]["backlinks"]) == 2

    @pytest.mark.asyncio
    async def test_broken_backlinks(self, api_key_credentials):
        result = await _run(
            AhrefsBrokenBacklinksConfig(target="ahrefs.com"),
            {"backlinks": [{"url_to": "dead.com/404"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "broken_backlinks"

    @pytest.mark.asyncio
    async def test_refdomains(self, api_key_credentials):
        result = await _run(
            AhrefsRefDomainsConfig(target="ahrefs.com"),
            {"refdomains": [{"domain": "x.com"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "refdomains"

    @pytest.mark.asyncio
    async def test_anchors(self, api_key_credentials):
        result = await _run(
            AhrefsAnchorsConfig(target="ahrefs.com"),
            {"anchors": [{"anchor": "seo tool"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "anchors"

    @pytest.mark.asyncio
    async def test_organic_keywords(self, api_key_credentials):
        result = await _run(
            AhrefsOrganicKeywordsConfig(date="2023-05-18", target="ahrefs.com", country="us"),
            {"keywords": [{"keyword": "seo", "volume": 1000}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "organic_keywords"

    @pytest.mark.asyncio
    async def test_organic_competitors(self, api_key_credentials):
        result = await _run(
            AhrefsOrganicCompetitorsConfig(date="2023-05-18", target="ahrefs.com"),
            {"competitors": [{"competitor_domain": "semrush.com"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "organic_competitors"

    @pytest.mark.asyncio
    async def test_top_pages(self, api_key_credentials):
        result = await _run(
            AhrefsTopPagesConfig(date="2023-05-18", target="ahrefs.com"),
            {"pages": [{"url": "ahrefs.com/blog"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "top_pages"

    @pytest.mark.asyncio
    async def test_paid_pages(self, api_key_credentials):
        result = await _run(
            AhrefsPaidPagesConfig(date="2023-05-18", target="ahrefs.com"),
            {"pages": [{"url": "ahrefs.com/pricing"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "paid_pages"

    @pytest.mark.asyncio
    async def test_best_by_external_links(self, api_key_credentials):
        result = await _run(
            AhrefsBestByExternalLinksConfig(target="ahrefs.com"),
            {"pages": [{"url": "ahrefs.com", "external_links": 500}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "best_by_external_links"

    @pytest.mark.asyncio
    async def test_linked_domains(self, api_key_credentials):
        result = await _run(
            AhrefsLinkedDomainsConfig(target="ahrefs.com"),
            {"domains": [{"domain": "twitter.com"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "linked_domains"

    @pytest.mark.asyncio
    async def test_metrics_history(self, api_key_credentials):
        result = await _run(
            AhrefsMetricsHistoryConfig(target="ahrefs.com"),
            {"metrics": [{"date": "2026-01-01", "org_traffic": 1000}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "metrics_history"


# ============================================================================
# Keywords Explorer
# ============================================================================


class TestAhrefsKeywordsExplorerMock:
    @pytest.mark.asyncio
    async def test_keywords_overview(self, api_key_credentials):
        result = await _run(
            AhrefsKeywordsOverviewConfig(keywords="seo, backlinks"),
            {"keywords": [{"keyword": "seo", "volume": 1000}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "keywords_overview"

    @pytest.mark.asyncio
    async def test_volume_history(self, api_key_credentials):
        result = await _run(
            AhrefsVolumeHistoryConfig(keyword="seo"),
            {"metrics": [{"date": "2026-01-01", "volume": 900}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "volume_history"

    @pytest.mark.asyncio
    async def test_volume_by_country(self, api_key_credentials):
        result = await _run(
            AhrefsVolumeByCountryConfig(keyword="seo"),
            {"metrics": [{"country": "us", "volume": 500}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "volume_by_country"

    @pytest.mark.asyncio
    async def test_matching_terms(self, api_key_credentials):
        result = await _run(
            AhrefsMatchingTermsConfig(keywords="seo"),
            {"keywords": [{"keyword": "seo tools"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "matching_terms"

    @pytest.mark.asyncio
    async def test_related_terms(self, api_key_credentials):
        result = await _run(
            AhrefsRelatedTermsConfig(keywords="seo"),
            {"keywords": [{"keyword": "search engine optimization"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "related_terms"

    @pytest.mark.asyncio
    async def test_search_suggestions(self, api_key_credentials):
        result = await _run(
            AhrefsSearchSuggestionsConfig(keywords="seo"),
            {"keywords": [{"keyword": "seo for beginners"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "search_suggestions"


# ============================================================================
# SERP / Batch
# ============================================================================


class TestAhrefsSerpBatchMock:
    @pytest.mark.asyncio
    async def test_serp_overview(self, api_key_credentials):
        result = await _run(
            AhrefsSerpOverviewConfig(keyword="seo"),
            {"positions": [{"position": 1, "url": "ahrefs.com"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "serp_overview"

    @pytest.mark.asyncio
    async def test_batch_analysis(self, api_key_credentials):
        result = await _run(
            AhrefsBatchAnalysisConfig(targets="ahrefs.com, semrush.com"),
            {"targets": [{"target": "ahrefs.com", "domain_rating": 92}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "batch_analysis"


# ============================================================================
# Site Audit
# ============================================================================


class TestAhrefsSiteAuditMock:
    @pytest.mark.asyncio
    async def test_site_audit_projects(self, api_key_credentials):
        result = await _run(
            AhrefsSiteAuditProjectsConfig(),
            {"projects": [{"id": "p1", "name": "My Site"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "site_audit_projects"

    @pytest.mark.asyncio
    async def test_site_audit_page_explorer(self, api_key_credentials):
        result = await _run(
            AhrefsSiteAuditPageExplorerConfig(project_id="p1"),
            {"pages": [{"url": "ahrefs.com", "issues": 2}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "site_audit_page_explorer"


# ============================================================================
# Rank Tracker / Management
# ============================================================================


class TestAhrefsRankTrackerManagementMock:
    @pytest.mark.asyncio
    async def test_rank_tracker_overview(self, api_key_credentials):
        result = await _run(
            AhrefsRankTrackerOverviewConfig(date="2023-05-18", project_id="p1"),
            {"overview": {"visibility": 45.2}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "rank_tracker_overview"

    @pytest.mark.asyncio
    async def test_list_projects(self, api_key_credentials):
        result = await _run(
            AhrefsListProjectsConfig(),
            {"projects": [{"id": "p1", "name": "My Site"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_projects"

    @pytest.mark.asyncio
    async def test_add_keywords(self, api_key_credentials):
        result = await _run(
            AhrefsAddKeywordsConfig(project_id="p1", keywords="seo, backlinks"),
            {"added": 2},
            api_key_credentials,
            status_code=200,
        )
        assert result["status"] == "success"
        assert result["action"] == "add_keywords"

    @pytest.mark.asyncio
    async def test_add_competitors(self, api_key_credentials):
        result = await _run(
            AhrefsAddCompetitorsConfig(project_id="p1", competitors="semrush.com"),
            {"added": 1},
            api_key_credentials,
            status_code=200,
        )
        assert result["status"] == "success"
        assert result["action"] == "add_competitors"


# ============================================================================
# Subscription / Public
# ============================================================================


class TestAhrefsSubscriptionPublicMock:
    @pytest.mark.asyncio
    async def test_limits_and_usage(self, api_key_credentials):
        result = await _run(
            AhrefsLimitsAndUsageConfig(),
            {"limits_and_usage": {"subscription": "Lite", "units_limit_api_key": 1000000,
                                  "units_usage_api_key": 5000}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "limits_and_usage"
        assert result["data"]["limits_and_usage"]["units_limit_api_key"] == 1000000

    @pytest.mark.asyncio
    async def test_crawler_ip_ranges(self, api_key_credentials):
        result = await _run(
            AhrefsCrawlerIpRangesConfig(),
            {"ips": ["54.36.148.0/24"]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "crawler_ip_ranges"


# ============================================================================
# Error handling
# ============================================================================


class TestAhrefsErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = AhrefsNodeConfig(
            config=AhrefsDomainRatingConfig(date="2023-05-18", target="ahrefs.com"),
            credentials=api_key_credentials,
        )
        node = create_ahrefs_node(config)
        mock_client = create_mock_client(401, {"error": "Invalid API token"})
        with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "401" in result["error"]
        assert "Invalid API token" not in result["error"]

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, api_key_credentials):
        config = AhrefsNodeConfig(
            config=AhrefsBacklinksConfig(target="ahrefs.com"),
            credentials=api_key_credentials,
        )
        node = create_ahrefs_node(config)
        mock_client = create_mock_client(429, {"error": "Too Many Requests"})
        with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 429

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = AhrefsNodeConfig(config=AhrefsLimitsAndUsageConfig(), credentials=None)
        node = create_ahrefs_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [302, 401, 403, 429, 500])
    async def test_non_2xx_never_succeeds_or_reflects_provider_secret(self, status_code):
        from nodes.ahrefs_node import _ahrefs_request

        secret = "sentinel_api_key_never_return"
        response = create_mock_response(status_code, {"error": f"echo {secret}"})
        response.text = f"<html>{secret}</html>"
        client = create_mock_client()
        client.request = AsyncMock(return_value=response)
        with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=client):
            result = await _ahrefs_request(secret, "GET", "/management/projects")
        assert result["status"] == "error"
        assert result["status_code"] == status_code
        assert secret not in str(result)
        assert secret not in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", ["", "<html>login</html>"])
    async def test_invalid_json_200_is_an_error(self, body):
        from nodes.ahrefs_node import _ahrefs_request

        response = create_mock_response(200)
        response.text = body
        response.json = Mock(side_effect=ValueError("invalid JSON"))
        client = create_mock_client()
        client.request = AsyncMock(return_value=response)
        with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=client):
            result = await _ahrefs_request("test-key", "GET", "/management/projects")
        assert result["status"] == "error"
        assert "raw" not in str(result)
        if body:
            assert body not in str(result)

    @pytest.mark.asyncio
    async def test_transport_exception_does_not_reflect_request_details(self):
        from nodes.ahrefs_node import _ahrefs_request

        client = create_mock_client()
        client.request = AsyncMock(side_effect=RuntimeError("echo sentinel_api_key_never_return"))
        with patch("nodes.ahrefs_node.httpx.AsyncClient", return_value=client):
            result = await _ahrefs_request("sentinel_api_key_never_return", "GET", "/management/projects")
        assert result["status"] == "error"
        assert "sentinel_api_key_never_return" not in str(result)


# ============================================================================
# Dynamic options
# ============================================================================


class TestAhrefsDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_rank_tracker_project_options(self):
        with patch(
            "nodes.ahrefs_node._ahrefs_request",
            return_value={
                "status": "success",
                "data": {"projects": [{"project_id": "p1", "project_name": "My Site"}]},
            },
        ):
            result = await AhrefsNode.load_field_options(
                field_name="project_id", credential_data={"api_key": "ahrefs_test"},
                context={}, page_token=None, search="My",
            )
        assert "options" in result
        assert result["options"][0]["value"] == "p1"
        assert result["options"][0]["label"] == "My Site"

    @pytest.mark.asyncio
    async def test_load_site_audit_project_options(self):
        with patch(
            "nodes.ahrefs_node._ahrefs_request",
            return_value={
                "status": "success",
                "data": {"healthscores": [{"project_id": "sa1", "project_name": "My Audit"}]},
            },
        ):
            result = await AhrefsNode.load_field_options(
                field_name="site_audit_project_id", credential_data={"api_key": "ahrefs_test"},
                context={}, page_token=None, search=None,
            )
        assert result["options"][0]["value"] == "sa1"
        assert result["options"][0]["label"] == "My Audit"

    @pytest.mark.asyncio
    async def test_load_options_no_credential(self):
        result = await AhrefsNode.load_field_options(
            field_name="project_id", credential_data={}, context={}, page_token=None, search=None,
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await AhrefsNode.load_field_options(
            field_name="target", credential_data={"api_key": "ahrefs_test"},
            context={}, page_token=None, search=None,
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_rejected_key_is_not_an_empty_project_list(self):
        with patch(
            "nodes.ahrefs_node._ahrefs_request",
            return_value={"status": "error", "error": "Ahrefs rejected the API key (HTTP 401)"},
        ):
            with pytest.raises(ValueError, match="HTTP 401"):
                await AhrefsNode.load_field_options(
                    field_name="project_id", credential_data={"api_key": "invalid"},
                    context={}, page_token=None, search=None,
                )

    @pytest.mark.asyncio
    async def test_actual_lookup_dispatcher_contract_uses_supplied_credential(self):
        from nodes.core.run_op import run_node_lookup

        with patch("nodes.core.run_op.resolve_operation_credential", new=AsyncMock(
            return_value={"api_key": "supplied-key"}
        )), patch("utils.credential_approval.admit_lookup", new=AsyncMock(return_value=None)), patch.object(
            AhrefsNode, "freshen_credential", new=AsyncMock(return_value={"api_key": "supplied-key"})
        ), patch("nodes.ahrefs_node._ahrefs_request", new=AsyncMock(return_value={
            "status": "success",
            "data": {"projects": [{"project_id": "p1", "project_name": "My Site"}]},
        })) as request:
            result = await run_node_lookup(
                node_type="automation-ahrefs", field_name="project_id", credential_id="cred-1",
                user_id="user-1", pool=Mock(), search="  My  ", page_token=None,
            )
        assert result["options"] == [{"value": "p1", "label": "My Site"}]
        assert request.await_args.args[0] == "supplied-key"


class TestAhrefsConnectionEvidence:
    @pytest.mark.asyncio
    async def test_authenticated_zero_unit_probe_accepts_key(self):
        from nodes.core.connection_evidence import collect_evidence

        with patch("nodes.ahrefs_node._ahrefs_request", new=AsyncMock(return_value={
            "status": "success",
            "data": {"limits_and_usage": {"subscription": "Free"}},
            "status_code": 200,
        })) as request:
            result = await collect_evidence(
                node_type="automation-ahrefs", credential_data={"api_key": "test-key"},
                user_id="user-1", pool=Mock(),
            )
        assert result.reachable is True
        assert result.account_label == "Free"
        assert request.await_args.args[:3] == ("test-key", "GET", "/subscription-info/limits-and-usage")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [
        {"other": "JSON but not usage"},
        {"limits_and_usage": []},
        {"limits_and_usage": {"subscription": "  "}},
        {"limits_and_usage": {"subscription": "Free"}, "error": {"code": "bad_key"}},
        {"limits_and_usage": {"subscription": "Free", "error": "not accepted"}},
        {"limits_and_usage": {"subscription": "Free"}, "success": False},
        {"limits_and_usage": {"subscription": "Free"}, "status": "error"},
    ])
    async def test_malformed_or_conflicting_200_cannot_verify_key(self, data):
        from nodes.core.connection_evidence import collect_evidence

        with patch("nodes.ahrefs_node._ahrefs_request", new=AsyncMock(return_value={
            "status": "success", "data": data, "status_code": 200,
        })):
            result = await collect_evidence(
                node_type="automation-ahrefs", credential_data={"api_key": "test-key"},
                user_id="user-1", pool=Mock(),
            )
        assert result.reachable is not True

    @pytest.mark.asyncio
    async def test_rejected_key_is_not_reported_working(self):
        from nodes.core.connection_evidence import collect_evidence

        with patch("nodes.ahrefs_node._ahrefs_request", new=AsyncMock(return_value={
            "status": "error", "error": "Ahrefs rejected the API key (HTTP 401)", "status_code": 401,
        })):
            result = await collect_evidence(
                node_type="automation-ahrefs", credential_data={"api_key": "bad-key"},
                user_id="user-1", pool=Mock(),
            )
        assert result.reachable is False

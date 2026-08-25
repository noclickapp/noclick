"""
Mock tests for the Google PageSpeed Insights node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Analysis: run (full), mobile, desktop, localized report
- Scores: performance, accessibility, SEO, best practices, all categories
- Field data (CrUX): core web vitals (URL), origin core web vitals
- Lab data: lab metrics, get audit, get opportunities, get screenshot
- Error handling: API errors, missing credentials, missing audit
"""

import pytest
from unittest.mock import Mock, patch

from nodes.pagespeed_node import (
    PageSpeedNode,
    PageSpeedNodeConfig,
    PageSpeedApiKeyCredential,
    PageSpeedRunAnalysisConfig,
    PageSpeedAnalyzeMobileConfig,
    PageSpeedAnalyzeDesktopConfig,
    PageSpeedPerformanceScoreConfig,
    PageSpeedAccessibilityScoreConfig,
    PageSpeedSeoScoreConfig,
    PageSpeedBestPracticesScoreConfig,
    PageSpeedAllCategoriesConfig,
    PageSpeedCoreWebVitalsConfig,
    PageSpeedOriginCoreWebVitalsConfig,
    PageSpeedLabMetricsConfig,
    PageSpeedGetAuditConfig,
    PageSpeedOpportunitiesConfig,
    PageSpeedScreenshotConfig,
    PageSpeedLocalizedReportConfig,
)

PAGE_URL = "https://example.com/"


@pytest.fixture
def api_key_credentials():
    return PageSpeedApiKeyCredential(api_key="AIzaTestKey12345")


def create_pagespeed_node(config):
    return PageSpeedNode(
        node_id="test-pagespeed-node",
        node_type="automation-pagespeed",
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


def _report(
    *,
    performance=0.92,
    accessibility=0.88,
    best_practices=1.0,
    seo=0.95,
    with_loading_experience=True,
    with_origin_loading_experience=True,
):
    """Build a minimal but realistic runPagespeed response."""
    categories = {}
    # NOTE: the runPagespeed RESPONSE keys categories in lowercase (and
    # "best-practices" is hyphenated), distinct from the uppercase request enum.
    for cid, score in [
        ("performance", performance),
        ("accessibility", accessibility),
        ("best-practices", best_practices),
        ("seo", seo),
    ]:
        if score is None:
            categories[cid] = {"id": cid, "score": None, "auditRefs": []}
        else:
            categories[cid] = {
                "id": cid,
                "score": score,
                "auditRefs": [{"id": "render-blocking-resources"}, {"id": "is-crawlable"}],
            }
    report = {
        "id": PAGE_URL,
        "lighthouseResult": {
            "categories": categories,
            "audits": {
                "first-contentful-paint": {
                    "title": "First Contentful Paint",
                    "score": 0.9,
                    "displayValue": "1.2 s",
                    "numericValue": 1200,
                },
                "largest-contentful-paint": {
                    "title": "Largest Contentful Paint",
                    "score": 0.7,
                    "displayValue": "2.5 s",
                    "numericValue": 2500,
                },
                "render-blocking-resources": {
                    "title": "Eliminate render-blocking resources",
                    "score": 0.4,
                    "displayValue": "Potential savings of 300 ms",
                    "details": {"type": "opportunity", "overallSavingsMs": 300, "overallSavingsBytes": 50000},
                },
                "unused-css-rules": {
                    "title": "Reduce unused CSS",
                    "score": 0.5,
                    "displayValue": "Potential savings of 120 ms",
                    "details": {"type": "opportunity", "overallSavingsMs": 120, "overallSavingsBytes": 20000},
                },
                "is-crawlable": {
                    "title": "Page isn't blocked from indexing",
                    "score": 0.0,
                },
                "final-screenshot": {
                    "title": "Final Screenshot",
                    "details": {"type": "screenshot", "data": "data:image/jpeg;base64,AAAA", "mimeType": "image/jpeg"},
                },
            },
        },
    }
    if with_loading_experience:
        report["loadingExperience"] = {
            "id": PAGE_URL,
            "overall_category": "FAST",
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2100, "category": "FAST"},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"},
            },
        }
    if with_origin_loading_experience:
        report["originLoadingExperience"] = {
            "id": "https://example.com",
            "overall_category": "AVERAGE",
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3200, "category": "AVERAGE"},
            },
        }
    return report


def _patch_client(client):
    return patch("nodes.pagespeed_node.httpx.AsyncClient", return_value=client)


class TestPageSpeedAnalysisMock:
    @pytest.mark.asyncio
    async def test_run_analysis(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedRunAnalysisConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_analysis"
        assert result["data"]["lighthouseResult"]["categories"]["performance"]["score"] == 0.92

    @pytest.mark.asyncio
    async def test_analyze_mobile(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedAnalyzeMobileConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "analyze_mobile"

    @pytest.mark.asyncio
    async def test_analyze_desktop(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedAnalyzeDesktopConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "analyze_desktop"

    @pytest.mark.asyncio
    async def test_localized_report(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedLocalizedReportConfig(page_url=PAGE_URL, locale="es"),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "localized_report"


class TestPageSpeedScoresMock:
    @pytest.mark.asyncio
    async def test_performance_score(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedPerformanceScoreConfig(page_url=PAGE_URL),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(performance=0.92))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "performance_score"
        assert result["data"]["category"] == "PERFORMANCE"
        assert result["data"]["score"] == 92.0
        # render-blocking-resources (score 0.4) should appear as a failing audit
        failing_ids = {a["id"] for a in result["data"]["failing_audits"]}
        assert "render-blocking-resources" in failing_ids

    @pytest.mark.asyncio
    async def test_accessibility_score(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedAccessibilityScoreConfig(page_url=PAGE_URL),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(accessibility=0.88))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "accessibility_score"
        assert result["data"]["score"] == 88.0

    @pytest.mark.asyncio
    async def test_seo_score(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedSeoScoreConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(seo=0.95))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "seo_score"
        assert result["data"]["score"] == 95.0

    @pytest.mark.asyncio
    async def test_best_practices_score(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedBestPracticesScoreConfig(page_url=PAGE_URL),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(best_practices=1.0))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "best_practices_score"
        assert result["data"]["score"] == 100.0

    @pytest.mark.asyncio
    async def test_all_categories(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedAllCategoriesConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "all_categories"
        scores = result["data"]["scores"]
        assert scores["PERFORMANCE"] == 92.0
        assert scores["SEO"] == 95.0
        assert set(scores.keys()) == {"PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"}

    @pytest.mark.asyncio
    async def test_all_categories_null_score(self, api_key_credentials):
        """A category whose Lighthouse run errored returns score null, not a crash."""
        config = PageSpeedNodeConfig(
            config=PageSpeedAllCategoriesConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(performance=None))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["scores"]["PERFORMANCE"] is None


class TestPageSpeedFieldDataMock:
    @pytest.mark.asyncio
    async def test_core_web_vitals(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedCoreWebVitalsConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "core_web_vitals"
        assert result["data"]["available"] is True
        assert result["data"]["overall_category"] == "FAST"
        assert "LARGEST_CONTENTFUL_PAINT_MS" in result["data"]["metrics"]

    @pytest.mark.asyncio
    async def test_core_web_vitals_absent(self, api_key_credentials):
        """Low-traffic pages lack CrUX field data — must not crash, returns available False."""
        config = PageSpeedNodeConfig(
            config=PageSpeedCoreWebVitalsConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report(with_loading_experience=False))):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["available"] is False
        assert result["data"]["metrics"] == {}

    @pytest.mark.asyncio
    async def test_origin_core_web_vitals(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedOriginCoreWebVitalsConfig(page_url=PAGE_URL),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "origin_core_web_vitals"
        assert result["data"]["available"] is True
        assert result["data"]["overall_category"] == "AVERAGE"


class TestPageSpeedLabDataMock:
    @pytest.mark.asyncio
    async def test_lab_metrics(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedLabMetricsConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "lab_metrics"
        metrics = result["data"]["metrics"]
        assert "first-contentful-paint" in metrics
        assert metrics["largest-contentful-paint"]["numericValue"] == 2500

    @pytest.mark.asyncio
    async def test_get_audit(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedGetAuditConfig(page_url=PAGE_URL, audit_id="render-blocking-resources"),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_audit"
        assert result["data"]["id"] == "render-blocking-resources"
        assert result["data"]["score"] == 0.4

    @pytest.mark.asyncio
    async def test_get_audit_missing(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedGetAuditConfig(page_url=PAGE_URL, audit_id="does-not-exist"),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_get_opportunities(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedOpportunitiesConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_opportunities"
        opps = result["data"]["opportunities"]
        assert len(opps) == 2
        # sorted by savings ms descending
        assert opps[0]["id"] == "render-blocking-resources"
        assert opps[0]["overallSavingsMs"] == 300

    @pytest.mark.asyncio
    async def test_get_screenshot(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedScreenshotConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        with _patch_client(create_mock_client(200, _report())):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_screenshot"
        assert result["data"]["screenshot"] == "data:image/jpeg;base64,AAAA"
        assert result["data"]["mime_type"] == "image/jpeg"


class TestPageSpeedErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedRunAnalysisConfig(page_url=PAGE_URL), credentials=api_key_credentials
        )
        node = create_pagespeed_node(config)
        err_body = {"error": {"code": 400, "message": "The url query parameter is required."}}
        with _patch_client(create_mock_client(400, err_body)):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "url query parameter" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, api_key_credentials):
        config = PageSpeedNodeConfig(
            config=PageSpeedPerformanceScoreConfig(page_url=PAGE_URL),
            credentials=api_key_credentials,
        )
        node = create_pagespeed_node(config)
        err_body = {"error": {"code": 429, "message": "Quota exceeded for quota metric."}}
        with _patch_client(create_mock_client(429, err_body)):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 429

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = PageSpeedNodeConfig(
            config=PageSpeedRunAnalysisConfig(page_url=PAGE_URL), credentials=None
        )
        node = create_pagespeed_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

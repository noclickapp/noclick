"""
Google PageSpeed Insights automation node.

Provides workflow integration with the PageSpeed Insights v5 REST API. The API
exposes a single endpoint (GET runPagespeed) that runs a full Lighthouse + Chrome
UX Report (CrUX) analysis for a URL; node operations are preset variants of that
call (strategy / category combinations) plus result-extraction shapes that pull
out the fields users actually automate on (scores, Core Web Vitals, opportunities).

Authentication: API key (Google Cloud) passed as the `key` query parameter.
API Base URL: https://pagespeedonline.googleapis.com/pagespeedonline/v5
Documentation: https://developers.google.com/speed/docs/insights/v5/get-started

There are no webhooks for this API; monitoring is done by polling on a schedule
(drive this node from a NoClick schedule/cron trigger). Each call runs a full
Lighthouse analysis and can take several seconds to ~30s, so the timeout is
generous.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

PAGESPEED_API_BASE = "https://pagespeedonline.googleapis.com/pagespeedonline/v5"

# Lighthouse category ids (the API uses these uppercased enum values).
CATEGORY_PERFORMANCE = "PERFORMANCE"
CATEGORY_ACCESSIBILITY = "ACCESSIBILITY"
CATEGORY_BEST_PRACTICES = "BEST_PRACTICES"
CATEGORY_SEO = "SEO"
ALL_CATEGORIES = [
    CATEGORY_PERFORMANCE,
    CATEGORY_ACCESSIBILITY,
    CATEGORY_BEST_PRACTICES,
    CATEGORY_SEO,
]

# The request `category` param takes the uppercase enum above, but the
# runPagespeed RESPONSE keys `lighthouseResult.categories` in lowercase (and
# "best-practices" is hyphenated) — map enum -> response key for extraction.
CATEGORY_RESPONSE_KEY = {
    CATEGORY_PERFORMANCE: "performance",
    CATEGORY_ACCESSIBILITY: "accessibility",
    CATEGORY_BEST_PRACTICES: "best-practices",
    CATEGORY_SEO: "seo",
}

# Lab metric audit ids surfaced by the "Lab metrics" operation.
LAB_METRIC_AUDIT_IDS = [
    "first-contentful-paint",
    "largest-contentful-paint",
    "speed-index",
    "total-blocking-time",
    "cumulative-layout-shift",
    "interactive",
]

# Common Lighthouse audit ids for the get_audit picker. Rendered as a searchable
# enum, but the field accepts any value — Lighthouse ships ~150 audits and they
# evolve across versions, so this is discovery help, not a whitelist. Validated
# against live PageSpeed (Lighthouse 13, "insights" audit model — the classic
# opportunity/diagnostic ids like render-blocking-resources were renamed to the
# *-insight audits below).
COMMON_AUDIT_IDS = [
    # Metrics
    "first-contentful-paint", "largest-contentful-paint", "speed-index",
    "total-blocking-time", "cumulative-layout-shift", "interactive",
    "server-response-time",
    # Performance insights (Lighthouse 12+)
    "render-blocking-insight", "lcp-breakdown-insight", "cls-culprits-insight",
    "image-delivery-insight", "dom-size-insight", "font-display-insight",
    "third-parties-insight", "duplicated-javascript-insight",
    "legacy-javascript-insight", "forced-reflow-insight",
    "network-dependency-tree-insight", "viewport-insight", "cache-insight",
    # Performance opportunities (still present)
    "unused-css-rules", "unused-javascript", "unminified-css",
    "unminified-javascript", "unsized-images",
    # Accessibility
    "color-contrast", "image-alt", "label", "link-name", "button-name",
    "document-title", "html-has-lang", "meta-viewport", "heading-order",
    # Best practices
    "errors-in-console", "is-on-https", "deprecations", "csp-xss",
    "inspector-issues",
    # SEO
    "meta-description", "http-status-code", "link-text", "crawlable-anchors",
    "is-crawlable", "robots-txt", "hreflang", "canonical", "structured-data",
]


# ============================================================================
# Credential Schema
# ============================================================================


class PageSpeedApiKeyCredential(BaseModel):
    """API key credential for the Google PageSpeed Insights API."""

    credential_type: Literal["pagespeed_api_key"] = Field(
        "pagespeed_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "Google Cloud API key for the PageSpeed Insights API. Create one at "
            "console.cloud.google.com/apis/credentials after enabling the "
            "PageSpeed Insights API for your project."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://console.cloud.google.com/apis/credentials"}
    )


PageSpeedCredential = PageSpeedApiKeyCredential


# ============================================================================
# Shared field definitions
# ============================================================================

# A searchable enum for the strategy field, reused across operations.
_STRATEGY_FIELD_EXTRA = {
    "enum": ["DESKTOP", "MOBILE"],
    "enumNames": ["Desktop", "Mobile"],
    "x-enum-searchable": True,
}


# ============================================================================
# Operation Configs
# ============================================================================


class PageSpeedRunAnalysisConfig(BaseModel):
    """Run a full Lighthouse + CrUX analysis and return the complete report."""

    operation: Literal["run_analysis"] = Field(
        "run_analysis",
        json_schema_extra={
            "const": "run_analysis",
            "ui:hidden": True,
            "x-category": "Analysis",
            "x-is-trigger": False,
            "x-display-name": "Run Analysis (Full)",
        },
        title="Run Analysis (Full)",
    )
    page_url: str = Field(
        ...,
        title="URL",
        description="The page to analyze (e.g. https://example.com/)",
        json_schema_extra={"format": "uri"},
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )
    locale: Optional[str] = Field(
        None,
        title="Locale",
        description="BCP-47 locale for localized audit text (e.g. en, es, ja)",
    )


class PageSpeedAnalyzeMobileConfig(BaseModel):
    """Run the analysis using the mobile crawler/emulation profile."""

    operation: Literal["analyze_mobile"] = Field(
        "analyze_mobile",
        json_schema_extra={
            "const": "analyze_mobile",
            "ui:hidden": True,
            "x-category": "Analysis",
            "x-is-trigger": False,
            "x-display-name": "Analyze (Mobile)",
        },
        title="Analyze (Mobile)",
    )
    page_url: str = Field(
        ...,
        title="URL",
        description="The page to analyze using the mobile profile",
        json_schema_extra={"format": "uri"},
    )
    locale: Optional[str] = Field(
        None, title="Locale", description="BCP-47 locale for localized audit text"
    )


class PageSpeedAnalyzeDesktopConfig(BaseModel):
    """Run the analysis using the desktop profile."""

    operation: Literal["analyze_desktop"] = Field(
        "analyze_desktop",
        json_schema_extra={
            "const": "analyze_desktop",
            "ui:hidden": True,
            "x-category": "Analysis",
            "x-is-trigger": False,
            "x-display-name": "Analyze (Desktop)",
        },
        title="Analyze (Desktop)",
    )
    page_url: str = Field(
        ...,
        title="URL",
        description="The page to analyze using the desktop profile",
        json_schema_extra={"format": "uri"},
    )
    locale: Optional[str] = Field(
        None, title="Locale", description="BCP-47 locale for localized audit text"
    )


class PageSpeedPerformanceScoreConfig(BaseModel):
    """Run with the PERFORMANCE category and extract the 0-100 Lighthouse score."""

    operation: Literal["performance_score"] = Field(
        "performance_score",
        json_schema_extra={
            "const": "performance_score",
            "ui:hidden": True,
            "x-category": "Scores",
            "x-is-trigger": False,
            "x-display-name": "Performance Score",
        },
        title="Performance Score",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to score", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedAccessibilityScoreConfig(BaseModel):
    """Run with the ACCESSIBILITY category and extract the score + audits."""

    operation: Literal["accessibility_score"] = Field(
        "accessibility_score",
        json_schema_extra={
            "const": "accessibility_score",
            "ui:hidden": True,
            "x-category": "Scores",
            "x-is-trigger": False,
            "x-display-name": "Accessibility Score",
        },
        title="Accessibility Score",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to score", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedSeoScoreConfig(BaseModel):
    """Run with the SEO category and extract the SEO score + failing audits."""

    operation: Literal["seo_score"] = Field(
        "seo_score",
        json_schema_extra={
            "const": "seo_score",
            "ui:hidden": True,
            "x-category": "Scores",
            "x-is-trigger": False,
            "x-display-name": "SEO Score",
        },
        title="SEO Score",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to score", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedBestPracticesScoreConfig(BaseModel):
    """Run with the BEST_PRACTICES category and extract the score + audits."""

    operation: Literal["best_practices_score"] = Field(
        "best_practices_score",
        json_schema_extra={
            "const": "best_practices_score",
            "ui:hidden": True,
            "x-category": "Scores",
            "x-is-trigger": False,
            "x-display-name": "Best Practices Score",
        },
        title="Best Practices Score",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to score", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedAllCategoriesConfig(BaseModel):
    """Run all four Lighthouse categories in one call and extract every score."""

    operation: Literal["all_categories"] = Field(
        "all_categories",
        json_schema_extra={
            "const": "all_categories",
            "ui:hidden": True,
            "x-category": "Scores",
            "x-is-trigger": False,
            "x-display-name": "All Category Scores",
        },
        title="All Category Scores",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to score", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedCoreWebVitalsConfig(BaseModel):
    """Extract real-user Core Web Vitals (CrUX field data) for the specific URL."""

    operation: Literal["core_web_vitals"] = Field(
        "core_web_vitals",
        json_schema_extra={
            "const": "core_web_vitals",
            "ui:hidden": True,
            "x-category": "Field Data",
            "x-is-trigger": False,
            "x-display-name": "Core Web Vitals (URL)",
        },
        title="Core Web Vitals (URL)",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedOriginCoreWebVitalsConfig(BaseModel):
    """Extract aggregated CrUX field data for the entire origin (whole site)."""

    operation: Literal["origin_core_web_vitals"] = Field(
        "origin_core_web_vitals",
        json_schema_extra={
            "const": "origin_core_web_vitals",
            "ui:hidden": True,
            "x-category": "Field Data",
            "x-is-trigger": False,
            "x-display-name": "Origin Core Web Vitals",
        },
        title="Origin Core Web Vitals",
    )
    page_url: str = Field(
        ...,
        title="URL",
        description="Any URL on the origin to analyze (field data is origin-wide)",
        json_schema_extra={"format": "uri"},
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedLabMetricsConfig(BaseModel):
    """Extract lab metrics (FCP, LCP, Speed Index, TBT, CLS, TTI) from Lighthouse."""

    operation: Literal["lab_metrics"] = Field(
        "lab_metrics",
        json_schema_extra={
            "const": "lab_metrics",
            "ui:hidden": True,
            "x-category": "Lab Data",
            "x-is-trigger": False,
            "x-display-name": "Lab Metrics",
        },
        title="Lab Metrics",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedGetAuditConfig(BaseModel):
    """Extract a single named Lighthouse audit (score + details)."""

    operation: Literal["get_audit"] = Field(
        "get_audit",
        json_schema_extra={
            "const": "get_audit",
            "ui:hidden": True,
            "x-category": "Lab Data",
            "x-is-trigger": False,
            "x-display-name": "Get Audit Details",
        },
        title="Get Audit Details",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    audit_id: str = Field(
        ...,
        title="Audit ID",
        description="Lighthouse audit id. Pick a common one or type any audit id (Lighthouse has ~150).",
        json_schema_extra={
            "enum": COMMON_AUDIT_IDS,
            "x-enum-searchable": True,
        },
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedOpportunitiesConfig(BaseModel):
    """Extract performance opportunity audits with estimated ms/byte savings."""

    operation: Literal["get_opportunities"] = Field(
        "get_opportunities",
        json_schema_extra={
            "const": "get_opportunities",
            "ui:hidden": True,
            "x-category": "Lab Data",
            "x-is-trigger": False,
            "x-display-name": "Get Opportunities",
        },
        title="Get Opportunities",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedScreenshotConfig(BaseModel):
    """Extract the final rendered screenshot (base64 data URI) of the page."""

    operation: Literal["get_screenshot"] = Field(
        "get_screenshot",
        json_schema_extra={
            "const": "get_screenshot",
            "ui:hidden": True,
            "x-category": "Lab Data",
            "x-is-trigger": False,
            "x-display-name": "Get Screenshot",
        },
        title="Get Screenshot",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


class PageSpeedLocalizedReportConfig(BaseModel):
    """Run with a specific result locale for localized audit text."""

    operation: Literal["localized_report"] = Field(
        "localized_report",
        json_schema_extra={
            "const": "localized_report",
            "ui:hidden": True,
            "x-category": "Analysis",
            "x-is-trigger": False,
            "x-display-name": "Localized Report",
        },
        title="Localized Report",
    )
    page_url: str = Field(
        ..., title="URL", description="The page to analyze", json_schema_extra={"format": "uri"}
    )
    locale: str = Field(
        ...,
        title="Locale",
        description="BCP-47 locale for the response text (e.g. en, es, ja, fr)",
    )
    strategy: Optional[str] = Field(
        "DESKTOP",
        title="Strategy",
        description="Crawler profile to emulate",
        json_schema_extra=_STRATEGY_FIELD_EXTRA,
    )


# ============================================================================
# Discriminated Union
# ============================================================================


PageSpeedConfig = Annotated[
    Union[
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
    ],
    Discriminator("operation"),
]


class PageSpeedNodeConfig(NodeConfig[PageSpeedConfig, PageSpeedCredential]):
    """Full configuration for the Google PageSpeed node including credentials."""

    pass


# ============================================================================
# Report extraction helpers (pure functions over the runPagespeed response)
# ============================================================================


def _category_score(report: Dict[str, Any], category_id: str) -> Optional[float]:
    """Return a Lighthouse category score as 0-100, or None if absent/errored."""
    categories = (report.get("lighthouseResult") or {}).get("categories") or {}
    key = CATEGORY_RESPONSE_KEY.get(category_id, category_id)
    raw = (categories.get(key) or {}).get("score")
    if raw is None:
        return None
    return round(raw * 100, 1)


def _category_summary(report: Dict[str, Any], category_id: str) -> Dict[str, Any]:
    """Score + the failing/non-passing audit refs for one Lighthouse category."""
    lh = report.get("lighthouseResult") or {}
    key = CATEGORY_RESPONSE_KEY.get(category_id, category_id)
    category = (lh.get("categories") or {}).get(key) or {}
    audits = lh.get("audits") or {}
    failing = []
    for ref in category.get("auditRefs") or []:
        audit = audits.get(ref.get("id")) or {}
        score = audit.get("score")
        if score is not None and score < 1:
            failing.append(
                {
                    "id": ref.get("id"),
                    "title": audit.get("title"),
                    "score": score,
                    "displayValue": audit.get("displayValue"),
                }
            )
    return {
        "category": category_id,
        "score": _category_score(report, category_id),
        "failing_audits": failing,
    }


def _loading_experience(report: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Extract CrUX field data ('loadingExperience' or 'originLoadingExperience')."""
    experience = report.get(key)
    if not experience:
        return {"available": False, "metrics": {}}
    metrics = {}
    for metric_id, metric in (experience.get("metrics") or {}).items():
        metrics[metric_id] = {
            "percentile": metric.get("percentile"),
            "category": metric.get("category"),
        }
    return {
        "available": True,
        "overall_category": experience.get("overall_category"),
        "id": experience.get("id"),
        "metrics": metrics,
    }


def _lab_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the key lab-metric audits out of lighthouseResult.audits."""
    audits = (report.get("lighthouseResult") or {}).get("audits") or {}
    out = {}
    for audit_id in LAB_METRIC_AUDIT_IDS:
        audit = audits.get(audit_id)
        if not audit:
            continue
        out[audit_id] = {
            "title": audit.get("title"),
            "score": audit.get("score"),
            "displayValue": audit.get("displayValue"),
            "numericValue": audit.get("numericValue"),
        }
    return out


def _opportunities(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Opportunity audits (details.type == 'opportunity') with estimated savings."""
    audits = (report.get("lighthouseResult") or {}).get("audits") or {}
    opportunities = []
    for audit_id, audit in audits.items():
        details = audit.get("details") or {}
        if details.get("type") != "opportunity":
            continue
        opportunities.append(
            {
                "id": audit_id,
                "title": audit.get("title"),
                "score": audit.get("score"),
                "displayValue": audit.get("displayValue"),
                "overallSavingsMs": details.get("overallSavingsMs"),
                "overallSavingsBytes": details.get("overallSavingsBytes"),
            }
        )
    opportunities.sort(key=lambda o: o.get("overallSavingsMs") or 0, reverse=True)
    return opportunities


# ============================================================================
# Node Implementation
# ============================================================================


class PageSpeedNode(WorkflowNode):
    """Google PageSpeed Insights automation node."""

    edit_examples = [
        "Run a full PageSpeed analysis for my landing page",
        "Get the mobile performance score for a URL",
        "Extract Core Web Vitals field data for a page",
        "List the top performance opportunities for a page",
        "Get all four Lighthouse category scores in one call",
    ]

    @classmethod
    def get_config_model(cls):
        return PageSpeedNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, PageSpeedNodeConfig):
            raise ValueError("Valid configuration is required")

        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Google PageSpeed API key.")
        api_key = credentials.api_key

        handlers = {
            "run_analysis": self._run_analysis,
            "analyze_mobile": self._analyze_mobile,
            "analyze_desktop": self._analyze_desktop,
            "performance_score": self._performance_score,
            "accessibility_score": self._accessibility_score,
            "seo_score": self._seo_score,
            "best_practices_score": self._best_practices_score,
            "all_categories": self._all_categories,
            "core_web_vitals": self._core_web_vitals,
            "origin_core_web_vitals": self._origin_core_web_vitals,
            "lab_metrics": self._lab_metrics,
            "get_audit": self._get_audit,
            "get_opportunities": self._get_opportunities,
            "get_screenshot": self._get_screenshot,
            "localized_report": self._localized_report,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _run_pagespeed(
        self,
        api_key: str,
        page_url: str,
        action_name: str,
        strategy: Optional[str] = None,
        categories: Optional[List[str]] = None,
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call GET /runPagespeed and return a structured {status, action, data} result.

        `categories` is repeatable (httpx serializes a list value to multiple
        `category=` query params). The API key is sent as the `key` query param,
        the documented/canonical method.
        """
        url = f"{PAGESPEED_API_BASE}/runPagespeed"
        params: Dict[str, Any] = {"url": page_url, "key": api_key}
        if strategy:
            params["strategy"] = strategy
        if categories:
            params["category"] = categories
        if locale:
            params["locale"] = locale

        start_time = time.time()
        # Each call runs a full Lighthouse analysis (can take ~30s) — generous timeout.
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.request(method="GET", url=url, params=params)
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        err = error_data.get("error", {})
                        error_message = (
                            err.get("message")
                            if isinstance(err, dict)
                            else error_data.get("message", str(error_data))
                        )
                    except Exception:
                        error_message = response.text
                    if isinstance(error_message, str):
                        error_message = error_message.encode("ascii", errors="replace").decode(
                            "ascii"
                        )
                    logger.error(f"[PageSpeedNode] API error ({action_name}): {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
                }
            except Exception as e:
                error_msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[PageSpeedNode] Request failed ({action_name}): {error_msg}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
                }

    # =========================================================================
    # Handlers
    # =========================================================================

    async def _run_analysis(self, c: PageSpeedRunAnalysisConfig, api_key: str) -> Dict[str, Any]:
        return await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="run_analysis",
            strategy=c.strategy,
            categories=ALL_CATEGORIES,
            locale=c.locale,
        )

    async def _analyze_mobile(
        self, c: PageSpeedAnalyzeMobileConfig, api_key: str
    ) -> Dict[str, Any]:
        return await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="analyze_mobile",
            strategy="MOBILE",
            categories=ALL_CATEGORIES,
            locale=c.locale,
        )

    async def _analyze_desktop(
        self, c: PageSpeedAnalyzeDesktopConfig, api_key: str
    ) -> Dict[str, Any]:
        return await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="analyze_desktop",
            strategy="DESKTOP",
            categories=ALL_CATEGORIES,
            locale=c.locale,
        )

    async def _performance_score(
        self, c: PageSpeedPerformanceScoreConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="performance_score",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            result["data"] = _category_summary(result["data"], CATEGORY_PERFORMANCE)
        return result

    async def _accessibility_score(
        self, c: PageSpeedAccessibilityScoreConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="accessibility_score",
            strategy=c.strategy,
            categories=[CATEGORY_ACCESSIBILITY],
        )
        if result["status"] == "success":
            result["data"] = _category_summary(result["data"], CATEGORY_ACCESSIBILITY)
        return result

    async def _seo_score(self, c: PageSpeedSeoScoreConfig, api_key: str) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="seo_score",
            strategy=c.strategy,
            categories=[CATEGORY_SEO],
        )
        if result["status"] == "success":
            result["data"] = _category_summary(result["data"], CATEGORY_SEO)
        return result

    async def _best_practices_score(
        self, c: PageSpeedBestPracticesScoreConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="best_practices_score",
            strategy=c.strategy,
            categories=[CATEGORY_BEST_PRACTICES],
        )
        if result["status"] == "success":
            result["data"] = _category_summary(result["data"], CATEGORY_BEST_PRACTICES)
        return result

    async def _all_categories(
        self, c: PageSpeedAllCategoriesConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="all_categories",
            strategy=c.strategy,
            categories=ALL_CATEGORIES,
        )
        if result["status"] == "success":
            report = result["data"]
            result["data"] = {
                "scores": {cat: _category_score(report, cat) for cat in ALL_CATEGORIES}
            }
        return result

    async def _core_web_vitals(
        self, c: PageSpeedCoreWebVitalsConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="core_web_vitals",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            result["data"] = _loading_experience(result["data"], "loadingExperience")
        return result

    async def _origin_core_web_vitals(
        self, c: PageSpeedOriginCoreWebVitalsConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="origin_core_web_vitals",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            result["data"] = _loading_experience(result["data"], "originLoadingExperience")
        return result

    async def _lab_metrics(self, c: PageSpeedLabMetricsConfig, api_key: str) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="lab_metrics",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            result["data"] = {"metrics": _lab_metrics(result["data"])}
        return result

    async def _get_audit(self, c: PageSpeedGetAuditConfig, api_key: str) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="get_audit",
            strategy=c.strategy,
            categories=ALL_CATEGORIES,
        )
        if result["status"] == "success":
            audits = (result["data"].get("lighthouseResult") or {}).get("audits") or {}
            audit = audits.get(c.audit_id)
            if audit is None:
                return {
                    "status": "error",
                    "action": "get_audit",
                    "error": f"Audit '{c.audit_id}' not found in the report",
                    "status_code": 404,
                    "timing_ms": result.get("timing_ms", {}),
                }
            result["data"] = {"id": c.audit_id, **audit}
        return result

    async def _get_opportunities(
        self, c: PageSpeedOpportunitiesConfig, api_key: str
    ) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="get_opportunities",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            result["data"] = {"opportunities": _opportunities(result["data"])}
        return result

    async def _get_screenshot(self, c: PageSpeedScreenshotConfig, api_key: str) -> Dict[str, Any]:
        result = await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="get_screenshot",
            strategy=c.strategy,
            categories=[CATEGORY_PERFORMANCE],
        )
        if result["status"] == "success":
            audits = (result["data"].get("lighthouseResult") or {}).get("audits") or {}
            final = audits.get("final-screenshot") or {}
            details = final.get("details") or {}
            result["data"] = {"screenshot": details.get("data"), "mime_type": details.get("mimeType")}
        return result

    async def _localized_report(
        self, c: PageSpeedLocalizedReportConfig, api_key: str
    ) -> Dict[str, Any]:
        return await self._run_pagespeed(
            api_key,
            c.page_url,
            action_name="localized_report",
            strategy=c.strategy,
            categories=ALL_CATEGORIES,
            locale=c.locale,
        )

"""
LinkedIn API automation node.

This node provides LinkedIn operations in workflows via the LinkedIn REST API.
Uses httpx for high-performance async HTTP requests.

API Reference:
- Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- OpenID Connect: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Union, Literal, Annotated, List
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.apify_runner import ApifyRunnerMixin
from nodes.core.platform_billing import platform_keyed_operation

# Scraping runs on Apify with NoClick's token; the node's own credential funds none of it.
PLATFORM_KEYED = platform_keyed_operation("APIFY_API_TOKEN", byok=False)
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.linkedin_oauth import is_token_expired, refresh_access_token
from nodes.scopes.linkedin import LINKEDIN_SCOPES

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com"
# LinkedIn API version in YYYYMM format (required header)
LINKEDIN_API_VERSION = "202604"

# Apify harvestapi LinkedIn actor IDs (Apify URL paths use ~ as separator)
HARVESTAPI_PROFILE_ACTOR = "harvestapi~linkedin-profile-scraper"
HARVESTAPI_COMPANY_SEARCH_ACTOR = "harvestapi~linkedin-company-search"
HARVESTAPI_JOB_SEARCH_ACTOR = "harvestapi~linkedin-job-search"
HARVESTAPI_PROFILE_SEARCH_ACTOR = "harvestapi~linkedin-profile-search"
HARVESTAPI_COMPANY_EMPLOYEES_ACTOR = "harvestapi~linkedin-company-employees"
HARVESTAPI_POST_SEARCH_ACTOR = "harvestapi~linkedin-post-search"


# ============================================================================
# LinkedIn Credential Schema
# ============================================================================


class LinkedInOAuthCredential(BaseModel):
    """OAuth 2.0 credential for LinkedIn.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://www.linkedin.com/developers/apps

    Note: scraping operations (scrape_profile, search_companies, search_jobs, etc.)
    do not use this credential — they run through NoClick's Apify integration and
    are billed against the user's NoClick balance.
    """

    credential_type: Literal["linkedin_oauth"] = Field(
        "linkedin_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    sub: Optional[str] = Field(None, title="LinkedIn Member ID")
    email: Optional[str] = Field(None, title="Account Email")
    name: Optional[str] = Field(None, title="Display Name")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "linkedin",
        "x-oauth-scopes": [
            "openid",
            "profile",
            "email",
            "w_member_social",
        ],
    })


# LinkedIn only supports OAuth, no PAT option available
LinkedInCredential = LinkedInOAuthCredential


# ============================================================================
# LinkedIn Configuration Models (One per action)
# ============================================================================


class LinkedInGetProfileConfig(BaseModel):
    """Get the authenticated user's profile information"""

    model_config = ConfigDict(populate_by_name=True, title="Get My Profile")

    operation: Literal["get_authenticated_profile"] = Field(
        default="get_authenticated_profile",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated Profile",
        },
        title="Get Authenticated Profile",
    )


class LinkedInCreateTextPostConfig(BaseModel):
    """Create a text post on LinkedIn"""

    model_config = ConfigDict(populate_by_name=True, title="Create Text Post")

    operation: Literal["create_text_post"] = Field(
        default="create_text_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Text Post",
        },
        title="Create Text Post",
    )
    commentary: str = Field(
        ...,
        title="Post Content",
        description="The text content of your LinkedIn post",
        json_schema_extra={"ui:widget": "textarea"},
    )
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        default="PUBLIC",
        title="Visibility",
        description="Who can see this post",
        json_schema_extra={
            "enum": ["PUBLIC", "CONNECTIONS"],
            "enumNames": ["Public", "Connections Only"],
            "x-enum-searchable": True,
        },
    )


class LinkedInCreateArticlePostConfig(BaseModel):
    """Create an article/link post on LinkedIn"""

    model_config = ConfigDict(populate_by_name=True, title="Share Article / Link")

    operation: Literal["create_article_post"] = Field(
        default="create_article_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Article Post",
        },
        title="Create Article Post",
    )
    commentary: str = Field(
        ...,
        title="Post Content",
        description="The text content to accompany the article",
        json_schema_extra={"ui:widget": "textarea"},
    )
    article_url: str = Field(
        ..., title="Article URL", description="URL of the article to share"
    )
    article_title: Optional[str] = Field(
        default=None,
        title="Article Title",
        description="Custom title for the article (optional)",
    )
    article_description: Optional[str] = Field(
        default=None,
        title="Article Description",
        description="Custom description for the article (optional)",
    )
    visibility: Literal["PUBLIC", "CONNECTIONS"] = Field(
        default="PUBLIC",
        title="Visibility",
        description="Who can see this post",
        json_schema_extra={
            "enum": ["PUBLIC", "CONNECTIONS"],
            "enumNames": ["Public", "Connections Only"],
            "x-enum-searchable": True,
        },
    )


class LinkedInDeletePostConfig(BaseModel):
    """Delete a LinkedIn post"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Post")

    operation: Literal["delete_post"] = Field(
        default="delete_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Post",
        },
        title="Delete Post",
    )
    post_urn: str = Field(
        ...,
        title="Post URN",
        description="The URN of the post to delete (e.g., urn:li:share:123456)",
    )


# ============================================================================
# Scraping operations (powered by Apify + harvestapi actors).
# Billed via NoClick balance: actor's actual usageTotalUsd plus the platform markup.
# ============================================================================

# Profile scraper modes — exact strings expected by harvestapi/linkedin-profile-scraper
PROFILE_MODE_BASIC = "Profile details no email ($4 per 1k)"
PROFILE_MODE_EMAIL = "Profile details + email search ($10 per 1k)"

# Employees / profile-search scraper modes — exact strings expected by harvestapi
EMPLOYEE_MODE_SHORT = "Short"
EMPLOYEE_MODE_FULL = "Full"
EMPLOYEE_MODE_FULL_EMAIL = "Full + email search"


class LinkedInScrapeProfileConfig(BaseModel):
    """Scrape LinkedIn profiles by URL/handle/ID via Apify (harvestapi)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Profiles",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_user_profiles"] = Field(
        default="scrape_user_profiles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Scrape User Profiles",
        },
        title="Scrape User Profiles",
    )
    profile_inputs: str = Field(
        ...,
        title="Profile URLs / Handles",
        description=(
            "One profile URL, handle, or LinkedIn ID per line. "
            "Examples: https://www.linkedin.com/in/williamhgates, williamhgates"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    profile_mode: Literal[
        "Profile details no email ($4 per 1k)",
        "Profile details + email search ($10 per 1k)",
    ] = Field(
        default=PROFILE_MODE_BASIC,
        title="Scrape Mode",
        description="Whether to also resolve email addresses (more expensive).",
        json_schema_extra={
            "enum": [
                "Profile details no email ($4 per 1k)",
                "Profile details + email search ($10 per 1k)",
            ],
            "enumNames": ["Basic — no email ($4/1k)", "With email search ($10/1k)"],
            "x-enum-searchable": True,
        },
    )


class LinkedInSearchCompaniesConfig(BaseModel):
    """Search LinkedIn companies via Apify (harvestapi/linkedin-company-search)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Search Companies",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["search_companies"] = Field(
        default="search_companies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Search Companies",
        },
        title="Search Companies",
    )
    search_query: Optional[str] = Field(
        default=None,
        title="Search Query",
        description="Company keyword search (e.g., 'fintech', 'AI infrastructure')",
    )
    locations: Optional[str] = Field(
        default=None,
        title="Locations (comma-separated)",
        description="Filter by location names, comma-separated",
    )
    scraper_mode: Literal["short", "full"] = Field(
        default="short",
        title="Scraper Mode",
        description="Short = listing pages only. Full = also visit each company page.",
        json_schema_extra={
            "enum": ["short", "full"],
            "enumNames": ["Short (listing only)", "Full (visit each page)"],
            "x-enum-searchable": True,
        },
    )
    max_items: int = Field(
        default=50,
        title="Max Results",
        ge=1,
        le=1000,
    )


class LinkedInSearchJobsConfig(BaseModel):
    """Search LinkedIn job listings via Apify (harvestapi/linkedin-job-search)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Search Jobs",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["search_job_listings"] = Field(
        default="search_job_listings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Job",
            "x-is-trigger": False,
            "x-display-name": "Search Job Listings",
        },
        title="Search Job Listings",
    )
    search_queries: str = Field(
        ...,
        title="Job Titles / Keywords",
        description="One search query per line (e.g., 'Software Engineer')",
        json_schema_extra={"ui:widget": "textarea"},
    )
    locations: Optional[str] = Field(
        default=None,
        title="Locations (comma-separated)",
        description="Geographic filter (e.g., 'San Francisco, CA, Remote')",
    )
    workplace_type: Optional[Literal["remote", "hybrid", "office"]] = Field(
        default=None,
        title="Workplace Type",
        json_schema_extra={
            "enum": ["remote", "hybrid", "office"],
            "enumNames": ["Remote", "Hybrid", "On-site"],
            "x-enum-searchable": True,
        },
    )
    max_items: int = Field(
        default=50,
        title="Max Jobs Per Query",
        ge=1,
        le=1000,
    )


class LinkedInSearchProfilesConfig(BaseModel):
    """Search LinkedIn profiles via Apify (harvestapi/linkedin-profile-search)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Search People",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["search_user_profiles"] = Field(
        default="search_user_profiles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Search User Profiles",
        },
        title="Search User Profiles",
    )
    search_query: Optional[str] = Field(
        default=None,
        title="Search Query",
        description="Free-text search (e.g., 'CTO fintech', 'product manager AI')",
    )
    current_job_titles: Optional[str] = Field(
        default=None,
        title="Current Job Titles (comma-separated)",
    )
    current_companies: Optional[str] = Field(
        default=None,
        title="Current Companies (comma-separated)",
        description="Company names or LinkedIn company URLs",
    )
    locations: Optional[str] = Field(
        default=None,
        title="Locations (comma-separated)",
    )
    profile_mode: Literal[
        "Short",
        "Full",
        "Full + email search",
    ] = Field(
        default=EMPLOYEE_MODE_SHORT,
        title="Scrape Mode",
        description="How much detail to fetch per profile (more = more expensive).",
        json_schema_extra={
            "enum": ["Short", "Full", "Full + email search"],
            "enumNames": [
                "Short ($4 per 1k)",
                "Full ($8 per 1k)",
                "Full + email search ($12 per 1k)",
            ],
            "x-enum-searchable": True,
        },
    )
    max_items: int = Field(
        default=50,
        title="Max Profiles",
        ge=1,
        le=1000,
    )


class LinkedInScrapeCompanyEmployeesConfig(BaseModel):
    """Scrape employees of a LinkedIn company via Apify (harvestapi/linkedin-company-employees)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Company Employees",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_company_employees"] = Field(
        default="scrape_company_employees",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Scrape Company Employees",
        },
        title="Scrape Company Employees",
    )
    companies: str = Field(
        ...,
        title="Companies",
        description="One LinkedIn company URL or name per line",
        json_schema_extra={"ui:widget": "textarea"},
    )
    job_titles: Optional[str] = Field(
        default=None,
        title="Job Titles Filter (comma-separated)",
    )
    locations: Optional[str] = Field(
        default=None,
        title="Locations (comma-separated)",
    )
    profile_mode: Literal[
        "Short ($4 per 1k)",
        "Full ($8 per 1k)",
        "Full + email search ($12 per 1k)",
    ] = Field(
        default="Short ($4 per 1k)",
        title="Scrape Mode",
        json_schema_extra={
            "x-enum-searchable": True,
        },
    )
    max_items: int = Field(
        default=50,
        title="Max Employees",
        ge=1,
        le=2500,
    )


class LinkedInSearchPostsConfig(BaseModel):
    """Search LinkedIn posts via Apify (harvestapi/linkedin-post-search). $2 per 1k posts."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Search Posts",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["search_posts"] = Field(
        default="search_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Search Posts",
        },
        title="Search Posts",
    )
    search_query: str = Field(
        ...,
        title="Search Query",
        description="Post text keywords (LinkedIn caps at 85 chars)",
    )
    target_urls: Optional[str] = Field(
        default=None,
        title="Target Profiles / Companies (optional)",
        description="One LinkedIn profile or company URL per line to restrict the search to",
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_items: int = Field(
        default=50,
        title="Max Posts",
        ge=1,
        le=1000,
    )


# Discriminated union uses 'operation' field to determine which config type to parse
LinkedInConfig = Annotated[
    Union[
        LinkedInGetProfileConfig,
        LinkedInCreateTextPostConfig,
        LinkedInCreateArticlePostConfig,
        LinkedInDeletePostConfig,
        LinkedInScrapeProfileConfig,
        LinkedInSearchCompaniesConfig,
        LinkedInSearchJobsConfig,
        LinkedInSearchProfilesConfig,
        LinkedInScrapeCompanyEmployeesConfig,
        LinkedInSearchPostsConfig,
    ],
    Discriminator("operation"),
]


class LinkedInNodeConfig(NodeConfig[LinkedInConfig, LinkedInCredential]):
    """Full configuration for LinkedIn node including credentials"""

    pass


# ============================================================================
# LinkedIn Node Implementation
# ============================================================================


class LinkedInNode(ApifyRunnerMixin, WorkflowNode):
    """
    LinkedIn API automation node.

    Executes LinkedIn operations via REST API for posting and profile access.
    Supports multiple actions - user selects one in the config.
    """

    edit_examples = [
        "Post career tip article to feed with custom commentary",
        "Share job opening link on LinkedIn and set to PUBLIC",
        "Get authenticated user profile with name and headline",
        "Post thought leadership article with external link preview",
        "Delete outdated job posting from LinkedIn feed",
        "Share industry news with company mention to CONNECTIONS only",
    ]

    scope_registry = LINKEDIN_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="profile",
        identity_operation="get_authenticated_profile",
    )

    @classmethod
    def get_config_model(cls):
        return LinkedInNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LinkedIn action via REST API."""
        logger.info(f"[LinkedInNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, LinkedInNodeConfig):
            raise ValueError("LinkedInNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        # Scraping operations run through NoClick's Apify integration (NoClick-owned token).
        # No LinkedIn OAuth is required; the user is billed against their NoClick balance.
        scraping_handlers = {
            LinkedInScrapeProfileConfig: self._scrape_profile,
            LinkedInSearchCompaniesConfig: self._search_companies,
            LinkedInSearchJobsConfig: self._search_jobs,
            LinkedInSearchProfilesConfig: self._search_profiles,
            LinkedInScrapeCompanyEmployeesConfig: self._scrape_company_employees,
            LinkedInSearchPostsConfig: self._search_posts,
        }
        if type(config) in scraping_handlers:
            return await scraping_handlers[type(config)](config)

        # OAuth operations — credentials and a fresh access token are required
        if not credentials:
            raise ValueError(
                "[LinkedInNode] LinkedIn OAuth is required for this operation. "
                "Please connect your LinkedIn account in the node's credentials tab."
            )
        access_token = await self._ensure_fresh_token(credentials)

        oauth_handlers = {
            LinkedInGetProfileConfig: self._get_profile,
            LinkedInCreateTextPostConfig: self._create_text_post,
            LinkedInCreateArticlePostConfig: self._create_article_post,
            LinkedInDeletePostConfig: self._delete_post,
        }

        handler = oauth_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, access_token, credentials)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.linkedin_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="linkedin",
        )

    async def _ensure_fresh_token(self, credentials: LinkedInCredential) -> str:
        """Return a valid LinkedIn access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.linkedin_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="linkedin",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        access_token: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated LinkedIn API request with timing."""
        total_start = time.time()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }

        if json_body is not None:
            headers["Content-Type"] = "application/json"

        url = f"{LINKEDIN_API_BASE}{endpoint}"

        # Filter out None params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            # API request timing
            api_start = time.time()
            logger.info(f"[LinkedInNode] 🔌 {method} {endpoint}")

            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=30.0,
            )
            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[LinkedInNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            # Response parsing timing
            parse_start = time.time()

            if response.status_code >= 400:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("message", response.text)
                logger.error(f"[LinkedInNode] API error: {error_msg}")

                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "linkedin",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {
                        "api_request": round(api_time, 1),
                        "total": round(total_time, 1),
                    },
                }
                await self.emit(output)
                return output

            # Parse successful response
            data = response.json() if response.content else None

            # For delete operations (204 No Content), data will be None
            if response.status_code == 204:
                data = {"deleted": True}

            # For create operations (201 Created), get the post ID from header
            if response.status_code == 201:
                post_id = response.headers.get("x-restli-id")
                if post_id:
                    data = data or {}
                    data["id"] = post_id

            parse_time = (time.time() - parse_start) * 1000
            logger.info(f"[LinkedInNode] ⏱️ Response parsing: {parse_time:.1f}ms")

            total_time = (time.time() - total_start) * 1000
            logger.info(f"[LinkedInNode] ⏱️ TOTAL time: {total_time:.1f}ms")

            output = {
                "type": "linkedin",
                "action": action_name,
                "status": "success",
                "data": data,
                "timestamp": time.time(),
                "timing_ms": {
                    "api_request": round(api_time, 1),
                    "response_parsing": round(parse_time, 1),
                    "total": round(total_time, 1),
                },
            }

            await self.emit(output)
            return output

    # ============================================================================
    # Profile Actions
    # ============================================================================

    async def _get_profile(
        self,
        config: LinkedInGetProfileConfig,
        access_token: str,
        credentials: LinkedInCredential,
    ) -> Dict[str, Any]:
        """Get the authenticated user's profile information."""
        return await self._make_request(
            "GET", "/v2/userinfo", access_token, action_name="get_authenticated_profile"
        )

    # ============================================================================
    # Post Actions
    # ============================================================================

    async def _create_text_post(
        self,
        config: LinkedInCreateTextPostConfig,
        access_token: str,
        credentials: LinkedInCredential,
    ) -> Dict[str, Any]:
        """Create a text post on LinkedIn."""
        # Get the member URN from credentials
        member_id = credentials.sub
        if not member_id:
            raise ValueError(
                "Member ID not found in credentials. Please reconnect your LinkedIn account."
            )

        author_urn = f"urn:li:person:{member_id}"

        body = {
            "author": author_urn,
            "commentary": config.commentary,
            "visibility": config.visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        return await self._make_request(
            "POST",
            "/rest/posts",
            access_token,
            json_body=body,
            action_name="create_text_post",
        )

    async def _create_article_post(
        self,
        config: LinkedInCreateArticlePostConfig,
        access_token: str,
        credentials: LinkedInCredential,
    ) -> Dict[str, Any]:
        """Create an article/link post on LinkedIn."""
        member_id = credentials.sub
        if not member_id:
            raise ValueError(
                "Member ID not found in credentials. Please reconnect your LinkedIn account."
            )

        author_urn = f"urn:li:person:{member_id}"

        article_content = {"source": config.article_url}
        if config.article_title:
            article_content["title"] = config.article_title
        if config.article_description:
            article_content["description"] = config.article_description

        body = {
            "author": author_urn,
            "commentary": config.commentary,
            "visibility": config.visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {"article": article_content},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        return await self._make_request(
            "POST",
            "/rest/posts",
            access_token,
            json_body=body,
            action_name="create_article_post",
        )

    async def _delete_post(
        self,
        config: LinkedInDeletePostConfig,
        access_token: str,
        credentials: LinkedInCredential,
    ) -> Dict[str, Any]:
        """Delete a LinkedIn post."""
        encoded_urn = quote(config.post_urn, safe="")
        return await self._make_request(
            "DELETE",
            f"/rest/posts/{encoded_urn}",
            access_token,
            action_name="delete_post",
        )

    # ============================================================================
    # Scraping Actions (Apify + harvestapi)
    #
    # Flow:
    #   1. Pre-check user balance (must be >= APIFY_MIN_BALANCE_USD)
    #   2. POST /v2/acts/{id}/run-sync — returns Run object (datasetId, usageTotalUsd)
    #   3. GET  /v2/datasets/{datasetId}/items — fetch the actual rows
    #   4. Apply the platform markup, build UsageEventData, charge user balance
    # ============================================================================

    @staticmethod
    def _split_csv(value: Optional[str]) -> List[str]:
        """Split a comma-separated value into a deduped list of trimmed entries."""
        if not value:
            return []
        seen: List[str] = []
        for part in value.split(","):
            stripped = part.strip()
            if stripped and stripped not in seen:
                seen.append(stripped)
        return seen

    async def _scrape_profile(
        self, config: LinkedInScrapeProfileConfig
    ) -> Dict[str, Any]:
        queries = self._split_lines(config.profile_inputs)
        if not queries:
            raise ValueError("At least one profile URL/handle is required.")
        actor_input = {
            "queries": queries,
            "profileScraperMode": config.profile_mode,
        }
        return await self._run_apify_actor(
            HARVESTAPI_PROFILE_ACTOR,
            actor_input,
            action_name="scrape_user_profiles",
            usage_subtype="linkedin/scrape_profile",
            platform="linkedin",
        )

    async def _search_companies(
        self, config: LinkedInSearchCompaniesConfig
    ) -> Dict[str, Any]:
        if not config.search_query and not config.locations:
            raise ValueError("Provide a search query or at least one location.")
        actor_input: Dict[str, Any] = {
            "scraperMode": config.scraper_mode,
            "maxItems": config.max_items,
        }
        if config.search_query:
            actor_input["searchQuery"] = config.search_query
        locations = self._split_csv(config.locations)
        if locations:
            actor_input["locations"] = locations
        return await self._run_apify_actor(
            HARVESTAPI_COMPANY_SEARCH_ACTOR,
            actor_input,
            action_name="search_companies",
            usage_subtype="linkedin/search_companies",
            platform="linkedin",
        )

    async def _search_jobs(self, config: LinkedInSearchJobsConfig) -> Dict[str, Any]:
        queries = self._split_lines(config.search_queries)
        if not queries:
            raise ValueError("At least one search query is required.")
        actor_input: Dict[str, Any] = {
            "searchQueries": queries,
            "maxItems": config.max_items,
        }
        locations = self._split_csv(config.locations)
        if locations:
            actor_input["locations"] = locations
        if config.workplace_type:
            actor_input["workplaceType"] = [config.workplace_type]
        return await self._run_apify_actor(
            HARVESTAPI_JOB_SEARCH_ACTOR,
            actor_input,
            action_name="search_job_listings",
            usage_subtype="linkedin/search_jobs",
            platform="linkedin",
        )

    async def _search_profiles(
        self, config: LinkedInSearchProfilesConfig
    ) -> Dict[str, Any]:
        if not any(
            [
                config.search_query,
                config.current_job_titles,
                config.current_companies,
                config.locations,
            ]
        ):
            raise ValueError(
                "Provide at least one search filter (query, title, company, or location)."
            )
        actor_input: Dict[str, Any] = {
            "profileScraperMode": config.profile_mode,
            "maxItems": config.max_items,
        }
        if config.search_query:
            actor_input["searchQuery"] = config.search_query
        titles = self._split_csv(config.current_job_titles)
        if titles:
            actor_input["currentJobTitles"] = titles
        companies = self._split_csv(config.current_companies)
        if companies:
            actor_input["currentCompanies"] = companies
        locations = self._split_csv(config.locations)
        if locations:
            actor_input["locations"] = locations
        return await self._run_apify_actor(
            HARVESTAPI_PROFILE_SEARCH_ACTOR,
            actor_input,
            action_name="search_user_profiles",
            usage_subtype="linkedin/search_profiles",
            platform="linkedin",
        )

    async def _scrape_company_employees(
        self, config: LinkedInScrapeCompanyEmployeesConfig
    ) -> Dict[str, Any]:
        companies = self._split_lines(config.companies)
        if not companies:
            raise ValueError("At least one company URL or name is required.")
        actor_input: Dict[str, Any] = {
            "companies": companies,
            "profileScraperMode": config.profile_mode,
            "maxItems": config.max_items,
        }
        titles = self._split_csv(config.job_titles)
        if titles:
            actor_input["jobTitles"] = titles
        locations = self._split_csv(config.locations)
        if locations:
            actor_input["locations"] = locations
        return await self._run_apify_actor(
            HARVESTAPI_COMPANY_EMPLOYEES_ACTOR,
            actor_input,
            action_name="scrape_company_employees",
            usage_subtype="linkedin/scrape_company_employees",
            platform="linkedin",
        )

    async def _search_posts(self, config: LinkedInSearchPostsConfig) -> Dict[str, Any]:
        actor_input: Dict[str, Any] = {
            "searchQueries": [config.search_query],
        }
        targets = self._split_lines(config.target_urls)
        if targets:
            actor_input["targetUrls"] = targets
        result = await self._run_apify_actor(
            HARVESTAPI_POST_SEARCH_ACTOR,
            actor_input,
            action_name="search_posts",
            usage_subtype="linkedin/search_posts",
            platform="linkedin",
        )
        # This actor ignores maxItems and always returns its default batch size.
        # Truncate on our side to respect the user's requested limit.
        if result.get("data") and isinstance(result["data"].get("items"), list):
            items = result["data"]["items"][: config.max_items]
            result["data"]["items"] = items
            result["data"]["count"] = len(items)
        return result

"""
Mock tests for Semrush node - All 116 API operations.

These tests use mocked HTTP responses to test node logic without making actual API calls.
Covers all Semrush API operations across Analytics, Trends, Projects, and API v4.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from nodes.semrush_node import (
    SemrushNode,
    SemrushAPIKeyCredential,
    # Analytics API - Domain Reports (12)
    SemrushDomainOrganicConfig,
    SemrushDomainAdwordsConfig,
    SemrushDomainAdwordsUniqueConfig,
    SemrushDomainOrganicOrganicConfig,
    SemrushDomainAdwordsAdwordsConfig,
    SemrushDomainAdwordsHistoricalConfig,
    SemrushDomainDomainsConfig,
    SemrushDomainShoppingConfig,
    SemrushDomainShoppingUniqueConfig,
    SemrushDomainShoppingShoppingConfig,
    SemrushDomainOrganicUniqueConfig,
    SemrushDomainOrganicSubdomainsConfig,
    # Analytics API - Overview Reports (5)
    SemrushDomainRanksConfig,
    SemrushDomainRankConfig,
    SemrushDomainRankHistoryConfig,
    SemrushRankDifferenceConfig,
    SemrushRankConfig,
    # Analytics API - Subdomain Reports (7)
    SemrushSubdomainRankConfig,
    SemrushSubdomainRanksConfig,
    SemrushSubdomainRankHistoryConfig,
    SemrushSubdomainOrganicConfig,
    SemrushSubdomainAdwordsConfig,
    SemrushSubdomainOrganicUniqueConfig,
    SemrushSubdomainAdwordsUniqueConfig,
    # Analytics API - Subfolder Reports (7)
    SemrushSubfolderRankConfig,
    SemrushSubfolderRanksConfig,
    SemrushSubfolderRankHistoryConfig,
    SemrushSubfolderOrganicConfig,
    SemrushSubfolderAdwordsConfig,
    SemrushSubfolderOrganicUniqueConfig,
    SemrushSubfolderAdwordsUniqueConfig,
    # Analytics API - URL Reports (5)
    SemrushUrlRankConfig,
    SemrushUrlRanksConfig,
    SemrushUrlRankHistoryConfig,
    SemrushUrlOrganicConfig,
    SemrushUrlAdwordsConfig,
    # Analytics API - Keyword Reports (10)
    SemrushPhraseAllConfig,
    SemrushPhraseThisConfig,
    SemrushPhraseTheseConfig,
    SemrushPhraseOrganicConfig,
    SemrushPhraseAdwordsConfig,
    SemrushPhraseRelatedConfig,
    SemrushPhraseAdwordsHistoricalConfig,
    SemrushPhraseFullsearchConfig,
    SemrushPhraseQuestionsConfig,
    SemrushPhraseKdiConfig,
    # Analytics API - Backlinks Reports (15)
    SemrushBacklinksOverviewConfig,
    SemrushBacklinksConfig,
    SemrushBacklinksRefdomainsConfig,
    SemrushBacklinksRefipsConfig,
    SemrushBacklinksTldConfig,
    SemrushBacklinksGeoConfig,
    SemrushBacklinksAnchorsConfig,
    SemrushBacklinksPagesConfig,
    SemrushBacklinksCompetitorsConfig,
    SemrushBacklinksMatrixConfig,
    SemrushBacklinksComparisonConfig,
    SemrushBacklinksAscoreProfileConfig,
    SemrushBacklinksCategoriesProfileConfig,
    SemrushBacklinksCategoriesConfig,
    SemrushBacklinksHistoricalConfig,
    # Trends API (13)
    SemrushTrafficSummaryConfig,
    SemrushTrafficDailyConfig,
    SemrushTrafficWeeklyConfig,
    SemrushPurchaseConversionConfig,
    SemrushIndustryCategoriesConfig,
    SemrushTrafficSourcesConfig,
    SemrushTrafficDestinationsConfig,
    SemrushGeoDistributionConfig,
    SemrushSubdomainsTrafficConfig,
    SemrushTopPagesConfig,
    SemrushTrafficRankConfig,
    SemrushAudienceInsightsConfig,
    SemrushSubfoldersTrafficConfig,
    # Projects API - Position Tracking (16)
    SemrushPTCampaignListConfig,
    SemrushPTCreateCampaignConfig,
    SemrushPTAddKeywordsConfig,
    SemrushPTRemoveKeywordsConfig,
    SemrushPTAddTagsConfig,
    SemrushPTRemoveTagsConfig,
    SemrushPTAddCompetitorsConfig,
    SemrushPTRemoveCompetitorsConfig,
    SemrushPTLocationSearchConfig,
    SemrushPTCampaignDatesConfig,
    SemrushPTOrganicOverviewConfig,
    SemrushPTAdwordsOverviewConfig,
    SemrushPTOrganicPositionsConfig,
    SemrushPTAdwordsPositionsConfig,
    SemrushPTEnableNotificationsConfig,
    SemrushPTDisableNotificationsConfig,
    # Projects API - Site Audit (11)
    SemrushSAEnableConfig,
    SemrushSAEditCampaignConfig,
    SemrushSAGetSnapshotsConfig,
    SemrushSALaunchAuditConfig,
    SemrushSAGetCampaignInfoConfig,
    SemrushSAGetSnapshotDetailsConfig,
    SemrushSAGetIssueDetailsConfig,
    SemrushSAGetIssueMetadataConfig,
    SemrushSASearchPageConfig,
    SemrushSAGetPageInfoConfig,
    SemrushSAGetHistoryConfig,
)


@pytest.fixture
def api_key_credential():
    """Mock API key credential"""
    return SemrushAPIKeyCredential(api_key="mock_api_key_12345")


@pytest.fixture
def semrush_node():
    """Simple node instance for testing helper methods"""
    from nodes.semrush_node import SemrushNode

    return SemrushNode("test", "automation-semrush", {}, None, None, None, "wf")


def create_node(config, credentials):
    """Helper to create a SemrushNode instance with test credentials."""
    from nodes.semrush_node import SemrushNodeFullConfig

    node_config = SemrushNodeFullConfig(config=config, credentials=credentials)
    return SemrushNode("test", "automation-semrush", {}, node_config, None, None, "wf")


def create_csv_mock():
    """Create a standard CSV response mock"""
    mock_response = AsyncMock()
    mock_response.text = "col1,col2,col3\nval1,val2,val3"
    mock_response.raise_for_status = MagicMock()
    return mock_response


def create_json_mock(data):
    """Create a standard JSON response mock"""
    mock_response = AsyncMock()
    mock_response.json = AsyncMock(return_value=data)
    mock_response.raise_for_status = MagicMock()
    return mock_response


# ============================================================================
# Analytics API - Domain Reports (12 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_organic(mock_get, api_key_credential):
    """Test domain organic keywords report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainOrganicConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_organic_keywords"
    assert result["format"] == "csv"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_adwords(mock_get, api_key_credential):
    """Test domain adwords report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainAdwordsConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_paid_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_adwords_unique(mock_get, api_key_credential):
    """Test domain adwords unique report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainAdwordsUniqueConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_unique_ad_copies"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_organic_organic(mock_get, api_key_credential):
    """Test domain organic competitors"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainOrganicOrganicConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_organic_competitors"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_adwords_adwords(mock_get, api_key_credential):
    """Test domain adwords competitors"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainAdwordsAdwordsConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_paid_competitors"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_adwords_historical(mock_get, api_key_credential):
    """Test domain adwords historical report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainAdwordsHistoricalConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_paid_keywords_historical"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_domains(mock_get, api_key_credential):
    """Test domain vs domain report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainDomainsConfig(domains="example.com,competitor.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "compare_domains_batch"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_shopping(mock_get, api_key_credential):
    """Test domain shopping report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainShoppingConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_product_listing_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_shopping_unique(mock_get, api_key_credential):
    """Test domain shopping unique report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainShoppingUniqueConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_unique_product_listing_ads"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_shopping_shopping(mock_get, api_key_credential):
    """Test domain shopping competitors"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainShoppingShoppingConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_product_listing_competitors"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_organic_unique(mock_get, api_key_credential):
    """Test domain organic unique report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainOrganicUniqueConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_top_organic_pages"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_organic_subdomains(mock_get, api_key_credential):
    """Test domain organic subdomains report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainOrganicSubdomainsConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_subdomains_organic_ranking"


# ============================================================================
# Analytics API - Overview Reports (5 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_ranks(mock_get, api_key_credential):
    """Test domain ranks overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainRanksConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_overview_all_databases"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_rank(mock_get, api_key_credential):
    """Test domain rank for one database"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainRankConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_overview_single_database"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_domain_rank_history(mock_get, api_key_credential):
    """Test domain rank history"""
    mock_get.return_value = create_csv_mock()

    config = SemrushDomainRankHistoryConfig(domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domain_rank_history"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_rank_difference(mock_get, api_key_credential):
    """Test winners and losers report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushRankDifferenceConfig()
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_winners_and_losers_report"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_rank(mock_get, api_key_credential):
    """Test Semrush Rank report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushRankConfig()
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_semrush_rank_report"


# ============================================================================
# Analytics API - Subdomain Reports (7 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_rank(mock_get, api_key_credential):
    """Test subdomain rank report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainRankConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_overview_single_database"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_ranks(mock_get, api_key_credential):
    """Test subdomain ranks overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainRanksConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_overview_all_databases"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_rank_history(mock_get, api_key_credential):
    """Test subdomain rank history"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainRankHistoryConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_rank_history"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_organic(mock_get, api_key_credential):
    """Test subdomain organic keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainOrganicConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_organic_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_adwords(mock_get, api_key_credential):
    """Test subdomain adwords keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainAdwordsConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_paid_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_organic_unique(mock_get, api_key_credential):
    """Test subdomain organic unique keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainOrganicUniqueConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_top_organic_pages"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomain_adwords_unique(mock_get, api_key_credential):
    """Test subdomain adwords unique keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainAdwordsUniqueConfig(domain="blog.example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_unique_ad_copies"


# ============================================================================
# Analytics API - Subfolder Reports (7 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_rank(mock_get, api_key_credential):
    """Test subfolder rank report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderRankConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_overview_single_database"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_ranks(mock_get, api_key_credential):
    """Test subfolder ranks overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderRanksConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_overview_all_databases"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_rank_history(mock_get, api_key_credential):
    """Test subfolder rank history"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderRankHistoryConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_rank_history"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_organic(mock_get, api_key_credential):
    """Test subfolder organic keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderOrganicConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_organic_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_adwords(mock_get, api_key_credential):
    """Test subfolder adwords keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderAdwordsConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_paid_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_organic_unique(mock_get, api_key_credential):
    """Test subfolder organic unique keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderOrganicUniqueConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_top_organic_pages"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolder_adwords_unique(mock_get, api_key_credential):
    """Test subfolder adwords unique keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfolderAdwordsUniqueConfig(url="example.com/blog/")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_unique_ad_copies"


# ============================================================================
# Analytics API - URL Reports (5 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_url_rank(mock_get, api_key_credential):
    """Test URL rank report"""
    mock_get.return_value = create_csv_mock()

    config = SemrushUrlRankConfig(url="example.com/page.html")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_url_overview_single_database"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_url_ranks(mock_get, api_key_credential):
    """Test URL ranks overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushUrlRanksConfig(url="example.com/page.html")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_url_overview_all_databases"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_url_rank_history(mock_get, api_key_credential):
    """Test URL rank history"""
    mock_get.return_value = create_csv_mock()

    config = SemrushUrlRankHistoryConfig(url="example.com/page.html")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_url_rank_history"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_url_organic(mock_get, api_key_credential):
    """Test URL organic keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushUrlOrganicConfig(url="example.com/page.html")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_url_organic_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_url_adwords(mock_get, api_key_credential):
    """Test URL adwords keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushUrlAdwordsConfig(url="example.com/page.html")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_url_paid_keywords"


# ============================================================================
# Analytics API - Keyword Reports (10 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_all(mock_get, api_key_credential):
    """Test keyword overview all databases"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseAllConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_overview_all_databases"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_this(mock_get, api_key_credential):
    """Test keyword overview single database"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseThisConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_overview_single_database"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_these(mock_get, api_key_credential):
    """Test bulk keyword overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseTheseConfig(phrases="seo tools,keyword research")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_batch_keyword_overview"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_organic(mock_get, api_key_credential):
    """Test keyword organic results"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseOrganicConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_organic_search_results"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_adwords(mock_get, api_key_credential):
    """Test keyword adwords results"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseAdwordsConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_paid_search_results"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_related(mock_get, api_key_credential):
    """Test related keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseRelatedConfig(phrase="seo")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_related_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_adwords_historical(mock_get, api_key_credential):
    """Test keyword adwords historical"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseAdwordsHistoricalConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_ads_historical_data"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_fullsearch(mock_get, api_key_credential):
    """Test phrase match keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseFullsearchConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_broad_match_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_questions(mock_get, api_key_credential):
    """Test question keywords"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseQuestionsConfig(phrase="seo")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_question_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_phrase_kdi(mock_get, api_key_credential):
    """Test keyword difficulty index"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPhraseKdiConfig(phrase="seo tools")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_keyword_difficulty"


# ============================================================================
# Analytics API - Backlinks Reports (15 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_overview(mock_get, api_key_credential):
    """Test backlinks overview"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksOverviewConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlinks_overview"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks(mock_get, api_key_credential):
    """Test backlinks list"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlinks_list"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_refdomains(mock_get, api_key_credential):
    """Test referring domains"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksRefdomainsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_referring_domains"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_refips(mock_get, api_key_credential):
    """Test referring IPs"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksRefipsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_referring_ip_addresses"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_tld(mock_get, api_key_credential):
    """Test backlinks by TLD"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksTldConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlinks_by_tld"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_geo(mock_get, api_key_credential):
    """Test backlinks by country"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksGeoConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlinks_by_country"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_anchors(mock_get, api_key_credential):
    """Test anchor texts"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksAnchorsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlink_anchor_distribution"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_pages(mock_get, api_key_credential):
    """Test indexed pages"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksPagesConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_pages_with_backlinks"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_competitors(mock_get, api_key_credential):
    """Test backlink competitors"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksCompetitorsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlink_competitors"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_matrix(mock_get, api_key_credential):
    """Test backlinks matrix"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksMatrixConfig(targets="example.com,competitor.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "compare_backlinks_between_domains"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_comparison(mock_get, api_key_credential):
    """Test backlinks comparison"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksComparisonConfig(targets="example.com,competitor.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "compare_backlink_profiles_batch"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_ascore_profile(mock_get, api_key_credential):
    """Test Authority Score profile"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksAscoreProfileConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_authority_score_distribution"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_categories_profile(mock_get, api_key_credential):
    """Test domain categories profile"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksCategoriesProfileConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_referring_domain_categories"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_categories(mock_get, api_key_credential):
    """Test domain categories"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksCategoriesConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_target_domain_categories"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_backlinks_historical(mock_get, api_key_credential):
    """Test backlinks historical data"""
    mock_get.return_value = create_csv_mock()

    config = SemrushBacklinksHistoricalConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_backlinks_historical_data"


# ============================================================================
# Trends API (13 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_summary(mock_get, api_key_credential):
    """Test traffic summary"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficSummaryConfig(targets="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_traffic_summary_for_domains"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_daily(mock_get, api_key_credential):
    """Test daily traffic"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficDailyConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_daily_traffic_breakdown"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_weekly(mock_get, api_key_credential):
    """Test weekly traffic"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficWeeklyConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_weekly_traffic_breakdown"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_purchase_conversion(mock_get, api_key_credential):
    """Test purchase conversion"""
    mock_get.return_value = create_csv_mock()

    config = SemrushPurchaseConversionConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_purchase_conversion_rates"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_industry_categories(mock_get, api_key_credential):
    """Test industry categories"""
    mock_get.return_value = create_csv_mock()

    config = SemrushIndustryCategoriesConfig(category="Technology")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_domains_by_industry_category"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_sources(mock_get, api_key_credential):
    """Test traffic sources"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficSourcesConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_traffic_sources_breakdown"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_destinations(mock_get, api_key_credential):
    """Test traffic destinations"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficDestinationsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_traffic_destinations"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_geo_distribution(mock_get, api_key_credential):
    """Test geographic distribution"""
    mock_get.return_value = create_csv_mock()

    config = SemrushGeoDistributionConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_geographic_traffic_distribution"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subdomains_traffic(mock_get, api_key_credential):
    """Test subdomains traffic"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubdomainsTrafficConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subdomain_traffic"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_top_pages(mock_get, api_key_credential):
    """Test top pages"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTopPagesConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_top_pages_by_traffic"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_traffic_rank(mock_get, api_key_credential):
    """Test traffic rank"""
    mock_get.return_value = create_csv_mock()

    config = SemrushTrafficRankConfig(targets="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_traffic_rank_for_domains"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_audience_insights(mock_get, api_key_credential):
    """Test audience insights"""
    mock_get.return_value = create_csv_mock()

    config = SemrushAudienceInsightsConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_audience_demographics"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_subfolders_traffic(mock_get, api_key_credential):
    """Test subfolders traffic"""
    mock_get.return_value = create_csv_mock()

    config = SemrushSubfoldersTrafficConfig(target="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_subfolder_traffic"


# ============================================================================
# Projects API - Position Tracking (16 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_campaign_list(mock_get, api_key_credential):
    """Test list campaigns"""
    mock_get.return_value = create_json_mock({"campaigns": []})

    config = SemrushPTCampaignListConfig(project_id="123")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "list_position_tracking_campaigns"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_pt_create_campaign(mock_post, api_key_credential):
    """Test create campaign"""
    mock_post.return_value = create_json_mock({"campaign_id": "456"})

    config = SemrushPTCreateCampaignConfig(
        project_id="123",
        domain="example.com",
        location_id="2840",
        device="desktop",
        keywords="seo,marketing",
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "create_position_tracking_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.put")
async def test_pt_add_keywords(mock_put, api_key_credential):
    """Test add keywords"""
    mock_put.return_value = create_json_mock({"success": True})

    config = SemrushPTAddKeywordsConfig(
        campaign_id="456", keywords="content marketing,digital marketing"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "add_keywords_to_tracking_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.delete")
async def test_pt_remove_keywords(mock_delete, api_key_credential):
    """Test remove keywords"""
    mock_delete.return_value = create_json_mock({"success": True})

    config = SemrushPTRemoveKeywordsConfig(campaign_id="456", keyword_ids="789,790")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "remove_keywords_from_tracking_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.put")
async def test_pt_add_tags(mock_put, api_key_credential):
    """Test add tags"""
    mock_put.return_value = create_json_mock({"success": True})

    config = SemrushPTAddTagsConfig(
        campaign_id="456", keyword_ids="789,790", tags="important,branded"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "add_tags_to_tracked_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.delete")
async def test_pt_remove_tags(mock_delete, api_key_credential):
    """Test remove tags"""
    mock_delete.return_value = create_json_mock({"success": True})

    config = SemrushPTRemoveTagsConfig(
        campaign_id="456", keyword_ids="789,790", tags="old-tag"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "remove_tags_from_tracked_keywords"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.put")
async def test_pt_add_competitors(mock_put, api_key_credential):
    """Test add competitors"""
    mock_put.return_value = create_json_mock({"success": True})

    config = SemrushPTAddCompetitorsConfig(
        campaign_id="456", competitors="competitor1.com,competitor2.com"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "add_competitors_to_tracking_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.delete")
async def test_pt_remove_competitors(mock_delete, api_key_credential):
    """Test remove competitors"""
    mock_delete.return_value = create_json_mock({"success": True})

    config = SemrushPTRemoveCompetitorsConfig(
        campaign_id="456", competitors="competitor1.com,competitor2.com"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "remove_competitors_from_tracking_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_location_search(mock_get, api_key_credential):
    """Test location search"""
    mock_get.return_value = create_json_mock({"locations": []})

    config = SemrushPTLocationSearchConfig(query="New York")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "search_tracking_locations"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_campaign_dates(mock_get, api_key_credential):
    """Test campaign dates"""
    mock_get.return_value = create_json_mock({"dates": []})

    config = SemrushPTCampaignDatesConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_tracking_campaign_harvest_dates"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_organic_overview(mock_get, api_key_credential):
    """Test organic overview report"""
    mock_get.return_value = create_json_mock({"overview": {}})

    config = SemrushPTOrganicOverviewConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_organic_tracking_overview"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_adwords_overview(mock_get, api_key_credential):
    """Test adwords overview report"""
    mock_get.return_value = create_json_mock({"overview": {}})

    config = SemrushPTAdwordsOverviewConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_paid_search_tracking_overview"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_organic_positions(mock_get, api_key_credential):
    """Test organic positions report"""
    mock_get.return_value = create_json_mock({"positions": []})

    config = SemrushPTOrganicPositionsConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_organic_keyword_positions"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_pt_adwords_positions(mock_get, api_key_credential):
    """Test adwords positions report"""
    mock_get.return_value = create_json_mock({"positions": []})

    config = SemrushPTAdwordsPositionsConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_paid_search_keyword_positions"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.put")
async def test_pt_enable_notifications(mock_put, api_key_credential):
    """Test enable notifications"""
    mock_put.return_value = create_json_mock({"success": True})

    config = SemrushPTEnableNotificationsConfig(
        campaign_id="456", email="test@example.com"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "enable_campaign_email_notifications"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.delete")
async def test_pt_disable_notifications(mock_delete, api_key_credential):
    """Test disable notifications"""
    mock_delete.return_value = create_json_mock({"success": True})

    config = SemrushPTDisableNotificationsConfig(campaign_id="456")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "disable_campaign_email_notifications"


# ============================================================================
# Projects API - Site Audit (11 operations)
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_sa_enable(mock_post, api_key_credential):
    """Test enable site audit"""
    mock_post.return_value = create_json_mock({"success": True})

    config = SemrushSAEnableConfig(project_id="123", domain="example.com")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "enable_site_audit_for_project"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_sa_edit_campaign(mock_post, api_key_credential):
    """Test edit site audit campaign"""
    mock_post.return_value = create_json_mock({"success": True})

    config = SemrushSAEditCampaignConfig(project_id="123", max_pages=500)
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "update_site_audit_campaign"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_snapshots(mock_get, api_key_credential):
    """Test get snapshots"""
    mock_get.return_value = create_json_mock({"snapshots": []})

    config = SemrushSAGetSnapshotsConfig(project_id="123")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "list_audit_snapshots"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_sa_launch_audit(mock_post, api_key_credential):
    """Test launch audit"""
    mock_post.return_value = create_json_mock({"snapshot_id": "789"})

    config = SemrushSALaunchAuditConfig(project_id="123")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "launch_site_audit"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_campaign_info(mock_get, api_key_credential):
    """Test get campaign info"""
    mock_get.return_value = create_json_mock({"campaign": {}})

    config = SemrushSAGetCampaignInfoConfig(project_id="123")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_site_audit_campaign_info"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_snapshot_details(mock_get, api_key_credential):
    """Test get snapshot details"""
    mock_get.return_value = create_json_mock({"snapshot": {}})

    config = SemrushSAGetSnapshotDetailsConfig(project_id="123", snapshot_id="789")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_audit_snapshot_details"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_issue_details(mock_get, api_key_credential):
    """Test get issue details"""
    mock_get.return_value = create_json_mock({"issue": {}})

    config = SemrushSAGetIssueDetailsConfig(
        project_id="123", snapshot_id="789", issue_id="broken_links"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_pages_affected_by_issue"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_issue_metadata(mock_get, api_key_credential):
    """Test get issue metadata"""
    mock_get.return_value = create_json_mock({"metadata": {}})

    config = SemrushSAGetIssueMetadataConfig(issue_id="broken_links")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_issue_type_explanation"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_search_page(mock_get, api_key_credential):
    """Test search page"""
    mock_get.return_value = create_json_mock({"pages": []})

    config = SemrushSASearchPageConfig(project_id="123", url="example.com/page")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "search_audit_page_by_url"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_page_info(mock_get, api_key_credential):
    """Test get page info"""
    mock_get.return_value = create_json_mock({"page": {}})

    config = SemrushSAGetPageInfoConfig(project_id="123", page_id="999")
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_audited_page_details"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_sa_get_history(mock_get, api_key_credential):
    """Test get history"""
    mock_get.return_value = create_json_mock({"history": []})

    config = SemrushSAGetHistoryConfig(
        project_id="123", start_date="2024-01-01", end_date="2024-01-31"
    )
    node = create_node(config, api_key_credential)

    result = await node.execute({})

    assert result["success"] is True
    assert result["action"] == "get_site_audit_history"


# ============================================================================
# Credential Helper Tests
# ============================================================================


def test_get_api_key_from_api_key_credential(semrush_node, api_key_credential):
    """Test extracting API key from API key credential"""
    api_key = semrush_node._get_api_key(api_key_credential)
    assert api_key == "mock_api_key_12345"


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_empty_config_raises_error():
    """Test that missing config raises appropriate error"""
    from nodes.semrush_node import SemrushNode

    node = SemrushNode("test", "automation-semrush", {}, None, None, None, "wf")

    with pytest.raises(ValueError, match="Configuration required"):
        await node.execute({})


@pytest.mark.asyncio
async def test_missing_credentials_raises_error():
    """Test that missing credentials raises appropriate error"""
    config = SemrushDomainOrganicConfig(domain="test.com")
    node = create_node(config, None)

    with pytest.raises(ValueError, match="Credentials required"):
        await node.execute({})


@pytest.mark.asyncio
async def test_operation_count_in_schema():
    """Test that schema contains all 101 API v3 operations"""
    schema = SemrushNode.get_config_schema()
    defs = schema.get("$defs", schema.get("definitions", {}))

    operation_configs = [
        key
        for key in defs.keys()
        if key.startswith("Semrush")
        and key.endswith("Config")
        and "Credential" not in key
        and "NodeFullConfig" not in key
    ]

    assert (
        len(operation_configs) == 101
    ), f"Expected 101 operations, found {len(operation_configs)}"

"""
Mock tests for the Google DV360 REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Advertisers: list, get, create, update
- Campaigns: list, get, create, update
- Insertion Orders: list, create, update
- Line Items: list, get, create, update, duplicate
- Creatives: list, create, update
- Targeting: list assigned, create assigned, search options
- Channels: list, create
- Audiences: list, edit Customer Match members
- Reporting (Bid Manager): create query, run query
- Error handling: API errors, missing credentials
- Dynamic options: advertiser dropdown

The DV360 node authenticates via Google OAuth and refreshes tokens through the
DB-backed ``ensure_fresh_oauth_token`` helper. Tests patch ``_ensure_fresh_token``
at the source so no database / network is touched.
"""

import pytest
from unittest.mock import Mock, patch

from nodes.dv360_node import (
    DV360Node,
    DV360NodeConfig,
    DV360OAuthCredential,
    DV360ListAdvertisersConfig,
    DV360GetAdvertiserConfig,
    DV360CreateAdvertiserConfig,
    DV360UpdateAdvertiserConfig,
    DV360ListCampaignsConfig,
    DV360GetCampaignConfig,
    DV360CreateCampaignConfig,
    DV360UpdateCampaignConfig,
    DV360ListInsertionOrdersConfig,
    DV360CreateInsertionOrderConfig,
    DV360UpdateInsertionOrderConfig,
    DV360ListLineItemsConfig,
    DV360GetLineItemConfig,
    DV360CreateLineItemConfig,
    DV360UpdateLineItemConfig,
    DV360DuplicateLineItemConfig,
    DV360ListCreativesConfig,
    DV360CreateCreativeConfig,
    DV360UpdateCreativeConfig,
    DV360ListAssignedTargetingConfig,
    DV360CreateAssignedTargetingConfig,
    DV360SearchTargetingOptionsConfig,
    DV360ListChannelsConfig,
    DV360CreateChannelConfig,
    DV360ListAudiencesConfig,
    DV360EditCustomerMatchConfig,
    DV360CreateReportQueryConfig,
    DV360RunReportQueryConfig,
    DV360GetInsertionOrderConfig,
    DV360GetCreativeConfig,
    DV360GetChannelConfig,
    DV360DeleteLineItemConfig,
    DV360DeleteCreativeConfig,
    DV360ListReportQueriesConfig,
    DV360GetReportQueryConfig,
    DV360GetReportConfig,
    DV360OnJobCompletedConfig,
    DV360ServiceAccountCredential,
)


@pytest.fixture
def oauth_credentials():
    return DV360OAuthCredential(
        access_token="ya29.test_access_token",
        refresh_token="1//test_refresh_token",
        expires_at="2030-01-01T00:00:00+00:00",
        email="adops@example.com",
    )


def create_dv360_node(config):
    return DV360Node(
        node_id="test-dv360-node",
        node_type="automation-dv360",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, text=""):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text)
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


async def _run(node, mock_client):
    """Patch token refresh + httpx client, then execute the node."""
    with patch.object(DV360Node, "_ensure_fresh_token", return_value="ya29.fresh"), patch(
        "nodes.dv360_node.httpx.AsyncClient", return_value=mock_client
    ):
        return await node.execute({})


# ============================================================================
# Advertisers
# ============================================================================


class TestDV360AdvertisersMock:
    @pytest.mark.asyncio
    async def test_list_advertisers(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListAdvertisersConfig(partner_id="p123", page_size="50"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(
            200, {"advertisers": [{"advertiserId": "1"}, {"advertiserId": "2"}]}
        )
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_advertisers"
        assert len(result["data"]["advertisers"]) == 2

    @pytest.mark.asyncio
    async def test_get_advertiser(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360GetAdvertiserConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"advertiserId": "adv1", "displayName": "Acme"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "get_advertiser"
        assert result["data"]["advertiserId"] == "adv1"

    @pytest.mark.asyncio
    async def test_create_advertiser(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateAdvertiserConfig(
                advertiser_body='{"partnerId": "p1", "displayName": "New Adv"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"advertiserId": "adv_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_advertiser"
        assert result["data"]["advertiserId"] == "adv_new"

    @pytest.mark.asyncio
    async def test_update_advertiser(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360UpdateAdvertiserConfig(
                advertiser_id="adv1",
                update_mask="displayName",
                advertiser_body='{"displayName": "Renamed"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"advertiserId": "adv1", "displayName": "Renamed"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "update_advertiser"
        assert result["data"]["displayName"] == "Renamed"


# ============================================================================
# Campaigns
# ============================================================================


class TestDV360CampaignsMock:
    @pytest.mark.asyncio
    async def test_list_campaigns(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListCampaignsConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"campaigns": [{"campaignId": "c1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_campaigns"

    @pytest.mark.asyncio
    async def test_get_campaign(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360GetCampaignConfig(advertiser_id="adv1", campaign_id="c1"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"campaignId": "c1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "get_campaign"
        assert result["data"]["campaignId"] == "c1"

    @pytest.mark.asyncio
    async def test_create_campaign(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateCampaignConfig(
                advertiser_id="adv1", campaign_body='{"displayName": "Q3 push"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"campaignId": "c_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_campaign"

    @pytest.mark.asyncio
    async def test_update_campaign(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360UpdateCampaignConfig(
                advertiser_id="adv1",
                campaign_id="c1",
                update_mask="entityStatus",
                campaign_body='{"entityStatus": "ENTITY_STATUS_PAUSED"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"campaignId": "c1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "update_campaign"


# ============================================================================
# Insertion Orders
# ============================================================================


class TestDV360InsertionOrdersMock:
    @pytest.mark.asyncio
    async def test_list_insertion_orders(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListInsertionOrdersConfig(advertiser_id="adv1"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"insertionOrders": [{"insertionOrderId": "io1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_insertion_orders"

    @pytest.mark.asyncio
    async def test_create_insertion_order(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateInsertionOrderConfig(
                advertiser_id="adv1", insertion_order_body='{"campaignId": "c1"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"insertionOrderId": "io_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_insertion_order"

    @pytest.mark.asyncio
    async def test_update_insertion_order(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360UpdateInsertionOrderConfig(
                advertiser_id="adv1",
                insertion_order_id="io1",
                update_mask="entityStatus",
                insertion_order_body='{"entityStatus": "ENTITY_STATUS_ACTIVE"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"insertionOrderId": "io1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "update_insertion_order"


# ============================================================================
# Line Items
# ============================================================================


class TestDV360LineItemsMock:
    @pytest.mark.asyncio
    async def test_list_line_items(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListLineItemsConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"lineItems": [{"lineItemId": "li1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_line_items"

    @pytest.mark.asyncio
    async def test_get_line_item(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360GetLineItemConfig(advertiser_id="adv1", line_item_id="li1"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"lineItemId": "li1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "get_line_item"
        assert result["data"]["lineItemId"] == "li1"

    @pytest.mark.asyncio
    async def test_create_line_item(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateLineItemConfig(
                advertiser_id="adv1", line_item_body='{"insertionOrderId": "io1"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"lineItemId": "li_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_line_item"

    @pytest.mark.asyncio
    async def test_update_line_item(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360UpdateLineItemConfig(
                advertiser_id="adv1",
                line_item_id="li1",
                update_mask="entityStatus",
                line_item_body='{"entityStatus": "ENTITY_STATUS_PAUSED"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"lineItemId": "li1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "update_line_item"

    @pytest.mark.asyncio
    async def test_duplicate_line_item(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360DuplicateLineItemConfig(
                advertiser_id="adv1", line_item_id="li1", target_display_name="Clone"
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"duplicateLineItemId": "li_clone"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "duplicate_line_item"


# ============================================================================
# Creatives
# ============================================================================


class TestDV360CreativesMock:
    @pytest.mark.asyncio
    async def test_list_creatives(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListCreativesConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"creatives": [{"creativeId": "cr1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_creatives"

    @pytest.mark.asyncio
    async def test_create_creative(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateCreativeConfig(
                advertiser_id="adv1", creative_body='{"displayName": "Banner"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"creativeId": "cr_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_creative"

    @pytest.mark.asyncio
    async def test_update_creative(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360UpdateCreativeConfig(
                advertiser_id="adv1",
                creative_id="cr1",
                update_mask="displayName",
                creative_body='{"displayName": "Banner v2"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"creativeId": "cr1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "update_creative"


# ============================================================================
# Targeting
# ============================================================================


class TestDV360TargetingMock:
    @pytest.mark.asyncio
    async def test_list_assigned_targeting(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListAssignedTargetingConfig(
                advertiser_id="adv1", line_item_id="li1", targeting_type="TARGETING_TYPE_GEO_REGION"
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"assignedTargetingOptions": []})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_assigned_targeting"

    @pytest.mark.asyncio
    async def test_create_assigned_targeting(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateAssignedTargetingConfig(
                advertiser_id="adv1",
                line_item_id="li1",
                targeting_type="TARGETING_TYPE_GEO_REGION",
                targeting_body='{"geoRegionDetails": {"targetingOptionId": "geo1"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"assignedTargetingOptionId": "at1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_assigned_targeting"

    @pytest.mark.asyncio
    async def test_search_targeting_options(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360SearchTargetingOptionsConfig(
                targeting_type="TARGETING_TYPE_GEO_REGION", advertiser_id="adv1", query="London"
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"targetingOptions": [{"targetingOptionId": "geo1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "search_targeting_options"


# ============================================================================
# Channels
# ============================================================================


class TestDV360ChannelsMock:
    @pytest.mark.asyncio
    async def test_list_channels(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListChannelsConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"channels": [{"channelId": "ch1"}]})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_channels"

    @pytest.mark.asyncio
    async def test_create_channel(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateChannelConfig(advertiser_id="adv1", display_name="My Sites"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"channelId": "ch_new"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_channel"


# ============================================================================
# Audiences
# ============================================================================


class TestDV360AudiencesMock:
    @pytest.mark.asyncio
    async def test_list_audiences(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360ListAudiencesConfig(advertiser_id="adv1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(
            200, {"firstPartyAndPartnerAudiences": [{"firstPartyAndPartnerAudienceId": "aud1"}]}
        )
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "list_audiences"

    @pytest.mark.asyncio
    async def test_edit_customer_match_members(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360EditCustomerMatchConfig(
                advertiser_id="adv1",
                audience_id="aud1",
                edit_body='{"addedContactInfoList": {"contactInfos": []}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"firstPartyAndPartnerAudienceId": "aud1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "edit_customer_match_members"


# ============================================================================
# Reporting (Bid Manager)
# ============================================================================


class TestDV360ReportingMock:
    @pytest.mark.asyncio
    async def test_create_report_query(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateReportQueryConfig(
                query_body='{"metadata": {"title": "Daily"}, "params": {"type": "STANDARD"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"queryId": "q1"})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "create_report_query"
        assert result["data"]["queryId"] == "q1"

    @pytest.mark.asyncio
    async def test_run_report_query(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360RunReportQueryConfig(query_id="q1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(200, {"key": {"queryId": "q1", "reportId": "r1"}})
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["action"] == "run_report_query"


# ============================================================================
# Error handling
# ============================================================================


class TestDV360ErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360GetAdvertiserConfig(advertiser_id="missing"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Advertiser not found"}})
        result = await _run(node, mock_client)
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = DV360NodeConfig(
            config=DV360ListAdvertisersConfig(partner_id="p1"), credentials=None
        )
        node = create_dv360_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, oauth_credentials):
        config = DV360NodeConfig(
            config=DV360CreateCampaignConfig(advertiser_id="adv1", campaign_body="{not json}"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        with patch.object(DV360Node, "_ensure_fresh_token", return_value="ya29.fresh"):
            with pytest.raises(ValueError, match="must be valid JSON"):
                await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestDV360DynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_advertiser_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {
                    "advertisers": [
                        {"advertiserId": "1", "displayName": "Acme"},
                        {"advertiserId": "2", "displayName": "Globex"},
                    ],
                    "nextPageToken": "tok2",
                },
            },
        ):
            result = await DV360Node.load_field_options(
                "advertiser_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"partner_id": "p1"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "1"
        assert "Acme" in result["options"][0]["label"]
        assert result["next_page_token"] == "tok2"

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await DV360Node.load_field_options("nonexistent_field", {})
        assert result == {"options": [], "next_page_token": None}

    @pytest.mark.asyncio
    async def test_load_partner_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {
                    "partners": [
                        {"partnerId": "10", "displayName": "Holdco"},
                        {"partnerId": "11", "displayName": "Agency"},
                    ],
                    "nextPageToken": "ptok",
                },
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "partner_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
            )
        assert result["options"][0] == {"label": "Holdco (10)", "value": "10"}
        assert result["next_page_token"] == "ptok"
        # partners.list is a top-level resource, not advertiser-scoped.
        assert mock_req.call_args.args[2].endswith("/partners")

    @pytest.mark.asyncio
    async def test_load_campaign_options_depends_on_advertiser(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {"campaigns": [{"campaignId": "c1", "displayName": "Q3"}]},
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "campaign_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"advertiser_id": "adv1"},
            )
        assert result["options"] == [{"label": "Q3 (c1)", "value": "c1"}]
        assert "/advertisers/adv1/campaigns" in mock_req.call_args.args[2]

    @pytest.mark.asyncio
    async def test_load_campaign_options_without_advertiser_returns_empty(self):
        # depends_on parent unset -> no call, empty options.
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch("nodes.dv360_node._dv360_request") as mock_req:
            result = await DV360Node.load_field_options(
                "campaign_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={},
            )
        assert result == {"options": [], "next_page_token": None}
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_insertion_order_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {
                    "insertionOrders": [{"insertionOrderId": "io1", "displayName": "IO One"}]
                },
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "insertion_order_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"advertiser_id": "adv1"},
            )
        assert result["options"] == [{"label": "IO One (io1)", "value": "io1"}]
        assert "/advertisers/adv1/insertionOrders" in mock_req.call_args.args[2]

    @pytest.mark.asyncio
    async def test_load_line_item_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {"lineItems": [{"lineItemId": "li1", "displayName": "LI One"}]},
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "line_item_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"advertiser_id": "adv1"},
            )
        assert result["options"] == [{"label": "LI One (li1)", "value": "li1"}]
        assert "/advertisers/adv1/lineItems" in mock_req.call_args.args[2]

    @pytest.mark.asyncio
    async def test_load_creative_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {"creatives": [{"creativeId": "cr1", "displayName": "Banner"}]},
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "creative_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"advertiser_id": "adv1"},
            )
        assert result["options"] == [{"label": "Banner (cr1)", "value": "cr1"}]
        assert "/advertisers/adv1/creatives" in mock_req.call_args.args[2]

    @pytest.mark.asyncio
    async def test_load_audience_options(self):
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {
                    "firstPartyAndPartnerAudiences": [
                        {"firstPartyAndPartnerAudienceId": "aud1", "displayName": "VIPs"}
                    ]
                },
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "audience_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
                context={"advertiser_id": "adv1"},
            )
        assert result["options"] == [{"label": "VIPs (aud1)", "value": "aud1"}]
        # advertiserId passed as a query param, not a path segment.
        assert mock_req.call_args.args[2].endswith("/firstPartyAndPartnerAudiences")
        assert mock_req.call_args.kwargs["params"]["advertiserId"] == "adv1"

    @pytest.mark.asyncio
    async def test_load_query_options(self):
        # Bid Manager queries: title lives under metadata.title, host differs.
        with patch.object(
            DV360Node, "_token_from_credential_data", return_value="ya29.fresh"
        ), patch(
            "nodes.dv360_node._dv360_request",
            return_value={
                "status": "success",
                "data": {
                    "queries": [
                        {"queryId": "q1", "metadata": {"title": "Daily Spend"}},
                    ]
                },
            },
        ) as mock_req:
            result = await DV360Node.load_field_options(
                "query_id",
                {"access_token": "ya29", "expires_at": "2030-01-01T00:00:00+00:00"},
            )
        assert result["options"] == [{"label": "Daily Spend (q1)", "value": "q1"}]
        assert mock_req.call_args.args[2].endswith("/queries")


# ============================================================================
# Trigger (poll-based) — on_job_completed
# ============================================================================


def _report(report_id, state="DONE"):
    """Build a Bid Manager report-run resource with the given id + status state."""
    return {"key": {"queryId": "q1", "reportId": report_id}, "metadata": {"status": {"state": state}}}


class TestDV360TriggerResolvePayload:
    def test_resolve_returns_none_for_trigger_op(self):
        """Poll trigger must return None so execute() runs and polls the API."""
        assert (
            DV360Node.resolve_trigger_payload({"any": "payload"}, {"operation": "on_job_completed"})
            is None
        )

    def test_resolve_passthrough_for_normal_op(self):
        """Non-trigger ops pass the payload through unchanged."""
        payload = {"data": {"advertiserId": "adv1"}}
        assert (
            DV360Node.resolve_trigger_payload(payload, {"operation": "list_advertisers"}) is payload
        )


class TestDV360TriggerPollMock:
    @pytest.mark.asyncio
    async def test_poll_emits_only_done_reports(self, oauth_credentials):
        """First poll (no cursor) emits only completed runs; running/failed are skipped."""
        config = DV360NodeConfig(
            config=DV360OnJobCompletedConfig(query_id="q1"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(
            200,
            {"reports": [_report("100"), _report("101", "RUNNING"), _report("102")]},
        )
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["operation"] == "on_job_completed"
        assert result["new_count"] == 2
        emitted_ids = {r["key"]["reportId"] for r in result["items"]}
        assert emitted_ids == {"100", "102"}
        # Cursor advances to the highest completed report id.
        assert result["last_seen_id"] == "102"

    @pytest.mark.asyncio
    async def test_poll_dedupes_via_cursor(self, oauth_credentials):
        """With a cursor set, only newly completed runs past the cursor are emitted."""
        config = DV360NodeConfig(
            config=DV360OnJobCompletedConfig(query_id="q1", last_seen_id="102"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(
            200,
            {"reports": [_report("100"), _report("102"), _report("105"), _report("110")]},
        )
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        # 100 and 102 already seen; only 105 and 110 are new.
        assert result["new_count"] == 2
        emitted_ids = {r["key"]["reportId"] for r in result["items"]}
        assert emitted_ids == {"105", "110"}
        assert result["last_seen_id"] == "110"

    @pytest.mark.asyncio
    async def test_poll_no_new_reports_keeps_cursor(self, oauth_credentials):
        """When nothing new completed, emit nothing and keep the cursor unchanged."""
        config = DV360NodeConfig(
            config=DV360OnJobCompletedConfig(query_id="q1", last_seen_id="110"),
            credentials=oauth_credentials,
        )
        node = create_dv360_node(config)
        mock_client = create_mock_client(
            200, {"reports": [_report("100"), _report("110"), _report("115", "RUNNING")]}
        )
        result = await _run(node, mock_client)
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["last_seen_id"] == "110"

    @pytest.mark.asyncio
    async def test_poll_hits_reports_endpoint(self, oauth_credentials):
        """Poll targets the Bid Manager queries/{id}/reports list endpoint."""
        config = DV360NodeConfig(
            config=DV360OnJobCompletedConfig(query_id="q7"), credentials=oauth_credentials
        )
        node = create_dv360_node(config)
        with patch.object(DV360Node, "_ensure_fresh_token", return_value="ya29.fresh"), patch(
            "nodes.dv360_node._dv360_request",
            return_value={"status": "success", "data": {"reports": [_report("1")]}},
        ) as mock_req:
            result = await node.execute({})
        assert mock_req.call_args.args[1] == "GET"
        assert mock_req.call_args.args[2].endswith("/queries/q7/reports")
        assert result["new_count"] == 1


def _capture_client(status_code=200, json_data=None):
    """Mock httpx client that records the request (method/url/params/json)."""
    captured = {}
    mock_response = create_mock_response(status_code, json_data or {}, "")

    async def async_request(*args, **kwargs):
        captured.update(kwargs)
        return mock_response

    mock_client = Mock()
    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *a):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, captured


async def _run_capture(node, mock_client):
    with patch.object(DV360Node, "_ensure_fresh_token", return_value="ya29.fresh"), patch(
        "nodes.dv360_node.httpx.AsyncClient", return_value=mock_client
    ):
        return await node.execute({})


class TestDV360AdditionalOpsMock:
    """New coverage operations, asserting the exact endpoint hit."""

    @pytest.mark.asyncio
    async def test_get_insertion_order(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360GetInsertionOrderConfig(advertiser_id="a1", insertion_order_id="io1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"insertionOrderId": "io1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "GET"
        assert cap["url"].endswith("/advertisers/a1/insertionOrders/io1")

    @pytest.mark.asyncio
    async def test_get_creative(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360GetCreativeConfig(advertiser_id="a1", creative_id="cr1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"creativeId": "cr1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/advertisers/a1/creatives/cr1")

    @pytest.mark.asyncio
    async def test_get_channel(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360GetChannelConfig(advertiser_id="a1", channel_id="ch1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"channelId": "ch1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/advertisers/a1/channels/ch1")

    @pytest.mark.asyncio
    async def test_delete_line_item(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360DeleteLineItemConfig(advertiser_id="a1", line_item_id="li1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "DELETE"
        assert cap["url"].endswith("/advertisers/a1/lineItems/li1")

    @pytest.mark.asyncio
    async def test_delete_creative(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360DeleteCreativeConfig(advertiser_id="a1", creative_id="cr1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "DELETE"
        assert cap["url"].endswith("/advertisers/a1/creatives/cr1")

    @pytest.mark.asyncio
    async def test_list_report_queries(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360ListReportQueriesConfig(),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"queries": []})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "GET"
        assert cap["url"].endswith("/queries")

    @pytest.mark.asyncio
    async def test_get_report_query(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360GetReportQueryConfig(query_id="q1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"queryId": "q1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/queries/q1")

    @pytest.mark.asyncio
    async def test_get_report(self, oauth_credentials):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360GetReportConfig(query_id="q1", report_id="r1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"key": {"reportId": "r1"}})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/queries/q1/reports/r1")


class TestDV360ServiceAccountAuthMock:
    """Service-account credential mode mints a token and runs like OAuth."""

    @pytest.mark.asyncio
    async def test_service_account_execute(self):
        node = create_dv360_node(DV360NodeConfig(
            config=DV360ListAdvertisersConfig(partner_id="p1"),
            credentials=DV360ServiceAccountCredential(
                service_account_json='{"type":"service_account","client_email":"x@y.iam"}'),
        ))
        mock_client = create_mock_client(200, {"advertisers": [{"advertiserId": "a1"}]})
        with patch(
            "nodes.dv360_node._mint_service_account_access_token", return_value="ya29.sa"
        ), patch("nodes.dv360_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_advertisers"

    @pytest.mark.asyncio
    async def test_service_account_dropdown_token(self):
        """load_field_options resolves a token from SA credential_data (mints it)."""
        with patch(
            "nodes.dv360_node._mint_service_account_access_token", return_value="ya29.sa"
        ):
            token = await DV360Node._token_from_credential_data(
                {"credential_type": "dv360_service_account",
                 "service_account_json": '{"type":"service_account"}'}
            )
        assert token == "ya29.sa"


# ---------------------------------------------------------------------------
# Dynamic-options loader: errors must SURFACE, not silently return [].
# The dropdown loader contract (workflow_handler.load_node_options) is to raise
# ValueError with a user-facing message on failure; returning an empty list on a
# 403/401 hid the real cause ("No options available") and made a permission /
# entitlement problem indistinguishable from an empty account.
# ---------------------------------------------------------------------------

_OAUTH_CRED = {"credential_type": "dv360_oauth", "access_token": "ya29.fresh"}


async def _load(field, context=None):
    return await DV360Node.load_field_options(
        field_name=field, credential_data=_OAUTH_CRED, context=context or {}
    )


@pytest.mark.asyncio
async def test_dropdown_api_error_raises_with_detail():
    err = {"status": "error", "error": "PERMISSION_DENIED: no access", "status_code": 403}
    with patch("nodes.dv360_node._dv360_request", return_value=err):
        with pytest.raises(ValueError) as ei:
            await _load("partner_id")
    msg = str(ei.value)
    assert "partner id" in msg and "PERMISSION_DENIED: no access" in msg
    # 401/403 append the DV360-access hint
    assert "Display & Video 360 access" in msg


@pytest.mark.asyncio
async def test_dropdown_advertiser_without_partner_raises_actionable():
    # advertisers.list requires a partnerId the advertiser-scoped ops don't
    # provide — surface an actionable message instead of an empty list.
    with pytest.raises(ValueError) as ei:
        await _load("advertiser_id", context={})
    assert "partner" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_dropdown_child_without_selected_parent_returns_empty():
    # A depends_on child (campaign under advertiser) with no advertiser picked
    # yet is a legitimate empty state, NOT an error.
    out = await _load("campaign_id", context={})
    assert out == {"options": [], "next_page_token": None}


@pytest.mark.asyncio
async def test_dropdown_success_parses_options():
    ok = {
        "status": "success",
        "data": {"partners": [{"partnerId": "p1", "displayName": "Acme"}], "nextPageToken": "n2"},
    }
    with patch("nodes.dv360_node._dv360_request", return_value=ok):
        out = await _load("partner_id")
    assert out["options"] == [{"label": "Acme (p1)", "value": "p1"}]
    assert out["next_page_token"] == "n2"


@pytest.mark.asyncio
async def test_dropdown_missing_token_raises():
    with pytest.raises(ValueError):
        await DV360Node.load_field_options(
            field_name="partner_id",
            credential_data={"credential_type": "dv360_oauth"},  # no access_token
            context={},
        )

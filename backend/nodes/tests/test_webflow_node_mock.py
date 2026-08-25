"""
Mock tests for the Webflow Data API (v2) node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Sites: list, get, publish
- Pages: list, get content, update content
- Collections: list, get, create, create field
- CMS Items: list, get, create, create live, update, delete, publish
- Forms: list, get schema, list submissions, get submission
- Assets: list
- Ecommerce: list/create products, list/get/fulfill orders, list inventory
- Comments: list comment threads
- Webhooks: list, create, remove
- Token: get authorized user
- Triggers: one operation per Webflow event; passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: site dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.webflow_node import (
    WebflowNode,
    WebflowNodeConfig,
    WebflowApiTokenCredential,
    WebflowOAuthCredential,
    _extract_token,
    WebflowListSitesConfig,
    WebflowGetSiteConfig,
    WebflowPublishSiteConfig,
    WebflowListPagesConfig,
    WebflowGetPageContentConfig,
    WebflowUpdatePageContentConfig,
    WebflowListCollectionsConfig,
    WebflowGetCollectionConfig,
    WebflowCreateCollectionConfig,
    WebflowCreateCollectionFieldConfig,
    WebflowListItemsConfig,
    WebflowGetItemConfig,
    WebflowCreateItemConfig,
    WebflowCreateLiveItemConfig,
    WebflowUpdateItemConfig,
    WebflowDeleteItemConfig,
    WebflowPublishItemsConfig,
    WebflowListFormsConfig,
    WebflowGetFormConfig,
    WebflowListFormSubmissionsConfig,
    WebflowGetFormSubmissionConfig,
    WebflowListAssetsConfig,
    WebflowListProductsConfig,
    WebflowCreateProductConfig,
    WebflowListOrdersConfig,
    WebflowGetOrderConfig,
    WebflowFulfillOrderConfig,
    WebflowListInventoryConfig,
    WebflowListCommentThreadsConfig,
    WebflowListWebhooksConfig,
    WebflowCreateWebhookConfig,
    WebflowRemoveWebhookConfig,
    WebflowGetAuthorizedUserConfig,
    WEBFLOW_TRIGGER_CONFIGS,
    WEBFLOW_TRIGGER_TYPES,
    # Coverage-expansion ops
    WebflowGetCustomDomainsConfig,
    WebflowGetPageMetadataConfig,
    WebflowUpdatePageMetadataConfig,
    WebflowListComponentsConfig,
    WebflowUpdateComponentContentConfig,
    WebflowDeleteCollectionConfig,
    WebflowUpdateCollectionFieldConfig,
    WebflowDeleteCollectionFieldConfig,
    WebflowListLiveItemsConfig,
    WebflowGetLiveItemConfig,
    WebflowUpdateLiveItemConfig,
    WebflowDeleteLiveItemConfig,
    WebflowCreateBulkItemsConfig,
    WebflowGetProductConfig,
    WebflowUpdateProductConfig,
    WebflowCreateSkusConfig,
    WebflowUpdateSkuConfig,
    WebflowUpdateInventoryConfig,
    WebflowGetEcommerceSettingsConfig,
    WebflowUpdateOrderConfig,
    WebflowUnfulfillOrderConfig,
    WebflowRefundOrderConfig,
    WebflowListSiteFormSubmissionsConfig,
    WebflowModifySubmissionConfig,
    WebflowDeleteSubmissionConfig,
    WebflowGetAssetConfig,
    WebflowCreateAssetConfig,
    WebflowUpdateAssetConfig,
    WebflowDeleteAssetConfig,
    WebflowListAssetFoldersConfig,
    WebflowCreateAssetFolderConfig,
    WebflowGetCommentThreadConfig,
    WebflowListCommentRepliesConfig,
    WebflowGetWebhookConfig,
    WebflowIntrospectTokenConfig,
    WebflowRegisterInlineScriptConfig,
    WebflowListRegisteredScriptsConfig,
    WebflowApplySiteCustomCodeConfig,
    WebflowRemoveSiteCustomCodeConfig,
    WebflowApplyPageCustomCodeConfig,
)


@pytest.fixture
def api_token_credentials():
    return WebflowApiTokenCredential(api_token="wf_test_token_12345")


@pytest.fixture
def oauth_credentials():
    return WebflowOAuthCredential(
        access_token="wf_oauth_access_token",
        name="Jane Designer",
        email="jane@example.com",
    )


def create_webflow_node(config):
    return WebflowNode(
        node_id="test-webflow-node",
        node_type="automation-webflow",
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


def run_op(config_obj, credentials, status_code=200, json_data=None):
    """Build a node, mock the HTTP client, run execute({}), return the result."""
    config = WebflowNodeConfig(config=config_obj, credentials=credentials)
    node = create_webflow_node(config)
    mock_client = create_mock_client(status_code, json_data)
    return node, mock_client


class TestWebflowSitesMock:
    @pytest.mark.asyncio
    async def test_list_sites(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListSitesConfig(), api_token_credentials, 200, {"sites": [{"id": "s1"}]}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_sites"
        assert result["data"]["sites"][0]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_get_site(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetSiteConfig(site_id="s1"), api_token_credentials, 200, {"id": "s1", "displayName": "My Site"}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_site"
        assert result["data"]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_publish_site(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowPublishSiteConfig(site_id="s1", publish_to_webflow_subdomain="true"),
            api_token_credentials,
            200,
            {"queued": True},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "publish_site"


class TestWebflowPagesMock:
    @pytest.mark.asyncio
    async def test_list_pages(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListPagesConfig(site_id="s1"), api_token_credentials, 200, {"pages": [{"id": "p1"}]}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_pages"

    @pytest.mark.asyncio
    async def test_get_page_content(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetPageContentConfig(page_id="p1"), api_token_credentials, 200, {"nodes": []}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_page_content"

    @pytest.mark.asyncio
    async def test_update_page_content(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowUpdatePageContentConfig(
                page_id="p1", nodes_json='[{"nodeId":"n1","text":"Hello"}]'
            ),
            api_token_credentials,
            200,
            {"errors": []},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_page_content"


class TestWebflowCollectionsMock:
    @pytest.mark.asyncio
    async def test_list_collections(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListCollectionsConfig(site_id="s1"),
            api_token_credentials,
            200,
            {"collections": [{"id": "c1"}]},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_collections"

    @pytest.mark.asyncio
    async def test_get_collection(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetCollectionConfig(collection_id="c1"),
            api_token_credentials,
            200,
            {"id": "c1", "fields": []},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_collection"
        assert result["data"]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_create_collection(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateCollectionConfig(
                site_id="s1", display_name="Blog Posts", singular_name="Blog Post", slug="blog-posts"
            ),
            api_token_credentials,
            201,
            {"id": "c_new"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_collection"
        assert result["data"]["id"] == "c_new"

    @pytest.mark.asyncio
    async def test_create_collection_field(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateCollectionFieldConfig(
                collection_id="c1", field_type="PlainText", display_name="Subtitle", is_required="false"
            ),
            api_token_credentials,
            201,
            {"id": "f_new"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_collection_field"


class TestWebflowItemsMock:
    @pytest.mark.asyncio
    async def test_list_items(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListItemsConfig(collection_id="c1", limit="50"),
            api_token_credentials,
            200,
            {"items": [{"id": "i1"}, {"id": "i2"}]},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_items"
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_item(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetItemConfig(collection_id="c1", item_id="i1"),
            api_token_credentials,
            200,
            {"id": "i1"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_item"
        assert result["data"]["id"] == "i1"

    @pytest.mark.asyncio
    async def test_create_item(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateItemConfig(
                collection_id="c1", field_data_json='{"name":"My Item","slug":"my-item"}'
            ),
            api_token_credentials,
            201,
            {"id": "i_new"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_item"
        assert result["data"]["id"] == "i_new"

    @pytest.mark.asyncio
    async def test_create_live_item(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateLiveItemConfig(
                collection_id="c1", field_data_json='{"name":"Live Item","slug":"live-item"}'
            ),
            api_token_credentials,
            202,
            {"id": "i_live"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_live_item"

    @pytest.mark.asyncio
    async def test_update_item(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowUpdateItemConfig(
                collection_id="c1", item_id="i1", field_data_json='{"name":"Renamed"}'
            ),
            api_token_credentials,
            200,
            {"items": [{"id": "i1"}]},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_item"

    @pytest.mark.asyncio
    async def test_delete_item(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowDeleteItemConfig(collection_id="c1", item_id="i1"),
            api_token_credentials,
            204,
            None,
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_item"

    @pytest.mark.asyncio
    async def test_publish_items(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowPublishItemsConfig(collection_id="c1", item_ids="i1, i2"),
            api_token_credentials,
            200,
            {"publishedItemIds": ["i1", "i2"]},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "publish_items"


class TestWebflowFormsMock:
    @pytest.mark.asyncio
    async def test_list_forms(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListFormsConfig(site_id="s1"), api_token_credentials, 200, {"forms": [{"id": "fm1"}]}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_forms"

    @pytest.mark.asyncio
    async def test_get_form(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetFormConfig(form_id="fm1"), api_token_credentials, 200, {"id": "fm1"}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_form"

    @pytest.mark.asyncio
    async def test_list_form_submissions(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListFormSubmissionsConfig(site_id="s1", form_id="fm1", limit="10"),
            api_token_credentials,
            200,
            {"formSubmissions": [{"id": "sub1"}]},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_form_submissions"

    @pytest.mark.asyncio
    async def test_get_form_submission(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetFormSubmissionConfig(site_id="s1", form_submission_id="sub1"),
            api_token_credentials,
            200,
            {"id": "sub1"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_form_submission"


class TestWebflowAssetsMock:
    @pytest.mark.asyncio
    async def test_list_assets(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListAssetsConfig(site_id="s1"), api_token_credentials, 200, {"assets": []}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_assets"


class TestWebflowEcommerceMock:
    @pytest.mark.asyncio
    async def test_list_products(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListProductsConfig(site_id="s1"), api_token_credentials, 200, {"items": []}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_products"

    @pytest.mark.asyncio
    async def test_create_product(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateProductConfig(
                site_id="s1",
                product_field_data_json='{"name":"T-Shirt","slug":"t-shirt"}',
                sku_field_data_json='{"name":"Default","price":{"value":1000,"unit":"USD"}}',
            ),
            api_token_credentials,
            201,
            {"product": {"id": "prod1"}},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_product"

    @pytest.mark.asyncio
    async def test_list_orders(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListOrdersConfig(site_id="s1"), api_token_credentials, 200, {"orders": []}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_orders"

    @pytest.mark.asyncio
    async def test_get_order(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetOrderConfig(site_id="s1", order_id="o1"),
            api_token_credentials,
            200,
            {"orderId": "o1"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_order"

    @pytest.mark.asyncio
    async def test_fulfill_order(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowFulfillOrderConfig(site_id="s1", order_id="o1", send_order_fulfilled_email="true"),
            api_token_credentials,
            200,
            {"status": "fulfilled"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "fulfill_order"

    @pytest.mark.asyncio
    async def test_list_inventory(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListInventoryConfig(collection_id="sku_c1", sku_id="sku1"),
            api_token_credentials,
            200,
            {"quantity": 5},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_inventory"


class TestWebflowCommentsMock:
    @pytest.mark.asyncio
    async def test_list_comment_threads(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListCommentThreadsConfig(site_id="s1"),
            api_token_credentials,
            200,
            {"comments": []},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_comment_threads"


class TestWebflowWebhooksMock:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowListWebhooksConfig(site_id="s1"), api_token_credentials, 200, {"webhooks": []}
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowCreateWebhookConfig(
                site_id="s1", trigger_type="form_submission", url="https://abc.hooks.example.test"
            ),
            api_token_credentials,
            201,
            {"id": "wh1"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["id"] == "wh1"

    @pytest.mark.asyncio
    async def test_remove_webhook(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowRemoveWebhookConfig(webhook_id="wh1"), api_token_credentials, 204, None
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "remove_webhook"


class TestWebflowTokenMock:
    @pytest.mark.asyncio
    async def test_get_authorized_user(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetAuthorizedUserConfig(),
            api_token_credentials,
            200,
            {"user": {"email": "ada@example.com"}},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_authorized_user"
        assert result["data"]["user"]["email"] == "ada@example.com"


class TestWebflowTriggerMock:
    def test_one_operation_per_event(self):
        """Every Webflow event type is its own trigger operation (no trigger_type field)."""
        assert set(WEBFLOW_TRIGGER_CONFIGS) == set(WEBFLOW_TRIGGER_TYPES)
        assert len(WEBFLOW_TRIGGER_CONFIGS) == 14
        for op, cls in WEBFLOW_TRIGGER_CONFIGS.items():
            assert "trigger_type" not in cls.model_fields
            const = cls.model_fields["operation"].json_schema_extra["const"]
            assert const == op
            assert cls.model_fields["operation"].json_schema_extra["x-is-trigger"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trigger_op", WEBFLOW_TRIGGER_TYPES)
    async def test_trigger_passthrough(self, trigger_op):
        """Each per-event trigger passes the inbound webhook payload through as output."""
        config = WebflowNodeConfig(
            config=WEBFLOW_TRIGGER_CONFIGS[trigger_op](
                site_id="s1", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_webflow_node(config)
        payload = {"triggerType": trigger_op, "payload": {"name": "Ada"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == trigger_op
        assert result["data"]["triggerType"] == trigger_op
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trigger_op", WEBFLOW_TRIGGER_TYPES)
    async def test_register_external_webhook_uses_operation_as_trigger_type(self, trigger_op):
        """Registration derives the Webflow triggerType from the operation discriminator."""
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={"status": "success", "data": {"id": "wh99"}},
        ) as mock_req:
            extra = await WebflowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_token": "wf_test"},
                config={"site_id": "s1", "operation": trigger_op},
                node_id="node-1",
            )
        assert mock_req.called
        # triggerType posted to Webflow == the selected operation
        assert mock_req.call_args.kwargs["json_body"]["triggerType"] == trigger_op
        assert extra["external_webhook_id"] == "wh99"
        assert extra["signing_secret"]

    @pytest.mark.asyncio
    async def test_register_external_webhook_rejects_non_trigger_operation(self):
        with pytest.raises(ValueError, match="Unsupported Webflow trigger"):
            await WebflowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_token": "wf_test"},
                config={"site_id": "s1", "operation": "list_sites"},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_site(self):
        with pytest.raises(ValueError, match="site"):
            await WebflowNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_token": "wf_test"},
                config={"operation": "form_submission"},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await WebflowNode._unregister_external_webhook(
                credential={"api_token": "wf_test"},
                config={"external_webhook_id": "wh99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        timestamp = "1700000000000"
        body = b'{"triggerType":"form_submission"}'
        message = f"{timestamp}:{body.decode()}".encode()
        good_sig = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        assert WebflowNode.verify_webhook_signature(
            body,
            {"x-webflow-signature": good_sig, "x-webflow-timestamp": timestamp},
            {"client_secret": secret},
        )
        assert not WebflowNode.verify_webhook_signature(
            body,
            {"x-webflow-signature": "deadbeef", "x-webflow-timestamp": timestamp},
            {"client_secret": secret},
        )
        # no secret configured (Site-Token webhook, unsigned) -> accept
        assert WebflowNode.verify_webhook_signature(body, {}, {})


class TestWebflowErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_token_credentials):
        node, mock_client = run_op(
            WebflowGetSiteConfig(site_id="missing"),
            api_token_credentials,
            404,
            {"message": "Site not found"},
        )
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = WebflowNodeConfig(config=WebflowListSitesConfig(), credentials=None)
        node = create_webflow_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_json_field(self, api_token_credentials):
        config = WebflowNodeConfig(
            config=WebflowCreateItemConfig(collection_id="c1", field_data_json="not json"),
            credentials=api_token_credentials,
        )
        node = create_webflow_node(config)
        with pytest.raises(ValueError, match="valid JSON"):
            await node.execute({})


class TestWebflowDynamicOptionsMock:
    # Canonical signature: (field_name, credential_data, context, page_token, search)
    # with credential_data pre-decrypted — the old (user_id, config_data,
    # credential_ids, pool) signature raised a TypeError in the config panel.
    @pytest.mark.asyncio
    async def test_load_site_options(self):
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={
                "status": "success",
                "data": {"sites": [{"id": "s1", "displayName": "Marketing Site"}]},
            },
        ):
            result = await WebflowNode.load_field_options(
                field_name="site_id", credential_data={"api_token": "wf_test"}, context={}
            )
        assert result["options"][0] == {"value": "s1", "label": "Marketing Site"}

    @pytest.mark.asyncio
    async def test_load_form_options(self):
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={
                "status": "success",
                "data": {"forms": [{"id": "fm1", "displayName": "Contact Form"}]},
            },
        ):
            result = await WebflowNode.load_field_options(
                field_name="form_id", credential_data={"api_token": "wf_test"}, context={"site_id": "s1"}
            )
        assert result["options"][0] == {"value": "fm1", "label": "Contact Form"}

    @pytest.mark.asyncio
    async def test_load_form_options_requires_site(self):
        """form_id depends on site_id; with no parent value, return no options."""
        with patch("nodes.webflow_node._webflow_request") as mock_request:
            result = await WebflowNode.load_field_options(
                field_name="form_id", credential_data={"api_token": "wf_test"}, context={}
            )
        assert result["options"] == []
        mock_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_order_options(self):
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={
                "status": "success",
                "data": {
                    "orders": [
                        {
                            "orderId": "ABC123",
                            "status": "unfulfilled",
                            "customerInfo": {"fullName": "Jane Doe"},
                        }
                    ]
                },
            },
        ):
            result = await WebflowNode.load_field_options(
                field_name="order_id",
                credential_data={"api_token": "wf_test"},
                context={"config": {"site_id": "s1"}},
            )
        assert result["options"][0] == {"value": "ABC123", "label": "ABC123 - Jane Doe"}


class TestWebflowOAuthCredential:
    """The OAuth credential resolves to the same Bearer-token request path as the
    API-token credential (access_token vs api_token), and the node's
    rotating-OAuth freshen contract is wired in."""

    def test_extract_token_handles_both_shapes(self):
        assert _extract_token({"access_token": "oauth-tok"}) == "oauth-tok"
        assert _extract_token({"api_token": "site-tok"}) == "site-tok"
        # OAuth access_token takes precedence when both somehow present.
        assert _extract_token({"access_token": "a", "api_token": "b"}) == "a"
        assert _extract_token({}) is None
        assert _extract_token(None) is None

    @pytest.mark.asyncio
    async def test_execute_with_oauth_credential(self, oauth_credentials):
        """An OAuth credential executes and sends its access_token as the Bearer
        header on the live Webflow API call."""
        captured = {}

        async def async_request(*args, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return create_mock_response(200, {"sites": [{"id": "s1"}]})

        mock_client = create_mock_client(200, {"sites": [{"id": "s1"}]})
        mock_client.request = async_request

        config = WebflowNodeConfig(config=WebflowListSitesConfig(), credentials=oauth_credentials)
        node = create_webflow_node(config)
        with patch("nodes.webflow_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["sites"][0]["id"] == "s1"
        assert captured["headers"]["Authorization"] == "Bearer wf_oauth_access_token"

    @pytest.mark.asyncio
    async def test_dynamic_options_with_oauth_credential(self):
        """Site dropdown resolves a token from an OAuth credential (access_token),
        not just the API-token credential (api_token)."""
        with patch(
            "nodes.webflow_node._webflow_request",
            return_value={
                "status": "success",
                "data": {"sites": [{"id": "s1", "displayName": "OAuth Site"}]},
            },
        ) as mock_request:
            result = await WebflowNode.load_field_options(
                field_name="site_id",
                credential_data={"access_token": "wf_oauth_access_token"},
                context={},
            )
        assert result["options"][0]["value"] == "s1"
        # The token passed to the request helper is the OAuth access_token.
        assert mock_request.call_args.args[0] == "wf_oauth_access_token"

    def test_freshen_credential_override_present(self):
        """The rotating-OAuth structural guard requires this override because the
        OAuth credential model exposes a refresh_token field."""
        from nodes.core.base import WorkflowNode

        assert (
            WebflowNode.freshen_credential.__func__
            is not WorkflowNode.freshen_credential.__func__
        )

    @pytest.mark.asyncio
    async def test_freshen_credential_is_noop_without_refresh_token(self):
        """Webflow tokens are non-expiring and carry no refresh_token, so freshen
        returns the credential unchanged (the shared choke point short-circuits)."""
        cred = {"access_token": "wf_oauth_access_token", "expires_at": None}
        out = await WebflowNode.freshen_credential(cred)
        assert out == {"access_token": "wf_oauth_access_token", "expires_at": None}


# ============================================================================
# Coverage-expansion ops: verify each hits the correct v2 endpoint (method+path)
# ============================================================================


async def _capture(config_obj, credentials):
    """Run an op with a capturing client; return the captured method + url."""
    cap = {}
    resp = create_mock_response(200, {"ok": True})
    client = Mock()

    async def async_request(*args, **kwargs):
        cap["method"] = kwargs.get("method")
        cap["url"] = kwargs.get("url")
        return resp

    client.request = async_request

    async def aenter(self):
        return client

    async def aexit(self, *a):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    node = create_webflow_node(WebflowNodeConfig(config=config_obj, credentials=credentials))
    with patch("nodes.webflow_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    return cap


class TestWebflowExpandedCoverage:
    @pytest.mark.asyncio
    async def test_endpoint_paths(self, api_token_credentials):
        SID, CID, IID = "s1", "c1", "i1"
        cases = [
            (WebflowGetCustomDomainsConfig(site_id=SID), "GET", f"/sites/{SID}/custom_domains"),
            (WebflowGetPageMetadataConfig(page_id="p1"), "GET", "/pages/p1"),
            (WebflowUpdatePageMetadataConfig(page_id="p1", metadata_json='{"title":"T"}'), "PUT", "/pages/p1"),
            (WebflowListComponentsConfig(site_id=SID), "GET", f"/sites/{SID}/components"),
            (WebflowUpdateComponentContentConfig(site_id=SID, component_id="cm1", nodes_json='[]'), "PATCH", f"/sites/{SID}/components/cm1/dom"),
            (WebflowDeleteCollectionConfig(collection_id=CID), "DELETE", f"/collections/{CID}"),
            (WebflowUpdateCollectionFieldConfig(collection_id=CID, field_id="f1", display_name="X"), "PATCH", f"/collections/{CID}/fields/f1"),
            (WebflowDeleteCollectionFieldConfig(collection_id=CID, field_id="f1"), "DELETE", f"/collections/{CID}/fields/f1"),
            (WebflowListLiveItemsConfig(collection_id=CID), "GET", f"/collections/{CID}/items/live"),
            (WebflowGetLiveItemConfig(collection_id=CID, item_id=IID), "GET", f"/collections/{CID}/items/{IID}/live"),
            (WebflowUpdateLiveItemConfig(collection_id=CID, item_id=IID, field_data_json='{"name":"N"}'), "PATCH", f"/collections/{CID}/items/{IID}/live"),
            (WebflowDeleteLiveItemConfig(collection_id=CID, item_id=IID), "DELETE", f"/collections/{CID}/items/{IID}/live"),
            (WebflowCreateBulkItemsConfig(collection_id=CID, items_json='[]'), "POST", f"/collections/{CID}/items/bulk"),
            (WebflowGetProductConfig(site_id=SID, product_id="pr1"), "GET", f"/sites/{SID}/products/pr1"),
            (WebflowUpdateProductConfig(site_id=SID, product_id="pr1", product_field_data_json='{"name":"N"}'), "PATCH", f"/sites/{SID}/products/pr1"),
            (WebflowCreateSkusConfig(site_id=SID, product_id="pr1", skus_json='[]'), "POST", f"/sites/{SID}/products/pr1/skus"),
            (WebflowUpdateSkuConfig(site_id=SID, product_id="pr1", sku_id="sk1", sku_field_data_json='{}'), "PATCH", f"/sites/{SID}/products/pr1/skus/sk1"),
            (WebflowUpdateInventoryConfig(collection_id=CID, sku_id="sk1", inventory_json='{"quantity":5}'), "PATCH", f"/collections/{CID}/items/sk1/inventory"),
            (WebflowGetEcommerceSettingsConfig(site_id=SID), "GET", f"/sites/{SID}/ecommerce/settings"),
            (WebflowUpdateOrderConfig(site_id=SID, order_id="o1", order_json='{"comment":"c"}'), "PATCH", f"/sites/{SID}/orders/o1"),
            (WebflowUnfulfillOrderConfig(site_id=SID, order_id="o1"), "POST", f"/sites/{SID}/orders/o1/unfulfill"),
            (WebflowRefundOrderConfig(site_id=SID, order_id="o1", reason="requested"), "POST", f"/sites/{SID}/orders/o1/refund"),
            (WebflowListSiteFormSubmissionsConfig(site_id=SID), "GET", f"/sites/{SID}/form_submissions"),
            (WebflowModifySubmissionConfig(form_submission_id="fs1", data_json='{}'), "PATCH", "/form_submissions/fs1"),
            (WebflowDeleteSubmissionConfig(form_submission_id="fs1"), "DELETE", "/form_submissions/fs1"),
            (WebflowGetAssetConfig(asset_id="a1"), "GET", "/assets/a1"),
            (WebflowCreateAssetConfig(site_id=SID, file_name="f.png", file_hash="abc"), "POST", f"/sites/{SID}/assets"),
            (WebflowUpdateAssetConfig(asset_id="a1", display_name="X"), "PATCH", "/assets/a1"),
            (WebflowDeleteAssetConfig(asset_id="a1"), "DELETE", "/assets/a1"),
            (WebflowListAssetFoldersConfig(site_id=SID), "GET", f"/sites/{SID}/asset_folders"),
            (WebflowCreateAssetFolderConfig(site_id=SID, display_name="F"), "POST", f"/sites/{SID}/asset_folders"),
            (WebflowGetCommentThreadConfig(site_id=SID, comment_thread_id="ct1"), "GET", f"/sites/{SID}/comments/ct1"),
            (WebflowListCommentRepliesConfig(site_id=SID, comment_thread_id="ct1"), "GET", f"/sites/{SID}/comments/ct1/replies"),
            (WebflowGetWebhookConfig(webhook_id="wh1"), "GET", "/webhooks/wh1"),
            (WebflowIntrospectTokenConfig(), "GET", "/token/introspect"),
            (WebflowRegisterInlineScriptConfig(site_id=SID, script_json='{"sourceCode":"x"}'), "POST", f"/sites/{SID}/registered_scripts/inline"),
            (WebflowListRegisteredScriptsConfig(site_id=SID), "GET", f"/sites/{SID}/registered_scripts"),
            (WebflowApplySiteCustomCodeConfig(site_id=SID, scripts_json='{"scripts":[]}'), "PUT", f"/sites/{SID}/custom_code"),
            (WebflowRemoveSiteCustomCodeConfig(site_id=SID), "DELETE", f"/sites/{SID}/custom_code"),
            (WebflowApplyPageCustomCodeConfig(page_id="p1", scripts_json='{"scripts":[]}'), "PUT", "/pages/p1/custom_code"),
        ]
        for op, method, suffix in cases:
            cap = await _capture(op, api_token_credentials)
            assert cap["method"] == method, f"{op.operation}: method {cap['method']} != {method}"
            assert cap["url"].endswith(suffix), f"{op.operation}: url {cap['url']} !~ {suffix}"

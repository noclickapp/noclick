"""
Mock tests for Shopify Admin REST API and GraphQL API node.

Tests the Shopify API node functionality
organized by category: products, product variants, product images, orders, refunds,
transactions, customers, customer addresses, inventory, fulfillments, collections,
locations, shop, metafields, webhooks, and GraphQL.

Uses unittest.mock to mock all HTTP requests. Tests both OAuth and Access Token credentials.
Tests success cases, error handling, and edge cases without hitting the actual Shopify API.
"""

import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

# Import the node and config classes
from nodes.shopify_node import (
    ShopifyNode,
    ShopifyNodeConfig,
    ShopifyOAuthCredential,
    ShopifyAccessTokenCredential,
    # Product operations (6)
    ShopifyListProductsConfig,
    ShopifyGetProductConfig,
    ShopifyCreateProductConfig,
    ShopifyUpdateProductConfig,
    ShopifyDeleteProductConfig,
    ShopifyCountProductsConfig,
    # Product Variant operations (6) - NEW
    ShopifyListProductVariantsConfig,
    ShopifyGetProductVariantConfig,
    ShopifyCreateProductVariantConfig,
    ShopifyUpdateProductVariantConfig,
    ShopifyDeleteProductVariantConfig,
    ShopifyCountProductVariantsConfig,
    # Product Image operations (4) - NEW
    ShopifyListProductImagesConfig,
    ShopifyGetProductImageConfig,
    ShopifyCreateProductImageConfig,
    ShopifyDeleteProductImageConfig,
    # Order operations (9)
    ShopifyListOrdersConfig,
    ShopifyGetOrderConfig,
    ShopifyCreateOrderConfig,
    ShopifyUpdateOrderConfig,
    ShopifyDeleteOrderConfig,
    ShopifyCancelOrderConfig,
    ShopifyCloseOrderConfig,
    ShopifyOpenOrderConfig,
    ShopifyCountOrdersConfig,
    # Customer operations (8)
    ShopifyListCustomersConfig,
    ShopifyGetCustomerConfig,
    ShopifyCreateCustomerConfig,
    ShopifyUpdateCustomerConfig,
    ShopifyDeleteCustomerConfig,
    ShopifySearchCustomersConfig,
    ShopifyCountCustomersConfig,
    ShopifyGetCustomerOrdersConfig,
    # Inventory operations (5)
    ShopifyListInventoryLevelsConfig,
    ShopifyAdjustInventoryLevelConfig,
    ShopifySetInventoryLevelConfig,
    ShopifyConnectInventoryLevelConfig,
    ShopifyDeleteInventoryLevelConfig,
    # Fulfillment operations (6)
    ShopifyListFulfillmentsConfig,
    ShopifyGetFulfillmentConfig,
    ShopifyCreateFulfillmentConfig,
    ShopifyUpdateFulfillmentConfig,
    ShopifyCompleteFulfillmentConfig,
    ShopifyCancelFulfillmentConfig,
    # Collection operations (6)
    ShopifyListCollectionsConfig,
    ShopifyGetCollectionConfig,
    ShopifyCreateCollectionConfig,
    ShopifyUpdateCollectionConfig,
    ShopifyDeleteCollectionConfig,
    ShopifyAddProductToCollectionConfig,
    # Location operations (2)
    ShopifyListLocationsConfig,
    ShopifyGetLocationConfig,
    # Shop operations (1)
    ShopifyGetShopConfig,
    # Metafield operations (5)
    ShopifyListMetafieldsConfig,
    ShopifyGetMetafieldConfig,
    ShopifyCreateMetafieldConfig,
    ShopifyUpdateMetafieldConfig,
    ShopifyDeleteMetafieldConfig,
    # Webhook operations (5)
    ShopifyListWebhooksConfig,
    ShopifyGetWebhookConfig,
    ShopifyCreateWebhookConfig,
    ShopifyUpdateWebhookConfig,
    ShopifyDeleteWebhookConfig,
)

# Test constants
TEST_STORE = "test-store"
TEST_TOKEN = "test-token-123"
BASE_URL = f"https://{TEST_STORE}.myshopify.com/admin/api/2024-01"


# Mock HTTP client fixture
@pytest.fixture
def mock_httpx():
    """Mock httpx.AsyncClient for all Shopify API requests."""
    def create_mock_response(status_code=200, json_data=None):
        """Create a mock httpx response."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = json_data or {}
        mock_response.raise_for_status = MagicMock()
        if status_code >= 400:
            from httpx import HTTPStatusError, Request, Response
            mock_response.raise_for_status.side_effect = HTTPStatusError(
                "HTTP Error",
                request=MagicMock(spec=Request),
                response=MagicMock(spec=Response, status_code=status_code, json=lambda: json_data or {})
            )
        return mock_response

    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Store responses queue for test configuration
        mock_client._response_queue = []

        async def mock_request(method, url, **kwargs):
            if mock_client._response_queue:
                return mock_client._response_queue.pop(0)
            return create_mock_response(200, {})

        mock_client.request = mock_request
        mock_client.get = mock_request
        mock_client.post = mock_request
        mock_client.put = mock_request
        mock_client.delete = mock_request

        yield mock_client, create_mock_response


def get_oauth_credentials():
    """Get a merchant-supplied OAuth credential for legacy REST tests."""
    return ShopifyOAuthCredential(
        store_name=TEST_STORE,
        access_token=TEST_TOKEN,
        custom_client_id="legacy-test-client",
    )


def get_access_token_credentials():
    """Get Access Token credentials for testing."""
    return ShopifyAccessTokenCredential(
        store_name=TEST_STORE,
        access_token=TEST_TOKEN
    )


def create_node(config, credentials) -> ShopifyNode:
    """Create a ShopifyNode instance with the given config and credentials."""
    node_config = ShopifyNodeConfig(config=config, credentials=credentials)
    node = ShopifyNode(
        node_id="test-node",
        node_type="automation-shopify",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


# ============================================================================
# Product Operations Tests (6 operations)
# ============================================================================

class TestProductOperations:
    """Test product-related Shopify API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_products_with_oauth(self, mock_httpx):
        """Test listing products with OAuth credential."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"products": [{"id": 123, "title": "Test Product"}]})
        )

        config = ShopifyListProductsConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_products"
        assert len(result["data"]["products"]) == 1
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_list_products_with_access_token(self, mock_httpx):
        """Test listing products with Access Token credential."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"products": []})
        )

        config = ShopifyListProductsConfig(limit=5)
        node = create_node(config, get_access_token_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_products"
        assert result["data"]["products"] == []

    @pytest.mark.asyncio
    async def test_get_product(self, mock_httpx):
        """Test getting a specific product."""
        mock_client, create_response = mock_httpx
        product_id = "123"
        mock_client._response_queue.append(
            create_response(200, {"product": {"id": product_id, "title": "Test Product"}})
        )

        config = ShopifyGetProductConfig(product_id=product_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_product_by_id"
        assert result["data"]["product"]["id"] == product_id

    @pytest.mark.asyncio
    async def test_create_product(self, mock_httpx):
        """Test creating a product."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"product": {"id": 456, "title": "New Product"}})
        )

        config = ShopifyCreateProductConfig(
            title="New Product",
            body_html="<p>Description</p>",
            vendor="Test Vendor"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_product"
        assert result["data"]["product"]["id"] == 456

    @pytest.mark.asyncio
    async def test_update_product(self, mock_httpx):
        """Test updating a product."""
        mock_client, create_response = mock_httpx
        product_id = "123"
        mock_client._response_queue.append(
            create_response(200, {"product": {"id": product_id, "title": "Updated Product"}})
        )

        config = ShopifyUpdateProductConfig(
            product_id=product_id,
            title="Updated Product"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_product"
        assert result["data"]["product"]["title"] == "Updated Product"

    @pytest.mark.asyncio
    async def test_delete_product(self, mock_httpx):
        """Test deleting a product."""
        mock_client, create_response = mock_httpx
        product_id = "123"
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteProductConfig(product_id=product_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_product"

    @pytest.mark.asyncio
    async def test_count_products(self, mock_httpx):
        """Test counting products."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"count": 42})
        )

        config = ShopifyCountProductsConfig()
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "count_products"
        assert result["data"]["count"] == 42


# ============================================================================
# Order Operations Tests (9 operations)
# ============================================================================

class TestOrderOperations:
    """Test order-related Shopify API operations (9 total)."""

    @pytest.mark.asyncio
    async def test_list_orders(self, mock_httpx):
        """Test listing orders."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"orders": [{"id": 123, "name": "#1001"}]})
        )

        config = ShopifyListOrdersConfig(limit=10, status="any")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_orders"
        assert len(result["data"]["orders"]) == 1

    @pytest.mark.asyncio
    async def test_get_order(self, mock_httpx):
        """Test getting a specific order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": order_id, "name": "#1001"}})
        )

        config = ShopifyGetOrderConfig(order_id=order_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_order_by_id"
        assert result["data"]["order"]["id"] == order_id

    @pytest.mark.asyncio
    async def test_create_order(self, mock_httpx):
        """Test creating an order."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": 456, "name": "#1002"}})
        )

        config = ShopifyCreateOrderConfig(
            line_items=[{"variant_id": 789, "quantity": 1}]
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_order"
        assert result["data"]["order"]["id"] == 456

    @pytest.mark.asyncio
    async def test_update_order(self, mock_httpx):
        """Test updating an order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": order_id, "note": "Updated note"}})
        )

        config = ShopifyUpdateOrderConfig(
            order_id=order_id,
            note="Updated note"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_order"

    @pytest.mark.asyncio
    async def test_delete_order(self, mock_httpx):
        """Test deleting an order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteOrderConfig(order_id=order_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_order"

    @pytest.mark.asyncio
    async def test_cancel_order(self, mock_httpx):
        """Test canceling an order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": order_id, "cancelled_at": "2024-01-01T00:00:00Z"}})
        )

        config = ShopifyCancelOrderConfig(order_id=order_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "cancel_order"

    @pytest.mark.asyncio
    async def test_close_order(self, mock_httpx):
        """Test closing an order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": order_id, "closed_at": "2024-01-01T00:00:00Z"}})
        )

        config = ShopifyCloseOrderConfig(order_id=order_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "close_order"

    @pytest.mark.asyncio
    async def test_open_order(self, mock_httpx):
        """Test opening an order."""
        order_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"order": {"id": order_id, "closed_at": None}})
        )

        config = ShopifyOpenOrderConfig(order_id=order_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "reopen_closed_order"

    @pytest.mark.asyncio
    async def test_count_orders(self, mock_httpx):
        """Test counting orders."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"count": 25})
        )

        config = ShopifyCountOrdersConfig(status="any")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "count_orders"
        assert result["data"]["count"] == 25


# ============================================================================
# Customer Operations Tests (8 operations)
# ============================================================================

class TestCustomerOperations:
    """Test customer-related Shopify API operations (8 total)."""

    @pytest.mark.asyncio
    async def test_list_customers(self, mock_httpx):
        """Test listing customers."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"customers": [{"id": 123, "email": "test@example.com"}]})
        )

        config = ShopifyListCustomersConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_customers"
        assert len(result["data"]["customers"]) == 1

    @pytest.mark.asyncio
    async def test_get_customer(self, mock_httpx):
        """Test getting a specific customer."""
        customer_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"customer": {"id": customer_id, "email": "test@example.com"}})
        )

        config = ShopifyGetCustomerConfig(customer_id=customer_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_customer_by_id"
        assert result["data"]["customer"]["id"] == customer_id

    @pytest.mark.asyncio
    async def test_create_customer(self, mock_httpx):
        """Test creating a customer."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"customer": {"id": 456, "email": "new@example.com"}})
        )

        config = ShopifyCreateCustomerConfig(
            email="new@example.com",
            first_name="John",
            last_name="Doe"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_customer"
        assert result["data"]["customer"]["id"] == 456

    @pytest.mark.asyncio
    async def test_update_customer(self, mock_httpx):
        """Test updating a customer."""
        customer_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"customer": {"id": customer_id, "first_name": "Jane"}})
        )

        config = ShopifyUpdateCustomerConfig(
            customer_id=customer_id,
            first_name="Jane"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_customer"

    @pytest.mark.asyncio
    async def test_delete_customer(self, mock_httpx):
        """Test deleting a customer."""
        customer_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteCustomerConfig(customer_id=customer_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_customer"

    @pytest.mark.asyncio
    async def test_search_customers(self, mock_httpx):
        """Test searching customers."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"customers": [{"id": 123, "email": "test@example.com"}]})
        )

        config = ShopifySearchCustomersConfig(query="email:test@example.com")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_customers"

    @pytest.mark.asyncio
    async def test_count_customers(self, mock_httpx):
        """Test counting customers."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"count": 100})
        )

        config = ShopifyCountCustomersConfig()
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "count_customers"
        assert result["data"]["count"] == 100

    @pytest.mark.asyncio
    async def test_get_customer_orders(self, mock_httpx):
        """Test getting customer orders."""
        customer_id = "123"
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"orders": [{"id": 456, "name": "#1001"}]})
        )

        config = ShopifyGetCustomerOrdersConfig(customer_id=customer_id)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_customer_orders"


# ============================================================================
# Inventory Operations Tests (5 operations)
# ============================================================================

class TestInventoryOperations:
    """Test inventory-related Shopify API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_list_inventory_levels(self, mock_httpx):
        """Test listing inventory levels."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"inventory_levels": [{"inventory_item_id": 123, "available": 10}]})
        )

        config = ShopifyListInventoryLevelsConfig(inventory_item_ids="123", location_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_inventory_levels"

    @pytest.mark.asyncio
    async def test_adjust_inventory_level(self, mock_httpx):
        """Test adjusting inventory level."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"inventory_level": {"available": 15}})
        )

        config = ShopifyAdjustInventoryLevelConfig(
            inventory_item_id="123",
            location_id="456",
            available_adjustment=5
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "adjust_inventory_level_at_location"

    @pytest.mark.asyncio
    async def test_set_inventory_level(self, mock_httpx):
        """Test setting inventory level."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"inventory_level": {"available": 20}})
        )

        config = ShopifySetInventoryLevelConfig(
            inventory_item_id="123",
            location_id="456",
            available=20
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_inventory_level_at_location"

    @pytest.mark.asyncio
    async def test_connect_inventory_level(self, mock_httpx):
        """Test connecting inventory level to location."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"inventory_level": {"inventory_item_id": 123, "location_id": 456}})
        )

        config = ShopifyConnectInventoryLevelConfig(
            inventory_item_id="123",
            location_id="456"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "connect_inventory_item_to_location"

    @pytest.mark.asyncio
    async def test_delete_inventory_level(self, mock_httpx):
        """Test deleting inventory level."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteInventoryLevelConfig(
            inventory_item_id="123",
            location_id="456"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_inventory_level"


# ============================================================================
# Fulfillment Operations Tests (6 operations)
# ============================================================================

class TestFulfillmentOperations:
    """Test fulfillment-related Shopify API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_fulfillments(self, mock_httpx):
        """Test listing fulfillments."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillments": [{"id": 456, "status": "success"}]})
        )

        config = ShopifyListFulfillmentsConfig(order_id="123")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_order_fulfillments"

    @pytest.mark.asyncio
    async def test_get_fulfillment(self, mock_httpx):
        """Test getting a specific fulfillment."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillment": {"id": 456, "status": "success"}})
        )

        config = ShopifyGetFulfillmentConfig(order_id="123", fulfillment_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_order_fulfillment"

    @pytest.mark.asyncio
    async def test_create_fulfillment(self, mock_httpx):
        """Test creating a fulfillment."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillment": {"id": 789, "status": "success"}})
        )

        config = ShopifyCreateFulfillmentConfig(
            order_id="123",
            line_items_by_fulfillment_order=[
                {"fulfillment_order_id": "123"}
            ]
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_order_fulfillment"

    @pytest.mark.asyncio
    async def test_update_fulfillment(self, mock_httpx):
        """Test updating a fulfillment."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillment": {"id": 456, "tracking_number": "TRACK123"}})
        )

        config = ShopifyUpdateFulfillmentConfig(
            order_id="123",
            fulfillment_id="456",
            tracking_number="TRACK123"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_order_fulfillment"

    @pytest.mark.asyncio
    async def test_complete_fulfillment(self, mock_httpx):
        """Test completing a fulfillment."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillment": {"id": 456, "status": "success"}})
        )

        config = ShopifyCompleteFulfillmentConfig(order_id="123", fulfillment_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "complete_order_fulfillment"

    @pytest.mark.asyncio
    async def test_cancel_fulfillment(self, mock_httpx):
        """Test canceling a fulfillment."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"fulfillment": {"id": 456, "status": "cancelled"}})
        )

        config = ShopifyCancelFulfillmentConfig(order_id="123", fulfillment_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "cancel_order_fulfillment"


# ============================================================================
# Collection Operations Tests (6 operations)
# ============================================================================

class TestCollectionOperations:
    """Test collection-related Shopify API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_collections(self, mock_httpx):
        """Test listing collections."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"custom_collections": [{"id": 123, "title": "Test Collection"}]})
        )

        config = ShopifyListCollectionsConfig(collection_type="custom", limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_collections"

    @pytest.mark.asyncio
    async def test_get_collection(self, mock_httpx):
        """Test getting a specific collection."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"custom_collection": {"id": 123, "title": "Test Collection"}})
        )

        config = ShopifyGetCollectionConfig(collection_id="123", collection_type="custom")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_collection_by_id"

    @pytest.mark.asyncio
    async def test_create_collection(self, mock_httpx):
        """Test creating a collection."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"custom_collection": {"id": 456, "title": "New Collection"}})
        )

        config = ShopifyCreateCollectionConfig(
            title="New Collection",
            collection_type="custom"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_collection"

    @pytest.mark.asyncio
    async def test_update_collection(self, mock_httpx):
        """Test updating a collection."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"custom_collection": {"id": 123, "title": "Updated Collection"}})
        )

        config = ShopifyUpdateCollectionConfig(
            collection_id="123",
            collection_type="custom",
            title="Updated Collection"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_collection"

    @pytest.mark.asyncio
    async def test_delete_collection(self, mock_httpx):
        """Test deleting a collection."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteCollectionConfig(collection_id="123", collection_type="custom")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_collection"

    @pytest.mark.asyncio
    async def test_add_product_to_collection(self, mock_httpx):
        """Test adding a product to a collection."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"collect": {"id": 789, "product_id": 456, "collection_id": 123}})
        )

        config = ShopifyAddProductToCollectionConfig(
            product_id="456",
            collection_id="123"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_product_to_collection"


# ============================================================================
# Location Operations Tests (2 operations)
# ============================================================================

class TestLocationOperations:
    """Test location-related Shopify API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_list_locations(self, mock_httpx):
        """Test listing locations."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"locations": [{"id": 123, "name": "Main Store"}]})
        )

        config = ShopifyListLocationsConfig()
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_all_locations"

    @pytest.mark.asyncio
    async def test_get_location(self, mock_httpx):
        """Test getting a specific location."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"location": {"id": 123, "name": "Main Store"}})
        )

        config = ShopifyGetLocationConfig(location_id="123")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_location_by_id"


# ============================================================================
# Shop Operations Tests (1 operation)
# ============================================================================

class TestShopOperations:
    """Test shop-related Shopify API operations (1 total)."""

    @pytest.mark.asyncio
    async def test_get_shop(self, mock_httpx):
        """Test getting shop information."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"shop": {"id": 123, "name": "Test Store", "email": "shop@example.com"}})
        )

        config = ShopifyGetShopConfig()
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_shop_information"


# ============================================================================
# Metafield Operations Tests (5 operations)
# ============================================================================

class TestMetafieldOperations:
    """Test metafield-related Shopify API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_list_metafields(self, mock_httpx):
        """Test listing metafields."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"metafields": [{"id": 456, "key": "test_key"}]})
        )

        config = ShopifyListMetafieldsConfig(resource="product", resource_id="123")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_metafields"

    @pytest.mark.asyncio
    async def test_get_metafield(self, mock_httpx):
        """Test getting a specific metafield."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"metafield": {"id": 456, "key": "test_key"}})
        )

        config = ShopifyGetMetafieldConfig(metafield_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_metafield_by_id"

    @pytest.mark.asyncio
    async def test_create_metafield(self, mock_httpx):
        """Test creating a metafield."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"metafield": {"id": 789, "key": "new_key"}})
        )

        config = ShopifyCreateMetafieldConfig(
            namespace="custom",
            key="new_key",
            value="test_value",
            type="single_line_text_field",
            resource="product",
            resource_id="123"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_metafield"

    @pytest.mark.asyncio
    async def test_update_metafield(self, mock_httpx):
        """Test updating a metafield."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"metafield": {"id": 456, "value": "updated_value"}})
        )

        config = ShopifyUpdateMetafieldConfig(
            metafield_id="456",
            value="updated_value"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_metafield"

    @pytest.mark.asyncio
    async def test_delete_metafield(self, mock_httpx):
        """Test deleting a metafield."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteMetafieldConfig(metafield_id="456")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_metafield"


# ============================================================================
# Webhook Operations Tests (5 operations)
# ============================================================================

class TestWebhookOperations:
    """Test webhook-related Shopify API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_list_webhooks(self, mock_httpx):
        """Test listing webhooks."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"webhooks": [{"id": 123, "topic": "orders/create"}]})
        )

        config = ShopifyListWebhooksConfig()
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_get_webhook(self, mock_httpx):
        """Test getting a specific webhook."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"webhook": {"id": 123, "topic": "orders/create"}})
        )

        config = ShopifyGetWebhookConfig(webhook_id="123")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_webhook_by_id"

    @pytest.mark.asyncio
    async def test_create_webhook(self, mock_httpx):
        """Test creating a webhook."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"webhook": {"id": 456, "topic": "products/create"}})
        )

        config = ShopifyCreateWebhookConfig(
            topic="products/create",
            address="https://example.com/webhook",
            format="json"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_webhook"

    @pytest.mark.asyncio
    async def test_update_webhook(self, mock_httpx):
        """Test updating a webhook."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"webhook": {"id": 123, "address": "https://new.example.com/webhook"}})
        )

        config = ShopifyUpdateWebhookConfig(
            webhook_id="123",
            address="https://new.example.com/webhook"
        )
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_webhook"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, mock_httpx):
        """Test deleting a webhook."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {})
        )

        config = ShopifyDeleteWebhookConfig(webhook_id="123")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_404_not_found(self, mock_httpx):
        """Test handling of 404 not found errors."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(404, {"errors": "Not Found"})
        )

        config = ShopifyGetProductConfig(product_id="99999")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_401_unauthorized(self, mock_httpx):
        """Test handling of 401 unauthorized errors."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(401, {"errors": "Unauthorized"})
        )

        config = ShopifyListProductsConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_422_validation_error(self, mock_httpx):
        """Test handling of 422 validation errors."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(422, {"errors": {"title": ["can't be blank"]}})
        )

        config = ShopifyCreateProductConfig(title="")
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 422

    @pytest.mark.asyncio
    async def test_429_rate_limit(self, mock_httpx):
        """Test handling of 429 rate limit errors."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(429, {"errors": "Rate limit exceeded"})
        )

        config = ShopifyListProductsConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 429

    @pytest.mark.asyncio
    async def test_500_server_error(self, mock_httpx):
        """Test handling of 500 server errors."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(500, {"errors": "Internal Server Error"})
        )

        config = ShopifyListProductsConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = ShopifyListProductsConfig(limit=10)
        node_config = ShopifyNodeConfig(config=config, credentials=None)
        node = ShopifyNode(
            node_id="test-node",
            node_type="automation-shopify",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Timing and Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self, mock_httpx):
        """Test that timing information is included in responses."""
        mock_client, create_response = mock_httpx
        mock_client._response_queue.append(
            create_response(200, {"products": []})
        )

        config = ShopifyListProductsConfig(limit=10)
        node = create_node(config, get_oauth_credentials())

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] > 0
        assert result["timing_ms"]["total"] > 0


if __name__ == "__main__":
    # Run tests with: pytest tests/nodes/test_shopify_mock.py -v
    pytest.main([__file__, "-v"])

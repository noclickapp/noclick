"""GoodBarber Commerce v2 operations backed by the published OpenAPI contract.

Uses the administrator-issued token header and a fixed provider origin. Polling
new orders uses documented creation filters and the shared persistent seen set.
"""
from typing import Annotated, Any, Literal, Optional, Union
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://commerce.goodbarber.dev"
DOCS = "https://commerce.goodbarber.dev/publicapi/v2/documentation/"

class GoodBarberTokenCredential(BaseModel):
    model_config = ConfigDict(title="GoodBarber API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Ask your shop administrator for a Commerce Public API token and shop ID (webzine_id). Paste the token without a header prefix. Its permissions must allow the operations you select. Connecting reads one product page from your shop."})
    credential_type: Literal["goodbarber_api_token"] = Field("goodbarber_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, json_schema_extra={"ui:widget": "password"})
    webzine_id: int = Field(..., title="Shop ID", gt=0)

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(ch.isspace() for ch in value):
            raise ValueError("Paste the token without whitespace")
        return value

class Operation(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

class ListCollections(Operation):
    operation: Literal['list_collections'] = Field('list_collections', title='List Collections', json_schema_extra={"ui:hidden": True})
    keyword: Optional[str] = Field(None, description='Restricts the list of returned collections to the ones whose name contains the provided argument.To select instances whose name contains a word "A" OR a word "B", use the following syntax:?keyword=A,B.')
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of collections displayed on each page.', gt=0)
    sort: Optional[str] = Field(None, description='Sorts the returned collections.Possible values:alpha: ascending alphabetical orderalpha_desc: descending alphabetical orderfirst_added: ascending creation date orderlast_added: descending creation date order')

class GetCollection(Operation):
    operation: Literal['get_collection'] = Field('get_collection', title='Get Collection', json_schema_extra={"ui:hidden": True})
    collection_id: int = Field(..., description='Collection Unique ID.', gt=0)

class ListOptions(Operation):
    operation: Literal['list_options'] = Field('list_options', title='List Options', json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of variant options displayed on each page.', gt=0)
    search: Optional[str] = Field(None, description='Restricts the list of returned options to the ones whose name contains the provided argument.')

class CreateOption(Operation):
    operation: Literal['create_option'] = Field('create_option', title='Create Option', json_schema_extra={"ui:hidden": True})
    name: str = Field(...)

class UpdateOption(Operation):
    operation: Literal['update_option'] = Field('update_option', title='Update Option', json_schema_extra={"ui:hidden": True})
    option_id: int = Field(..., description='Unique ID of the variant option.', gt=0)
    name: Optional[str] = Field(None)

class DeleteOption(Operation):
    operation: Literal['delete_option'] = Field('delete_option', title='Delete Option', json_schema_extra={"ui:hidden": True})
    option_id: int = Field(..., description='Option Unique ID.', gt=0)

class ListProducts(Operation):
    operation: Literal['list_products'] = Field('list_products', title='List Products', json_schema_extra={"ui:hidden": True})
    collection: Optional[int] = Field(None, description='Restricts the list of returned products to the ones that belong to the specified collection (an unique ID is expected). To filter instances that belong to a collection 1 OR a collection 2, use the following syntax:?collection={ID1}&collection={ID2}', gt=0)
    keyword: Optional[str] = Field(None, description='Restricts the list of returned products to the ones whose title, summary, description, tags, SKU or slug contains the provided argument. To select instances that contain a word "A" OR a word "B", use the following syntax: ?keyword=A,B.')
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of products displayed on each page.', gt=0)
    status: Optional[Literal['DEMO', 'DRAFT', 'INVISIBLE', 'PUBLISHED']] = Field(None, description='Restricts the list of returned products to a certain publishing status.')

class CreateProduct(Operation):
    operation: Literal['create_product'] = Field('create_product', title='Create Product', json_schema_extra={"ui:hidden": True})
    title: Optional[str] = Field(None)
    meta_title: Optional[str] = Field(None)
    meta_description: Optional[str] = Field(None)
    summary: Optional[str] = Field(None)
    status: Optional[Literal['DRAFT', 'PUBLISHED', 'INVISIBLE']] = Field(None)
    visibility_start: Optional[str] = Field(None)
    visibility_end: Optional[str] = Field(None)
    highlight: Optional[bool] = Field(None)
    slug: Optional[str] = Field(None)
    media: Optional[int] = Field(None)
    tags: list[str] = Field(...)
    collections: list[int] = Field(...)
    show_similar_products: Optional[bool] = Field(None)
    set_custom_similar_products: list[int] = Field(...)
    product_ref: Optional[str] = Field(None)
    brand: Optional[str] = Field(None)

class GetProduct(Operation):
    operation: Literal['get_product'] = Field('get_product', title='Get Product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='Product Unique ID.', gt=0)

class UpdateProduct(Operation):
    operation: Literal['update_product'] = Field('update_product', title='Update Product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='Product Unique ID.', gt=0)
    title: Optional[str] = Field(None)
    meta_title: Optional[str] = Field(None)
    meta_description: Optional[str] = Field(None)
    summary: Optional[str] = Field(None)
    status: Optional[Literal['DRAFT', 'PUBLISHED', 'INVISIBLE', 'DEMO']] = Field(None)
    visibility_start: Optional[str] = Field(None)
    visibility_end: Optional[str] = Field(None)
    highlight: Optional[bool] = Field(None)
    slug: Optional[str] = Field(None)
    tags: Optional[list[str]] = Field(None)
    media: Optional[int] = Field(None)
    collections: Optional[list[int]] = Field(None)
    set_custom_similar_products: Optional[list[int]] = Field(None)
    show_similar_products: Optional[bool] = Field(None)
    product_ref: Optional[str] = Field(None)
    brand: Optional[str] = Field(None)

class DeleteProduct(Operation):
    operation: Literal['delete_product'] = Field('delete_product', title='Delete Product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='Product Unique ID.', gt=0)

class ListTags(Operation):
    operation: Literal['list_tags'] = Field('list_tags', title='List Tags', json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of tags displayed on each page.', gt=0)
    sort: Optional[str] = Field(None, description='Sorts the returned tags.Possible values:alpha: ascending alphabetical orderlast_created: descending creation date ordermost_tagged: sorted by descending number of products using this tag')

class ListCustomers(Operation):
    operation: Literal['list_customers'] = Field('list_customers', title='List Customers', json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of customers displayed on each page.', gt=0)

class GetCustomer(Operation):
    operation: Literal['get_customer'] = Field('get_customer', title='Get Customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., description='Unique ID of the customer.', gt=0)

class ListProspects(Operation):
    operation: Literal['list_prospects'] = Field('list_prospects', title='List Prospects', json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of prospects displayed on each page.', gt=0)

class GetProspect(Operation):
    operation: Literal['get_prospect'] = Field('get_prospect', title='Get Prospect', json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., description='Unique ID of the User.', gt=0)

class ListOrders(Operation):
    operation: Literal['list_orders'] = Field('list_orders', title='List Orders', json_schema_extra={"ui:hidden": True})
    creation_date_from: Optional[str] = Field(None, description='Restricts the list of returned orders to the ones created after (or on) the provided datetime.This parameter should use the following format yyyy-mm-ddThh:MM (year, month, day, 24-hour and minute) and be expressed in UTC time.')
    creation_date_to: Optional[str] = Field(None, description='Restricts the list of returned orders to the ones created before (or on) the provided datetime.This parameter should use the following format yyyy-mm-ddThh:MM (year, month, day, 24-hour and minute) and be expressed in UTC time.')
    delivery_date_from: Optional[str] = Field(None, description='Restricts the list of returned orders to the ones whose selected delivery slot lands after (or on) the provided datetime.This parameter should use the following format yyyy-mm-ddThh:MM (year, month, day, 24-hour and minute) and be expressed in UTC time. When this filter is applied, orders that do not have a selected delivery slot (shipped by transporter, for instance) will not be returned.Also, note that a delivery slot is said to land after a given datetime if its slot_start value is later than that datetime.')
    delivery_date_to: Optional[str] = Field(None, description='Restricts the list of returned orders to the ones whose selected delivery slot lands before (or on) the provided datetime.This parameter should use the following format yyyy-mm-ddThh:MM (year, month, day, 24-hour and minute) and be expressed in UTC time. When this filter is applied, orders that do not have a selected delivery slot (shipped by transporter, for instance) will not be returned.Also, note that a delivery slot is said to land before a given datetime if its slot_end value comes before that datetime.')
    page: Optional[int] = Field(None, description='Page number.', gt=0)
    per_page: Optional[int] = Field(None, description='Number of orders displayed on each page.', gt=0)
    status: Optional[Literal['CANCELLED', 'DELIVERED', 'FULFILLED', 'PENDING']] = Field(None, description='Restricts the list of returned orders to a certain status.To filter several statuses use the following syntax: ?status={STATUS1}&status={STATUS2}')

class GetOrder(Operation):
    operation: Literal['get_order'] = Field('get_order', title='Get Order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., description='Unique ID of the order.', gt=0)

class GetShipping(Operation):
    operation: Literal['get_shipping'] = Field('get_shipping', title='Get Shipping', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., description='Unique ID of the order.', gt=0)

class UpdateShipping(Operation):
    operation: Literal['update_shipping'] = Field('update_shipping', title='Update Shipping', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., description='Unique ID of the order.', gt=0)
    status: Optional[Literal['FULFILLED', 'DELIVERED']] = Field(None)
    shipping_tracking_url: Optional[str] = Field(None)
    shipping_tracking_num: Optional[str] = Field(None)

class OnNewOrder(PollTriggerConfigBase):
    operation: Literal["on_new_order"] = Field("on_new_order", title="On New Order", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    creation_date_from: Optional[str] = Field(None, description="UTC lower bound yyyy-mm-ddThh:MM. Only pending, fulfilled, delivered and cancelled orders are returned by the API.")

OPERATIONS = {'list_collections': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/collection/', 'query': ['keyword', 'page', 'per_page', 'sort'], 'body': []}, 'get_collection': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/collection/{collection_id}/', 'query': [], 'body': []}, 'list_options': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/option/', 'query': ['page', 'per_page', 'search'], 'body': []}, 'create_option': {'method': 'POST', 'path': '/publicapi/v2/general/catalog/{webzine_id}/option/', 'query': [], 'body': ['name']}, 'update_option': {'method': 'PATCH', 'path': '/publicapi/v2/general/catalog/{webzine_id}/option/{option_id}/', 'query': [], 'body': ['name']}, 'delete_option': {'method': 'DELETE', 'path': '/publicapi/v2/general/catalog/{webzine_id}/option/{option_id}/', 'query': [], 'body': []}, 'list_products': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/product/', 'query': ['collection', 'keyword', 'page', 'per_page', 'status'], 'body': []}, 'create_product': {'method': 'POST', 'path': '/publicapi/v2/general/catalog/{webzine_id}/product/', 'query': [], 'body': ['title', 'meta_title', 'meta_description', 'summary', 'status', 'visibility_start', 'visibility_end', 'highlight', 'slug', 'media', 'tags', 'collections', 'show_similar_products', 'set_custom_similar_products', 'product_ref', 'brand']}, 'get_product': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/product/{product_id}/', 'query': [], 'body': []}, 'update_product': {'method': 'PATCH', 'path': '/publicapi/v2/general/catalog/{webzine_id}/product/{product_id}/', 'query': [], 'body': ['title', 'meta_title', 'meta_description', 'summary', 'status', 'visibility_start', 'visibility_end', 'highlight', 'slug', 'tags', 'media', 'collections', 'set_custom_similar_products', 'show_similar_products', 'product_ref', 'brand']}, 'delete_product': {'method': 'DELETE', 'path': '/publicapi/v2/general/catalog/{webzine_id}/product/{product_id}/', 'query': [], 'body': []}, 'list_tags': {'method': 'GET', 'path': '/publicapi/v2/general/catalog/{webzine_id}/tag/', 'query': ['page', 'per_page', 'sort'], 'body': []}, 'list_customers': {'method': 'GET', 'path': '/publicapi/v2/general/customer/{webzine_id}/customer/', 'query': ['page', 'per_page'], 'body': []}, 'get_customer': {'method': 'GET', 'path': '/publicapi/v2/general/customer/{webzine_id}/customer/{customer_id}/', 'query': [], 'body': []}, 'list_prospects': {'method': 'GET', 'path': '/publicapi/v2/general/customer/{webzine_id}/prospect/', 'query': ['page', 'per_page'], 'body': []}, 'get_prospect': {'method': 'GET', 'path': '/publicapi/v2/general/customer/{webzine_id}/prospect/{user_id}/', 'query': [], 'body': []}, 'list_orders': {'method': 'GET', 'path': '/publicapi/v2/general/orders/{webzine_id}/', 'query': ['creation_date_from', 'creation_date_to', 'delivery_date_from', 'delivery_date_to', 'page', 'per_page', 'status'], 'body': []}, 'get_order': {'method': 'GET', 'path': '/publicapi/v2/general/orders/{webzine_id}/order/{order_id}/', 'query': [], 'body': []}, 'get_shipping': {'method': 'GET', 'path': '/publicapi/v2/general/orders/{webzine_id}/order/{order_id}/shipping/', 'query': [], 'body': []}, 'update_shipping': {'method': 'PATCH', 'path': '/publicapi/v2/general/orders/{webzine_id}/order/{order_id}/shipping/', 'query': [], 'body': ['status', 'shipping_tracking_url', 'shipping_tracking_num']}}

GoodBarberConfig = Annotated[Union[ListCollections, GetCollection, ListOptions, CreateOption, UpdateOption, DeleteOption, ListProducts, CreateProduct, GetProduct, UpdateProduct, DeleteProduct, ListTags, ListCustomers, GetCustomer, ListProspects, GetProspect, ListOrders, GetOrder, GetShipping, UpdateShipping, OnNewOrder], Field(discriminator="operation")]

class GoodBarberFullConfig(NodeConfig[GoodBarberConfig, GoodBarberTokenCredential]):
    pass

class GoodBarberNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-goodbarber"
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return GoodBarberFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={"token": credential.api_token, "Accept": "application/json"}, params=params, json=body)
        if response.status_code == 204:
            return None
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError(f"GoodBarber returned a non-JSON response (HTTP {response.status_code})") from None
        if isinstance(data, dict) and "error_code" in data:
            # Keep the provider's reason, but never echo a credential.
            reason = str(data.get("error_description", "Request rejected")).replace(credential.api_token, "[redacted]")
            raise ValueError(reason)
        if response.status_code >= 300:
            raise ValueError(f"GoodBarber request failed (HTTP {response.status_code})")
        return data

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GoodBarber shop")
        config = self.config.config
        if isinstance(config, OnNewOrder):
            rows = []
            for page in range(1, 21):
                params = {"page": page, "per_page": 100}
                if config.creation_date_from:
                    params["creation_date_from"] = config.creation_date_from
                data = await self._request("GET", f"/publicapi/v2/general/orders/{self.config.credentials.webzine_id}/", params=params)
                batch = data.get("orders") if isinstance(data, dict) else None
                if not isinstance(batch, list) or any(not isinstance(row, dict) or "id" not in row for row in batch):
                    raise ValueError("GoodBarber order list is invalid")
                rows.extend(batch)
                if not data.get("next"):
                    break
            else:
                raise ValueError("Over 20 order pages; narrow the creation date lower bound")
            fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
            return {"orders": fresh, "new_order_count": len(fresh), "shop_id": self.config.credentials.webzine_id}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"].replace("{webzine_id}", str(self.config.credentials.webzine_id))
        for key, value in values.items():
            path = path.replace("{" + key + "}", str(value))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values} if spec["body"] else None
        if spec["method"] == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        data = await self._request(spec["method"], path, params=params, body=body)
        return {"status": "success", "data": data}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_order":
            return bool(output.get("new_order_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        orders = output.get("orders")
        if not orders:
            return None
        lines = [f"- Order {row['id']}: {row.get('first_name', '')} {row.get('last_name', '')} ({row.get('email', '')}), {row.get('total', '')} {row.get('currency', '')}, status {row.get('status', '')}" for row in orders[:10]]
        return {"text": f"GoodBarber shop {output.get('shop_id')}: {len(orders)} new orders\n" + "\n".join(lines), "conversation_key": None}

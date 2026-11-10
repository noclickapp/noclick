"""MyCashflow API: routes and schemas pinned to https://support.mycashflow.com/api.

API user email is the Basic username; API key is the password (official user guide).
"""
import base64
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

class MyCashflowCredential(BaseModel):
    model_config = ConfigDict(title="MyCashflow API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://support.mycashflow.com/en/user-guide/mycashflow-api",
        "x-credential-instructions": "Enable the API extension, then create an API user under Account > Users. Enter its email and API key, and your default store subdomain (without .mycashflow.fi)."})
    credential_type: Literal["mycashflow_api_key"] = Field("mycashflow_api_key", json_schema_extra={"ui:hidden": True})
    store_name: str = Field(..., title="Store subdomain", min_length=1, max_length=63)
    email: str = Field(..., title="API user email", min_length=3)
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("store_name")
    @classmethod
    def store(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only the default store subdomain")
        return value

    @field_validator("email")
    @classmethod
    def user(cls, value):
        if not re.fullmatch(r"[^\s:@]+@[^\s:@]+", value):
            raise ValueError("Enter the API user's email")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListCustomersConfig(_Input):
    operation: Literal["list_customers"] = Field("list_customers", title='Retrieve a list of customers', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class GetCustomerConfig(_Input):
    operation: Literal["get_customer"] = Field("get_customer", title='Retrieve a customer', json_schema_extra={"ui:hidden": True})
    customerID: int = Field(..., title='Customerid', ge=1)

class CreateCustomerConfig(_Input):
    operation: Literal["create_customer"] = Field("create_customer", title='Create a new customer account', json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., title='First Name')
    last_name: str = Field(..., title='Last Name')
    login_allowed: bool = Field(..., title='Login Allowed')
    postal_code: str = Field(..., title='Postal Code')
    email: str = Field(..., title='Email')
    city: str = Field(..., title='City')
    street_address: str = Field(..., title='Street Address')
    country: str = Field(..., title='Country')
    phone: str | None = Field(None, title='Phone')
    language: str | None = Field(None, title='Language')

class UpdateCustomerConfig(_Input):
    operation: Literal["update_customer"] = Field("update_customer", title="Modify a customer's details", json_schema_extra={"ui:hidden": True})
    customerID: int = Field(..., title='Customerid', ge=1)
    first_name: str | None = Field(None, title='First Name')
    last_name: str | None = Field(None, title='Last Name')
    phone: str | None = Field(None, title='Phone')
    email: str | None = Field(None, title='Email')
    street_address: str | None = Field(None, title='Street Address')
    postal_code: str | None = Field(None, title='Postal Code')
    city: str | None = Field(None, title='City')
    country: str | None = Field(None, title='Country')

class GetCustomerByEmailConfig(_Input):
    operation: Literal["get_customer_by_email"] = Field("get_customer_by_email", title='Retrieve a customer designated by their email address', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title='Email')

class ListProductsConfig(_Input):
    operation: Literal["list_products"] = Field("list_products", title='Retrieve a list of products', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class GetProductConfig(_Input):
    operation: Literal["get_product"] = Field("get_product", title='Retrieve a product', json_schema_extra={"ui:hidden": True})
    productID: int = Field(..., title='Productid', ge=1)

class CreateProductConfig(_Input):
    operation: Literal["create_product"] = Field("create_product", title='Create a new product', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name')
    product_code: str | None = Field(None, title='Product Code')
    price: float | None = Field(None, title='Price')
    vat_rate: float | None = Field(None, title='Vat Rate')
    description: str | None = Field(None, title='Description')

class UpdateProductConfig(_Input):
    operation: Literal["update_product"] = Field("update_product", title='Modify a product', json_schema_extra={"ui:hidden": True})
    productID: int = Field(..., title='Productid', ge=1)
    name: str | None = Field(None, title='Name')
    product_code: str | None = Field(None, title='Product Code')
    price: float | None = Field(None, title='Price')
    vat_rate: float | None = Field(None, title='Vat Rate')
    description: str | None = Field(None, title='Description')

class GetProductByCodeConfig(_Input):
    operation: Literal["get_product_by_code"] = Field("get_product_by_code", title='Retrieve a product using its product code', json_schema_extra={"ui:hidden": True})
    productCode: str = Field(..., title='Productcode')

class ListOrdersConfig(_Input):
    operation: Literal["list_orders"] = Field("list_orders", title='Retrieve a list of orders', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class GetOrderConfig(_Input):
    operation: Literal["get_order"] = Field("get_order", title='Retrieve an order', json_schema_extra={"ui:hidden": True})
    orderID: int = Field(..., title='Orderid', ge=1)

class CancelOrderConfig(_Input):
    operation: Literal["cancel_order"] = Field("cancel_order", title='Cancel an order', json_schema_extra={"ui:hidden": True})
    orderID: int = Field(..., title='Orderid', ge=1)
    send_emails: bool | None = Field(None, title='Send Emails')

class ArchiveOrderConfig(_Input):
    operation: Literal["archive_order"] = Field("archive_order", title='Archive an order', json_schema_extra={"ui:hidden": True})
    orderID: int = Field(..., title='Orderid', ge=1)

class AddOrderCommentConfig(_Input):
    operation: Literal["add_order_comment"] = Field("add_order_comment", title='Post a new comment (private or public) for the order', json_schema_extra={"ui:hidden": True})
    orderID: int = Field(..., title='Orderid', ge=1)
    text: str = Field(..., title='Text')
    visibility: Literal['PUBLIC', 'PRIVATE'] | None = Field(None, title='Visibility')
    update_timestamp: bool | None = Field(None, title='Update Timestamp')

class ListStockConfig(_Input):
    operation: Literal["list_stock"] = Field("list_stock", title='Retrieve a list of stock items', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class GetStockConfig(_Input):
    operation: Literal["get_stock"] = Field("get_stock", title="Retrieve a product's stock item using the product code", json_schema_extra={"ui:hidden": True})
    productCode: str = Field(..., title='Productcode')

class AdjustStockConfig(_Input):
    operation: Literal["adjust_stock"] = Field("adjust_stock", title='Update the balance of the stock item', json_schema_extra={"ui:hidden": True})
    productCode: str = Field(..., title='Productcode')
    balance_change: int = Field(..., title='Balance Change')

class ListCategoriesConfig(_Input):
    operation: Literal["list_categories"] = Field("list_categories", title='Retrieve a list of categories', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class ListBrandsConfig(_Input):
    operation: Literal["list_brands"] = Field("list_brands", title='Retrieve a list of brands', json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    page: int | None = Field(None, title='Page', ge=1)

class SubscribeEmailConfig(_Input):
    operation: Literal["subscribe_email"] = Field("subscribe_email", title="Subscribe email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Email")

class UnsubscribeEmailConfig(_Input):
    operation: Literal["unsubscribe_email"] = Field("unsubscribe_email", title="Remove a subscriber from the store's mailing list", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title='Email')

OPERATIONS = {'list_customers': {'method': 'GET', 'path': '/v1/customers', 'query': ['page_size', 'page'], 'body': []}, 'get_customer': {'method': 'GET', 'path': '/v1/customers/{customerID}', 'query': [], 'body': []}, 'create_customer': {'method': 'POST', 'path': '/v1/customers', 'query': [], 'body': ['first_name', 'last_name', 'login_allowed', 'postal_code', 'email', 'city', 'street_address', 'country', 'phone', 'language']}, 'update_customer': {'method': 'PATCH', 'path': '/v1/customers/{customerID}', 'query': [], 'body': ['first_name', 'last_name', 'phone', 'email', 'street_address', 'postal_code', 'city', 'country']}, 'get_customer_by_email': {'method': 'GET', 'path': '/v1/customers/email={email}', 'query': [], 'body': []}, 'list_products': {'method': 'GET', 'path': '/v1/products', 'query': ['page_size', 'page'], 'body': []}, 'get_product': {'method': 'GET', 'path': '/v1/products/{productID}', 'query': [], 'body': []}, 'create_product': {'method': 'POST', 'path': '/v1/products', 'query': [], 'body': ['name', 'product_code', 'price', 'vat_rate', 'description']}, 'update_product': {'method': 'PATCH', 'path': '/v1/products/{productID}', 'query': [], 'body': ['name', 'product_code', 'price', 'vat_rate', 'description']}, 'get_product_by_code': {'method': 'GET', 'path': '/v1/products/product_code={productCode}', 'query': [], 'body': []}, 'list_orders': {'method': 'GET', 'path': '/v0/orders', 'query': ['page_size', 'page'], 'body': []}, 'get_order': {'method': 'GET', 'path': '/v0/orders/{orderID}', 'query': [], 'body': []}, 'cancel_order': {'method': 'POST', 'path': '/v0/orders/{orderID}/cancel', 'query': [], 'body': ['send_emails']}, 'archive_order': {'method': 'POST', 'path': '/v0/orders/{orderID}/archive', 'query': [], 'body': []}, 'add_order_comment': {'method': 'POST', 'path': '/v0/orders/{orderID}/comments', 'query': [], 'body': ['text', 'visibility', 'update_timestamp']}, 'list_stock': {'method': 'GET', 'path': '/v1/stock', 'query': ['page_size', 'page'], 'body': []}, 'get_stock': {'method': 'GET', 'path': '/v1/stock/{productCode}', 'query': [], 'body': []}, 'adjust_stock': {'method': 'POST', 'path': '/v1/stock/{productCode}/update-balance', 'query': [], 'body': ['balance_change']}, 'list_categories': {'method': 'GET', 'path': '/v1/categories', 'query': ['page_size', 'page'], 'body': []}, 'list_brands': {'method': 'GET', 'path': '/v1/brands', 'query': ['page_size', 'page'], 'body': []}, 'subscribe_email': {'method': 'POST', 'path': '/v1/email-subscribers', 'query': [], 'body': ['email']}, 'unsubscribe_email': {'method': 'DELETE', 'path': '/v1/email-subscribers/email={email}', 'query': [], 'body': []}}

class OnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On MyCashflow Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True})
    event_type: Literal["order.created", "order.archived", "order.unarchived", "order.comment.created", "campaign.created", "campaign.updated", "marketing.newsletter.updated"] = Field("order.created", title="Event type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

MyCashflowConfig = Annotated[Union[ListCustomersConfig, GetCustomerConfig, CreateCustomerConfig, UpdateCustomerConfig, GetCustomerByEmailConfig, ListProductsConfig, GetProductConfig, CreateProductConfig, UpdateProductConfig, GetProductByCodeConfig, ListOrdersConfig, GetOrderConfig, CancelOrderConfig, ArchiveOrderConfig, AddOrderCommentConfig, ListStockConfig, GetStockConfig, AdjustStockConfig, ListCategoriesConfig, ListBrandsConfig, SubscribeEmailConfig, UnsubscribeEmailConfig, OnEventConfig], Field(discriminator="operation")]

class MyCashflowNodeConfig(NodeConfig[MyCashflowConfig, MyCashflowCredential]):
    pass

class MyCashflowNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-mycashflow"
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products")

    @classmethod
    def get_config_model(cls):
        return MyCashflowNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = MyCashflowCredential.model_validate(credential)
        auth = base64.b64encode(f"{cred.email}:{cred.api_key}".encode()).decode()
        async with guarded_async_client(timeout=30) as client:
            response = await client.request(method, f"https://{cred.store_name}.mycashflow.fi/api{path}",
                headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}, params=params, json=body)
        if response.is_error:
            raise ValueError(f"MyCashflow API {response.status_code}: {response.text[:1000]}")
        return response.json() if response.content else {"deleted": True}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = OnEventConfig.model_validate(config).event_type
        result = await cls._request(credential, "POST", "/v1/webhooks", body={"topic": event, "url": webhook_url})
        identifier = result.get("data", {}).get("uuid")
        if not identifier:
            raise ValueError("MyCashflow did not return the webhook UUID")
        return {"external_webhook_id": identifier, "signing_secret": credential["api_key"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier:
            await cls._request(credential, "DELETE", "/v1/webhooks/" + quote(str(identifier), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "order.created")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        if not secret:
            return False
        signature = next((v for k, v in headers.items() if k.lower() == "x-mcf-webhook-signature"), "")
        expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload if payload.get("meta", {}).get("webhook_topic") == config.get("event_type", "order.created") else None

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output
        data = payload.get("data", {})
        meta = payload.get("meta", {})
        topic = meta.get("webhook_topic", "event")
        identifier = data.get("order_id") if topic == "order.comment.created" else data.get("id")
        return {"text": f"MyCashflow {topic}: resource {identifier}. "
                f"Details: {json.dumps(data, ensure_ascii=False)}",
                "conversation_key": str(identifier)}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, OnEventConfig):
            return inputs
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        result = await self._request(self.config.credentials.model_dump(), spec["method"], path,
            params={k: values[k] for k in spec["query"] if k in values},
            body={k: values[k] for k in spec["body"] if k in values} if spec["body"] else None)
        return {"status": "success", "operation": op.operation, **result}

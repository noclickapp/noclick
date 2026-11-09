"""SellerCloud REST v1 actions and scheduled order/inventory change detection.

Wire names and response fields follow the published SellerCloud Swagger contract.
Bearer tokens are supplied by the user; this module never requests a sign-in.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

AUTH_DOC = "https://developer.sellercloud.com/dev-article/authentication/"


class SellerCloudTokenCredential(BaseModel):
    model_config = ConfigDict(title="SellerCloud API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOC,
            "x-credential-instructions": "Paste an existing access_token and your SellerCloud REST API endpoint. Obtain the token using your integration employee in SellerCloud Swagger. SellerCloud tokens expire (the docs state 60 minutes); replace expired tokens here. NoClick does not store your SellerCloud password or renew tokens."})
    credential_type: Literal["sellercloud_api_token"] = Field("sellercloud_api_token", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="REST API endpoint", description="Your assigned endpoint, e.g. https://pbf2.api.sellercloud.com/rest. SellerCloud .com and .us API hosts are supported.")
    api_token: str = Field(..., title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url")
    @classmethod
    def endpoint(cls, value):
        parts = urlsplit(value.strip())
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
            or parts.port is not None or parts.query or parts.fragment or parts.path.rstrip("/") != "/rest"
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.api\.sellercloud\.(?:com|us)", parts.hostname or "")):
            raise ValueError("Use your assigned HTTPS SellerCloud API endpoint ending in /rest")
        return "https://" + parts.hostname + "/rest"

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the access_token, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_number: int = Field(1, ge=1, le=1000000, title="Page number")
    page_size: int = Field(100, ge=1, le=200, title="Page size")


class SellerCloudListOrdersConfig(_Page):
    operation: Literal['list_orders'] = Field('list_orders', title='List Orders', json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Search text')
    created_from: str | None = Field(None, description='Date/time filter: mm/dd/yyyy hh:mm')
    updated_from: str | None = Field(None, description='Date/time filter: mm/dd/yyyy hh:mm')

class SellerCloudGetOrderConfig(_Input):
    operation: Literal['get_order'] = Field('get_order', title='Get Order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudListCustomersConfig(_Page):
    operation: Literal['list_customers'] = Field('list_customers', title='List Customers', json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Search text')
    created_from: str | None = Field(None, description='Date/time filter: mm/dd/yyyy hh:mm')
    modified_from: str | None = Field(None, description='Date/time filter: mm/dd/yyyy hh:mm')

class SellerCloudGetCustomerConfig(_Input):
    operation: Literal['get_customer'] = Field('get_customer', title='Get Customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudListInventoryConfig(_Page):
    operation: Literal['list_inventory'] = Field('list_inventory', title='List Inventory', json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Search text')
    updated_from: str | None = Field(None, description='Date/time filter: mm/dd/yyyy hh:mm')

class SellerCloudGetInventoryConfig(_Input):
    operation: Literal['get_inventory'] = Field('get_inventory', title='Get Inventory', json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=256, title="Product SKU")

class SellerCloudListCompaniesConfig(_Page):
    operation: Literal['list_companies'] = Field('list_companies', title='List Companies', json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Search text')

class SellerCloudGetCompanyConfig(_Input):
    operation: Literal['get_company'] = Field('get_company', title='Get Company', json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudListWarehousesConfig(_Page):
    operation: Literal['list_warehouses'] = Field('list_warehouses', title='List Warehouses', json_schema_extra={"ui:hidden": True})

class SellerCloudGetWarehouseConfig(_Input):
    operation: Literal['get_warehouse'] = Field('get_warehouse', title='Get Warehouse', json_schema_extra={"ui:hidden": True})
    warehouse_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudListVendorsConfig(_Page):
    operation: Literal['list_vendors'] = Field('list_vendors', title='List Vendors', json_schema_extra={"ui:hidden": True})

class SellerCloudGetVendorConfig(_Input):
    operation: Literal['get_vendor'] = Field('get_vendor', title='Get Vendor', json_schema_extra={"ui:hidden": True})
    vendor_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudListPurchaseOrdersConfig(_Page):
    operation: Literal['list_purchase_orders'] = Field('list_purchase_orders', title='List Purchase Orders', json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Search text')

class SellerCloudGetPurchaseOrderConfig(_Input):
    operation: Literal['get_purchase_order'] = Field('get_purchase_order', title='Get Purchase Order', json_schema_extra={"ui:hidden": True})
    purchase_order_id: int = Field(..., ge=1, le=2147483647)

class SellerCloudCreateCustomerConfig(_Input):
    operation: Literal['create_customer'] = Field('create_customer', title='Create Customer', json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=500)
    last_name: str | None = None
    email: str | None = None
    company_id: int | None = Field(None, ge=1)
    business_name: str | None = None
    customer_type: Literal[0, 1] = 1

class SellerCloudUpdateCustomerConfig(_Input):
    operation: Literal['update_customer'] = Field('update_customer', title='Update Customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)
    name: str | None = None
    email: str | None = None
    business_name: str | None = None
    comments: str | None = None
    phone: str | None = None

class SellerCloudCreateProductConfig(_Input):
    operation: Literal['create_product'] = Field('create_product', title='Create Product', json_schema_extra={"ui:hidden": True})
    product_name: str = Field(..., min_length=1)
    product_sku: str = Field(..., min_length=1)
    product_type_name: str = Field(..., min_length=1)
    company_id: int | None = Field(None, ge=1, le=2147483647)
    site_cost: float | None = None
    default_price: float | None = None
    upc: str | None = None

class SellerCloudAdjustInventoryConfig(_Input):
    operation: Literal['adjust_inventory'] = Field('adjust_inventory', title='Adjust Inventory', json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1)
    warehouse_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)
    adjustment_type: Literal[0, 1] = Field(..., description="0 subtracts stock; 1 adds stock")
    reason: str = Field(..., min_length=1)
    pin_code: str | None = Field(None, json_schema_extra={"ui:widget": "password"})

class SellerCloudAddOrderNoteConfig(_Input):
    operation: Literal['add_order_note'] = Field('add_order_note', title='Add Order Note', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1)
    category: Literal[0, 1, 2] = 0
    is_pinned: bool = False

class SellerCloudSetOrderStatusConfig(_Input):
    operation: Literal['set_order_status'] = Field('set_order_status', title='Set Order Status', json_schema_extra={"ui:hidden": True})
    order_ids: list[int] = Field(..., min_length=1, max_length=100)
    status: Literal[1, 2, 3, 100, 200, 300, 999, -1] = Field(..., description="1 cart, 2 in process, 3 completed, 100 problem, 200 on hold, 300 quote, 999 void, -1 canceled")

class SellerCloudOnNewOrUpdatedOrderConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_order"] = Field("on_new_or_updated_order", title="New or Updated Order", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    updated_from: str | None = Field(None, description="Optional fixed start time (mm/dd/yyyy hh:mm). All matching pages are scanned; first poll establishes a baseline. Keep the scope under 10,000 records.")

class SellerCloudOnNewOrUpdatedInventoryConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_inventory"] = Field("on_new_or_updated_inventory", title="New or Updated Inventory", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    updated_from: str | None = Field(None, description="Optional fixed start time (mm/dd/yyyy hh:mm). All matching pages are scanned; first poll establishes a baseline. Keep the scope under 10,000 records.")



class SellerCloudOrderItem(_Input):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=2147483647)
    unit_price: float = Field(..., ge=0)
    warehouse_id: int | None = Field(None, ge=1, le=2147483647)


class SellerCloudCreateOrderConfig(_Input):
    operation: Literal["create_order"] = Field("create_order", title="Create Order", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, le=2147483647)
    customer_email: str = Field(..., min_length=1)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    address2: str | None = None
    city: str = Field(..., min_length=1)
    state: str | None = None
    zip_code: str = Field(..., min_length=1)
    country: str = Field(..., min_length=1)
    source_order_id: str | None = Field(None, description="External OrderSourceOrderID; SellerCloud controls duplicate handling")
    products: list[SellerCloudOrderItem] = Field(..., min_length=1, max_length=100)


class SellerCloudUpdateShippingStatusConfig(_Input):
    operation: Literal["update_shipping_status"] = Field("update_shipping_status", title="Update Shipping Status", description="Records shipping details and tracking for an order.", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, le=2147483647)
    shipping_carrier: str = Field(..., min_length=1)
    shipping_service: str = Field(..., min_length=1)
    tracking_number: str = Field(..., min_length=1)
    warehouse_id: int | None = Field(None, ge=1, le=2147483647)
    shipping_cost: float | None = Field(None, ge=0)


class SellerCloudPurchaseOrderItem(_Input):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=2147483647)
    unit_price: float = Field(..., ge=0)
    warehouse_id: int | None = Field(None, ge=1, le=2147483647)


class SellerCloudCreatePurchaseOrderConfig(_Input):
    operation: Literal["create_purchase_order"] = Field("create_purchase_order", title="Create Purchase Order", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, le=2147483647)
    vendor_id: int = Field(..., ge=1, le=2147483647)
    description: str | None = None
    vendor_note: str | None = None
    products: list[SellerCloudPurchaseOrderItem] = Field(..., min_length=1, max_length=100)


OPERATIONS = {'list_orders': {'method': 'GET',
                 'path': '/api/Orders',
                 'query': {'page_number': 'model.pageNumber',
                           'page_size': 'model.pageSize',
                           'keyword': 'model.keyword',
                           'created_from': 'model.createdOnFrom',
                           'updated_from': 'model.lastUpdatedFrom'},
                 'body': {},
                 'path_fields': {}},
 'get_order': {'method': 'GET',
               'path': '/api/Orders/{id}',
               'query': {},
               'body': {},
               'path_fields': {'id': 'order_id'}},
 'list_customers': {'method': 'GET',
                    'path': '/api/Customers',
                    'query': {'page_number': 'model.pageNumber',
                              'page_size': 'model.pageSize',
                              'keyword': 'model.keyword',
                              'created_from': 'model.createdOnFrom',
                              'modified_from': 'model.modifiedOnFrom'},
                    'body': {},
                    'path_fields': {}},
 'get_customer': {'method': 'GET',
                  'path': '/api/Customers/{id}',
                  'query': {},
                  'body': {},
                  'path_fields': {'id': 'customer_id'}},
 'list_inventory': {'method': 'GET',
                    'path': '/api/Inventory',
                    'query': {'page_number': 'model.pageNumber',
                              'page_size': 'model.pageSize',
                              'keyword': 'model.keyword',
                              'updated_from': 'model.lastUpdatedFrom'},
                    'body': {},
                    'path_fields': {}},
 'get_inventory': {'method': 'GET',
                   'path': '/api/Inventory/Details',
                   'query': {'product_id': 'productID'},
                   'body': {},
                   'path_fields': {}},
 'list_companies': {'method': 'GET',
                    'path': '/api/Companies',
                    'query': {'page_number': 'model.pageNumber',
                              'page_size': 'model.pageSize',
                              'keyword': 'model.keyword'},
                    'body': {},
                    'path_fields': {}},
 'get_company': {'method': 'GET',
                 'path': '/api/Companies/{id}',
                 'query': {},
                 'body': {},
                 'path_fields': {'id': 'company_id'}},
 'list_warehouses': {'method': 'GET',
                     'path': '/api/Warehouses',
                     'query': {'page_number': 'model.pageNumber', 'page_size': 'model.pageSize'},
                     'body': {},
                     'path_fields': {}},
 'get_warehouse': {'method': 'GET',
                   'path': '/api/Warehouses/{id}',
                   'query': {},
                   'body': {},
                   'path_fields': {'id': 'warehouse_id'}},
 'list_vendors': {'method': 'GET',
                  'path': '/api/Vendors',
                  'query': {'page_number': 'model.pageNumber', 'page_size': 'model.pageSize'},
                  'body': {},
                  'path_fields': {}},
 'get_vendor': {'method': 'GET',
                'path': '/api/Vendors/{id}',
                'query': {},
                'body': {},
                'path_fields': {'id': 'vendor_id'}},
 'list_purchase_orders': {'method': 'GET',
                          'path': '/api/PurchaseOrders',
                          'query': {'page_number': 'model.pageNumber',
                                    'page_size': 'model.pageSize',
                                    'keyword': 'model.keyword'},
                          'body': {},
                          'path_fields': {}},
 'get_purchase_order': {'method': 'GET',
                        'path': '/api/PurchaseOrders/{id}',
                        'query': {},
                        'body': {},
                        'path_fields': {'id': 'purchase_order_id'}},
 'create_customer': {'method': 'POST',
                     'path': '/api/Customers',
                     'query': {},
                     'body': {'first_name': 'FirstName',
                              'last_name': 'LastName',
                              'email': 'Email',
                              'company_id': 'CompanyID',
                              'business_name': 'BusinessName',
                              'customer_type': 'CustomerType'},
                     'path_fields': {}},
 'update_customer': {'method': 'PUT',
                     'path': '/api/Customers/{id}',
                     'query': {},
                     'body': {'name': 'Name',
                              'email': 'Email',
                              'business_name': 'BusinessName',
                              'comments': 'Comments',
                              'phone': 'Phone1'},
                     'path_fields': {'id': 'customer_id'}},
 'create_product': {'method': 'POST',
                    'path': '/api/Products',
                    'query': {},
                    'body': {'product_name': 'ProductName',
                             'product_sku': 'ProductSKU',
                             'product_type_name': 'ProductTypeName',
                             'company_id': 'CompanyId',
                             'site_cost': 'SiteCost',
                             'default_price': 'DefaultPrice',
                             'upc': 'UPC'},
                    'path_fields': {}},
 'adjust_inventory': {'method': 'PUT',
                      'path': '/api/Inventory/AdjustPhysicalInventory',
                      'query': {},
                      'body': {'product_id': 'ProductID',
                               'warehouse_id': 'WarehouseID',
                               'quantity': 'Qty',
                               'adjustment_type': 'AdjustmentType',
                               'reason': 'Reason',
                               'pin_code': 'PinCode'},
                      'path_fields': {}},
 'add_order_note': {'method': 'POST',
                    'path': '/api/Orders/{orderID}/Notes',
                    'query': {},
                    'body': {'message': 'Message', 'category': 'Category', 'is_pinned': 'IsPinned'},
                    'path_fields': {'orderID': 'order_id'}},
 'set_order_status': {'method': 'PUT',
                      'path': '/api/Orders/StatusCode',
                      'query': {},
                      'body': {'order_ids': 'Orders', 'status': 'Status'},
                      'path_fields': {}}}

OPERATIONS.update({
    "create_order": {"method": "POST", "path": "/api/Orders", "query": {}, "body": {}, "path_fields": {}},
    "create_purchase_order": {"method": "POST", "path": "/api/PurchaseOrders", "query": {}, "body": {}, "path_fields": {}},
    "update_shipping_status": {"method": "PUT", "path": "/api/Orders/ShippingStatus", "query": {}, "body": {"order_id": "OrderID", "shipping_carrier": "ShippingCarrier", "shipping_service": "ShippingService", "tracking_number": "TrackingNumber", "warehouse_id": "ShipFromWarehouseID", "shipping_cost": "ShippingCost"}, "path_fields": {}},
})

SellerCloudConfig = Annotated[Union[SellerCloudCreateOrderConfig, SellerCloudCreatePurchaseOrderConfig, SellerCloudUpdateShippingStatusConfig, SellerCloudListOrdersConfig, SellerCloudGetOrderConfig, SellerCloudListCustomersConfig, SellerCloudGetCustomerConfig, SellerCloudListInventoryConfig, SellerCloudGetInventoryConfig, SellerCloudListCompaniesConfig, SellerCloudGetCompanyConfig, SellerCloudListWarehousesConfig, SellerCloudGetWarehouseConfig, SellerCloudListVendorsConfig, SellerCloudGetVendorConfig, SellerCloudListPurchaseOrdersConfig, SellerCloudGetPurchaseOrderConfig, SellerCloudCreateCustomerConfig, SellerCloudUpdateCustomerConfig, SellerCloudCreateProductConfig, SellerCloudAdjustInventoryConfig, SellerCloudAddOrderNoteConfig, SellerCloudSetOrderStatusConfig, SellerCloudOnNewOrUpdatedOrderConfig, SellerCloudOnNewOrUpdatedInventoryConfig], Field(discriminator="operation")]


class SellerCloudNodeConfig(NodeConfig[SellerCloudConfig, SellerCloudTokenCredential]):
    pass


class SellerCloudNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-sellercloud"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="SellerCloud companies", label_keys=("CompanyName", "ID"))

    @classmethod
    def get_config_model(cls):
        return SellerCloudNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SellerCloud API token")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.api_base_url + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection visible to the connection evidence seam.
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"SellerCloud HTTP {response.status_code}: {detail}")
        if not response.content:
            return None
        if len(response.content) > 10000000:
            raise ValueError("SellerCloud response exceeds 10 MB; request a smaller page")
        return response.json()

    @staticmethod
    def _page(body):
        if not isinstance(body, dict) or not isinstance(body.get("Items"), list):
            raise ValueError("SellerCloud list response must contain Items")
        if any(not isinstance(row, dict) for row in body["Items"]):
            raise ValueError("SellerCloud Items must contain records")
        total = body.get("TotalResults")
        if type(total) is not int or total < 0:
            raise ValueError("SellerCloud list response must contain TotalResults")
        return body["Items"], total

    async def _poll(self, config):
        orders = config.operation == "on_new_or_updated_order"
        path = "/api/Orders" if orders else "/api/Inventory"
        timestamp = "LastUpdated" if orders else "LastModifiedDate"
        rows = []
        for page in range(1, 51):
            params = {"model.pageNumber": page, "model.pageSize": 200}
            if config.updated_from:
                params["model.lastUpdatedFrom"] = config.updated_from
            body = await self._request("GET", path, params=params)
            items, total = self._page(body)
            if total > 10000:
                raise ValueError("SellerCloud poll scope exceeds 10,000 records; set a later updated_from")
            for item in items:
                if item.get("ID") is None or not isinstance(item.get(timestamp), str) or not item[timestamp]:
                    raise ValueError("SellerCloud change detection requires ID and " + timestamp)
            rows.extend(items)
            if page * 200 >= total:
                break
            if not items:
                raise ValueError("SellerCloud returned an incomplete page; change baseline was not advanced")
        else:
            raise ValueError("SellerCloud polling page bound reached; narrow updated_from")
        # Include the documented version timestamp to emit edits as well as new IDs.
        fresh = await self._filter_unseen(rows, lambda row: json.dumps([row["ID"], row[timestamp]]))
        return {"operation": config.operation, "items": fresh, "new_item_count": len(fresh)}

    async def execute(self, inputs):
        config = self.config.config
        if not self.config.credentials:
            raise ValueError("Connect a SellerCloud API token")
        if isinstance(config, (SellerCloudOnNewOrUpdatedOrderConfig, SellerCloudOnNewOrUpdatedInventoryConfig)):
            return await self._poll(config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for wire, key in spec["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(str(values[key]), safe=""))
        params = {wire: values[key] for key, wire in spec["query"].items() if key in values}
        body = {wire: values[key] for key, wire in spec["body"].items() if key in values} if spec["body"] else None
        if isinstance(config, SellerCloudCreateOrderConfig):
            address_fields = {"first_name": "FirstName", "last_name": "LastName", "address": "Address", "address2": "Address2", "city": "City", "state": "State", "zip_code": "ZipCode", "country": "Country"}
            body = {
                "CustomerDetails": {"Email": config.customer_email, "FirstName": config.first_name, "LastName": config.last_name},
                "OrderDetails": {"CompanyID": config.company_id, **({"OrderSourceOrderID": config.source_order_id} if config.source_order_id else {})},
                "ShippingAddress": {wire: values[key] for key, wire in address_fields.items() if key in values},
                "Products": [{"ProductID": item.product_id, "Qty": item.quantity, "SitePrice": item.unit_price,
                    **({"ShipFromWareHouseID": item.warehouse_id} if item.warehouse_id is not None else {})} for item in config.products],
            }
        elif isinstance(config, SellerCloudCreatePurchaseOrderConfig):
            body = {"CompanyID": config.company_id, "VendorID": config.vendor_id, "POType": 0, "CaseQtyMode": False,
                **({"Description": config.description} if config.description is not None else {}),
                **({"VendorNote": config.vendor_note} if config.vendor_note is not None else {}),
                "Products": [{"ProductID": item.product_id, "QtyUnitsOrdered": item.quantity, "UnitPrice": item.unit_price,
                    **({"WarehouseID": item.warehouse_id} if item.warehouse_id is not None else {})} for item in config.products]}
        if config.operation == "update_customer" and not body:
            raise ValueError("Supply at least one customer field to update")
        data = await self._request(spec["method"], path, params=params, body=body)
        if config.operation.startswith("list_"):
            items, total = self._page(data)
            return {"data": data, "items": items, "total_results": total,
                "next_page_number": config.page_number + 1 if config.page_number * config.page_size < total else None}
        return {"data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in {"on_new_or_updated_order", "on_new_or_updated_inventory"}:
            return super().resolve_agent_event(output)
        items = output.get("items")
        if not isinstance(items, list) or not items:
            return None
        orders = output["operation"] == "on_new_or_updated_order"
        lines = ["SellerCloud: new or updated " + ("orders" if orders else "inventory")]
        for row in items[:20]:
            if orders:
                who = " ".join(str(row.get(k) or "") for k in ("FirstName", "LastName")).strip()
                lines.append(f"Order {row['ID']}: {who}; company {row.get('CompanyName', '')}; total {row.get('GrandTotal', '')}; updated {row.get('LastUpdated', '')}. Use get_order with order_id={row['ID']} to act.")
            else:
                lines.append(f"Product {row['ID']}: {row.get('ProductName', '')}; physical quantity {row.get('PhysicalQty', '')}; updated {row.get('LastModifiedDate', '')}. Use get_inventory with product_id={row['ID']} to act.")
        return {"text": "\n".join(lines), "title": lines[0],
            "conversation_key": "sellercloud:" + ("order:" if orders else "inventory:") + str(items[0]["ID"])}

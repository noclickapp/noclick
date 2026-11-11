"""VTEX Orders API, pinned to the official Orders OpenAPI 1.0 contract.

Use a dedicated app key for the order hook: VTEX permits one hook per app key,
and activating the trigger replaces that key's current hook configuration.
Delivery uses the provider's configurable credential header, not a body HMAC.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    create_model,
    field_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from utils.ssrf import guarded_async_client


class VTEXAppKeyCredential(BaseModel):
    credential_type: Literal["vtex_app_key"] = Field(
        "vtex_app_key", json_schema_extra={"ui:hidden": True}
    )
    account_name: str = Field(
        ...,
        title="Account Name",
        description="VTEX account name, without a URL or domain.",
    )
    app_key: str = Field(
        ..., title="App Key", json_schema_extra={"ui:widget": "password"}
    )
    app_token: str = Field(
        ..., title="App Token", json_schema_extra={"ui:widget": "password"}
    )
    model_config = ConfigDict(
        title="VTEX App Key",
        json_schema_extra={
            "x-credential-url": "https://help.vtex.com/en/tutorial/application-keys--2iffYzlvvz4BDMr6WGUtet",
            "x-credential-instructions": "Enter your VTEX account name and an app key/token pair with the License Manager resources needed for your actions. Use a dedicated app key with Feed v3 and Hook Admin for the order trigger: activating it replaces the single hook configured for this key.",
        },
    )

    @field_validator("account_name")
    @classmethod
    def account(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter the account name only, without a URL or domain")
        return value


OPERATIONS = {
    "get_order": {
        "method": "GET",
        "path": "/api/oms/pvt/orders/{orderId}",
        "label": "Get order",
        "params": [("orderId", "path")],
        "body": [],
    },
    "list_orders": {
        "method": "GET",
        "path": "/api/oms/pvt/orders",
        "label": "List orders",
        "params": [
            ("orderBy", "query"),
            ("page", "query"),
            ("per_page", "query"),
            ("f_hasInputInvoice", "query"),
            ("q", "query"),
            ("f_shippingEstimate", "query"),
            ("f_invoicedDate", "query"),
            ("f_creationDate", "query"),
            ("f_authorizedDate", "query"),
            ("f_UtmSource", "query"),
            ("f_sellerNames", "query"),
            ("f_callCenterOperatorName", "query"),
            ("f_salesChannel", "query"),
            ("salesChannelId", "query"),
            ("f_affiliateId", "query"),
            ("f_status", "query"),
            ("incompleteOrders", "query"),
            ("f_paymentNames", "query"),
            ("f_RnB", "query"),
            ("searchField", "query"),
            ("f_isInstore", "query"),
        ],
        "body": [],
    },
    "start_handling": {
        "method": "POST",
        "path": "/api/oms/pvt/orders/{orderId}/start-handling",
        "label": "Start handling order",
        "params": [("orderId", "path")],
        "body": [],
    },
    "cancel_order": {
        "method": "POST",
        "path": "/api/oms/pvt/orders/{orderId}/cancel",
        "label": "Cancel order",
        "params": [("orderId", "path")],
        "body": [("reason", "reason", False)],
    },
    "register_change": {
        "method": "POST",
        "path": "/api/oms/pvt/orders/{orderId}/changes",
        "label": "Register modifications on order",
        "params": [("orderId", "path")],
        "body": [
            ("requestId", "requestId", False),
            ("reason", "reason", False),
            ("discountValue", "discountValue", False),
            ("incrementValue", "incrementValue", False),
            ("itemsRemoved_json", "itemsRemoved", True),
            ("itemsAdded_json", "itemsAdded", True),
        ],
    },
    "add_order_log": {
        "method": "POST",
        "path": "/api/oms/pvt/orders/{orderId}/interactions",
        "label": "Add log in orders",
        "params": [("orderId", "path")],
        "body": [("source", "source", False), ("message", "message", False)],
    },
    "notify_invoice": {
        "method": "POST",
        "path": "/api/oms/pvt/orders/{orderId}/invoice",
        "label": "Order invoice notification",
        "params": [("orderId", "path")],
        "body": [
            ("type", "type", False),
            ("issuanceDate", "issuanceDate", False),
            ("invoiceNumber", "invoiceNumber", False),
            ("invoiceValue", "invoiceValue", False),
            ("invoiceKey", "invoiceKey", False),
            ("invoiceUrl", "invoiceUrl", False),
            ("embeddedInvoice", "embeddedInvoice", False),
            ("courier", "courier", False),
            ("trackingNumber", "trackingNumber", False),
            ("trackingUrl", "trackingUrl", False),
            ("dispatchedDate", "dispatchedDate", False),
            ("items_json", "items", True),
        ],
    },
    "update_invoice_tracking": {
        "method": "PATCH",
        "path": "/api/oms/pvt/orders/{orderId}/invoice/{invoiceNumber}",
        "label": "Update order's partial invoice (send tracking number)",
        "params": [("orderId", "path"), ("invoiceNumber", "path")],
        "body": [
            ("trackingNumber", "trackingNumber", False),
            ("trackingUrl", "trackingUrl", False),
            ("dispatchedDate", "dispatchedDate", False),
            ("courier", "courier", False),
        ],
    },
    "update_tracking_status": {
        "method": "PUT",
        "path": "/api/oms/pvt/orders/{orderId}/invoice/{invoiceNumber}/tracking",
        "label": "Update order tracking status",
        "params": [("orderId", "path"), ("invoiceNumber", "path")],
        "body": [
            ("isDelivered", "isDelivered", False),
            ("deliveredDate", "deliveredDate", False),
            ("events_json", "events", True),
        ],
    },
    "get_conversation": {
        "method": "GET",
        "path": "/api/oms/pvt/orders/{orderId}/conversation-message",
        "label": "Retrieve order conversation",
        "params": [("orderId", "path")],
        "body": [],
    },
    "get_payment_transaction": {
        "method": "GET",
        "path": "/api/oms/pvt/orders/{orderId}/payment-transaction",
        "label": "Retrieve payment transaction",
        "params": [("orderId", "path")],
        "body": [],
    },
    "get_feed_configuration": {
        "method": "GET",
        "path": "/api/orders/feed/config",
        "label": "Get feed configuration",
        "params": [],
        "body": [],
    },
    "get_hook_configuration": {
        "method": "GET",
        "path": "/api/orders/hook/config",
        "label": "Get hook configuration",
        "params": [("clientEmail", "query"), ("page", "query"), ("per_page", "query")],
        "body": [],
    },
    "get_change_summary": {
        "method": "GET",
        "path": "/api/orders/pvt/document/{orderId}/change-summary",
        "label": "Get order modifications summary",
        "params": [("orderId", "path")],
        "body": [],
    },
    "create_change": {
        "method": "PATCH",
        "path": "/api/order-system/orders/{changeOrderId}/changes",
        "label": "Create order modifications",
        "params": [("accountName", "query"), ("changeOrderId", "path")],
        "body": [
            ("reason", "reason", False),
            ("replace_json", "replace", True),
            ("settings_json", "settings", True),
        ],
    },
    "get_change_history": {
        "method": "GET",
        "path": "/api/order-system/orders/{changeOrderId}/changes",
        "label": "Get order modifications history",
        "params": [("an", "query"), ("changeOrderId", "path")],
        "body": [],
    },
    "get_change_detail": {
        "method": "GET",
        "path": "/api/order-system/orders/{changeOrderId}/changes/{changeRequestId}",
        "label": "Get order modifications details",
        "params": [
            ("an", "query"),
            ("changeOrderId", "path"),
            ("changeRequestId", "path"),
        ],
        "body": [],
    },
    "preview_change": {
        "method": "POST",
        "path": "/api/order-system/orders/{changeOrderId}/changes/preview",
        "label": "Preview order modifications",
        "params": [("an", "query"), ("changeOrderId", "path")],
        "body": [
            ("reason", "reason", False),
            ("replace_json", "replace", True),
            ("settings_json", "settings", True),
        ],
    },
    "retry_change": {
        "method": "POST",
        "path": "/api/order-system/orders/{changeOrderId}/changes/{changeRequestId}/retry",
        "label": "Retry order modifications",
        "params": [
            ("an", "query"),
            ("changeOrderId", "path"),
            ("changeRequestId", "path"),
        ],
        "body": [
            ("reason", "reason", False),
            ("replace_json", "replace", True),
            ("settings_json", "settings", True),
        ],
    },
    "cancel_change": {
        "method": "POST",
        "path": "/api/order-system/orders/{changeOrderId}/changes/{changeRequestId}/cancel",
        "label": "Cancel order modifications",
        "params": [
            ("an", "query"),
            ("changeOrderId", "path"),
            ("changeRequestId", "path"),
        ],
        "body": [("reason", "reason", False)],
    },
}

FIELDS = {
    "get_order": {
        "orderId": (
            "string",
            True,
            "Order ID is a unique code that identifies an order. Instead of using `orderId`, you can also make the request using the sequence, a six-digit string that follows the order ID. For example, in order 1268540501456-01 (501456), the sequence is 501456. To use this parameter, replace the value between `{ }` keys in `seq{sequence-number}` with the sequence. For example: `seq501456`.",
        )
    },
    "list_orders": {
        "orderBy": (
            "string",
            False,
            "You can retrieve orders lists filtering by an `OrderField` combined with an `OrderType`. To do so, you have to concatenate them: `orderBy={{OrderField}},{{OrderType}}`. \r\n- `OrderField` values accepted: `creationDate`, `orderId`, `items`, `totalValue` and `origin`. \r\n- `OrderType` values accepted: `asc` and `desc`.",
        ),
        "page": (
            "integer",
            False,
            "Define the number of pages you wish to retrieve, restricted to the limit of 30 pages.",
        ),
        "per_page": (
            "integer",
            False,
            "Quantity of orders for each page, the default value is 15 and it goes up to 100 orders per page. Be aware that the limit of retrieval ofthis endpoint is 30 pages.",
        ),
        "f_hasInputInvoice": (
            "boolean",
            False,
            "Filters list to return only orders with non `null` values for the `invoiceInput` field.",
        ),
        "q": (
            "string",
            False,
            "This parameter filters using Fulltext and accepts the values below. Be aware that the `+` caracter is not allowed in Fulltext Search. \r\n- Order Id \r\n- Client email \r\n- Client document \r\n- Client name \r\n\r\n B2B Buyer Portal users can search for contact information fields, which includes the values below: \r\n- User email. \r\n- User first name. \r\n- User last name. \r\n- User phone number. \r\n- User document ID. \r\n- User document type.",
        ),
        "f_shippingEstimate": (
            "string",
            False,
            "You can filter orders by shipping estimate time in days by concatenating the desired number of days with the sufix `.days`. For example: \r\n- Next 7 days: `7.days` \r\n- Tomorrow: `1.days` \r\n- Today: `0.days` \r\n- Late: `-1.days`",
        ),
        "f_invoicedDate": (
            "string",
            False,
            "You can filter orders by invoiced date by concatenating the sufix `invoicedDate:` with the range date in Timestamp format. For example: \r\n- 1 Day: `invoicedDate:[2022-01-01T02:00:00.000Z TO 2022-01-02T01:59:59.999Z]`\r\n- 1 Month: `invoicedDate:[2022-01-01T02:00:00.000Z TO 2022-02-01T01:59:59.999Z]` \r\n- 1 Year: `invoicedDate:[2022-01-01T02:00:00.000Z TO 2022-01-01T01:59:59.999Z]`",
        ),
        "f_creationDate": (
            "string",
            False,
            "You can filter orders by creation date by concatenating the sufix `creationDate:` with the range date in Timestamp format. For example: \r\n- 1 Day: `creationDate:[2022-01-01T02:00:00.000Z TO 2022-01-02T01:59:59.999Z]`\r\n- 1 Month: `creationDate:[2022-01-01T02:00:00.000Z TO 2022-02-01T01:59:59.999Z]` \r\n- 1 Year: `creationDate:[2022-01-01T02:00:00.000Z TO 2022-01-01T01:59:59.999Z]`",
        ),
        "f_authorizedDate": (
            "string",
            False,
            "You can filter orders by creation date by concatenating the sufix `authorizedDate:` with the range date in Timestamp format. For example: \r\n- 1 Day: `authorizedDate:[2022-01-01T02:00:00.000Z TO 2022-01-02T01:59:59.999Z]`\r\n- 1 Month: `authorizedDate:[2022-01-01T02:00:00.000Z TO 2022-02-01T01:59:59.999Z]` \r\n- 1 Year: `authorizedDate:[2022-01-01T02:00:00.000Z TO 2022-01-01T01:59:59.999Z]`",
        ),
        "f_UtmSource": (
            "string",
            False,
            "You can filter orders by Urchin Tracking Module (UTM) source.",
        ),
        "f_sellerNames": (
            "string",
            False,
            "You can filter orders by using a seller's name.",
        ),
        "f_callCenterOperatorName": (
            "string",
            False,
            "You can filter orders by using a Call Center Operator's identification.",
        ),
        "f_salesChannel": (
            "string",
            False,
            "You can filter orders by sales channel's ([or trade policy](https://help.vtex.com/en/tutorial/how-trade-policies-work--6Xef8PZiFm40kg2STrMkMV)) name.",
        ),
        "salesChannelId": (
            "string",
            False,
            "You can filter orders by sales channel's ([or trade policy](https://help.vtex.com/en/tutorial/how-trade-policies-work--6Xef8PZiFm40kg2STrMkMV)) ID.",
        ),
        "f_affiliateId": ("string", False, "You can filter orders by affiliate ID."),
        "f_status": (
            "string",
            False,
            "You can filter orders by the following [order status](https://help.vtex.com/en/tutorial/order-flow-and-status--tutorials_196): \r\n- `waiting-for-sellers-confirmation` \r\n- `payment-pending` \r\n- `payment-approved` \r\n- `ready-for-handling` \r\n- `handling` \r\n- `invoiced` \r\n- `canceled`",
        ),
        "incompleteOrders": (
            "boolean",
            False,
            "When set as `true`, you retrieve [incomplete orders](https://help.vtex.com/en/tutorial/understanding-incomplete-orders), when set as `false`, you retrieve orders that are not incomplete.",
        ),
        "f_paymentNames": ("string", False, "You can filter orders by payment type."),
        "f_RnB": (
            "string",
            False,
            "You can filter orders by rates and benefits (promotions).",
        ),
        "searchField": (
            "string",
            False,
            "You can search orders by using one of the following criterias: \r\n- SKU ID - `sku_Ids&sku_Ids` \r\n- Gift List ID - `listId&listId` \r\n- Transaction ID (TID) - `tid&tid` \r\n- PCI Connector's Transaction ID (TID) - `pci_tid&pci_tid` \r\n- Payment ID (PID) - `paymentId&paymentId` \r\n- Connector's NSU - `nsu&nsu`",
        ),
        "f_isInstore": (
            "boolean",
            False,
            "When set as `true`, this parameter filters orders made via [inStore](https://help.vtex.com/en/tracks/what-is-instore--zav76TFEZlAjnyBVL5tRc), and when set as `false`, it filters orders that were not made via inStore.",
        ),
    },
    "start_handling": {
        "orderId": (
            "string",
            True,
            "Order ID is a unique code that identifies an order.",
        )
    },
    "cancel_order": {
        "orderId": ("string", True, "ID that identifies the order in the seller."),
        "reason": ("string", False, "Reason for cancelling the order."),
    },
    "register_change": {
        "orderId": ("string", True, "ID that identifies the order in the seller."),
        "requestId": (
            "string",
            True,
            "Request identification of the modification. Only the first modification made with each `requestId` will be effective on a given order. Use different IDs for different modifications to the same order.",
        ),
        "reason": (
            "string",
            True,
            "Reason for order modification. This may be shown to the shopper in the UI or transactional emails.",
        ),
        "discountValue": (
            "integer",
            True,
            "This field can be used to apply a discount to the total value of the order. Value in cents.",
        ),
        "incrementValue": (
            "integer",
            True,
            "This field can be used to increment the total value of the order. Value in cents.",
        ),
        "itemsRemoved_json": (
            "array",
            False,
            "List of items that should be removed from the order.",
        ),
        "itemsAdded_json": (
            "array",
            False,
            "List of items that should be added to the order.",
        ),
    },
    "add_order_log": {
        "orderId": ("string", True, "Unique code that identifies an order."),
        "source": ("string", True, "Source information."),
        "message": ("string", True, "Interactions message."),
    },
    "notify_invoice": {
        "orderId": (
            "string",
            True,
            "Unique code that identifies the order whose invoice is being sent.",
        ),
        "type": (
            "string",
            True,
            "The type of invoice. There are two possible values: **Output** and **Input**. The Output type should be used when the invoice you are sending is a selling invoice. The Input type should be used when you send a return invoice.",
        ),
        "issuanceDate": (
            "string",
            True,
            "The invoice date is when the order was [invoiced](https://help.vtex.com/en/tracks/orders--2xkTisx4SXOWXQel8Jg8sa/2WgQrlHTyVo4hLjhUs1LMT) in the VTEX platform, and the `IssuanceDate` is the date when the merchant registers the order's invoice in the store's system. The `IssuanceDate` can be different from the invoice date, because the merchant can register the invoice days or even months after order invoicing. You must add date and time in this field.",
        ),
        "invoiceNumber": (
            "string",
            True,
            "Unique code that identifies the invoice. When you call this endpoint using the same invoice number, you generate a new `receipt` code.",
        ),
        "invoiceValue": (
            "string",
            True,
            "Total amount being invoiced in cents. Must be greater than 0. Do not use any decimal separator. For instance, `$24.99` should be represented as `2499`.",
        ),
        "invoiceKey": ("string", False, "Information about invoice key."),
        "invoiceUrl": (
            "string",
            False,
            "URL of the invoice. Can be used to send the URL of an XML file, for example, which is useful for some integrations.",
        ),
        "embeddedInvoice": (
            "string",
            False,
            "XML text of the invoice, not the URL. This field is very important for external marketplace integrations such as Mercado Libre.",
        ),
        "courier": (
            "string",
            False,
            "The name of the carrier responsible for delivering the order.",
        ),
        "trackingNumber": (
            "string",
            False,
            'The number code that identifies the order tracking. *This field should only be used when sending the **tracking** information. When the request is used for sending the invoice, this field should be left empty (`""`)*.',
        ),
        "trackingUrl": (
            "string",
            False,
            'The URL used to track the order. *This field should only be used when sending the **tracking** information. When the request is used for sending the invoice, this field should be left empty (`""`)*.',
        ),
        "dispatchedDate": ("string", False, "Order dispatch date. May be `null`."),
        "items_json": (
            "array",
            True,
            "Array containing the SKUs that are being invoiced.",
        ),
    },
    "update_invoice_tracking": {
        "orderId": (
            "string",
            True,
            "Unique code that identifies the order whose invoice is being sent.",
        ),
        "invoiceNumber": ("string", True, "Number that identifies the invoice."),
        "trackingNumber": (
            "string",
            True,
            "The number code that identifies the order tracking.",
        ),
        "trackingUrl": ("string", True, "Package tracking URL."),
        "dispatchedDate": (
            "string",
            True,
            "Date when the package was dispatched. For example, 2023-01-08T13:16:13.4617653+00:00.",
        ),
        "courier": (
            "string",
            True,
            "The name of the carrier responsible for delivering the order.",
        ),
    },
    "update_tracking_status": {
        "orderId": (
            "string",
            True,
            "Order ID is a unique code that identifies an order.",
        ),
        "invoiceNumber": ("string", True, "Number that identifies the invoice."),
        "isDelivered": (
            "boolean",
            True,
            "When set as `true`, it means the order got to its final shipping address, whether by delivery or pickup shipping type. When set as `false`, the order is still in transit to its shipping address.",
        ),
        "deliveredDate": (
            "string",
            True,
            "Date and time of when the package was delivered. Note that it is different from the tracking date parameter. The `deliveredDate` format is `yyyy-mm-dd hh:mm`.",
        ),
        "events_json": ("array", True, "Array containing events information."),
    },
    "get_conversation": {
        "orderId": (
            "string",
            True,
            "Order ID is a unique code that identifies an order.",
        )
    },
    "get_payment_transaction": {
        "orderId": (
            "string",
            True,
            "Order ID is a unique code that identifies an order.",
        )
    },
    "get_feed_configuration": {},
    "get_hook_configuration": {
        "clientEmail": ("string", False, "Customer email."),
        "page": ("string", False, "Page number for result pagination."),
        "per_page": ("string", False, "Page quantity for result pagination."),
    },
    "get_change_summary": {"orderId": ("string", True, "Order ID.")},
    "create_change": {
        "accountName": (
            "string",
            True,
            "Name of the VTEX account that created the order.",
        ),
        "changeOrderId": ("string", True, "Order ID of the order you wish to modify."),
        "reason": (
            "string",
            True,
            "Reason why you wish to modify order. Since you can make several modifications to an order, filling this field with a clear explanation helps organize the order modifications history. The shopper can view this field value in [transactional emails](https://help.vtex.com/en/tutorial/order-transactional-email-templates--3g2S2kqBOoSGcCaqMYK2my) and [My Account](https://help.vtex.com/en/tutorial/how-my-account-works--2BQ3GiqhqGJTXsWVuio3Xh).",
        ),
        "replace_json": (
            "array",
            False,
            "Array containing `replace` change information. Besides `replace`, you can `add` or `remove` items from an order.\r\n\r\n- `add`: the schema will correspond to the object `to` inside the `replace` array.\r\n\r\n- `remove`: the schema will correspond to the object `from` inside the `replace` array.\r\n\r\nYou will find request body examples of both cases in the endpoint description on the top of the page. The successful response `202 - Accepted` schema is the same for all three operations, whether they are used separately or combined in the same request.",
        ),
        "settings_json": ("object", False, ""),
    },
    "get_change_history": {
        "an": ("string", True, "Name of the VTEX account that created the order."),
        "changeOrderId": (
            "string",
            True,
            "Order ID of the order you wish to get the modifications history.",
        ),
    },
    "get_change_detail": {
        "an": ("string", True, "Name of the VTEX account that created the order."),
        "changeOrderId": (
            "string",
            True,
            "Order ID of the order you wish to get the modification detail.",
        ),
        "changeRequestId": (
            "string",
            True,
            "Once you make an order modification, you generate a `requestId` code that identifies the modifications made to that order. This field should be filled with that code. There are no limits to modifications you can perform using the same `changeRequestId`, and we recommend keeping all modifications of a given order grouped by the same `changeRequestId`, so you will have a unified modification history.",
        ),
    },
    "preview_change": {
        "an": ("string", True, "Name of the VTEX account that created the order."),
        "changeOrderId": (
            "string",
            True,
            "Order ID of the order you wish to preview modification.",
        ),
        "reason": (
            "string",
            True,
            "Reason why you wish to modify the order. Since you can make several modifications to an order, filling this field with a clear explanation helps organize the order modifications history. The shopper can view this field value in [transactional emails](https://help.vtex.com/en/tutorial/order-transactional-email-templates--3g2S2kqBOoSGcCaqMYK2my) and [My Account](https://help.vtex.com/en/tutorial/how-my-account-works--2BQ3GiqhqGJTXsWVuio3Xh).",
        ),
        "replace_json": (
            "array",
            True,
            "Name of the change operation you are performing, which can be `replace`, `add` or `remove`. If you want, you can combine all change operations in a single request.",
        ),
        "settings_json": ("object", False, ""),
    },
    "retry_change": {
        "an": ("string", True, "Name of the VTEX account that created the order."),
        "changeOrderId": (
            "string",
            True,
            "Order ID of the order you wish to retry modification.",
        ),
        "changeRequestId": (
            "string",
            True,
            "Once you make an order modification, you generate a `requestId` code that identifies the modifications made to that order. This field should be filled with that code.\r\n\r\nThere are no limits to modifications you can perform using the same `changeRequestId`, and we recommend keeping all modifications of a given order grouped by the same `changeRequestId`, so you will have a unified modification history.",
        ),
        "reason": (
            "string",
            True,
            "Reason why you wish to modify order. Since you can make several modifications to an order, filling this field with a clear explanation helps organize the order modifications history. The shopper can view this field value in [transactional emails](https://help.vtex.com/en/tutorial/order-transactional-email-templates--3g2S2kqBOoSGcCaqMYK2my) and [My Account](https://help.vtex.com/en/tutorial/how-my-account-works--2BQ3GiqhqGJTXsWVuio3Xh).",
        ),
        "replace_json": (
            "array",
            False,
            "Array containing `replace` change information. Besides `replace`, you can `add` or `remove` items from an order.\r\n\r\n- `add`: the schema will correspond to the object `to` inside the `replace` array.\r\n\r\n- `remove`: the schema will correspond to the object `from` inside the `replace` array.\r\n\r\nYou will find request body examples of both cases in the endpoint description on the top of the page. The successful response `202 - Accepted` schema is the same for all three operations, whether they are used separately or combined in the same request.",
        ),
        "settings_json": ("object", False, ""),
    },
    "cancel_change": {
        "an": ("string", True, "Name of the VTEX account that created the order."),
        "changeOrderId": (
            "string",
            True,
            "Order ID of the order with the modifications you wish to cancel.",
        ),
        "changeRequestId": (
            "string",
            True,
            "Once you make an order modification, you generate a `requestId` code that identifies the modifications made to that order. This field should be filled with that code. After cancelling an order modification, the `changeRequestId` will no longer be valid.",
        ),
        "reason": (
            "string",
            True,
            "Reason why you wish to cancel the order modification. The customer will not view the value inserted in this field.",
        ),
    },
}


def _make_config(name, spec):
    fields = {}
    for key, (kind, required, description) in FIELDS[name].items():
        typ = {"integer": int, "number": float, "boolean": bool}.get(kind, str)
        extra = {"ui:widget": "textarea"} if key.endswith("_json") else {}
        fields[key] = (
            Optional[typ] if key == "deliveredDate" or not required else typ,
            Field(
                ... if required else None,
                title=key.removesuffix("_json").replace("_", " ").title(),
                description=description,
                json_schema_extra=extra,
            ),
        )
    return create_model(
        "VTEX" + "".join(x.title() for x in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=spec["label"],
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-display-name": spec["label"],
                    "x-category": "Orders",
                    "x-is-trigger": False,
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class VTEXOnOrderUpdatedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_order_updated"] = Field(
        "on_order_updated",
        title="On Order Updated",
        json_schema_extra={
            "const": "on_order_updated",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Order Updated",
        },
    )
    expression: str = Field(
        "true",
        title="Order Filter Expression",
        description="JSONata expression against the order. Default true receives every update. This replaces the dedicated app key's existing hook; use one workflow per app key.",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    registered_webhook_url: Optional[str] = Field(
        None, json_schema_extra={"ui:hidden": True}
    )


VTEXConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + (VTEXOnOrderUpdatedConfig,)],
    Discriminator("operation"),
]


class VTEXNodeConfig(NodeConfig[VTEXConfig, VTEXAppKeyCredential]):
    pass


class VTEXNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-vtex"
    connection_evidence = ConnectionEvidence(
        operation="list_orders",
        noun="orders",
        label_keys=("orderId", "clientName", "sequence"),
    )
    edit_examples = [
        "List VTEX orders ready for handling",
        "Cancel a VTEX order",
        "Send an invoice to VTEX",
        "Run when a VTEX order changes",
    ]

    @classmethod
    def get_config_model(cls):
        return VTEXNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = VTEXAppKeyCredential.model_validate(credential)
        url = f"https://{cred.account_name}.vtexcommercestable.com.br{path}"
        async with guarded_async_client(
            timeout=45, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=body,
                headers={
                    "X-VTEX-API-AppKey": cred.app_key,
                    "X-VTEX-API-AppToken": cred.app_token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        if response.is_error:
            # Keep the provider's rejection visible to the connection proof.
            raise ValueError(
                f"VTEX API error {response.status_code}: {response.text[:2000]}"
            )
        if response.is_redirect:
            raise ValueError("VTEX returned an unexpected redirect")
        return response.json() if response.content else {"ok": True}

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        secret = secrets.token_urlsafe(32)
        await cls._request(
            credential,
            "POST",
            "/api/orders/hook/config",
            body={
                "filter": {
                    "type": "FromOrders",
                    "expression": (config or {}).get("expression") or "true",
                    "disableSingleFire": True,
                },
                "hook": {"url": webhook_url, "headers": {"key": secret}},
            },
        )
        return {
            "external_webhook_id": "orders-hook",
            "signing_secret": secret,
            "registered_webhook_url": webhook_url,
        }

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not (config or {}).get("external_webhook_id"):
            return
        current = await cls._request(credential, "GET", "/api/orders/hook/config")
        hook = current.get("hook") or {}
        # An app key has one hook. Never delete a replacement installed elsewhere.
        if hook.get("url") == (config or {}).get("registered_webhook_url") and hook.get(
            "url"
        ):
            await cls._request(credential, "DELETE", "/api/orders/hook/config")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"expression": (config or {}).get("expression") or "true"}

    @classmethod
    def handle_webhook_handshake(cls, body, headers, config=None):
        # VTEX pings during the registration POST, before its secret is persisted.
        try:
            if json.loads(body) == {"hookConfig": "ping"}:
                return {"ok": True}
        except (ValueError, TypeError):
            pass
        return None

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        expected = (config or {}).get("signing_secret")
        actual = next((v for k, v in headers.items() if k.lower() == "key"), "")
        return bool(
            expected
            and actual
            and hmac.compare_digest(str(expected).encode(), str(actual).encode())
        )

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and bool(payload.get("OrderId"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # Transport headers can carry the hook credential; keep them out of outputs.
        event = {key: value for key, value in payload.items() if key != "_webhook"}
        return {"status": "success", "operation": "on_order_updated", "data": event}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") != "on_order_updated":
            return super().resolve_agent_event(output)
        event = output.get("data") or {}
        origin = event.get("Origin") or {}
        return {
            "text": f"VTEX order {event.get('OrderId')} changed to {event.get('State')} at {event.get('LastChange')} in account {origin.get('Account')} ({event.get('Domain')}). Use this order ID to retrieve the order and take the next action.",
            "conversation_key": None,
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(self.config, VTEXNodeConfig)
            or self.config.credentials is None
        ):
            raise ValueError("Connect a VTEX app key")
        config = self.config.config
        name = config.operation
        if name == "on_order_updated":
            payload = (self.node_data or {}).get("config", {}).get(
                "_triggerPayload"
            ) or inputs
            return self.resolve_trigger_payload(payload, config.model_dump())
        spec = OPERATIONS[name]
        values = config.model_dump()
        path = spec["path"]
        params = {}
        for key, location in spec["params"]:
            if values.get(key) is not None:
                if location == "path":
                    value = str(values[key])
                    if value in {".", ".."} or "/" in value or "\\" in value:
                        raise ValueError("Use a single resource identifier")
                    path = path.replace("{" + key + "}", quote(value, safe=""))
                else:
                    params[key] = values[key]
        body = {}
        for field, key, complex_field in spec["body"]:
            if field not in values or (
                values[field] is None and not FIELDS[name][field][1]
            ):
                continue
            value = values[field]
            if complex_field:
                try:
                    value = json.loads(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{field} must contain valid JSON") from exc
                kind = FIELDS[name][field][0]
                if not isinstance(value, list if kind == "array" else dict):
                    raise ValueError(f"{field} must contain a JSON {kind}")
            body[key] = value
        data = await self._request(
            self.config.credentials.model_dump(),
            spec["method"],
            path,
            params=params or None,
            body=body if spec["body"] else None,
        )
        return {"status": "success", "operation": name, "data": data}

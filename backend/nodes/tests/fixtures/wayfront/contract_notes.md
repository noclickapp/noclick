# Wayfront contract evidence

The pinned contract is the provider-owned [OpenAPI document](https://clients.wayfront.com/api.yaml), version `latest`, SHA-256 `082b8e5a40c99bb16fab18feb9df06ff42ef0781bd6bad8603d949e4b89e6d24`. The [official API documentation](https://wayfront.com/docs/api) loads this same document. NoClick does not modify it.

The conformance run checks all 25 operations. Twelve pass request validation; the remaining 13 encounter the six contradictions below. All response parsers execute successfully against schema-generated responses; there are no fixture errors or advisory parser failures. These are schema-level checks, not live account or write verification.

## UserPathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/UserPathIdentifier) declares `type: integer` and `example: 1`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `get_client`, `update_client`.

## OrderPathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/OrderPathIdentifier) declares `type: string` and `example: E4A269FC`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `get_order`, `update_order`, `list_order_tasks`, `create_order_task`, `list_order_messages`, `create_order_message`.

## TaskPathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/TaskPathIdentifier) declares `type: integer` and `example: 1`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `update_task`, `delete_task`.

## ServicePathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/ServicePathIdentifier) declares `type: integer` and `example: 1`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `get_service`.

## InvoicePathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/InvoicePathIdentifier) declares `type: string` and `example: E4A269FC`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `get_invoice`.

## SubscriptionPathIdentifier

[Provider schema](https://clients.wayfront.com/api.yaml#/components/schemas/SubscriptionPathIdentifier) declares `type: integer` and `example: 10`, then `allOf: [{$ref: '#/components/schemas/PaginationLinks'}]`. `PaginationLinks` is an object. Requiring a scalar and an object simultaneously makes every scalar identifier invalid. The node uses the documented scalar.

Affected operations: `get_subscription`.

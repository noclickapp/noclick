"""SamCart Public API v1. API-key authentication; one provider request per operation.

Lists return one page and the provider's pagination links. Offset is a resource
ID cursor, not a row count. Writes are never retried automatically.
Contract: https://developer.samcart.com/specs/openapi.yaml (1.0.0).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.samcart.com/v1"


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def date_filters(cls, value, info):
        if value is not None and info.field_name.endswith(("_min", "_max")):
            try:
                if len(value) == 10:
                    date.fromisoformat(value)
                elif datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Use an ISO 8601 date or timestamp with timezone") from None
        return value


class SamCartApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Samcart API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.samcart.com/#section/Authentication",
        "x-credential-instructions": "In SamCart, open Settings > API Keys and create a key. Your plan must include API access. Paste the key below.",
    })
    credential_type: Literal["samcart_api_key"] = Field("samcart_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        description="The API key from SamCart Settings > API Keys.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def safe_key(cls, value):
        value = value.strip()
        if not value or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a SamCart API key without whitespace")
        return value


class ListCustomersConfig(_Config):
    operation: Literal['list_customers'] = Field('list_customers', title='List Customers', description='Retrieve all customers', json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, title='Email', description='Filter customers by email address (case-insensitive, exact match). Accepts a single email or multiple comma-separated emails (maximum 25).')
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetCustomerConfig(_Config):
    operation: Literal['get_customer'] = Field('get_customer', title='Get Customer', description='Retrieve a customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title='Customer Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')


class ListProductsConfig(_Config):
    operation: Literal['list_products'] = Field('list_products', title='List Products', description='Retrieve all products', json_schema_extra={"ui:hidden": True})
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    status: Literal['live', 'test', 'archived'] | None = Field(None, title='Status', description='Filter product by status')
    product_category: Literal['physical', 'digital'] | None = Field(None, title='Product Category', description='Filter product by category')
    pricing_type: Literal['one_time', 'limited_subscription', 'recurring_subscription', 'pwyw_one_time', 'pwyw_recurring_subscription', 'pwyw_limited_subscription'] | None = Field(None, title='Pricing Type', description='Filter product by pricing type')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetProductConfig(_Config):
    operation: Literal['get_product'] = Field('get_product', title='Get Product', description='Retrieve a product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., ge=1, title='Product Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    status: Literal['live', 'test', 'archived'] | None = Field(None, title='Status', description='Filter product by status')
    product_category: Literal['physical', 'digital'] | None = Field(None, title='Product Category', description='Filter product by category')
    pricing_type: Literal['one_time', 'limited_subscription', 'recurring_subscription', 'pwyw_one_time', 'pwyw_recurring_subscription', 'pwyw_limited_subscription'] | None = Field(None, title='Pricing Type', description='Filter product by pricing type')


class ListOrdersConfig(_Config):
    operation: Literal['list_orders'] = Field('list_orders', title='List Orders', description='Retrieve all orders', json_schema_extra={"ui:hidden": True})
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetOrderConfig(_Config):
    operation: Literal['get_order'] = Field('get_order', title='Get Order', description='Retrieve an order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, title='Order Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListChargesConfig(_Config):
    operation: Literal['list_charges'] = Field('list_charges', title='List Charges', description='Retrieve all charges', json_schema_extra={"ui:hidden": True})
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetChargeConfig(_Config):
    operation: Literal['get_charge'] = Field('get_charge', title='Get Charge', description='Retrieve a charge', json_schema_extra={"ui:hidden": True})
    charge_id: int = Field(..., ge=1, title='Charge Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListSubscriptionsConfig(_Config):
    operation: Literal['list_subscriptions'] = Field('list_subscriptions', title='List Subscriptions', description='Retrieve all subscriptions', json_schema_extra={"ui:hidden": True})
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    rebilling_at_min: str | None = Field(None, title='Rebilling At Min', description='Filter by rebilling date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    rebilling_at_max: str | None = Field(None, title='Rebilling At Max', description='Filter by rebilling date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    canceled_at_min: str | None = Field(None, title='Canceled At Min', description='Filter by canceled date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    canceled_at_max: str | None = Field(None, title='Canceled At Max', description='Filter by canceled date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    status: Literal['active', 'canceled', 'delinquent', 'completed', 'paused', 'invalid_processor', 'sca_required', 'deleted'] | None = Field(None, title='Status', description='Filter subscriptions by status')
    type: Literal['limited_subscription', 'recurring_subscription'] | None = Field(None, title='Type', description='Filter subscriptions by type')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetSubscriptionConfig(_Config):
    operation: Literal['get_subscription'] = Field('get_subscription', title='Get Subscription', description='Retrieve a subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title='Subscription Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    rebilling_at_min: str | None = Field(None, title='Rebilling At Min', description='Filter by rebilling date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    rebilling_at_max: str | None = Field(None, title='Rebilling At Max', description='Filter by rebilling date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    canceled_at_min: str | None = Field(None, title='Canceled At Min', description='Filter by canceled date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    canceled_at_max: str | None = Field(None, title='Canceled At Max', description='Filter by canceled date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    status: Literal['active', 'canceled', 'delinquent', 'completed', 'paused', 'invalid_processor', 'sca_required', 'deleted'] | None = Field(None, title='Status', description='Filter subscriptions by status')
    type: Literal['limited_subscription', 'recurring_subscription'] | None = Field(None, title='Type', description='Filter subscriptions by type')


class ListFailedChargesConfig(_Config):
    operation: Literal['list_failed_charges'] = Field('list_failed_charges', title='List Failed Charges', description='Retrieve all failed charges', json_schema_extra={"ui:hidden": True})
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class GetFailedChargeConfig(_Config):
    operation: Literal['get_failed_charge'] = Field('get_failed_charge', title='Get Failed Charge', description='Retrieve a failed charge', json_schema_extra={"ui:hidden": True})
    failed_charge_id: int = Field(..., ge=1, title='Failed Charge Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListRefundsConfig(_Config):
    operation: Literal['list_refunds'] = Field('list_refunds', title='List Refunds', description='Get a paginated list of refunds for the marketplace. Custom sorting is not allowed, and results are sorted by Refund ID.', json_schema_extra={"ui:hidden": True})
    offset: int | None = Field(None, title='Offset', description='The offset value used to paginate through a list of entries. If the dir query parameter is prev then the offset will be the id of the first record of the data set otherwise the offset will be the id of the last record', ge=1)
    limit: int = Field(100, title='Limit', description='An optional limit for the number of entries on a page with a maximum value of 100. Default value is 100 if not provided.', ge=1, le=100)
    dir: Literal['next', 'prev'] | None = Field(None, title='Dir', description='The direction to paginate the next set of data. If dir is prev the page will return a data set before the offset otherwise the data set will be after the offset. Default value is next if not provided.')


class ListChargeRefundsConfig(_Config):
    operation: Literal['list_charge_refunds'] = Field('list_charge_refunds', title='List Charge Refunds', description='Retrieve all refunds on a charge', json_schema_extra={"ui:hidden": True})
    charge_id: int = Field(..., ge=1, title='Charge Id', description="Existing SamCart resource ID.")


class ListCustomerOrdersConfig(_Config):
    operation: Literal['list_customer_orders'] = Field('list_customer_orders', title='List Customer Orders', description='Retrieve all orders for a customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title='Customer Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListCustomerSubscriptionsConfig(_Config):
    operation: Literal['list_customer_subscriptions'] = Field('list_customer_subscriptions', title='List Customer Subscriptions', description='Retrieve all subscriptions for a customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title='Customer Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    rebilling_at_min: str | None = Field(None, title='Rebilling At Min', description='Filter by rebilling date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    rebilling_at_max: str | None = Field(None, title='Rebilling At Max', description='Filter by rebilling date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    canceled_at_min: str | None = Field(None, title='Canceled At Min', description='Filter by canceled date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    canceled_at_max: str | None = Field(None, title='Canceled At Max', description='Filter by canceled date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    status: Literal['active', 'canceled', 'delinquent', 'completed', 'paused', 'invalid_processor', 'sca_required', 'deleted'] | None = Field(None, title='Status', description='Filter subscriptions by status')
    type: Literal['limited_subscription', 'recurring_subscription'] | None = Field(None, title='Type', description='Filter subscriptions by type')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListCustomerChargesConfig(_Config):
    operation: Literal['list_customer_charges'] = Field('list_customer_charges', title='List Customer Charges', description='Retrieve all charges for a customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title='Customer Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class ListOrderChargesConfig(_Config):
    operation: Literal['list_order_charges'] = Field('list_order_charges', title='List Order Charges', description='Retrieve all charges on an order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, title='Order Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')


class GetOrderCustomerConfig(_Config):
    operation: Literal['get_order_customer'] = Field('get_order_customer', title='Get Order Customer', description='Retrieve customer on an order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, title='Order Id', description="Existing SamCart resource ID.")


class ListOrderSubscriptionsConfig(_Config):
    operation: Literal['list_order_subscriptions'] = Field('list_order_subscriptions', title='List Order Subscriptions', description='Retrieve all subscriptions on an order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, title='Order Id', description="Existing SamCart resource ID.")
    created_at_min: str | None = Field(None, title='Created At Min', description='Filter by created at date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    created_at_max: str | None = Field(None, title='Created At Max', description='Filter by created at date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    rebilling_at_min: str | None = Field(None, title='Rebilling At Min', description='Filter by rebilling date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    rebilling_at_max: str | None = Field(None, title='Rebilling At Max', description='Filter by rebilling date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    canceled_at_min: str | None = Field(None, title='Canceled At Min', description='Filter by canceled date/time at or after given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 00:00:00 UTC.')
    canceled_at_max: str | None = Field(None, title='Canceled At Max', description='Filter by canceled date/time at or before given value. Accepts ISO 8601/RFC 3339 format with timezone (e.g., 2025-01-16T14:30:00Z) or date-only (e.g., 2025-01-16). Date-only values use 23:59:59 UTC.')
    test_mode: bool | None = Field(None, title='Test Mode', description='Filter by test mode')
    status: Literal['active', 'canceled', 'delinquent', 'completed', 'paused', 'invalid_processor', 'sca_required', 'deleted'] | None = Field(None, title='Status', description='Filter subscriptions by status')
    type: Literal['limited_subscription', 'recurring_subscription'] | None = Field(None, title='Type', description='Filter subscriptions by type')


class UpdateOrderCustomFieldConfig(_Config):
    operation: Literal['update_order_custom_field'] = Field('update_order_custom_field', title='Update Order Custom Field', description='Update order by ID', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1, title='Order Id', description="Existing SamCart resource ID.")
    custom_field_slug: str = Field(..., title='Custom Field Slug', description='Set this value to the slug of custom field', min_length=1)
    custom_field_data: str = Field(..., title='Custom Field Data', description='Set this value to the new data of the custom field', min_length=1)


class RefundChargeConfig(_Config):
    operation: Literal['refund_charge'] = Field('refund_charge', title='Refund Charge', description='Refund an individual charge. Omit amount for full refund, or specify amount in cents for partial refund.', json_schema_extra={"ui:hidden": True})
    charge_id: int = Field(..., ge=1, title='Charge Id', description="Existing SamCart resource ID.")
    amount: int | None = Field(None, title='Amount', description='Refund amount in cents. Omit for full refund.', ge=1)


class CancelSubscriptionConfig(_Config):
    operation: Literal['cancel_subscription'] = Field('cancel_subscription', title='Cancel Subscription', description='Cancel an individual subscription. Only subscriptions with an active, delinquent, or paused status may be canceled.', json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title='Subscription Id', description="Existing SamCart resource ID.")
    silent_cancel: bool | None = Field(False, title='Silent Cancel', description='Set this value to true so the Customer is not notified of the Subscription cancelation')


class ScheduleCancelSubscriptionConfig(_Config):
    operation: Literal['schedule_cancel_subscription'] = Field('schedule_cancel_subscription', title='Schedule Cancel Subscription', description='Schedule an individual subscription to be canceled. Only subscriptions with an active status may be scheduled.', json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title='Subscription Id', description="Existing SamCart resource ID.")
    cancel_when: Literal["end", "custom"] = Field(..., title='Cancel When', description='Either custom or end. When selecting end, the Subscription will be canceled at the end of the current billing period. When selecting custom, the Subscription will be canceled on the date specified with the schedule_date parameter', min_length=1)
    schedule_date: str | None = Field(None, title='Schedule Date', description='The date at which the Subscription should cancel. If cancel_when is set to custom, this parameter is required.')

    @model_validator(mode="after")
    def cancellation_date(self):
        if self.cancel_when == "custom" and not self.schedule_date:
            raise ValueError("Schedule Date is required for a custom cancellation")
        if self.schedule_date:
            date.fromisoformat(self.schedule_date)
        return self


class UpdateSubscriptionConfig(_Config):
    operation: Literal['update_subscription'] = Field('update_subscription', title='Update Subscription', description='Update a subscription. Currently supports updating the next rebilling date. Only subscriptions with an active or delinquent status may be updated.', json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title='Subscription Id', description="Existing SamCart resource ID.")
    next_rebilling_date: str = Field(..., title='Next Rebilling Date', description='The new next rebilling date for the subscription in ISO 8601 format. Must be a future date. For Stripe-managed subscriptions, must be within 2 years.', min_length=1)

    @field_validator("next_rebilling_date")
    @classmethod
    def timestamp(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Next Rebilling Date needs a timezone")
        return value


Operation = Annotated[Union[ListCustomersConfig, GetCustomerConfig, ListProductsConfig, GetProductConfig, ListOrdersConfig, GetOrderConfig, ListChargesConfig, GetChargeConfig, ListSubscriptionsConfig, GetSubscriptionConfig, ListFailedChargesConfig, GetFailedChargeConfig, ListRefundsConfig, ListChargeRefundsConfig, ListCustomerOrdersConfig, ListCustomerSubscriptionsConfig, ListCustomerChargesConfig, ListOrderChargesConfig, GetOrderCustomerConfig, ListOrderSubscriptionsConfig, UpdateOrderCustomFieldConfig, RefundChargeConfig, CancelSubscriptionConfig, ScheduleCancelSubscriptionConfig, UpdateSubscriptionConfig], Field(discriminator="operation")]


class SamCartNodeConfig(NodeConfig[Operation, SamCartApiKeyCredential]):
    pass


ROUTES = {'list_customers': ('GET',
                    '/customers',
                    None,
                    ['email', 'created_at_min', 'created_at_max', 'offset', 'limit', 'dir'],
                    []),
 'get_customer': ('GET', '/customers/{id}', 'customer_id', ['created_at_min', 'created_at_max'], []),
 'list_products': ('GET',
                   '/products',
                   None,
                   ['created_at_min',
                    'created_at_max',
                    'status',
                    'product_category',
                    'pricing_type',
                    'offset',
                    'limit',
                    'dir'],
                   []),
 'get_product': ('GET',
                 '/products/{id}',
                 'product_id',
                 ['created_at_min', 'created_at_max', 'status', 'product_category', 'pricing_type'],
                 []),
 'list_orders': ('GET',
                 '/orders',
                 None,
                 ['created_at_min', 'created_at_max', 'test_mode', 'offset', 'limit', 'dir'],
                 []),
 'get_order': ('GET', '/orders/{id}', 'order_id', ['created_at_min', 'created_at_max', 'test_mode'], []),
 'list_charges': ('GET',
                  '/charges',
                  None,
                  ['created_at_min', 'created_at_max', 'test_mode', 'offset', 'limit', 'dir'],
                  []),
 'get_charge': ('GET',
                '/charges/{id}',
                'charge_id',
                ['created_at_min', 'created_at_max', 'test_mode'],
                []),
 'list_subscriptions': ('GET',
                        '/subscriptions',
                        None,
                        ['created_at_min',
                         'created_at_max',
                         'rebilling_at_min',
                         'rebilling_at_max',
                         'canceled_at_min',
                         'canceled_at_max',
                         'test_mode',
                         'status',
                         'type',
                         'offset',
                         'limit',
                         'dir'],
                        []),
 'get_subscription': ('GET',
                      '/subscriptions/{id}',
                      'subscription_id',
                      ['created_at_min',
                       'created_at_max',
                       'rebilling_at_min',
                       'rebilling_at_max',
                       'canceled_at_min',
                       'canceled_at_max',
                       'test_mode',
                       'status',
                       'type'],
                      []),
 'list_failed_charges': ('GET',
                         '/failed-charges',
                         None,
                         ['created_at_min', 'created_at_max', 'test_mode', 'offset', 'limit', 'dir'],
                         []),
 'get_failed_charge': ('GET',
                       '/failed-charges/{id}',
                       'failed_charge_id',
                       ['created_at_min', 'created_at_max', 'test_mode'],
                       []),
 'list_refunds': ('GET', '/refunds', None, ['offset', 'limit', 'dir'], []),
 'list_charge_refunds': ('GET', '/charges/{id}/refunds', 'charge_id', [], []),
 'list_customer_orders': ('GET',
                          '/customers/{id}/orders',
                          'customer_id',
                          ['created_at_min', 'created_at_max', 'test_mode'],
                          []),
 'list_customer_subscriptions': ('GET',
                                 '/customers/{id}/subscriptions',
                                 'customer_id',
                                 ['created_at_min',
                                  'created_at_max',
                                  'rebilling_at_min',
                                  'rebilling_at_max',
                                  'canceled_at_min',
                                  'canceled_at_max',
                                  'status',
                                  'type',
                                  'test_mode'],
                                 []),
 'list_customer_charges': ('GET',
                           '/customers/{id}/charges',
                           'customer_id',
                           ['created_at_min', 'created_at_max', 'test_mode'],
                           []),
 'list_order_charges': ('GET',
                        '/orders/{id}/charges',
                        'order_id',
                        ['created_at_min', 'created_at_max', 'test_mode'],
                        []),
 'get_order_customer': ('GET', '/orders/{id}/customer', 'order_id', [], []),
 'list_order_subscriptions': ('GET',
                              '/orders/{id}/subscriptions',
                              'order_id',
                              ['created_at_min',
                               'created_at_max',
                               'rebilling_at_min',
                               'rebilling_at_max',
                               'canceled_at_min',
                               'canceled_at_max',
                               'test_mode',
                               'status',
                               'type'],
                              []),
 'update_order_custom_field': ('PUT',
                               '/orders/{id}',
                               'order_id',
                               [],
                               ['custom_field_slug', 'custom_field_data']),
 'refund_charge': ('POST', '/refunds/charges/{id}/', 'charge_id', [], ['amount']),
 'cancel_subscription': ('POST', '/subscriptions/{id}/cancel', 'subscription_id', [], ['silent_cancel']),
 'schedule_cancel_subscription': ('POST',
                                  '/subscriptions/{id}/scheduleCancel',
                                  'subscription_id',
                                  [],
                                  ['cancel_when', 'schedule_date']),
 'update_subscription': ('POST',
                         '/subscriptions/{id}/update',
                         'subscription_id',
                         [],
                         ['next_rebilling_date'])}


class SamCartNode(WorkflowNode):
    integration_type = "automation-samcart"
    credential_provider_labels = {"samcart": "SamCart"}
    connection_evidence = ConnectionEvidence(noun="products", operation="list_products", label_keys=("product_name", "internal_product_name", "id"))
    edit_examples = ["Find orders created this week", "Look up a customer by email", "Cancel this subscription at the end of the billing period"]

    @classmethod
    def get_config_model(cls):
        return SamCartNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return TypeAdapter(SamCartNodeConfig).validate_python(runtime_config_view(config_data, SamCartNodeConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SamCart API key")
        config = self.config.config
        method, route, id_field, query_fields, body_fields = ROUTES[config.operation]
        if id_field:
            route = route.replace("{id}", str(getattr(config, id_field)))
        values = config.model_dump(exclude_none=True)
        params = {key: (str(values[key]).lower() if isinstance(values[key], bool) else values[key])
                  for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        prefix = {"operation": config.operation}
        key = self.config.credentials.api_key
        try:
            async with asyncio.timeout(30):
                async with guarded_async_client(timeout=httpx.Timeout(25), follow_redirects=False, trust_env=False) as client:
                    async with client.stream(method, BASE_URL + route, params=params, json=body,
                                             headers={"sc-api": key, "Accept": "application/json"}) as response:
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 8 * 1024 * 1024:
                                raise ValueError("SamCart response exceeds 8 MiB")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        if response.status_code != 200:
                            message = "SamCart request failed (HTTP " + str(response.status_code) + ")"
                            try:
                                error_body = json.loads(raw)
                                detail = error_body.get("message", error_body.get("error")) if isinstance(error_body, dict) else None
                                if isinstance(detail, str):
                                    message = detail[:2000].replace(key, "[redacted]")
                            except (ValueError, TypeError):
                                pass
                            return {**prefix, "status": "error", "http_status": response.status_code,
                                    "error": message, "retry_after": response.headers.get("Retry-After"),
                                    "write_outcome_unknown": method != "GET" and response.status_code >= 500}
                        payload = json.loads(raw)
            if not isinstance(payload, (dict, list)):
                raise ValueError("SamCart returned an invalid JSON shape")
            if isinstance(payload, dict) and (payload.get("success") in (False, "false") or (payload.get("error") and "id" not in payload and "data" not in payload)):
                return {**prefix, "status": "error", "error": "SamCart returned an error response"}
            # Keep the published JSON shape intact, including all pagination links.
            # Links are returned as data; never follow a response-provided origin.
            output = {**prefix, "status": "success", "data": payload}
            if config.operation.startswith("list_"):
                rows = payload.get("data") if isinstance(payload, dict) else payload
                if not isinstance(rows, (list, dict)):
                    raise ValueError("SamCart list response lacks data")
                output["items"] = rows if isinstance(rows, list) else [rows]
                if isinstance(payload, dict) and "pagination" in payload:
                    output["pagination"] = payload["pagination"]
            else:
                output["item"] = payload
            return output
        except (httpx.HTTPError, TimeoutError, OSError):
            return {**prefix, "status": "error", "error": "SamCart request did not complete; inspect the account before retrying a write",
                    "write_outcome_unknown": method != "GET"}
        except (ValueError, TypeError):
            return {**prefix, "status": "error", "error": "SamCart returned an invalid or incomplete response",
                    "write_outcome_unknown": method != "GET"}

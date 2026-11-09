"""Tentary account, commerce, course and access automation over the published v1 API.

Each operation performs one documented request. List responses retain provider
cursors; callers pass the same filters when requesting the following page.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.tentary.com"
CREDENTIAL_TYPE = "tentary_api_key"


class TentaryAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tentary API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.tentary.com/ai",
            "x-credential-instructions": "In Tentary, open AI & API and create a personal API key. Paste the key alone, without Bearer. Read operations need read permission; writes need a key with write permission.",
        })
    credential_type: Literal["tentary_api_key"] = Field("tentary_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("Paste the API key alone, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_values(self):
        for name in ("from_date", "to_date", "starts_on", "ends_on", "access_starts_on", "available_from", "available_until"):
            value = getattr(self, name, None)
            if value is not None:
                date.fromisoformat(value)
        for start, end in (("from_date", "to_date"), ("starts_on", "ends_on"), ("available_from", "available_until")):
            if getattr(self, start, None) and getattr(self, end, None) and getattr(self, start) > getattr(self, end):
                raise ValueError("The start date must not follow the end date")
        if self.operation == "create_coupon":
            if (self.percent is not None) == (self.amount is not None):
                raise ValueError("Give exactly one of percent or amount")
        if self.operation == "update_coupon" and self.percent is not None and self.amount is not None:
            raise ValueError("Give percent or amount, not both")
        if getattr(self, "amount", None) is not None and Decimal(self.amount) <= 0:
            raise ValueError("The discount amount must be positive")
        return self


class TentaryGetAccountOverviewConfig(_Input):
    """Account overview."""
    operation: Literal['get_account_overview'] = Field('get_account_overview', json_schema_extra={"ui:hidden": True})

class TentaryListProductsConfig(_Input):
    """Products."""
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    type: Literal['download', 'link', 'newsletter', 'booking', 'course', 'bundle', 'external'] | None = Field(None, description='Only products of this type.')
    status: Literal['live', 'draft', 'archived'] | None = Field(None, description='Only products with this status.')
    query: str | None = Field(None, description='Part of the product name.', max_length=100)
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)

class TentaryGetProductConfig(_Input):
    """Product details."""
    operation: Literal['get_product'] = Field('get_product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='The id from list_products.', ge=1)

class TentaryCreateProductConfig(_Input):
    """Create product."""
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    type: Literal['download', 'link', 'newsletter', 'external', 'course', 'bundle'] = Field(..., description='The product type (see above). update_product cannot change it.')
    name: str = Field(..., description='Product name.', min_length=1, max_length=255)
    price: str | None = Field(None, description='Amount in the account currency, like 49 or 19.99. 0 = free. Paid prices start at 1.00. For external: the price shown on the card.', pattern='^[0-9]{1,9}(\\.[0-9]{1,2})?$')
    billing: Literal['one_time', 'subscription'] | None = Field(None, description='Default one_time.')
    billing_interval_months: int | None = Field(None, description='subscription: months between payments, default 1.', ge=1, le=12)
    description_html: str | None = Field(None, description='Sales page text as HTML (p, h1-h4, strong, em, ul, ol, li, a, img, blockquote; a with class "button" is a button). The page always has its own buy button. A buy button in the text links to the url of the product + "/checkout" (create_product and get_product give url); there is no #buy anchor.', max_length=200000)
    checkout_description_html: str | None = Field(None, description='Extra text only on the checkout page, HTML. Not for external.', max_length=20000)
    link_url: str | None = Field(None, description='link: the link that buyers get.', max_length=2048)
    access_text_html: str | None = Field(None, description='link: text that buyers see after purchase. bundle: extra details for the buyers. HTML. Takes the placeholders of text blocks.', max_length=65535)
    external_url: str | None = Field(None, description='external: where buyers buy it.', max_length=2048)
    course_id: int | None = Field(None, description='course: the course that buyers get (from list_courses or create_course). Needed to go live.', ge=1)
    marketing_emails: bool | None = Field(None, description='Subscribe buyers to the marketing e-mails (always on for newsletter).')
    ebook: bool | None = Field(None, description='Treat as e-publication (e-book) for VAT.')
    pdf_stamp: bool | None = Field(None, description="Stamp PDFs with the buyer's e-mail address.")
    login_protection: bool | None = Field(None, description='Buyers must log in to open the product.')
    show_in_search: bool | None = Field(None, description='Show the sales page in Google.')
    hide_in_shop: bool | None = Field(None, description='Do not show the product on the shop page.')
    coupon_field: bool | None = Field(None, description='Show the coupon field at checkout (default true).')
    stock_limit: int | None = Field(None, description='How many can be sold. null or 0 = no limit.', ge=0)
    buy_button_text: str | None = Field(None, description='Text of the buy button. Empty = default.', max_length=30)
    url_slug: str | None = Field(None, description='Own URL part: shop URL/p/<url_slug>. Lowercase letters, digits and hyphens.', max_length=120)
    access_days: int | None = Field(None, description='Access ends this many days after purchase (3 to 9999). null or 0 = no end.', ge=0, le=9999)
    access_starts_on: str | None = Field(None, description='Buyers get access from this day at the earliest (for example the start of a program). Before it they wait. null = at once. Not for newsletter and external.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    withdrawal_days: Literal[0, 14, 30] | None = Field(None, description='Withdrawal period shown at checkout.')
    available_from: str | None = Field(None, description='First day of sale.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    available_until: str | None = Field(None, description='Last day of sale.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')

class TentaryUpdateProductConfig(_Input):
    """Update product."""
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., description='The id from list_products.', ge=1)
    status: Literal['draft', 'live'] | None = Field(None, description='live = buyers can see and buy it. draft = hidden.')
    name: str | None = Field(None, description='Product name.', min_length=1, max_length=255)
    price: str | None = Field(None, description='Amount in the account currency, like 49 or 19.99. 0 = free. Paid prices start at 1.00. For external: the price shown on the card.', pattern='^[0-9]{1,9}(\\.[0-9]{1,2})?$')
    billing: Literal['one_time', 'subscription'] | None = Field(None, description='Default one_time.')
    billing_interval_months: int | None = Field(None, description='subscription: months between payments, default 1.', ge=1, le=12)
    description_html: str | None = Field(None, description='Sales page text as HTML (p, h1-h4, strong, em, ul, ol, li, a, img, blockquote; a with class "button" is a button). The page always has its own buy button. A buy button in the text links to the url of the product + "/checkout" (create_product and get_product give url); there is no #buy anchor.', max_length=200000)
    checkout_description_html: str | None = Field(None, description='Extra text only on the checkout page, HTML. Not for external.', max_length=20000)
    link_url: str | None = Field(None, description='link: the link that buyers get.', max_length=2048)
    access_text_html: str | None = Field(None, description='link: text that buyers see after purchase. bundle: extra details for the buyers. HTML. Takes the placeholders of text blocks.', max_length=65535)
    external_url: str | None = Field(None, description='external: where buyers buy it.', max_length=2048)
    course_id: int | None = Field(None, description='course: the course that buyers get (from list_courses or create_course). Needed to go live.', ge=1)
    marketing_emails: bool | None = Field(None, description='Subscribe buyers to the marketing e-mails (always on for newsletter).')
    ebook: bool | None = Field(None, description='Treat as e-publication (e-book) for VAT.')
    pdf_stamp: bool | None = Field(None, description="Stamp PDFs with the buyer's e-mail address.")
    login_protection: bool | None = Field(None, description='Buyers must log in to open the product.')
    show_in_search: bool | None = Field(None, description='Show the sales page in Google.')
    hide_in_shop: bool | None = Field(None, description='Do not show the product on the shop page.')
    coupon_field: bool | None = Field(None, description='Show the coupon field at checkout (default true).')
    stock_limit: int | None = Field(None, description='How many can be sold. null or 0 = no limit.', ge=0)
    buy_button_text: str | None = Field(None, description='Text of the buy button. Empty = default.', max_length=30)
    url_slug: str | None = Field(None, description='Own URL part: shop URL/p/<url_slug>. Lowercase letters, digits and hyphens.', max_length=120)
    access_days: int | None = Field(None, description='Access ends this many days after purchase (3 to 9999). null or 0 = no end.', ge=0, le=9999)
    access_starts_on: str | None = Field(None, description='Buyers get access from this day at the earliest (for example the start of a program). Before it they wait. null = at once. Not for newsletter and external.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    withdrawal_days: Literal[0, 14, 30] | None = Field(None, description='Withdrawal period shown at checkout.')
    available_from: str | None = Field(None, description='First day of sale.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    available_until: str | None = Field(None, description='Last day of sale.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')

class TentaryListCoursesConfig(_Input):
    """Courses."""
    operation: Literal['list_courses'] = Field('list_courses', json_schema_extra={"ui:hidden": True})

class TentaryGetCourseOutlineConfig(_Input):
    """Course outline."""
    operation: Literal['get_course_outline'] = Field('get_course_outline', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., description='The id from list_courses.', ge=1)

class TentaryCreateCourseConfig(_Input):
    """Create course."""
    operation: Literal['create_course'] = Field('create_course', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Course name.', min_length=1, max_length=255)
    description_html: str | None = Field(None, description='Introduction as HTML. Shows only with layout cards, above the modules.', max_length=65535)
    cover_image_url: str | None = Field(None, description='Course banner: the image_url from finish_image, or a public image URL that Tentary copies.', max_length=2048)
    layout: Literal['classic', 'fullscreen', 'fokus', 'cards'] | None = Field(None, description='How buyers see the course. classic (default): sidebar and content. fullscreen: edge to edge. fokus: reading without distraction. cards: a start screen with module cards.')
    tracks_progress: bool | None = Field(None, description='Buyers can mark lessons as done (default true). Needed for release type after_lesson.')

class TentaryUpdateCourseConfig(_Input):
    """Update course."""
    operation: Literal['update_course'] = Field('update_course', json_schema_extra={"ui:hidden": True})
    course_id: int = Field(..., description='The id from list_courses.', ge=1)
    name: str | None = Field(None, description='Course name.', min_length=1, max_length=255)
    description_html: str | None = Field(None, description='Introduction as HTML. Shows only with layout cards, above the modules.', max_length=65535)
    cover_image_url: str | None = Field(None, description='Course banner: the image_url from finish_image, or a public image URL that Tentary copies.', max_length=2048)
    layout: Literal['classic', 'fullscreen', 'fokus', 'cards'] | None = Field(None, description='How buyers see the course. classic (default): sidebar and content. fullscreen: edge to edge. fokus: reading without distraction. cards: a start screen with module cards.')
    tracks_progress: bool | None = Field(None, description='Buyers can mark lessons as done (default true). Needed for release type after_lesson.')

class TentaryListOrdersConfig(_Input):
    """Orders."""
    operation: Literal['list_orders'] = Field('list_orders', json_schema_extra={"ui:hidden": True})
    status: Literal['paid', 'refunded', 'pending', 'failed'] | None = Field(None, description='paid = paid and not refunded. refunded = paid with a full or partial refund (the rows show status paid). pending = payment in progress or an open bank transfer.')
    billing: Literal['one_time', 'subscription', 'installments'] | None = Field(None, description='Only orders with this billing.')
    product_id: int | None = Field(None, description='Only orders of this product (id from list_products).', ge=1)
    customer_id: int | None = Field(None, description='Only orders of this customer (id from search_customers).', ge=1)
    from_date: str | None = Field(None, description='Only orders created on or after this day (UTC), like 2026-01-31.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    to_date: str | None = Field(None, description='Only orders created on or before this day (UTC), like 2026-01-31.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    search: str | None = Field(None, description="Part of the buyer's e-mail address, or the order number.", max_length=100)
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)

class TentaryGetOrderConfig(_Input):
    """Order details."""
    operation: Literal['get_order'] = Field('get_order', json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., description='The id from list_orders (not the order number).', ge=1)

class TentarySearchCustomersConfig(_Input):
    """Customers."""
    operation: Literal['search_customers'] = Field('search_customers', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Part of the name or e-mail address. Leave out for all customers.', max_length=100)
    paid_only: bool | None = Field(None, description='Only customers with at least one payment that was not refunded in full (order, subscription or installment payment, paid payment reminder).')
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)

class TentaryGetCustomerConfig(_Input):
    """Customer details."""
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., description='The id from search_customers or from an order.', ge=1)

class TentaryListCouponsConfig(_Input):
    """Coupons."""
    operation: Literal['list_coupons'] = Field('list_coupons', json_schema_extra={"ui:hidden": True})
    status: Literal['active', 'archived'] | None = Field(None, description='active (default) or archived.')
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)

class TentaryCreateCouponConfig(_Input):
    """Create coupon."""
    operation: Literal['create_coupon'] = Field('create_coupon', json_schema_extra={"ui:hidden": True})
    code: str = Field(..., description='The code buyers type, like SUMMER20. Unique in the shop (upper and lower case count as the same).', min_length=1, max_length=255)
    percent: int | None = Field(None, description='Discount in percent. Give percent or amount.', ge=1, le=100)
    amount: str | None = Field(None, description='Fixed discount. Amount in the account currency, like 49 or 19.99.', pattern='^[0-9]{1,9}(\\.[0-9]{1,2})?$')
    max_uses: int | None = Field(None, description='How often the code can be used in total. 0 = no limit. On create, left out = no limit. On update, left out = no change, null removes the limit.', ge=0)
    starts_on: str | None = Field(None, description='First day the code works, like 2026-11-27. On create, left out = at once. On update, left out = no change, null removes the date.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    ends_on: str | None = Field(None, description='The code stops at the start of this day (00:00). On create, left out = no end. On update, left out = no change, null removes the date.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    product_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, description='Only these products (ids from list_products). null = all products. On create, left out = all products. On update, left out = no change. [] = no product (the code works nowhere).', max_length=200)

class TentaryUpdateCouponConfig(_Input):
    """Update coupon."""
    operation: Literal['update_coupon'] = Field('update_coupon', json_schema_extra={"ui:hidden": True})
    coupon_id: int = Field(..., description='The id from list_coupons.', ge=1)
    status: Literal['active', 'archived'] | None = Field(None, description='archived = switched off. active = on again.')
    code: str | None = Field(None, description='The code buyers type, like SUMMER20. Unique in the shop (upper and lower case count as the same).', min_length=1, max_length=255)
    percent: int | None = Field(None, description='Discount in percent. Give percent or amount.', ge=1, le=100)
    amount: str | None = Field(None, description='Fixed discount. Amount in the account currency, like 49 or 19.99.', pattern='^[0-9]{1,9}(\\.[0-9]{1,2})?$')
    max_uses: int | None = Field(None, description='How often the code can be used in total. 0 = no limit. On create, left out = no limit. On update, left out = no change, null removes the limit.', ge=0)
    starts_on: str | None = Field(None, description='First day the code works, like 2026-11-27. On create, left out = at once. On update, left out = no change, null removes the date.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    ends_on: str | None = Field(None, description='The code stops at the start of this day (00:00). On create, left out = no end. On update, left out = no change, null removes the date.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    product_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, description='Only these products (ids from list_products). null = all products. On create, left out = all products. On update, left out = no change. [] = no product (the code works nowhere).', max_length=200)

class TentaryGrantAccessConfig(_Input):
    """Grant access."""
    operation: Literal['grant_access'] = Field('grant_access', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., description="The customer's e-mail address.", min_length=3, max_length=255)
    product_id: int = Field(..., description='The id from list_products.', ge=1)
    variant_id: int | None = Field(None, description='Needed for a product with variants (get_product shows them).', ge=1)
    first_name: str | None = Field(None, description='For a new customer.', max_length=100)
    last_name: str | None = Field(None, description='For a new customer.', max_length=100)
    reason: Literal['manual', 'complimentary', 'purchased_elsewhere'] | None = Field(None, description='Shown in the app. Default manual.')
    send_email: bool | None = Field(None, description='Send the access e-mail (default true).')

class TentaryRevokeAccessConfig(_Input):
    """Revoke access."""
    operation: Literal['revoke_access'] = Field('revoke_access', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., description="The customer's e-mail address.", min_length=3, max_length=255)
    product_id: int = Field(..., description='The id from list_products.', ge=1)
    variant_id: int | None = Field(None, description='Only the grant of this variant. Leave out for all variants of the product.', ge=0)

class TentaryListEmailCampaignsConfig(_Input):
    """E-mail campaigns."""
    operation: Literal['list_email_campaigns'] = Field('list_email_campaigns', json_schema_extra={"ui:hidden": True})
    status: Literal['draft', 'scheduled', 'sending', 'sent'] | None = Field(None, description='Only campaigns with this status.')
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)

class TentaryGetEmailCampaignConfig(_Input):
    """E-mail campaign."""
    operation: Literal['get_email_campaign'] = Field('get_email_campaign', json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., description='The id from list_email_campaigns.', ge=1)

class TentaryGetSubscriptionSummaryConfig(_Input):
    """Subscriptions."""
    operation: Literal['get_subscription_summary'] = Field('get_subscription_summary', json_schema_extra={"ui:hidden": True})
    from_date: str | None = Field(None, description='First day (UTC) for new and ended subscriptions, like 2026-01-01.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    to_date: str | None = Field(None, description='Last day (UTC), like 2026-12-31. Default today. 731 days at most.', pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    product_id: int | None = Field(None, description='Only this product (id from list_products).', ge=1)

class TentaryListEmailAutomationsConfig(_Input):
    """E-mail automations."""
    operation: Literal['list_email_automations'] = Field('list_email_automations', json_schema_extra={"ui:hidden": True})
    status: Literal['active', 'inactive'] | None = Field(None, description='Only automations with this status.')
    cursor: str | None = Field(None, description='next_cursor of the previous page. Send the same filters and limit again: the cursor does not keep them. Leave out for the first page.')
    limit: int | None = Field(None, description='Items per page, default 25.', ge=1, le=50)


TentaryOperation = Annotated[Union[
    TentaryGetAccountOverviewConfig,
    TentaryListProductsConfig,
    TentaryGetProductConfig,
    TentaryCreateProductConfig,
    TentaryUpdateProductConfig,
    TentaryListCoursesConfig,
    TentaryGetCourseOutlineConfig,
    TentaryCreateCourseConfig,
    TentaryUpdateCourseConfig,
    TentaryListOrdersConfig,
    TentaryGetOrderConfig,
    TentarySearchCustomersConfig,
    TentaryGetCustomerConfig,
    TentaryListCouponsConfig,
    TentaryCreateCouponConfig,
    TentaryUpdateCouponConfig,
    TentaryGrantAccessConfig,
    TentaryRevokeAccessConfig,
    TentaryListEmailCampaignsConfig,
    TentaryGetEmailCampaignConfig,
    TentaryGetSubscriptionSummaryConfig,
    TentaryListEmailAutomationsConfig
], Field(discriminator="operation")]


class TentaryConfig(NodeConfig[TentaryOperation, TentaryAPIKeyCredential]):
    pass


OPERATIONS = {'get_account_overview': {'method': 'GET',
                          'path': '/v1/account',
                          'path_fields': [],
                          'query_fields': [],
                          'body_fields': [],
                          'nullable_fields': []},
 'list_products': {'method': 'GET',
                   'path': '/v1/products',
                   'path_fields': [],
                   'query_fields': [('type', 'type'),
                                    ('status', 'status'),
                                    ('query', 'query'),
                                    ('cursor', 'cursor'),
                                    ('limit', 'limit')],
                   'body_fields': [],
                   'nullable_fields': []},
 'get_product': {'method': 'GET',
                 'path': '/v1/products/{product_id}',
                 'path_fields': [('product_id', 'product_id')],
                 'query_fields': [],
                 'body_fields': [],
                 'nullable_fields': []},
 'create_product': {'method': 'POST',
                    'path': '/v1/products',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': ['type',
                                    'name',
                                    'price',
                                    'billing',
                                    'billing_interval_months',
                                    'description_html',
                                    'checkout_description_html',
                                    'link_url',
                                    'access_text_html',
                                    'external_url',
                                    'course_id',
                                    'marketing_emails',
                                    'ebook',
                                    'pdf_stamp',
                                    'login_protection',
                                    'show_in_search',
                                    'hide_in_shop',
                                    'coupon_field',
                                    'stock_limit',
                                    'buy_button_text',
                                    'url_slug',
                                    'access_days',
                                    'access_starts_on',
                                    'withdrawal_days',
                                    'available_from',
                                    'available_until'],
                    'nullable_fields': []},
 'update_product': {'method': 'PATCH',
                    'path': '/v1/products/{product_id}',
                    'path_fields': [('product_id', 'product_id')],
                    'query_fields': [],
                    'body_fields': ['status',
                                    'name',
                                    'price',
                                    'billing',
                                    'billing_interval_months',
                                    'description_html',
                                    'checkout_description_html',
                                    'link_url',
                                    'access_text_html',
                                    'external_url',
                                    'course_id',
                                    'marketing_emails',
                                    'ebook',
                                    'pdf_stamp',
                                    'login_protection',
                                    'show_in_search',
                                    'hide_in_shop',
                                    'coupon_field',
                                    'stock_limit',
                                    'buy_button_text',
                                    'url_slug',
                                    'access_days',
                                    'access_starts_on',
                                    'withdrawal_days',
                                    'available_from',
                                    'available_until'],
                    'nullable_fields': ['price',
                                        'billing_interval_months',
                                        'link_url',
                                        'access_text_html',
                                        'external_url',
                                        'stock_limit',
                                        'url_slug',
                                        'access_days',
                                        'access_starts_on',
                                        'available_from',
                                        'available_until']},
 'list_courses': {'method': 'GET',
                  'path': '/v1/courses',
                  'path_fields': [],
                  'query_fields': [],
                  'body_fields': [],
                  'nullable_fields': []},
 'get_course_outline': {'method': 'GET',
                        'path': '/v1/courses/{course_id}',
                        'path_fields': [('course_id', 'course_id')],
                        'query_fields': [],
                        'body_fields': [],
                        'nullable_fields': []},
 'create_course': {'method': 'POST',
                   'path': '/v1/courses',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': ['name',
                                   'description_html',
                                   'cover_image_url',
                                   'layout',
                                   'tracks_progress'],
                   'nullable_fields': ['cover_image_url']},
 'update_course': {'method': 'PATCH',
                   'path': '/v1/courses/{course_id}',
                   'path_fields': [('course_id', 'course_id')],
                   'query_fields': [],
                   'body_fields': ['name',
                                   'description_html',
                                   'cover_image_url',
                                   'layout',
                                   'tracks_progress'],
                   'nullable_fields': ['cover_image_url']},
 'list_orders': {'method': 'GET',
                 'path': '/v1/orders',
                 'path_fields': [],
                 'query_fields': [('status', 'status'),
                                  ('billing', 'billing'),
                                  ('product_id', 'product_id'),
                                  ('customer_id', 'customer_id'),
                                  ('from_date', 'from'),
                                  ('to_date', 'to'),
                                  ('search', 'search'),
                                  ('cursor', 'cursor'),
                                  ('limit', 'limit')],
                 'body_fields': [],
                 'nullable_fields': []},
 'get_order': {'method': 'GET',
               'path': '/v1/orders/{order_id}',
               'path_fields': [('order_id', 'order_id')],
               'query_fields': [],
               'body_fields': [],
               'nullable_fields': []},
 'search_customers': {'method': 'GET',
                      'path': '/v1/customers',
                      'path_fields': [],
                      'query_fields': [('query', 'query'),
                                       ('paid_only', 'paid_only'),
                                       ('cursor', 'cursor'),
                                       ('limit', 'limit')],
                      'body_fields': [],
                      'nullable_fields': []},
 'get_customer': {'method': 'GET',
                  'path': '/v1/customers/{customer_id}',
                  'path_fields': [('customer_id', 'customer_id')],
                  'query_fields': [],
                  'body_fields': [],
                  'nullable_fields': []},
 'list_coupons': {'method': 'GET',
                  'path': '/v1/coupons',
                  'path_fields': [],
                  'query_fields': [('status', 'status'), ('cursor', 'cursor'), ('limit', 'limit')],
                  'body_fields': [],
                  'nullable_fields': []},
 'create_coupon': {'method': 'POST',
                   'path': '/v1/coupons',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': ['code',
                                   'percent',
                                   'amount',
                                   'max_uses',
                                   'starts_on',
                                   'ends_on',
                                   'product_ids'],
                   'nullable_fields': ['product_ids']},
 'update_coupon': {'method': 'PATCH',
                   'path': '/v1/coupons/{coupon_id}',
                   'path_fields': [('coupon_id', 'coupon_id')],
                   'query_fields': [],
                   'body_fields': ['status',
                                   'code',
                                   'percent',
                                   'amount',
                                   'max_uses',
                                   'starts_on',
                                   'ends_on',
                                   'product_ids'],
                   'nullable_fields': ['percent',
                                       'amount',
                                       'max_uses',
                                       'starts_on',
                                       'ends_on',
                                       'product_ids']},
 'grant_access': {'method': 'POST',
                  'path': '/v1/access/grant',
                  'path_fields': [],
                  'query_fields': [],
                  'body_fields': ['email',
                                  'product_id',
                                  'variant_id',
                                  'first_name',
                                  'last_name',
                                  'reason',
                                  'send_email'],
                  'nullable_fields': []},
 'revoke_access': {'method': 'POST',
                   'path': '/v1/access/revoke',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': ['email', 'product_id', 'variant_id'],
                   'nullable_fields': []},
 'list_email_campaigns': {'method': 'GET',
                          'path': '/v1/email/campaigns',
                          'path_fields': [],
                          'query_fields': [('status', 'status'),
                                           ('cursor', 'cursor'),
                                           ('limit', 'limit')],
                          'body_fields': [],
                          'nullable_fields': []},
 'get_email_campaign': {'method': 'GET',
                        'path': '/v1/email/campaigns/{campaign_id}',
                        'path_fields': [('campaign_id', 'campaign_id')],
                        'query_fields': [],
                        'body_fields': [],
                        'nullable_fields': []},
 'get_subscription_summary': {'method': 'GET',
                              'path': '/v1/reports/subscriptions',
                              'path_fields': [],
                              'query_fields': [('from_date', 'from'),
                                               ('to_date', 'to'),
                                               ('product_id', 'product_id')],
                              'body_fields': [],
                              'nullable_fields': []},
 'list_email_automations': {'method': 'GET',
                            'path': '/v1/email/automations',
                            'path_fields': [],
                            'query_fields': [('status', 'status'),
                                             ('cursor', 'cursor'),
                                             ('limit', 'limit')],
                            'body_fields': [],
                            'nullable_fields': []}}


class TentaryNode(WorkflowNode):
    integration_type = "automation-tentary"
    connection_evidence = ConnectionEvidence(
        noun="Tentary shop", identity_operation="get_account_overview",
    )

    @classmethod
    def get_config_model(cls):
        return TentaryConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Tentary API key")
        op = config.config
        route = OPERATIONS[op.operation]
        path = route["path"]
        for name, wire_name in route["path_fields"]:
            path = path.replace("{" + wire_name + "}", str(getattr(op, name)))
        params = {}
        for name, wire_name in route["query_fields"]:
            value = getattr(op, name)
            if value is not None:
                params[wire_name] = str(value).lower() if isinstance(value, bool) else value
        body = {name: getattr(op, name) for name in route["body_fields"]
                if name in op.model_fields_set and
                (getattr(op, name) is not None or name in route["nullable_fields"])}
        key = config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                route["method"], BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                **({"json": body} if route["body_fields"] else {}),
            )
        if response.status_code >= 300:
            # Keep provider rejection text for connect evidence, while removing the secret.
            try:
                error = response.json()
                message = error.get("message") or error.get("error") or response.reason_phrase
                if isinstance(message, dict):
                    message = message.get("message") or message.get("code") or response.reason_phrase
            except (ValueError, AttributeError):
                message = response.reason_phrase
            return {"status": "error", "status_code": response.status_code,
                    "error": str(message).replace(key, "[redacted]")[:2000]}
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Tentary returned a web page instead of an API response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Tentary returned an unexpected response shape")
        if payload.get("error"):
            return {"status": "error", "error": str(payload["error"]).replace(key, "[redacted]")[:2000]}
        # Preserve the documented data and next_cursor without automatically fetching more pages.
        return {"status": "success", "data": payload}

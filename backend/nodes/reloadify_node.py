"""Reloadify marketing and commerce operations against its published v2 contract.

Each action makes one provider request using a manually supplied bearer token.
Scheduled polls use the shared baseline and deduplication family.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://app.reloadify.com/api"
DOCS = "https://app.reloadify.com/api-docs/"


class ReloadifyAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Reloadify Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Paste an existing access_token without the Bearer prefix. In Reloadify Settings > Reloadify API, generate a client ID and secret, then exchange them at POST https://app.reloadify.com/oauth/token with grant_type=client_credentials. Tokens last at most two hours: replace this token when it expires. The connection check reads your account's segments.",
        })
    credential_type: Literal["reloadify_access_token"] = Field("reloadify_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the access token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("language_id", "profile_id", "product_id", "order_id", "shopping_cart_id", "transactional_email_id", mode="before", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value is not None and (not isinstance(value, str) or not value or value in {".", ".."} or any(c in value for c in "/?#%") or any(ord(c) < 32 for c in value)):
            raise ValueError("Use a single Reloadify resource ID")
        return value



class ReloadifyProfileBodyCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyProfileBody(_Input):
    id: str = Field(...)
    email: str = Field(...)
    active: bool | None = Field(None)
    first_name: str | None = Field(None)
    middle_name: str | None = Field(None)
    last_name: str | None = Field(None)
    subscribed_to_newsletter: bool | None = Field(None)
    subscribed_to_newsletter_at: datetime | None = Field(None)
    subscribed_to_sms: bool | None = Field(None)
    subscribed_to_sms_at: datetime | None = Field(None)
    double_opt_in: bool | None = Field(None)
    is_registered: bool | None = Field(None)
    is_company: bool | None = Field(None)
    gender: Literal['male', 'female', 'unidentified'] | None = Field(None)
    company_name: str | None = Field(None)
    telephone: str | None = Field(None)
    mobile_phone: str | None = Field(None)
    street: str | None = Field(None)
    housenumber: str | None = Field(None)
    city: str | None = Field(None)
    province: str | None = Field(None)
    zipcode: str | None = Field(None)
    country_code: str | None = Field(None)
    tags: list[str] | None = Field(None)
    tag_import_type: Literal['overwrite_tag', 'add_tag', 'delete_tag'] | None = Field(None)
    birthdate: date | None = Field(None)
    custom_attributes: list[ReloadifyProfileBodyCustomAttributesItem] | None = Field(None)


class ReloadifyProductBodyCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyProductBody(_Input):
    id: str = Field(...)
    link_key: str | None = Field(None, description='One value that is the same for this item in every language, so Reloadify can link the translations. Stored once; a later different value is ignored. Example: SHIRT-001')
    name: str | None = Field(None)
    visible: bool | None = Field(None)
    purchasable: bool | None = Field(None)
    main_image: str | None = Field(None)
    url: str | None = Field(None)
    short_description: str | None = Field(None)
    price: float | None = Field(None)
    created_at: datetime | None = Field(None)
    updated_at: datetime | None = Field(None)
    brand_id: str | None = Field(None, description='An existing Brand ID')
    custom_attributes: list[ReloadifyProductBodyCustomAttributesItem] | None = Field(None)


class ReloadifyOrderBodyCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyOrderBody(_Input):
    id: str = Field(...)
    ordered_at: datetime = Field(...)
    profile_id: str = Field(..., description='An existing profile ID')
    currency: str | None = Field(None)
    created_at: datetime | None = Field(None)
    checkout_id: str | None = Field(None)
    number: str | None = Field(None)
    price: float | None = Field(None)
    status: str | None = Field(None)
    refunded_at: datetime | None = Field(None, description='When the order was refunded. Setting status to refunded does not populate this; send it explicitly to track refunds.')
    total_refunded: float | None = Field(None, description='Total amount refunded so far. Stored as the most recent reported amount.')
    discount_code: str | None = Field(None)
    is_discount_applied: bool | None = Field(None)
    paid: bool | None = Field(None)
    custom_attributes: list[ReloadifyOrderBodyCustomAttributesItem] | None = Field(None)


class ReloadifyShoppingCartBodyCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyShoppingCartBody(_Input):
    id: str = Field(...)
    profile_id: str = Field(..., description='An existing profile ID')
    currency: str | None = Field(None)
    price: str | None = Field(None)
    recovery_url: str | None = Field(None)
    recovery_token: str | None = Field(None)
    created_at: str | None = Field(None)
    updated_at: str | None = Field(None)
    custom_attributes: list[ReloadifyShoppingCartBodyCustomAttributesItem] | None = Field(None)


class ReloadifyCategoryBodyCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyCategoryBody(_Input):
    id: str = Field(...)
    link_key: str | None = Field(None, description='One value that is the same for this item in every language, so Reloadify can link the translations. Stored once; a later different value is ignored. Example: SHIRT-001')
    name: str = Field(...)
    parent_category_id: str | None = Field(None, description='An existing parent category ID')
    url: str | None = Field(None)
    visible: bool | None = Field(None)
    created_at: datetime | None = Field(None)
    updated_at: datetime | None = Field(None)
    custom_attributes: list[ReloadifyCategoryBodyCustomAttributesItem] | None = Field(None)


class ReloadifyGlobalUnsubscribeBody(_Input):
    email: str | None = Field(None)
    profile_id: str | None = Field(None)
    unsubscribed: bool = Field(...)


class ReloadifyEmailProfileCustomAttributesItem(_Input):
    name: str = Field(...)
    string_value: str | None = Field(None)
    integer_value: int | None = Field(None)
    date_value: date | None = Field(None)
    datetime_value: datetime | None = Field(None)
    boolean_value: bool | None = Field(None)
    string_list_value: list[str] | None = Field(None)


class ReloadifyEmailProfile(_Input):
    id: str | None = Field(None)
    email: str = Field(...)
    active: bool | None = Field(None)
    first_name: str | None = Field(None)
    middle_name: str | None = Field(None)
    last_name: str | None = Field(None)
    subscribed_to_newsletter: bool | None = Field(None)
    subscribed_to_newsletter_at: datetime | None = Field(None)
    subscribed_to_sms: bool | None = Field(None)
    subscribed_to_sms_at: datetime | None = Field(None)
    double_opt_in: bool | None = Field(None)
    is_registered: bool | None = Field(None)
    is_company: bool | None = Field(None)
    gender: Literal['male', 'female', 'unidentified'] | None = Field(None)
    company_name: str | None = Field(None)
    telephone: str | None = Field(None)
    mobile_phone: str | None = Field(None)
    street: str | None = Field(None)
    housenumber: str | None = Field(None)
    city: str | None = Field(None)
    province: str | None = Field(None)
    zipcode: str | None = Field(None)
    country_code: str | None = Field(None)
    tags: list[str] | None = Field(None)
    tag_import_type: Literal['overwrite_tag', 'add_tag', 'delete_tag'] | None = Field(None)
    birthdate: date | None = Field(None)
    custom_attributes: list[ReloadifyEmailProfileCustomAttributesItem] | None = Field(None)

class _OperationInput(_Input):
    # Canvas metadata is ignored; only declared fields are read or polled.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


# Fixed operation table: each entry names exactly one published endpoint.
OPERATIONS = {
    'list_languages': ('GET', '/v2/languages', 'List Languages'),
    'get_language': ('GET', '/v2/languages/{language_id}', 'Get Language'),
    'list_profiles': ('GET', '/v2/languages/{language_id}/profiles', 'List Profiles'),
    'get_profile': ('GET', '/v2/languages/{language_id}/profiles/{profile_id}', 'Get Profile'),
    'upsert_profile': ('PUT', '/v2/languages/{language_id}/profiles', 'Create or Update Profile'),
    'delete_profile': ('DELETE', '/v2/languages/{language_id}/profiles/{profile_id}', 'Delete Profile'),
    'list_products': ('GET', '/v2/languages/{language_id}/products', 'List Products'),
    'get_product': ('GET', '/v2/languages/{language_id}/products/{product_id}', 'Get Product'),
    'upsert_product': ('PUT', '/v2/languages/{language_id}/products', 'Create or Update Product'),
    'list_orders': ('GET', '/v2/languages/{language_id}/orders', 'List Orders'),
    'get_order': ('GET', '/v2/languages/{language_id}/orders/{order_id}', 'Get Order'),
    'upsert_order': ('PUT', '/v2/languages/{language_id}/orders', 'Create or Update Order'),
    'list_shopping_carts': ('GET', '/v2/languages/{language_id}/shopping_carts', 'List Shopping Carts'),
    'get_shopping_cart': ('GET', '/v2/languages/{language_id}/shopping_carts/{shopping_cart_id}', 'Get Shopping Cart'),
    'upsert_shopping_cart': ('PUT', '/v2/languages/{language_id}/shopping_carts', 'Create or Update Shopping Cart'),
    'delete_shopping_cart': ('DELETE', '/v2/languages/{language_id}/shopping_carts/{shopping_cart_id}', 'Delete Shopping Cart'),
    'list_categories': ('GET', '/v2/languages/{language_id}/categories', 'List Categories'),
    'upsert_category': ('PUT', '/v2/languages/{language_id}/categories', 'Create or Update Category'),
    'list_segments': ('GET', '/v2/segments', 'List Segments'),
    'list_global_unsubscribes': ('GET', '/v2/languages/{language_id}/global_unsubscribes', 'List Global Unsubscribes'),
    'upsert_global_unsubscribe': ('PUT', '/v2/languages/{language_id}/global_unsubscribes', 'Set Global Unsubscription'),
    'send_transactional_email': ('POST', '/v2/languages/{language_id}/transactional_emails/{transactional_email_id}/send', 'Send Transactional Email'),
}

CONFIG_MODELS = {}
ReloadifyListLanguagesConfig = create_model('ReloadifyListLanguagesConfig', __base__=_OperationInput,
    operation=(Literal['list_languages'], Field('list_languages', title='List Languages', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Languages', "x-is-trigger": False})),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_languages'] = ReloadifyListLanguagesConfig

ReloadifyGetLanguageConfig = create_model('ReloadifyGetLanguageConfig', __base__=_OperationInput,
    operation=(Literal['get_language'], Field('get_language', title='Get Language', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Language', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['get_language'] = ReloadifyGetLanguageConfig

ReloadifyListProfilesConfig = create_model('ReloadifyListProfilesConfig', __base__=_OperationInput,
    operation=(Literal['list_profiles'], Field('list_profiles', title='List Profiles', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Profiles', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250)),
    emails=(list[str] | None, Field(None, title="Email addresses"))
)
CONFIG_MODELS['list_profiles'] = ReloadifyListProfilesConfig

ReloadifyGetProfileConfig = create_model('ReloadifyGetProfileConfig', __base__=_OperationInput,
    operation=(Literal['get_profile'], Field('get_profile', title='Get Profile', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Profile', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    profile_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['get_profile'] = ReloadifyGetProfileConfig

ReloadifyUpsertProfileConfig = create_model('ReloadifyUpsertProfileConfig', __base__=_OperationInput,
    operation=(Literal['upsert_profile'], Field('upsert_profile', title='Create or Update Profile', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create or Update Profile', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    profile=(ReloadifyProfileBody, ...)
)
CONFIG_MODELS['upsert_profile'] = ReloadifyUpsertProfileConfig

ReloadifyDeleteProfileConfig = create_model('ReloadifyDeleteProfileConfig', __base__=_OperationInput,
    operation=(Literal['delete_profile'], Field('delete_profile', title='Delete Profile', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete Profile', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    profile_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['delete_profile'] = ReloadifyDeleteProfileConfig

ReloadifyListProductsConfig = create_model('ReloadifyListProductsConfig', __base__=_OperationInput,
    operation=(Literal['list_products'], Field('list_products', title='List Products', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Products', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_products'] = ReloadifyListProductsConfig

ReloadifyGetProductConfig = create_model('ReloadifyGetProductConfig', __base__=_OperationInput,
    operation=(Literal['get_product'], Field('get_product', title='Get Product', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Product', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    product_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['get_product'] = ReloadifyGetProductConfig

ReloadifyUpsertProductConfig = create_model('ReloadifyUpsertProductConfig', __base__=_OperationInput,
    operation=(Literal['upsert_product'], Field('upsert_product', title='Create or Update Product', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create or Update Product', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    product=(ReloadifyProductBody, ...)
)
CONFIG_MODELS['upsert_product'] = ReloadifyUpsertProductConfig

ReloadifyListOrdersConfig = create_model('ReloadifyListOrdersConfig', __base__=_OperationInput,
    operation=(Literal['list_orders'], Field('list_orders', title='List Orders', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Orders', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_orders'] = ReloadifyListOrdersConfig

ReloadifyGetOrderConfig = create_model('ReloadifyGetOrderConfig', __base__=_OperationInput,
    operation=(Literal['get_order'], Field('get_order', title='Get Order', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Order', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    order_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['get_order'] = ReloadifyGetOrderConfig

ReloadifyUpsertOrderConfig = create_model('ReloadifyUpsertOrderConfig', __base__=_OperationInput,
    operation=(Literal['upsert_order'], Field('upsert_order', title='Create or Update Order', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create or Update Order', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    order=(ReloadifyOrderBody, ...)
)
CONFIG_MODELS['upsert_order'] = ReloadifyUpsertOrderConfig

ReloadifyListShoppingCartsConfig = create_model('ReloadifyListShoppingCartsConfig', __base__=_OperationInput,
    operation=(Literal['list_shopping_carts'], Field('list_shopping_carts', title='List Shopping Carts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Shopping Carts', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_shopping_carts'] = ReloadifyListShoppingCartsConfig

ReloadifyGetShoppingCartConfig = create_model('ReloadifyGetShoppingCartConfig', __base__=_OperationInput,
    operation=(Literal['get_shopping_cart'], Field('get_shopping_cart', title='Get Shopping Cart', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Shopping Cart', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    shopping_cart_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['get_shopping_cart'] = ReloadifyGetShoppingCartConfig

ReloadifyUpsertShoppingCartConfig = create_model('ReloadifyUpsertShoppingCartConfig', __base__=_OperationInput,
    operation=(Literal['upsert_shopping_cart'], Field('upsert_shopping_cart', title='Create or Update Shopping Cart', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create or Update Shopping Cart', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    shopping_cart=(ReloadifyShoppingCartBody, ...)
)
CONFIG_MODELS['upsert_shopping_cart'] = ReloadifyUpsertShoppingCartConfig

ReloadifyDeleteShoppingCartConfig = create_model('ReloadifyDeleteShoppingCartConfig', __base__=_OperationInput,
    operation=(Literal['delete_shopping_cart'], Field('delete_shopping_cart', title='Delete Shopping Cart', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete Shopping Cart', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    shopping_cart_id=(str, Field(..., min_length=1, max_length=255))
)
CONFIG_MODELS['delete_shopping_cart'] = ReloadifyDeleteShoppingCartConfig

ReloadifyListCategoriesConfig = create_model('ReloadifyListCategoriesConfig', __base__=_OperationInput,
    operation=(Literal['list_categories'], Field('list_categories', title='List Categories', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Categories', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_categories'] = ReloadifyListCategoriesConfig

ReloadifyUpsertCategoryConfig = create_model('ReloadifyUpsertCategoryConfig', __base__=_OperationInput,
    operation=(Literal['upsert_category'], Field('upsert_category', title='Create or Update Category', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create or Update Category', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    category=(ReloadifyCategoryBody, ...)
)
CONFIG_MODELS['upsert_category'] = ReloadifyUpsertCategoryConfig

ReloadifyListSegmentsConfig = create_model('ReloadifyListSegmentsConfig', __base__=_OperationInput,
    operation=(Literal['list_segments'], Field('list_segments', title='List Segments', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Segments', "x-is-trigger": False})),
    language_id=(str | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_segments'] = ReloadifyListSegmentsConfig

ReloadifyListGlobalUnsubscribesConfig = create_model('ReloadifyListGlobalUnsubscribesConfig', __base__=_OperationInput,
    operation=(Literal['list_global_unsubscribes'], Field('list_global_unsubscribes', title='List Global Unsubscribes', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Global Unsubscribes', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    created_after=(datetime | None, None),
    created_before=(datetime | None, None),
    updated_after=(datetime | None, None),
    updated_before=(datetime | None, None),
    page=(int, Field(1, ge=1)),
    per_page=(int, Field(100, ge=1, le=250))
)
CONFIG_MODELS['list_global_unsubscribes'] = ReloadifyListGlobalUnsubscribesConfig

ReloadifyUpsertGlobalUnsubscribeConfig = create_model('ReloadifyUpsertGlobalUnsubscribeConfig', __base__=_OperationInput,
    operation=(Literal['upsert_global_unsubscribe'], Field('upsert_global_unsubscribe', title='Set Global Unsubscription', json_schema_extra={"ui:hidden": True, "x-display-name": 'Set Global Unsubscription', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    global_unsubscribe=(ReloadifyGlobalUnsubscribeBody, ...)
)
CONFIG_MODELS['upsert_global_unsubscribe'] = ReloadifyUpsertGlobalUnsubscribeConfig

ReloadifySendTransactionalEmailConfig = create_model('ReloadifySendTransactionalEmailConfig', __base__=_OperationInput,
    operation=(Literal['send_transactional_email'], Field('send_transactional_email', title='Send Transactional Email', json_schema_extra={"ui:hidden": True, "x-display-name": 'Send Transactional Email', "x-is-trigger": False})),
    language_id=(str, Field(..., min_length=1, max_length=255)),
    transactional_email_id=(str, Field(..., min_length=1, max_length=255)),
    profile=(ReloadifyEmailProfile, ...),
    data=(dict | None, None)
)
CONFIG_MODELS['send_transactional_email'] = ReloadifySendTransactionalEmailConfig


class ReloadifyOnNewProfileConfig(PollTriggerConfigBase, _OperationInput):
    operation: Literal["on_new_profile"] = Field("on_new_profile", title="On New Profile",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Profile", "x-category": "Triggers"})
    language_id: str = Field(..., min_length=1, max_length=255)
    created_after: datetime | None = Field(None, description="Optional earliest creation time to monitor. Existing profiles are baselined when armed.")


class ReloadifyOnNewOrderConfig(PollTriggerConfigBase, _OperationInput):
    operation: Literal["on_new_order"] = Field("on_new_order", title="On New Order",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Order", "x-category": "Triggers"})
    language_id: str = Field(..., min_length=1, max_length=255)
    created_after: datetime | None = None


class ReloadifyOnUpdatedCartConfig(PollTriggerConfigBase, _OperationInput):
    operation: Literal["on_new_or_updated_cart"] = Field("on_new_or_updated_cart", title="On New or Updated Cart",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New or Updated Cart", "x-category": "Triggers"})
    language_id: str = Field(..., min_length=1, max_length=255)
    updated_after: datetime | None = None


TRIGGERS = {"on_new_profile": "profiles", "on_new_order": "orders", "on_new_or_updated_cart": "shopping_carts"}
ReloadifyConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (
    ReloadifyOnNewProfileConfig, ReloadifyOnNewOrderConfig, ReloadifyOnUpdatedCartConfig)], Field(discriminator="operation")]


class ReloadifyFullConfig(NodeConfig[ReloadifyConfig, ReloadifyAccessTokenCredential]):
    pass


def _rows(body, identifier="id"):
    # v2's published list response references a single resource entity. Accept
    # that shape as well as a JSON array, preserving the provider's fields.
    if isinstance(body, dict) and identifier in body:
        return [body]
    if isinstance(body, list) and all(isinstance(row, dict) and identifier in row for row in body):
        return body
    raise ValueError("Reloadify returned an unexpected resource list")


class ReloadifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-reloadify"
    connection_evidence = ConnectionEvidence(operation="list_segments", noun="Reloadify segments")

    @classmethod
    def get_config_model(cls):
        return ReloadifyFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        if not self.config.credentials:
            raise ValueError("Connect a Reloadify access token")
        token = self.config.credentials.access_token
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = response.text.replace(token, "[redacted]")[:1000]
            raise ValueError(f"Reloadify HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return {"status": "success"}
        return response.json()

    async def execute(self, inputs):
        if not isinstance(self.config, ReloadifyFullConfig):
            raise ValueError("Reloadify configuration required")
        config = self.config.config
        op = config.operation
        if op in TRIGGERS:
            return await self._poll(config)
        method, path, _ = OPERATIONS[op]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        if "emails" in values:
            values["emails[]"] = values.pop("emails")
        body = values if method in {"PUT", "POST"} else None
        result = await self._request(method, path, params=values if method == "GET" else None, body=body)
        if op.startswith("list_"):
            return {"items": _rows(result, "profile_id" if op == "list_global_unsubscribes" else "id"), "page": config.page, "per_page": config.per_page}
        return {"data": result}

    async def _poll(self, config):
        resource = TRIGGERS[config.operation]
        path = "/v2/languages/" + quote(config.language_id, safe="") + "/" + resource
        values = config.model_dump(mode="json", exclude_none=True)
        params = {key: values[key] for key in ("created_after", "updated_after") if key in values}
        items = []
        for page in range(1, 21):
            rows = _rows(await self._request("GET", path, params={**params, "page": page, "per_page": 250}))
            items.extend(rows)
            if len(rows) < 250:
                break
        else:
            raise ValueError("Reloadify polling exceeds 5000 records; narrow the time filter before monitoring")
        def identity(row):
            key = str(row["id"])
            if resource == "shopping_carts":
                key += ":" + str(row["updated_at"])
            return key
        fresh = await self._filter_unseen(items, identity)
        return {"items": fresh, "new_item_count": len(fresh), "resource": resource, "language_id": config.language_id}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation") in TRIGGERS else True

    @classmethod
    def resolve_agent_event(cls, output):
        resource = output.get("resource")
        if resource not in TRIGGERS.values():
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items:
            return None
        lines = []
        for item in items[:10]:
            if resource == "profiles":
                detail = f"{item['email']} — {item['first_name']} {item['last_name']}"
            elif resource == "orders":
                detail = f"Order {item['number']} for profile {item['profile_id']}: {item['price']} {item['currency']} ({item['status']})"
            else:
                detail = f"Cart for profile {item['profile_id']}: {item['price']} {item['currency']}; updated {item['updated_at']}"
            lines.append(f"- {detail} (id {item['id']})")
        return {"text": f"Reloadify: {len(items)} new or changed {resource} in language {output['language_id']}:\n" + "\n".join(lines), "conversation_key": None}

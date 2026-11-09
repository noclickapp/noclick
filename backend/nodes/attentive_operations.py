"""Typed Attentive request models from the pinned v1/v2 OpenAPI contracts.

Wire field names intentionally match the provider. Each config is one API call.
"""
from __future__ import annotations
import json
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator

JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def editor_and_canvas_values(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        if "operation" in cls.model_fields:
            # Canvas persistence includes display metadata beside operation fields.
            for key in ("credentialIds", "label", "disabled", "goal", "operationReason",
                        "userFields", "mockedOutput", "credentials", "content", "color", "previewOutput"):
                values.pop(key, None)
        for name, field in cls.model_fields.items():
            types = (field.annotation, *get_args(field.annotation))
            structured = any(get_origin(t) in (list, dict) or isinstance(t, type) and issubclass(t, BaseModel) for t in types)
            if structured and isinstance(values.get(name), str):
                try:
                    values[name] = json.loads(values[name])
                except ValueError:
                    raise ValueError("Enter valid JSON for " + name) from None
        return values

    @model_validator(mode="after")
    def documented_constraints(self):
        values = self.model_dump(exclude_none=True)
        name = type(self).__name__
        if name in {"EventUser", "UserDto1"} and not any(values.get(k) for k in ("phone", "email", "externalIdentifiers")):
            raise ValueError("Provide a user phone, email or external identifier")
        if values.get("phone") is not None:
            import re
            if not re.fullmatch(r"\+[1-9][0-9]{1,14}", values["phone"]):
                raise ValueError("Use an E.164 phone number including +")
        if name in {"GetCustomAttributesConfig", "GetSubscriptionsConfig"} and sum(bool(values.get(k)) for k in ("phone", "email")) != 1:
            raise ValueError("Provide exactly one of phone or email")
        if name == "SubscribeUserConfig" and not (values.get("signUpSourceId") or (values.get("locale", {}).get("language") and values.get("locale", {}).get("country") and values.get("subscriptionType"))):
            raise ValueError("Provide a sign-up source ID or both locale and subscription type")
        if name == "UpdateSegmentConfig" and not (values.get("name") or values.get("description")):
            raise ValueError("Provide a name or description to update")
        if name == "SetCustomAttributesConfig" and any(isinstance(v, (dict, list)) for v in self.properties.values()):
            raise ValueError("Custom attributes support scalar values, not arrays or objects")
        if name == "SendCustomEventConfig" and any(c in self.type for c in '"\'(){}[]\\|,'):
            raise ValueError("Custom event type contains an unsupported character")
        return self


class GetMeConfig(_Input):
    """Me."""
    operation: Literal['get_me'] = Field('get_me', json_schema_extra={"ui:hidden": True})


class ListSegmentsConfig(_Input):
    """List segments."""
    operation: Literal['list_segments'] = Field('list_segments', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=240)
    externalId: str | None = Field(None, min_length=1, max_length=255)
    updatedSince: AwareDatetime | None = Field(None)
    cursor: str | None = Field(None, min_length=1)
    limit: int = Field(20, ge=1, le=1000)


class CreateSegmentConfig(_Input):
    """Create new segment."""
    operation: Literal['create_segment'] = Field('create_segment', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=240, description='The name of the segment. Cannot be empty or whitespace only. Leading and trailing whitespace will be trimmed.')
    description: str | None = Field(None, min_length=2, max_length=500, description='Optional description of the segment. If not provided, defaults to "Manual Segment Upload Public API V2". When provided, cannot be empty or whitespace only and must be at least 2 characters. Leading and trailing whitespace will be trimmed.')
    externalId: str | None = Field(None, min_length=1, max_length=255, description='Auto generated if not supplied. Optional externalId set on the segment. Cannot be empty or whitespace only. Leading and trailing whitespace will be trimmed.')


class GetSegmentConfig(_Input):
    """Get segment by external ID."""
    operation: Literal['get_segment'] = Field('get_segment', json_schema_extra={"ui:hidden": True})
    externalId: str = Field(..., min_length=1, max_length=255)


class UpdateSegmentConfig(_Input):
    """Partial update segment by external ID."""
    operation: Literal['update_segment'] = Field('update_segment', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=240, description='The name of the segment. If provided, cannot be empty or whitespace only and must be at most 240 characters. Leading and trailing whitespace will be trimmed. At least one field (name or description) must be provided for PATCH.')
    description: str | None = Field(None, min_length=2, max_length=500, description='The description of the segment. If provided, cannot be empty or whitespace only, must be at least 2 characters, and at most 500 characters. Leading and trailing whitespace will be trimmed. At least one field (name or description) must be provided for PATCH.')
    externalId: str = Field(..., min_length=1, max_length=255)


class ArchiveSegmentConfig(_Input):
    """Archive segment by external ID."""
    operation: Literal['archive_segment'] = Field('archive_segment', json_schema_extra={"ui:hidden": True})
    externalId: str = Field(..., min_length=1, max_length=255)


class ExternalIdentifiersCustomIdentifiersItem(_Input):
    name: str | None = Field(None, min_length=1)
    value: str | None = Field(None, min_length=1)


class ExternalIdentifiers(_Input):
    clientUserId: str | None = Field(None, min_length=1, description='(optional) Your primary ID for a user')
    customIdentifiers: list[ExternalIdentifiersCustomIdentifiersItem] | None = Field(None, description='(optional) Namespaced custom identifiers and their values.', json_schema_extra=JSON_EDITOR)


class EventUser(_Input):
    phone: str | None = Field(None, min_length=1, description='Phone number of the user associated with the action. [E.164 format](https://en.wikipedia.org/wiki/E.164) is required. This field is required if either email or an externalIdentifier is not provided.')
    email: str | None = Field(None, min_length=1, description='Email of the user associated with the action. This field is required if either phone or an externalIdentifier is not provided.')
    externalIdentifiers: ExternalIdentifiers | None = Field(None, json_schema_extra=JSON_EDITOR)


class SendCustomEventConfig(_Input):
    """Custom Events."""
    operation: Literal['send_custom_event'] = Field('send_custom_event', json_schema_extra={"ui:hidden": True})
    type: str = Field(..., min_length=1, description='The type of event. This name is case sensitive.\n"Order shipped" and "Order Shipped" would be considered different event types.')
    properties: dict[str, Any] | None = Field(None, description='Any metadata associated with the event.', json_schema_extra=JSON_EDITOR)
    externalEventId: str | None = Field(None, min_length=1, description='A unique identifier representing this specific event. A UUID is recommended.')
    occurredAt: AwareDatetime | None = Field(None, description='Timestamp of when the action occurred in [RFC 3339 format](https://datatracker.ietf.org/doc/html/rfc3339#section-5.8) with required UTC offset. If the timestamp is older than 12 hours, it will not trigger any relevant Journeys. If no timestamp is provided, it is assumed the event occurred when the endpoint is called.\n')
    user: EventUser = Field(..., json_schema_extra=JSON_EDITOR)


class SetCustomAttributesConfig(_Input):
    """Custom Attributes."""
    operation: Literal['set_custom_attributes'] = Field('set_custom_attributes', json_schema_extra={"ui:hidden": True})
    properties: dict[str, Any] = Field(..., description='Any metadata associated with the attribute. Object keys are expected to be strings. Object values can be any type. The key will be assigned a type corresponding to the type seen of the first value. For example, if \'Age\' is passed with the first value of \'24\', \'Age\' will be typed as a \'Number\'. There is no need to pass strings in double quotes. Both object keys and object values are case sensitive. "Favorite color" and "Favorite Color" would be considered different custom attributes.\n', json_schema_extra=JSON_EDITOR)
    user: EventUser = Field(..., json_schema_extra=JSON_EDITOR)


class GetCustomAttributesConfig(_Input):
    """Get Custom Attributes for a User."""
    operation: Literal['get_custom_attributes'] = Field('get_custom_attributes', json_schema_extra={"ui:hidden": True})
    phone: str | None = Field(None, min_length=1)
    email: str | None = Field(None, min_length=1)


class UserDto1(_Input):
    phone: str | None = Field(None, min_length=1, description='Phone number of the user associated with the action. [E.164 format](https://en.wikipedia.org/wiki/E.164) is required. This field is required if email is not provided.')
    email: str | None = Field(None, min_length=1, description='Email of the user associated with the action. This field is required if phone is not provided.')


class CustomIdentifierDto(_Input):
    name: str | None = Field(None, min_length=1)
    value: str | None = Field(None, min_length=1)


class NewExternalIdentifierDto(_Input):
    clientUserId: str | None = Field(None, min_length=1, description="Notes:\nSending duplicate values could lead to unintentionally bridging users together.\nDon't use customIdentifiers to send attributes (e.g., first name, last name). To send those types of attributes, use our Custom Attributes API.\nAvoid sending null values or empty strings. If you don't have a valid identifier, you should omit the field from the payload.\n")
    shopifyId: str | None = Field(None, min_length=1, description="Notes:\nSending duplicate values could lead to unintentionally bridging users together.\nDon't use customIdentifiers to send attributes (e.g., first name, last name). To send those types of attributes, use our Custom Attributes API.\nAvoid sending null values or empty strings. If you don't have a valid identifier, you should omit the field from the payload.\n")
    klaviyoId: str | None = Field(None, min_length=1, description="Notes:\nSending duplicate values could lead to unintentionally bridging users together.\nDon't use customIdentifiers to send attributes (e.g., first name, last name). To send those types of attributes, use our Custom Attributes API.\nAvoid sending null values or empty strings. If you don't have a valid identifier, you should omit the field from the payload.\n")
    customIdentifiers: list[CustomIdentifierDto] | None = Field(None, json_schema_extra=JSON_EDITOR)


class LocaleDto(_Input):
    language: str | None = Field(None, min_length=1, description='Two-letter language code of the locale. [ISO 639-1 alpha 2](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) is required. Values are case sensitive and must match exactly.')
    country: str | None = Field(None, min_length=1, description='Two-letter country code of the locale. [ISO-3166-1 alpha 2](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) is required. Values are case sensitive and must match exactly.')


class SubscribeUserConfig(_Input):
    """Subscribe user."""
    operation: Literal['subscribe_user'] = Field('subscribe_user', json_schema_extra={"ui:hidden": True})
    user: UserDto1 = Field(..., json_schema_extra=JSON_EDITOR)
    signUpSourceId: str | None = Field(None, min_length=1, description='The unique identifier of the sign-up source. This can be found in the Sign-up Units tab of the Attentive platform in the ID column for any API sign-up method.\nThis field is required if locale is not present. ')
    externalIdentifiers: NewExternalIdentifierDto | None = Field(None, json_schema_extra=JSON_EDITOR)
    locale: LocaleDto | None = Field(None, json_schema_extra=JSON_EDITOR)
    subscriptionType: Literal['MARKETING', 'TRANSACTIONAL'] | None = Field(None)
    singleOptIn: bool | None = Field(None, description='Opt in subscriber silently (do not send a Reply Y to subscribe text).')
    pixelTrackingConsent: bool | None = Field(None, description='Explicitly set subscriber pixel tracking consent. This is implemented in accordance with compliance requirements\nin France and Italy. French and Italian subscribers have to explicitly opt in to email pixel tracking, so this\nparameter allows third party developers to create a subscription with the tracking consent set.')


class GetSubscriptionsConfig(_Input):
    """Get subscription eligibility for a user."""
    operation: Literal['get_subscriptions'] = Field('get_subscriptions', json_schema_extra={"ui:hidden": True})
    phone: str | None = Field(None, min_length=1)
    email: str | None = Field(None, min_length=1)


class SubscriptionDto(_Input):
    type: Literal['MARKETING', 'TRANSACTIONAL', 'CHECKOUT_ABANDONED', 'CONTACT'] | None = Field(None)
    channel: Literal['TEXT', 'EMAIL'] | None = Field(None)


class NotificationConfigDto(_Input):
    language: str | None = Field(None, min_length=1, description='Standard language tags as defined by the ISO. Currently only supports en-US and fr-CA. Case sensitive, must match exactly.')
    disabled: bool | None = Field(None, description='A boolean representing if a user should not receive a confirmation message upon unsubscribing. Assumed false by default.')


class UnsubscribeUserConfig(_Input):
    """Unsubscribe subscriptions for a user."""
    operation: Literal['unsubscribe_user'] = Field('unsubscribe_user', json_schema_extra={"ui:hidden": True})
    user: UserDto1 = Field(..., json_schema_extra=JSON_EDITOR)
    subscriptions: list[SubscriptionDto] | None = Field(None, description="Omit to unsubscribe this user from all subscriptions. Supply type/channel combinations to limit the request. Confirmation messages may be sent.", json_schema_extra=JSON_EDITOR)
    notification: NotificationConfigDto | None = Field(None, json_schema_extra=JSON_EDITOR)


class Price(_Input):
    value: float = Field(..., description='The price of the product.')
    currency: str = Field('USD', description='The currency used for the price in [ISO 4217 format](https://www.iso.org/iso-4217-currency-codes.html).')


class ProductRequest(_Input):
    productId: str = Field(..., min_length=1, description='A unique identifier for the product (i.e. "T-Shirt"). If you are providing a [Google Shopping Feed](https://support.google.com/merchants/answer/7052112?hl=en), this should be [item_group_id](https://support.google.com/merchants/answer/6324507). If you don\'t have an [item_group_id](https://support.google.com/merchants/answer/6324507) in your feed, use [id](https://support.google.com/merchants/answer/6324405). If you are using [Shopify](https://help.shopify.com/en/manual/products), this should be Shopify product ID.\n')
    productVariantId: str = Field(..., min_length=1, description='A unique identifier for the product variant (i.e. "Medium Blue T-Shirt"). If you are providing a [Google Shopping Feed](https://support.google.com/merchants/answer/7052112?hl=en), this should be [id](https://support.google.com/merchants/answer/6324405). If you are using Shopify, this should be Shopify product Variant ID.\n')
    productImage: str | None = Field(None, min_length=1, description='A link to the image of the product. The image should not be larger than 500kb. This image will be used when sending MMS text messages.\n')
    productUrl: str | None = Field(None, min_length=1, description='The URL for the product.')
    name: str | None = Field(None, min_length=1, description='The name of the product. This should be in a format that could be used directly in a message.')
    price: list[Price] = Field(..., min_length=1, description='The price and currency of the product.', json_schema_extra=JSON_EDITOR)
    quantity: int | None = Field(None, description='The number of products.')


class RecordProductViewConfig(_Input):
    """Product view."""
    operation: Literal['record_product_view'] = Field('record_product_view', json_schema_extra={"ui:hidden": True})
    items: list[ProductRequest] = Field(..., description='List of items viewed.', json_schema_extra=JSON_EDITOR)
    occurredAt: AwareDatetime | None = Field(None, description='Timestamp of when the action occurred in [ISO 8601 format](https://xml2rfc.tools.ietf.org/public/rfc/html/rfc3339.html#date.and.time.format.examples). If the timestamp is older than 12 hours, it will not trigger any relevant journeys. If no timestamp is provided, it is assumed the event occurred when the endpoint is called.\n')
    user: EventUser = Field(..., json_schema_extra=JSON_EDITOR)


class RecordAddToCartConfig(_Input):
    """Add to cart."""
    operation: Literal['record_add_to_cart'] = Field('record_add_to_cart', json_schema_extra={"ui:hidden": True})
    items: list[ProductRequest] = Field(..., description='List of items added to cart.', json_schema_extra=JSON_EDITOR)
    occurredAt: AwareDatetime | None = Field(None, description='Timestamp of when the action occurred in [ISO 8601 format](https://xml2rfc.tools.ietf.org/public/rfc/html/rfc3339.html#date.and.time.format.examples). If the timestamp is older than 12 hours, it will not trigger any relevant journeys. If no timestamp is provided, it is assumed the event occurred when the endpoint is called.\n')
    user: EventUser = Field(..., json_schema_extra=JSON_EDITOR)


class SalesChannel(_Input):
    channelType: Literal['WEB', 'IOS_APP', 'ANDROID_APP', 'IN_STORE', 'PHONE', 'OTHER', ''] | None = Field(None, description='The type of sales channel.')


class RecordPurchaseConfig(_Input):
    """Purchase."""
    operation: Literal['record_purchase'] = Field('record_purchase', json_schema_extra={"ui:hidden": True})
    items: list[ProductRequest] = Field(..., description='List of items purchased.', json_schema_extra=JSON_EDITOR)
    orderId: str | None = Field(None, min_length=1)
    salesChannel: SalesChannel | None = Field(None, json_schema_extra=JSON_EDITOR)
    occurredAt: AwareDatetime | None = Field(None, description='Timestamp of when the action occurred in [ISO 8601 format](https://xml2rfc.tools.ietf.org/public/rfc/html/rfc3339.html#date.and.time.format.examples). If the timestamp is older than 12 hours, it will not trigger any relevant journeys. If no timestamp is provided, it is assumed the event occurred when the endpoint is called.\n')
    user: EventUser = Field(..., json_schema_extra=JSON_EDITOR)


AttentiveConfig = Annotated[Union[GetMeConfig, ListSegmentsConfig, CreateSegmentConfig, GetSegmentConfig, UpdateSegmentConfig, ArchiveSegmentConfig, SendCustomEventConfig, SetCustomAttributesConfig, GetCustomAttributesConfig, SubscribeUserConfig, GetSubscriptionsConfig, UnsubscribeUserConfig, RecordProductViewConfig, RecordAddToCartConfig, RecordPurchaseConfig], Field(discriminator="operation")]

# Exact, fixed routes; caller data can only fill encoded path components.
REQUESTS = {'get_me': {'method': 'GET',
            'path': '/v2/me',
            'query': [],
            'path_fields': [],
            'body': [],
            'success': [200]},
 'list_segments': {'method': 'GET',
                   'path': '/v2/segments',
                   'query': ['name', 'externalId', 'updatedSince', 'cursor', 'limit'],
                   'path_fields': [],
                   'body': [],
                   'success': [200]},
 'create_segment': {'method': 'POST',
                    'path': '/v2/segments',
                    'query': [],
                    'path_fields': [],
                    'body': ['name', 'description', 'externalId'],
                    'success': [201]},
 'get_segment': {'method': 'GET',
                 'path': '/v2/segments/external/{externalId}',
                 'query': [],
                 'path_fields': ['externalId'],
                 'body': [],
                 'success': [200]},
 'update_segment': {'method': 'PATCH',
                    'path': '/v2/segments/external/{externalId}',
                    'query': [],
                    'path_fields': ['externalId'],
                    'body': ['name', 'description'],
                    'success': [200]},
 'archive_segment': {'method': 'DELETE',
                     'path': '/v2/segments/external/{externalId}',
                     'query': [],
                     'path_fields': ['externalId'],
                     'body': [],
                     'success': [204]},
 'send_custom_event': {'method': 'POST',
                       'path': '/v1/events/custom',
                       'query': [],
                       'path_fields': [],
                       'body': ['type', 'properties', 'externalEventId', 'occurredAt', 'user'],
                       'success': [200]},
 'set_custom_attributes': {'method': 'POST',
                           'path': '/v1/attributes/custom',
                           'query': [],
                           'path_fields': [],
                           'body': ['properties', 'user'],
                           'success': [200]},
 'get_custom_attributes': {'method': 'GET',
                           'path': '/v1/attributes/custom',
                           'query': ['phone', 'email'],
                           'path_fields': [],
                           'body': [],
                           'success': [200]},
 'subscribe_user': {'method': 'POST',
                    'path': '/v1/subscriptions',
                    'query': [],
                    'path_fields': [],
                    'body': ['user',
                             'signUpSourceId',
                             'externalIdentifiers',
                             'locale',
                             'subscriptionType',
                             'singleOptIn',
                             'pixelTrackingConsent'],
                    'success': [202]},
 'get_subscriptions': {'method': 'GET',
                       'path': '/v1/subscriptions',
                       'query': ['phone', 'email'],
                       'path_fields': [],
                       'body': [],
                       'success': [200]},
 'unsubscribe_user': {'method': 'POST',
                      'path': '/v1/subscriptions/unsubscribe',
                      'query': [],
                      'path_fields': [],
                      'body': ['user', 'subscriptions', 'notification'],
                      'success': [202]},
 'record_product_view': {'method': 'POST',
                         'path': '/v1/events/ecommerce/product-view',
                         'query': [],
                         'path_fields': [],
                         'body': ['items', 'occurredAt', 'user'],
                         'success': [200]},
 'record_add_to_cart': {'method': 'POST',
                        'path': '/v1/events/ecommerce/add-to-cart',
                        'query': [],
                        'path_fields': [],
                        'body': ['items', 'occurredAt', 'user'],
                        'success': [200]},
 'record_purchase': {'method': 'POST',
                     'path': '/v1/events/ecommerce/purchase',
                     'query': [],
                     'path_fields': [],
                     'body': ['items', 'orderId', 'salesChannel', 'occurredAt', 'user'],
                     'success': [200]}}

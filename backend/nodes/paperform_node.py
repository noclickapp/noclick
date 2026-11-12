"""Paperform v1 form, submission, commerce and webhook operations.

Contract: https://paperform.readme.io/openapi/628f104209e221006e6c52fc
Each operation issues one request. Lists return one page with the provider's
pagination; writes are never retried automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.paperform.co/v1"


class PaperformApiTokenCredential(BaseModel):
    model_config = ConfigDict(title="Paperform API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://paperform.co/account/developer",
        "x-credential-instructions": "In Paperform, open Account → Developer and generate an API access token. Paste the token without the Bearer prefix. Your plan must include the API features you use; form, product and webhook writes require the Business API. NoClick checks access by listing your forms.",
    })
    credential_type: Literal["paperform_api_token"] = Field("paperform_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Paperform API token without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_component(cls, value, info):
        if info.field_name in {"slug_or_id", "field_key", "submission_id", "product_sku", "code", "webhook_id"}:
            if not isinstance(value, str) or not value.strip() or value in {".", ".."} or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a nonempty resource identifier without control characters")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, title="Page size")
    skip: int = Field(0, ge=0, title="Skip", description="Number of results to skip. Lists return one page.")
    after_id: str | None = None
    before_id: str | None = None
    after_date: str | None = Field(None, description="UTC date-time filter; after_id takes precedence.")
    before_date: str | None = Field(None, description="UTC date-time filter; before_id takes precedence.")
    sort: Literal["ASC", "DESC"] = "DESC"

    @field_validator("after_date", "before_date")
    @classmethod
    def date_time(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a UTC offset in the date-time")
        return value


class _Form(_Input):
    slug_or_id: str = Field(..., title="Form slug or ID", min_length=1, max_length=512)


class _Field(_Form):
    field_key: str = Field(..., title="Field key", min_length=1, max_length=512)


class _Submission(_Input):
    submission_id: str = Field(..., title="Submission ID", min_length=1, max_length=512)


class _Product(_Form):
    product_sku: str = Field(..., title="Product SKU", min_length=1, max_length=512)


class _Coupon(_Form):
    code: str = Field(..., title="Coupon code", min_length=1, max_length=512)


class ListForms(_Page):
    operation: Literal["list_forms"] = Field("list_forms", title="List Forms", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description="Search form titles.")
    search_fields: list[Literal["title", "slug", "custom_slug"]] | None = Field(None, description="Optional fields to search; sent as repeated search_fields parameters.")


class GetForm(_Form):
    operation: Literal["get_form"] = Field("get_form", title="Get Form", json_schema_extra={"ui:hidden": True})


class UpdateForm(_Form):
    operation: Literal["update_form"] = Field("update_form", title="Update Form", description="Requires the Business API.", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    description: str | None = None
    disabled: bool | None = None
    custom_slug: str | None = None
    space_id: str | None = None
    translation_id: str | None = Field(None, description="Set explicitly to null to restore the account's default translation.")


class ListFields(_Form):
    operation: Literal["list_fields"] = Field("list_fields", title="List Form Fields", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description="Search fields by name.")


class GetField(_Field):
    operation: Literal["get_field"] = Field("get_field", title="Get Form Field", json_schema_extra={"ui:hidden": True})


class ListSubmissions(_Form, _Page):
    operation: Literal["list_submissions"] = Field("list_submissions", title="List Form Submissions", json_schema_extra={"ui:hidden": True})


class GetSubmission(_Submission):
    operation: Literal["get_submission"] = Field("get_submission", title="Get Submission", json_schema_extra={"ui:hidden": True})


class DeleteSubmission(_Submission):
    operation: Literal["delete_submission"] = Field("delete_submission", title="Delete Submission", description="Permanently delete this submission.", json_schema_extra={"ui:hidden": True})


class ListPartialSubmissions(_Form, _Page):
    operation: Literal["list_partial_submissions"] = Field("list_partial_submissions", title="List Form Partial Submissions", json_schema_extra={"ui:hidden": True})


class GetPartialSubmission(_Submission):
    operation: Literal["get_partial_submission"] = Field("get_partial_submission", title="Get Partial Submission", json_schema_extra={"ui:hidden": True})


class ListProducts(_Form):
    operation: Literal["list_products"] = Field("list_products", title="List Form Products", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description="Search products by name.")


class GetProduct(_Product):
    operation: Literal["get_product"] = Field("get_product", title="Get Form Product", json_schema_extra={"ui:hidden": True})


class ProductImage(_Input):
    url: str
    width: int
    height: int | None = None


class _ProductValues(_Input):
    name: str | None = None
    quantity: int | None = None
    price: float | None = Field(None, allow_inf_nan=False)
    minimum: int | None = None
    maximum: int | None = None
    discountable: bool | None = None
    images: list[ProductImage] | None = None


class CreateProduct(_Form, _ProductValues):
    operation: Literal["create_product"] = Field("create_product", title="Create Form Product", description="Requires the Business API.", json_schema_extra={"ui:hidden": True})
    product_field_key: str = Field(..., min_length=1, title="Product field key")
    SKU: str = Field(..., min_length=1, title="New product SKU")
    name: str = Field(..., min_length=1)
    price: float = Field(..., allow_inf_nan=False)


class UpdateProduct(_Product, _ProductValues):
    operation: Literal["update_product"] = Field("update_product", title="Update Form Product", description="Requires the Business API.", json_schema_extra={"ui:hidden": True})


class DeleteProduct(_Product):
    operation: Literal["delete_product"] = Field("delete_product", title="Delete Form Product", json_schema_extra={"ui:hidden": True})


class UpdateProductQuantity(_Product):
    operation: Literal["update_product_quantity"] = Field("update_product_quantity", title="Set Product Quantity", json_schema_extra={"ui:hidden": True})
    quantity: int = Field(..., description="Replacement quantity, not an increment.")


class UpdateProductSold(_Product):
    operation: Literal["update_product_sold"] = Field("update_product_sold", title="Set Product Sold Count", json_schema_extra={"ui:hidden": True})
    sold: int = Field(..., description="Replacement sold count, not an increment.")


class ListCoupons(_Form):
    operation: Literal["list_coupons"] = Field("list_coupons", title="List Form Coupons", json_schema_extra={"ui:hidden": True})


class GetCoupon(_Coupon):
    operation: Literal["get_coupon"] = Field("get_coupon", title="Get Form Coupon", json_schema_extra={"ui:hidden": True})


class _CouponValues(_Input):
    enabled: bool | None = None
    target: Literal["price", "subscription"] | None = None
    discountAmount: float | None = Field(None, ge=0, allow_inf_nan=False, title="Discount amount")
    discountPercentage: float | None = Field(None, ge=0, le=100, allow_inf_nan=False, title="Discount percentage")
    expiresAt: str | None = Field(None, title="Expires at", description="ISO 8601 date-time; explicitly null removes expiry.")
    _expiry = field_validator("expiresAt")(_Page.date_time.__func__)


class CreateCoupon(_Coupon, _CouponValues):
    operation: Literal["create_coupon"] = Field("create_coupon", title="Create Form Coupon", json_schema_extra={"ui:hidden": True})


class UpdateCoupon(_Coupon, _CouponValues):
    operation: Literal["update_coupon"] = Field("update_coupon", title="Update Form Coupon", json_schema_extra={"ui:hidden": True})


class DeleteCoupon(_Coupon):
    operation: Literal["delete_coupon"] = Field("delete_coupon", title="Delete Form Coupon", json_schema_extra={"ui:hidden": True})


class ListWebhooks(_Form, _Page):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Form Webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(_Form):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Form Webhook", description="Paperform will send submission data to this URL when a selected trigger fires.", json_schema_extra={"ui:hidden": True})
    target_url: str = Field(..., title="Webhook URL", json_schema_extra={"format": "uri"})
    triggers: list[Literal["submission", "partial_submission"]] = Field(..., min_length=1, max_length=2)

    @field_validator("target_url")
    @classmethod
    def webhook_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use an absolute HTTPS webhook URL without user information or fragments")
        return value


class DeleteWebhook(_Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: str = Field(..., title="Webhook ID", min_length=1, max_length=512)


# Paperform's own MCP server: agents get its tools through a person's Paperform sign-in.
PaperformMcpCredential = mcp_credential("paperform", "https://api.paperform.app/mcp", app="Paperform")
PaperformCredential = Union[PaperformApiTokenCredential, PaperformMcpCredential]


Operation = Annotated[Union[ListForms, GetForm, UpdateForm, ListFields, GetField,
    ListSubmissions, GetSubmission, DeleteSubmission, ListPartialSubmissions, GetPartialSubmission,
    ListProducts, GetProduct, CreateProduct, UpdateProduct, DeleteProduct, UpdateProductQuantity,
    UpdateProductSold, ListCoupons, GetCoupon, CreateCoupon, UpdateCoupon, DeleteCoupon,
    ListWebhooks, CreateWebhook, DeleteWebhook], Field(discriminator="operation")]


class PaperformNodeConfig(NodeConfig[Operation, PaperformCredential]):
    pass


# method, path, result key, list result, paginated, body fields
_PRODUCT_FIELDS = ("name", "quantity", "price", "minimum", "maximum", "discountable", "images")
_COUPON_FIELDS = ("enabled", "target", "discountAmount", "discountPercentage", "expiresAt")
ROUTES = {
    "list_forms": ("GET", "/forms", "forms", True, True, ()),
    "get_form": ("GET", "/forms/{slug_or_id}", "form", False, False, ()),
    "update_form": ("PUT", "/forms/{slug_or_id}", "form", False, False, ("title", "description", "disabled", "custom_slug", "space_id", "translation_id")),
    "list_fields": ("GET", "/forms/{slug_or_id}/fields", "fields", True, False, ()),
    "get_field": ("GET", "/forms/{slug_or_id}/fields/{field_key}", "field", False, False, ()),
    "list_submissions": ("GET", "/forms/{slug_or_id}/submissions", "submissions", True, True, ()),
    "get_submission": ("GET", "/submissions/{submission_id}", "submission", False, False, ()),
    "delete_submission": ("DELETE", "/submissions/{submission_id}", None, False, False, ()),
    "list_partial_submissions": ("GET", "/forms/{slug_or_id}/partial-submissions", "partial-submissions", True, True, ()),
    "get_partial_submission": ("GET", "/partial-submissions/{submission_id}", "partial-submission", False, False, ()),
    "list_products": ("GET", "/forms/{slug_or_id}/products", "products", True, False, ()),
    "get_product": ("GET", "/forms/{slug_or_id}/products/{product_sku}", "products", True, False, ()),
    "create_product": ("POST", "/forms/{slug_or_id}/products", "product", False, False, ("product_field_key", "SKU", *_PRODUCT_FIELDS)),
    "update_product": ("PUT", "/forms/{slug_or_id}/products/{product_sku}", "product", False, False, _PRODUCT_FIELDS),
    "delete_product": ("DELETE", "/forms/{slug_or_id}/products/{product_sku}", None, False, False, ()),
    "update_product_quantity": ("PUT", "/forms/{slug_or_id}/products/{product_sku}/quantity", "product", False, False, ("quantity",)),
    "update_product_sold": ("PUT", "/forms/{slug_or_id}/products/{product_sku}/sold", "product", False, False, ("sold",)),
    "list_coupons": ("GET", "/forms/{slug_or_id}/coupons", "coupons", True, False, ()),
    "get_coupon": ("GET", "/forms/{slug_or_id}/coupons/{code}", "coupon", False, False, ()),
    "create_coupon": ("POST", "/forms/{slug_or_id}/coupons", "coupon", False, False, ("code", *_COUPON_FIELDS)),
    "update_coupon": ("PUT", "/forms/{slug_or_id}/coupons/{code}", "coupon", False, False, _COUPON_FIELDS),
    "delete_coupon": ("DELETE", "/forms/{slug_or_id}/coupons/{code}", None, False, False, ()),
    "list_webhooks": ("GET", "/forms/{slug_or_id}/webhooks", "webhooks", True, True, ()),
    "create_webhook": ("POST", "/forms/{slug_or_id}/webhooks", "webhook", False, False, ("target_url", "triggers")),
    "delete_webhook": ("DELETE", "/webhooks/{webhook_id}", None, False, False, ()),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class PaperformNode(WorkflowNode):
    integration_type = "automation-paperform"
    credential_provider_labels = {"paperform": "Paperform Account"}
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms", label_keys=("title", "slug", "id"))

    @classmethod
    def get_config_model(cls):
        return PaperformNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Paperform API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, key, is_list, paginated, body_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format_map({k: quote(str(v), safe="") for k, v in values.items()})
        params = {}
        if method == "GET":
            if paginated:
                params.update({k: values[k] for k in ("limit", "skip", "sort", "after_id", "before_id", "after_date", "before_date") if k in values})
            for name in ("search", "search_fields"):
                if name in values:
                    params[name] = values[name]
        body = None
        if body_fields:
            supplied = op.model_dump(exclude_unset=True)
            body = {name: supplied[name] for name in body_fields if name in supplied}
            # null is a documented clearing value only for nullable fields.
            nonnullable = {"disabled", "images", "enabled", "target", "discountAmount", "discountPercentage", "quantity", "sold", "target_url", "triggers", "code", "SKU", "product_field_key"}
            body = {k: v for k, v in body.items() if v is not None or k not in nonnullable or (k == "quantity" and op.operation in {"create_product", "update_product"})}
            if body.get("images") is not None:
                body["images"] = [image.model_dump(exclude_none=True) for image in op.images]
            if not body:
                raise ValueError("Provide at least one field to update")
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Paperform request did not complete; inspect the provider before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Paperform response exceeds the supported size")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Paperform returned an unexpected non-JSON response") from None
        counter_update = op.operation in {"update_product_quantity", "update_product_sold"}
        accepted = isinstance(payload, dict) and (type(payload.get("ok")) is int and payload.get("ok") == 1 if counter_update else payload.get("status") == "ok")
        if response.status_code != 200 or not accepted:
            message = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
            if not isinstance(message, str):
                message = "Paperform rejected the request"
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, token)}
        output = {"status": "success", "http_status": response.status_code, "operation": op.operation}
        if counter_update:
            output["update_acknowledged"] = True
        elif key is None:
            output["deletion_acknowledged"] = True
        else:
            results = payload.get("results")
            data = results.get(key) if isinstance(results, dict) else None
            if not isinstance(data, list if is_list else dict):
                raise ValueError("Paperform response is missing the documented " + key + " result")
            if is_list and any(not isinstance(item, dict) for item in data):
                raise ValueError("Paperform list contains an invalid record")
            output["data"] = data
            if paginated:
                pagination = {k: payload[k] for k in ("total", "has_more", "limit", "skip") if k in payload}
                output["pagination"] = pagination
        return _redact(output, token)

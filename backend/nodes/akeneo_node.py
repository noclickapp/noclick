"""Akeneo PIM REST API, pinned to the provider's published OpenAPI 1.0.0.

Bearer usage: https://api.akeneo.com/documentation/authentication.html
Updated filtering: https://api.akeneo.com/documentation/filter.html
Product webhooks: https://api.akeneo.com/event-platform/concepts.html
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client


class AkeneoTokenCredential(BaseModel):
    model_config = ConfigDict(title="Akeneo Bearer Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.akeneo.com/documentation/authentication.html",
        "x-credential-instructions": "Enter your Akeneo PIM HTTPS URL and an existing bearer access token. Connector tokens normally expire after one hour: replace an expired token here. An existing App token can also be pasted. NoClick does not generate or refresh tokens. Grant read access to products for connection verification and the permissions needed for your operations.",
    })
    credential_type: Literal["akeneo_token"] = Field("akeneo_token", json_schema_extra={"ui:hidden": True})
    pim_url: str = Field(..., title="PIM URL", description="Your Akeneo PIM origin, for example https://my-pim.cloud.akeneo.com")
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("pim_url", mode="before")
    @classmethod
    def origin(cls, value):
        value = https_origin(value, field_name="PIM URL")
        if not value.startswith("https://"):
            raise ValueError("Use an HTTPS PIM URL")
        return value

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _List(_Input):
    page: int = Field(1, ge=1, le=10000, description="Page number. Product lists beyond 10,000 items require search-after pagination.")
    limit: int = Field(100, ge=1, le=100)


class _ProductList(_List):
    search: str | None = Field(None, description="Akeneo JSON search object. Supports updated/created filters.", json_schema_extra={"ui:widget": "textarea"})
    scope: str | None = None
    locales: str | None = Field(None, description="Comma-separated locale codes")
    attributes: str | None = Field(None, description="Comma-separated attribute codes")
    search_after: str | None = Field(None, description="Cursor returned by a previous search-after page. Leave empty for the first page.")
    pagination_type: Literal["page", "search_after"] = "page"

    @field_validator("search")
    @classmethod
    def search_object(cls, value):
        if value is not None and not isinstance(json.loads(value), dict):
            raise ValueError("Search must be a JSON object")
        return value

    @model_validator(mode="after")
    def cursor_mode(self):
        if self.search_after and self.pagination_type != "search_after":
            raise ValueError("Use search_after pagination with a cursor")
        return self


class _Code(_Input):
    code: str = Field(..., min_length=1, max_length=255, description="Exact Akeneo resource code")


class _Uuid(_Input):
    uuid: str = Field(..., title="Product UUID")

    @field_validator("uuid")
    @classmethod
    def valid_uuid(cls, value):
        return str(UUID(value))


class _ProductWrite(_Input):
    enabled: bool | None = None
    family: str | None = None
    categories: list[str] | None = None
    groups: list[str] | None = None
    parent: str | None = None
    values: dict[str, list[dict[str, Any]]] | None = Field(None, description="Attribute codes mapped to arrays of {data, locale, scope}. Supply writable values only.")

    @field_validator("values")
    @classmethod
    def writable_values(cls, value):
        if value is not None:
            for entries in value.values():
                for entry in entries:
                    if "data" not in entry or set(entry) - {"data", "locale", "scope"}:
                        raise ValueError("Each value needs data and only writable locale/scope fields")
        return value


class _ProductCreate(_ProductWrite):
    uuid: str | None = None

    @field_validator("uuid")
    @classmethod
    def valid_uuid(cls, value):
        return str(UUID(value)) if value is not None else None


class _ProductUpdate(_Uuid, _ProductWrite):
    pass


class _ModelWrite(_Code):
    family: str | None = None
    parent: str | None = None
    categories: list[str] | None = None
    values: dict[str, list[dict[str, Any]]] | None = None

    _values = field_validator("values")(_ProductWrite.writable_values.__func__)


class _ModelCreate(_ModelWrite):
    family_variant: str = Field(..., min_length=1)


class _ModelUpdate(_ModelWrite):
    family_variant: str | None = None


class _CategoryWrite(_Code):
    parent: str | None = None
    labels: dict[str, str | None] | None = None


class _FamilyWrite(_Code):
    attributes: list[str] | None = None
    attribute_as_label: str | None = None
    attribute_as_image: str | None = None
    attribute_requirements: dict[str, list[str]] | None = None
    labels: dict[str, str | None] | None = None


class _OptionList(_List):
    attribute_code: str = Field(..., min_length=1, max_length=255)


class _OptionWrite(_Code):
    attribute_code: str = Field(..., min_length=1, max_length=255)
    sort_order: int | None = Field(None, ge=0)
    labels: dict[str, str | None] | None = None


class _SubscriberCreate(_Input):
    pim_client_id: str = Field(..., min_length=1, title="PIM client ID")
    name: str = Field("NoClick", title="Subscriber name")
    technical_email: EmailStr = Field(..., title="Technical contact email")


# Each entry makes exactly one request to one operation in the pinned contract.
# name -> method, route, model, query names
OPERATIONS = {
    "create_event_subscriber": ("POST", "/subscribers", _SubscriberCreate, ()),
    "list_products": ("GET", "/products-uuid", _ProductList, ("page", "limit", "search", "scope", "locales", "attributes", "pagination_type", "search_after")),
    "get_product": ("GET", "/products-uuid/{uuid}", _Uuid, ()),
    "create_product": ("POST", "/products-uuid", _ProductCreate, ()),
    "upsert_product": ("PATCH", "/products-uuid/{uuid}", _ProductUpdate, ()),
    "delete_product": ("DELETE", "/products-uuid/{uuid}", _Uuid, ()),
    "list_product_models": ("GET", "/product-models", _ProductList, ("page", "limit", "search", "scope", "locales", "attributes", "pagination_type", "search_after")),
    "get_product_model": ("GET", "/product-models/{code}", _Code, ()),
    "create_product_model": ("POST", "/product-models", _ModelCreate, ()),
    "upsert_product_model": ("PATCH", "/product-models/{code}", _ModelUpdate, ()),
    "delete_product_model": ("DELETE", "/product-models/{code}", _Code, ()),
    "list_categories": ("GET", "/categories", _List, ("page", "limit")),
    "get_category": ("GET", "/categories/{code}", _Code, ()),
    "upsert_category": ("PATCH", "/categories/{code}", _CategoryWrite, ()),
    "list_families": ("GET", "/families", _List, ("page", "limit")),
    "get_family": ("GET", "/families/{code}", _Code, ()),
    "upsert_family": ("PATCH", "/families/{code}", _FamilyWrite, ()),
    "list_attributes": ("GET", "/attributes", _List, ("page", "limit")),
    "get_attribute": ("GET", "/attributes/{code}", _Code, ()),
    "list_attribute_options": ("GET", "/attributes/{attribute_code}/options", _OptionList, ("page", "limit")),
    "upsert_attribute_option": ("PATCH", "/attributes/{attribute_code}/options/{code}", _OptionWrite, ()),
    "list_channels": ("GET", "/channels", _List, ("page", "limit")),
    "list_locales": ("GET", "/locales", _List, ("page", "limit")),
    "get_media_file": ("GET", "/media-files/{code}", _Code, ()),
}


def _config(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Akeneo" + label.replace(" ", "") + "Config", __base__=spec[2],
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
            "x-category": "Read" if spec[0] == "GET" else "Write"})))


CONFIGS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIGS.values()})


PRODUCT_EVENTS = (
    "com.akeneo.pim.v1.product.created",
    "com.akeneo.pim.v1.product.updated",
    "com.akeneo.pim.v1.product.deleted",
)


class AkeneoProductEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_product_event"] = Field("on_product_event", json_schema_extra={
        "const": "on_product_event", "ui:hidden": True, "x-display-name": "Product Created, Updated or Deleted",
        "x-is-trigger": True, "x-category": "Triggers"})
    pim_client_id: str = Field(..., min_length=1, title="PIM client ID", description="The connection or App client ID that issued your PIM token. Enable Event Platform permission for this connection in Akeneo.")
    subscriber_id: UUID = Field(..., title="Event Platform subscriber ID", description="Choose a subscriber linked to this PIM connection. Use Create Event Subscriber once if none exists. NoClick removes only this workflow's HTTPS subscription.", json_schema_extra={"x-dynamic-options": {"field_name": "subscriber_id", "depends_on": "pim_client_id", "allow_custom": True, "placeholder": "Choose an Event Platform subscriber"}})
    events: list[Literal[PRODUCT_EVENTS]] = Field(list(PRODUCT_EVENTS), min_length=1, title="Product events")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


AkeneoConfig = Annotated[Union[tuple(CONFIGS.values()) + (AkeneoProductEventConfig,)], Field(discriminator="operation")]


class AkeneoNodeConfig(NodeConfig[AkeneoConfig, AkeneoTokenCredential]):
    pass


class AkeneoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-akeneo"
    connection_evidence = ConnectionEvidence(operation="list_products", noun="products")

    @classmethod
    def get_config_model(cls):
        return AkeneoNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: config.get(key) for key in ("pim_client_id", "subscriber_id", "events")}

    @staticmethod
    async def _event_request(credential, config, method, path, *, body=None):
        data = AkeneoTokenCredential.model_validate(credential)
        client_id = config.get("pim_client_id")
        if not client_id:
            raise ValueError("Enter the PIM connection client ID before registering product events")
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, "https://event.prd.sdk.akeneo.cloud/api/v1" + path,
                json=body, headers={"x-pim-token": data.access_token, "x-pim-url": data.pim_url,
                                    "x-pim-client-id": client_id, "Accept": "application/json"})
        if response.status_code not in {200, 201, 204}:
            raise ValueError(f"Akeneo Event Platform API error (HTTP {response.status_code})")
        return response.json() if response.content else {}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "subscriber_id":
            return {"options": []}
        context = context or {}
        config = context.get("config") if isinstance(context.get("config"), dict) else context
        if not config.get("pim_client_id"):
            return {"options": []}
        rows = await cls._event_request(credential_data, config, "GET", "/subscribers")
        if not isinstance(rows, list):
            raise ValueError("Akeneo returned an invalid subscriber list")
        options = [{"value": str(UUID(str(row["id"]))), "label": row.get("name") or str(row["id"])} for row in rows]
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        return {"options": options}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        subscriber = str(UUID(str(config["subscriber_id"])))
        events = config.get("events") or list(PRODUCT_EVENTS)
        if not events or any(event not in PRODUCT_EVENTS for event in events):
            raise ValueError("Choose supported Akeneo product events")
        secret = secrets.token_urlsafe(32)
        data = await cls._event_request(credential, config, "POST", f"/subscribers/{subscriber}/subscriptions", body={
            "source": "pim", "subject": AkeneoTokenCredential.model_validate(credential).pim_url,
            "type": "https", "events": events, "send_product_identifier": True,
            "config": {"url": webhook_url, "secret": {"primary": secret}}})
        subscription = str(UUID(str(data.get("id"))))
        return {"external_webhook_id": subscription, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential is None or not config.get("external_webhook_id"):
            return
        subscriber = str(UUID(str(config["subscriber_id"])))
        subscription = str(UUID(str(config["external_webhook_id"])))
        await cls._event_request(credential, config, "DELETE", f"/subscribers/{subscriber}/subscriptions/{subscription}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        normalized = {key.lower(): value for key, value in headers.items()}
        if normalized.get("x-akeneo-signature-algorithm", "HmacSHA256") != "HmacSHA256":
            return False
        actual = normalized.get("x-akeneo-signature-primary", "")
        if not isinstance(actual, str) or len(actual) != 64:
            return False
        try:
            supplied = bytes.fromhex(actual)
        except ValueError:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        return hmac.compare_digest(expected, supplied)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") in (config.get("events") or PRODUCT_EVENTS)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"operation": "on_product_event", "event_id": payload["id"], "event_type": payload["type"],
                "time": payload["time"], "pim_subject": payload["subject"],
                "product": payload["data"]["product"], "author": payload["data"]["author"]}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") != "on_product_event":
            return super().resolve_agent_event(output)
        product, author = output["product"], output["author"]
        verb = output["event_type"].rsplit(".", 1)[-1]
        identifier = product.get("identifier") or product["uuid"]
        text = (f"Akeneo product {identifier} was {verb} by {author['type']} {author['identifier']} "
                f"in PIM {output['pim_subject']} at {output['time']}. "
                f"Product UUID: {product['uuid']}. Event ID: {output['event_id']}.")
        if verb != "deleted":
            text += " Use Get Product with this UUID to read its current attribute values."
        return {"text": text, "conversation_key": f"akeneo:{output['pim_subject']}:{product['uuid']}"}

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, credential.pim_url + "/api/rest/v1" + path,
                params=params, json=body, headers={"Authorization": "Bearer " + credential.access_token,
                "Accept": "application/json", "Content-Type": "application/json"})
        if response.is_error:
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            detail = message.replace(credential.access_token, "[redacted]") if isinstance(message, str) else "request rejected"
            raise ValueError(f"Akeneo API error (HTTP {response.status_code}): {detail}")
        if response.status_code not in {200, 201, 204}:
            raise ValueError(f"Unexpected Akeneo response (HTTP {response.status_code})")
        return response.status_code, response.json() if response.content else None, response.headers.get("Location")

    @staticmethod
    def _items(body):
        if not isinstance(body, dict) or not isinstance(body.get("_embedded"), dict) or not isinstance(body["_embedded"].get("items"), list):
            raise ValueError("Akeneo returned an invalid list envelope")
        items = body["_embedded"]["items"]
        if not all(isinstance(row, dict) for row in items):
            raise ValueError("Akeneo returned an invalid resource")
        return items

    async def execute(self, inputs):
        if not isinstance(self.config, AkeneoNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Akeneo PIM bearer token")
        credential, config = self.config.credentials, self.config.config
        if isinstance(config, AkeneoProductEventConfig):
            return self.no_event_output(config.operation)
        if config.operation == "create_event_subscriber":
            data = await self._event_request(credential.model_dump(), config.model_dump(), "POST", "/subscribers", body={
                "name": config.name, "contact": {"technical_email": config.technical_email}})
            UUID(str(data.get("id")))
            result = {"status": "success", "operation": config.operation, "data": data,
                      "acknowledged": True, "readback_verified": False}
            await self.emit(result)
            return result
        method, path, _, query_names = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_unset=method not in {"GET", "DELETE"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {k: v for k, v in values.items() if k in query_names and v is not None}
        if params.get("pagination_type") == "search_after":
            params.pop("page", None)
        body = {k: v for k, v in values.items() if k not in query_names} if method in {"POST", "PATCH"} else None
        if body is not None:
            nullable = {"parent", "attribute_as_image"}
            if config.operation in {"create_product", "upsert_product"}:
                nullable.add("family")
            body = {k: v for k, v in body.items() if v is not None or k in nullable}
        # PATCH codes come from the path; sending {} is a valid provider upsert request.
        status, data, location = await self._request(credential, method, path, params=params, body=body)
        result = {"status": "success", "operation": config.operation, "http_status": status}
        if config.operation.startswith("list_"):
            result.update(items=self._items(data), links=data.get("_links", {}), current_page=data.get("current_page"))
        elif method == "GET":
            if not isinstance(data, dict):
                raise ValueError("Akeneo returned an invalid resource")
            result["data"] = data
        else:
            result.update(acknowledged=True, readback_verified=False, data=data)
            if location:
                result["location"] = location
        await self.emit(result)
        return result

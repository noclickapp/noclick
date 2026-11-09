"""Kontent.ai Management API v2 operations using a pasted API key.

The pinned provider Postman collection supplies saved response examples.
Writes cover item metadata, language creation and variant lifecycle; content
schema editing and language-variant element writes are not exposed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://manage.kontent.ai/v2/projects/"
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


class KontentAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kontent.ai Management API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.kontent.ai/",
            "x-credential-instructions": "In Kontent.ai, open your environment's API keys and copy a Management API key and the environment ID. Paste the key without the Bearer prefix. The key must permit the operations you use. NoClick reads environment information to verify this connection. Replace expired keys manually.",
        })
    credential_type: Literal["kontent_ai_api_key"] = Field("kontent_ai_api_key", json_schema_extra={"ui:hidden": True})
    environment_id: str = Field(..., title="Environment ID", pattern="^" + UUID_PATTERN + "$", description="The environment UUID from Kontent.ai API keys.")
    api_key: str = Field(..., title="Management API key", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Management API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Management API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    continuation_token: str | None = Field(None, max_length=8192, description="X-Continuation value from the previous response. Each run returns one page; pass this token to continue.")

    @field_validator("continuation_token")
    @classmethod
    def token(cls, value):
        if value is not None and (not value or any(ord(c) < 33 or ord(c) > 126 for c in value)):
            raise ValueError("Use the opaque continuation token returned by the API")
        return value


class KontentAiGetEnvironmentConfig(_Input):
    """Retrieve environment information."""
    operation: Literal["get_environment"] = Field("get_environment", json_schema_extra={"ui:hidden": True})

class KontentAiListItemsConfig(_Page):
    """List content items."""
    operation: Literal["list_items"] = Field("list_items", json_schema_extra={"ui:hidden": True})

class KontentAiGetItemConfig(_Input):
    """Retrieve a content item."""
    operation: Literal["get_item"] = Field("get_item", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiUpdateItemConfig(_Input):
    """Upsert a content item."""
    operation: Literal["update_item"] = Field("update_item", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    name: str = Field(..., min_length=1, max_length=1000, description="New display name for this existing content item. This operation updates metadata; it does not write element content.")
    codename: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")

class KontentAiDeleteItemConfig(_Input):
    """Delete a content item."""
    operation: Literal["delete_item"] = Field("delete_item", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiListVariantsConfig(_Input):
    """Retrieve language variants of an item."""
    operation: Literal["list_variants"] = Field("list_variants", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiGetVariantConfig(_Input):
    """Retrieve the latest language variant."""
    operation: Literal["get_variant"] = Field("get_variant", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiGetPublishedVariantConfig(_Input):
    """Retrieve the published language variant."""
    operation: Literal["get_published_variant"] = Field("get_published_variant", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiDeleteVariantConfig(_Input):
    """Delete a language variant."""
    operation: Literal["delete_variant"] = Field("delete_variant", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiCreateVariantVersionConfig(_Input):
    """Create a new version of a language variant."""
    operation: Literal["create_variant_version"] = Field("create_variant_version", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiPublishVariantConfig(_Input):
    """Publish or schedule a language variant."""
    operation: Literal["publish_variant"] = Field("publish_variant", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiUnpublishVariantConfig(_Input):
    """Unpublish or schedule unpublishing of a language variant."""
    operation: Literal["unpublish_variant"] = Field("unpublish_variant", json_schema_extra={"ui:hidden": True})
    item_identifier: str = Field(..., title="Item Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiListAssetsConfig(_Page):
    """List assets."""
    operation: Literal["list_assets"] = Field("list_assets", json_schema_extra={"ui:hidden": True})

class KontentAiGetAssetConfig(_Input):
    """Retrieve an asset."""
    operation: Literal["get_asset"] = Field("get_asset", json_schema_extra={"ui:hidden": True})
    asset_identifier: str = Field(..., title="Asset Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiDeleteAssetConfig(_Input):
    """Delete an asset."""
    operation: Literal["delete_asset"] = Field("delete_asset", json_schema_extra={"ui:hidden": True})
    asset_identifier: str = Field(..., title="Asset Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiListTypesConfig(_Page):
    """List content types."""
    operation: Literal["list_types"] = Field("list_types", json_schema_extra={"ui:hidden": True})

class KontentAiGetTypeConfig(_Input):
    """Retrieve a content type."""
    operation: Literal["get_type"] = Field("get_type", json_schema_extra={"ui:hidden": True})
    type_identifier: str = Field(..., title="Type Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiListLanguagesConfig(_Page):
    """List languages."""
    operation: Literal["list_languages"] = Field("list_languages", json_schema_extra={"ui:hidden": True})

class KontentAiGetLanguageConfig(_Input):
    """Retrieve a language."""
    operation: Literal["get_language"] = Field("get_language", json_schema_extra={"ui:hidden": True})
    language_identifier: str = Field(..., title="Language Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiCreateLanguageConfig(_Input):
    """Add a language."""
    operation: Literal["create_language"] = Field("create_language", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    codename: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")

class KontentAiListTaxonomiesConfig(_Page):
    """List taxonomy groups."""
    operation: Literal["list_taxonomies"] = Field("list_taxonomies", json_schema_extra={"ui:hidden": True})

class KontentAiGetTaxonomyConfig(_Input):
    """Retrieve a taxonomy group."""
    operation: Literal["get_taxonomy"] = Field("get_taxonomy", json_schema_extra={"ui:hidden": True})
    taxonomy_group_identifier: str = Field(..., title="Taxonomy Group Identifier", pattern="^" + UUID_PATTERN + "$", description="Kontent.ai internal UUID.")

class KontentAiListCollectionsConfig(_Page):
    """List collections."""
    operation: Literal["list_collections"] = Field("list_collections", json_schema_extra={"ui:hidden": True})

class KontentAiListWorkflowsConfig(_Page):
    """Retrieve workflows."""
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})


KontentAiConfig = Annotated[Union[
    KontentAiGetEnvironmentConfig,
    KontentAiListItemsConfig,
    KontentAiGetItemConfig,
    KontentAiUpdateItemConfig,
    KontentAiDeleteItemConfig,
    KontentAiListVariantsConfig,
    KontentAiGetVariantConfig,
    KontentAiGetPublishedVariantConfig,
    KontentAiDeleteVariantConfig,
    KontentAiCreateVariantVersionConfig,
    KontentAiPublishVariantConfig,
    KontentAiUnpublishVariantConfig,
    KontentAiListAssetsConfig,
    KontentAiGetAssetConfig,
    KontentAiDeleteAssetConfig,
    KontentAiListTypesConfig,
    KontentAiGetTypeConfig,
    KontentAiListLanguagesConfig,
    KontentAiGetLanguageConfig,
    KontentAiCreateLanguageConfig,
    KontentAiListTaxonomiesConfig,
    KontentAiGetTaxonomyConfig,
    KontentAiListCollectionsConfig,
    KontentAiListWorkflowsConfig], Field(discriminator="operation")]


class KontentAiFullConfig(NodeConfig[KontentAiConfig, KontentAiAPIKeyCredential]):
    pass


ROUTES = {'get_environment': ('GET', '', 'read', []),
 'list_items': ('GET', '/items', 'list', []),
 'get_item': ('GET', '/items/{item_identifier}', 'read', ['item_identifier']),
 'update_item': ('PUT', '/items/{item_identifier}', 'write', ['item_identifier']),
 'delete_item': ('DELETE', '/items/{item_identifier}', 'write', ['item_identifier']),
 'list_variants': ('GET', '/items/{item_identifier}/variants', 'read', ['item_identifier']),
 'get_variant': ('GET',
                 '/items/{item_identifier}/variants/{language_identifier}',
                 'read',
                 ['item_identifier', 'language_identifier']),
 'get_published_variant': ('GET',
                           '/items/{item_identifier}/variants/{language_identifier}/published',
                           'read',
                           ['item_identifier', 'language_identifier']),
 'delete_variant': ('DELETE',
                    '/items/{item_identifier}/variants/{language_identifier}',
                    'write',
                    ['item_identifier', 'language_identifier']),
 'create_variant_version': ('PUT',
                            '/items/{item_identifier}/variants/{language_identifier}/new-version',
                            'write',
                            ['item_identifier', 'language_identifier']),
 'publish_variant': ('PUT',
                     '/items/{item_identifier}/variants/{language_identifier}/publish',
                     'write',
                     ['item_identifier', 'language_identifier']),
 'unpublish_variant': ('PUT',
                       '/items/{item_identifier}/variants/{language_identifier}/unpublish-and-archive',
                       'write',
                       ['item_identifier', 'language_identifier']),
 'list_assets': ('GET', '/assets', 'list', []),
 'get_asset': ('GET', '/assets/{asset_identifier}', 'read', ['asset_identifier']),
 'delete_asset': ('DELETE', '/assets/{asset_identifier}', 'write', ['asset_identifier']),
 'list_types': ('GET', '/types', 'list', []),
 'get_type': ('GET', '/types/{type_identifier}', 'read', ['type_identifier']),
 'list_languages': ('GET', '/languages', 'list', []),
 'get_language': ('GET', '/languages/{language_identifier}', 'read', ['language_identifier']),
 'create_language': ('POST', '/languages', 'write', []),
 'list_taxonomies': ('GET', '/taxonomies', 'list', []),
 'get_taxonomy': ('GET',
                  '/taxonomies/{taxonomy_group_identifier}',
                  'read',
                  ['taxonomy_group_identifier']),
 'list_collections': ('GET', '/collections', 'list', []),
 'list_workflows': ('GET', '/workflows', 'list', [])}


class KontentAiNode(WorkflowNode):
    integration_type = "automation-kontent-ai"
    connection_evidence = ConnectionEvidence(noun="Kontent.ai environment", identity_operation="get_environment")

    @classmethod
    def get_config_model(cls):
        return KontentAiFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Kontent.ai Management API key")
        credential = self.config.credentials
        config = self.config.config
        method, route, mode, path_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = route.format(**{key: quote(values.pop(key), safe="") for key in path_fields})
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        continuation = values.pop("continuation_token", None)
        if continuation is not None:
            headers["X-Continuation"] = continuation
        body = values if config.operation in {"update_item", "create_language"} else None
        # Empty JSON means publish/unpublish immediately, without scheduling.
        if config.operation in {"publish_variant", "unpublish_variant"}:
            body = {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + credential.environment_id + path,
                    headers=headers, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Kontent.ai request failed; inspect the connection before retrying writes") from None
        if not 200 <= response.status_code < 300:
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = ": " + error["message"][:2000].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            raise ValueError(f"Kontent.ai rejected the request (HTTP {response.status_code}){message}")
        if response.status_code == 204:
            return {"operation": config.operation, "http_status": 204, "acknowledged": True, "data": None}
        if len(response.content) > 8_000_000 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise ValueError("Expected a bounded JSON response from Kontent.ai")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Kontent.ai returned invalid JSON") from None
        if not isinstance(data, (dict, list)) or isinstance(data, dict) and any(k in data for k in ("error_code", "error", "errors")):
            raise ValueError("Kontent.ai did not confirm the request")

        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k.replace(credential.api_key, "[redacted]"): redact(v) for k, v in value.items()
                    if k.lower() not in {"api_key", "access_token", "refresh_token", "password", "client_secret"}}
            return value

        result = {"operation": config.operation, "http_status": response.status_code, "data": redact(data)}
        if mode == "list":
            # Preserve provider envelopes (including collection-saved placeholders).
            # Never follow pagination.next_page: the next request uses our fixed host.
            pagination = data.get("pagination") if isinstance(data, dict) else None
            next_token = response.headers.get("X-Continuation")
            if not next_token and isinstance(pagination, dict):
                next_token = pagination.get("continuation_token")
            if next_token is not None and not isinstance(next_token, str):
                raise ValueError("Kontent.ai returned an invalid continuation token")
            result["next_continuation_token"] = redact(next_token) if next_token else None
        return result

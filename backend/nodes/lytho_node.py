"""Lytho DAM actions against the published V1.5.0 OpenAPI contract.

API keys are tenant-bound. Polling uses documented date filters and the shared
scoped baseline; mutations never retry automatically.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://openapi.lytho.io/v1"
DOCS = "https://help.lytho.com/getting-started-with-the-api-dam"
ResourceId = Annotated[str, StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class LythoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Lytho API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS,
        "x-credential-instructions": "In Lytho DAM, open Settings → Advanced → API management. Add an API access key and paste its Value. The key is bound to your tenant. These operations use the published openapi.lytho.io/v1 API.",
    })
    credential_type: Literal["lytho_api_key"] = Field("lytho_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key value")
        return value


class LythoInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class LythoPage(LythoInput):
    page: int = Field(0, ge=0, description="Zero-based page number.")
    size: int = Field(20, ge=1, le=50, description="Records per page, at most 50.")


class LythoListAssetsConfig(LythoPage):
    operation: Literal["list_assets"] = Field("list_assets", title="List Assets", json_schema_extra={"ui:hidden": True, "x-display-name": "List Assets"})
    fileName: Optional[str] = None
    tagIds: Optional[list[str]] = None
    creationDateFrom: Optional[datetime] = None
    creationDateTo: Optional[datetime] = None
    modificationDateFrom: Optional[datetime] = None
    modificationDateTo: Optional[datetime] = None


class LythoSearchAssetsConfig(LythoPage):
    operation: Literal["search_assets"] = Field("search_assets", title="Search Assets", json_schema_extra={"ui:hidden": True, "x-display-name": "Search Assets"})
    searchQuery: str = Field(..., title="Search text", min_length=1)


class LythoGetAssetConfig(LythoInput):
    operation: Literal["get_asset"] = Field("get_asset", title="Get Asset", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Asset"})
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoDeleteAssetConfig(LythoInput):
    operation: Literal["delete_asset"] = Field("delete_asset", title="Delete Asset", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Asset"})
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoAddAssetTagConfig(LythoInput):
    operation: Literal["add_asset_tag"] = Field("add_asset_tag", title="Add Asset Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Add Asset Tag"})
    asset_id: ResourceId = Field(..., title="Asset Id")
    tag_id: ResourceId = Field(..., title="Tag Id")


class LythoRemoveAssetTagConfig(LythoInput):
    operation: Literal["remove_asset_tag"] = Field("remove_asset_tag", title="Remove Asset Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Remove Asset Tag"})
    asset_id: ResourceId = Field(..., title="Asset Id")
    tag_id: ResourceId = Field(..., title="Tag Id")


class LythoListAssetVersionsConfig(LythoPage):
    operation: Literal["list_asset_versions"] = Field("list_asset_versions", title="List Asset Versions", json_schema_extra={"ui:hidden": True, "x-display-name": "List Asset Versions"})
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoListAssetVariantsConfig(LythoPage):
    operation: Literal["list_asset_variants"] = Field("list_asset_variants", title="List Asset Variants", json_schema_extra={"ui:hidden": True, "x-display-name": "List Asset Variants"})
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoListAssetCollectionsConfig(LythoPage):
    operation: Literal["list_asset_collections"] = Field("list_asset_collections", title="List Asset Collections", json_schema_extra={"ui:hidden": True, "x-display-name": "List Asset Collections"})
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoListCollectionsConfig(LythoPage):
    operation: Literal["list_collections"] = Field("list_collections", title="List Collections", json_schema_extra={"ui:hidden": True, "x-display-name": "List Collections"})
    name: Optional[str] = None


class LythoGetCollectionConfig(LythoInput):
    operation: Literal["get_collection"] = Field("get_collection", title="Get Collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Collection"})
    collection_id: ResourceId = Field(..., title="Collection Id")


class LythoCreateCollectionConfig(LythoInput):
    operation: Literal["create_collection"] = Field("create_collection", title="Create Collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Collection"})
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    visibleToEveryone: Optional[bool] = Field(None, title="Visible to everyone")
    assets: Optional[list[ResourceId]] = None
    permissions: Optional[list[int]] = None


class LythoDeleteCollectionConfig(LythoInput):
    operation: Literal["delete_collection"] = Field("delete_collection", title="Delete Collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Collection"})
    collection_id: ResourceId = Field(..., title="Collection Id")


class LythoListCollectionAssetsConfig(LythoPage):
    operation: Literal["list_collection_assets"] = Field("list_collection_assets", title="List Collection Assets", json_schema_extra={"ui:hidden": True, "x-display-name": "List Collection Assets"})
    collection_id: ResourceId = Field(..., title="Collection Id")


class LythoAddCollectionAssetConfig(LythoInput):
    operation: Literal["add_collection_asset"] = Field("add_collection_asset", title="Add Collection Asset", json_schema_extra={"ui:hidden": True, "x-display-name": "Add Collection Asset"})
    collection_id: ResourceId = Field(..., title="Collection Id")
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoRemoveCollectionAssetConfig(LythoInput):
    operation: Literal["remove_collection_asset"] = Field("remove_collection_asset", title="Remove Collection Asset", json_schema_extra={"ui:hidden": True, "x-display-name": "Remove Collection Asset"})
    collection_id: ResourceId = Field(..., title="Collection Id")
    asset_id: ResourceId = Field(..., title="Asset Id")


class LythoListTagsConfig(LythoPage):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True, "x-display-name": "List Tags"})


class LythoGetTagConfig(LythoInput):
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Tag"})
    tag_id: ResourceId = Field(..., title="Tag Id")


class LythoCreateTagConfig(LythoInput):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Tag"})
    name: str = Field(..., min_length=1)
    locale: Optional[str] = None


class LythoUpdateTagConfig(LythoInput):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Tag"})
    tag_id: ResourceId = Field(..., title="Tag Id")
    name: str = Field(..., min_length=1)
    locale: Optional[str] = None


class LythoDeleteTagConfig(LythoInput):
    operation: Literal["delete_tag"] = Field("delete_tag", title="Delete Tag", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Tag"})
    tag_id: ResourceId = Field(..., title="Tag Id")


class LythoAssetPollConfig(PollTriggerConfigBase):
    lookback_hours: int = Field(24, ge=1, le=168, description="Poll assets created/modified in this rolling window. Keep it longer than the schedule interval; narrow it if more than 500 assets change.")
    fileName: Optional[str] = Field(None, title="Exact file name")
    tagIds: Optional[list[str]] = Field(None, title="Must contain all tag IDs")


class LythoOnNewAssetConfig(LythoAssetPollConfig):
    operation: Literal["on_new_asset"] = Field("on_new_asset", title="On New Asset", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Asset", "x-category": "Triggers"})


class LythoOnUpdatedAssetConfig(LythoAssetPollConfig):
    operation: Literal["on_updated_asset"] = Field("on_updated_asset", title="On Updated Asset", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Updated Asset", "x-category": "Triggers"})


LythoConfig = Annotated[Union[
    LythoListAssetsConfig,
    LythoSearchAssetsConfig,
    LythoGetAssetConfig,
    LythoDeleteAssetConfig,
    LythoAddAssetTagConfig,
    LythoRemoveAssetTagConfig,
    LythoListAssetVersionsConfig,
    LythoListAssetVariantsConfig,
    LythoListAssetCollectionsConfig,
    LythoListCollectionsConfig,
    LythoGetCollectionConfig,
    LythoCreateCollectionConfig,
    LythoDeleteCollectionConfig,
    LythoListCollectionAssetsConfig,
    LythoAddCollectionAssetConfig,
    LythoRemoveCollectionAssetConfig,
    LythoListTagsConfig,
    LythoGetTagConfig,
    LythoCreateTagConfig,
    LythoUpdateTagConfig,
    LythoDeleteTagConfig,
    LythoOnNewAssetConfig, LythoOnUpdatedAssetConfig,
], Field(discriminator="operation")]


class LythoNodeConfig(NodeConfig[LythoConfig, LythoAPIKeyCredential]):
    pass


# Each action maps to exactly one operation in the provider's contract.
OPERATIONS = {
    "list_assets": ('GET', '/assets', ('page', 'size', 'fileName', 'tagIds', 'creationDateFrom', 'creationDateTo', 'modificationDateFrom', 'modificationDateTo'), ()),
    "search_assets": ('GET', '/assets/search', ('page', 'size', 'searchQuery'), ()),
    "get_asset": ('GET', '/assets/{asset_id}', (), ()),
    "delete_asset": ('DELETE', '/assets/{asset_id}', (), ()),
    "add_asset_tag": ('PUT', '/assets/{asset_id}/tags/{tag_id}', (), ()),
    "remove_asset_tag": ('DELETE', '/assets/{asset_id}/tags/{tag_id}', (), ()),
    "list_asset_versions": ('GET', '/assets/{asset_id}/versions', ('page', 'size'), ()),
    "list_asset_variants": ('GET', '/assets/{asset_id}/variants', ('page', 'size'), ()),
    "list_asset_collections": ('GET', '/assets/{asset_id}/collections', ('page', 'size'), ()),
    "list_collections": ('GET', '/collections', ('page', 'size', 'name'), ()),
    "get_collection": ('GET', '/collections/{collection_id}', (), ()),
    "create_collection": ('POST', '/collections', (), ('name', 'description', 'visibleToEveryone', 'assets', 'permissions')),
    "delete_collection": ('DELETE', '/collections/{collection_id}', (), ()),
    "list_collection_assets": ('GET', '/collections/{collection_id}/assets', ('page', 'size'), ()),
    "add_collection_asset": ('PUT', '/collections/{collection_id}/assets/{asset_id}', (), ()),
    "remove_collection_asset": ('DELETE', '/collections/{collection_id}/assets/{asset_id}', (), ()),
    "list_tags": ('GET', '/tags', ('page', 'size'), ()),
    "get_tag": ('GET', '/tags/{tag_id}', (), ()),
    "create_tag": ('POST', '/tags', ('locale',), ('name',)),
    "update_tag": ('PUT', '/tags/{tag_id}', ('locale',), ('name',)),
    "delete_tag": ('DELETE', '/tags/{tag_id}', (), ()),
}


class LythoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-lytho"
    connection_evidence = ConnectionEvidence(operation="list_collections", noun="collections")

    @classmethod
    def get_config_model(cls):
        return LythoNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Lytho DAM API key")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                json=body, headers={"x-api-key": credential.api_key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:1000]
            message = str(detail).replace(credential.api_key, "[redacted]")
            raise ValueError(f"Lytho API {response.status_code}: {message}")
        if response.status_code == 204:
            return {"deleted": True}
        data = response.json()
        if not isinstance(data, dict) or (
            params and "page" in params and not isinstance(data.get("content"), list)
        ):
            raise ValueError("Lytho returned an unexpected JSON response")
        return data

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, LythoAssetPollConfig):
            return await self._poll_assets(config)
        method, path, query_fields, body_fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        return {"data": await self._request(method, path, params=params, body=body)}

    async def _poll_assets(self, config):
        updated = config.operation == "on_updated_asset"
        date_field = "modificationDateFrom" if updated else "creationDateFrom"
        since = datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)
        params = {date_field: since.isoformat(), "size": 50}
        for field in ("fileName", "tagIds"):
            value = getattr(config, field)
            if value is not None:
                params[field] = value
        items = []
        for page in range(10):
            data = await self._request("GET", "/assets", params={**params, "page": page})
            rows = data.get("content")
            if not isinstance(rows, list):
                raise ValueError("Lytho asset page is missing content")
            for row in rows:
                if not isinstance(row, dict) or not row.get("id") or (updated and not row.get("modificationDate")):
                    raise ValueError("Lytho asset is missing its ID or modification time")
            items.extend(rows)
            total_pages = data.get("totalPages")
            if type(total_pages) is int and total_pages >= 0:
                if page + 1 >= total_pages:
                    break
            elif data.get("last") is True or ("last" not in data and len(rows) < 50):
                break
            if not rows:
                raise ValueError("Lytho returned an empty nonterminal asset page")
        else:
            raise ValueError("More than 500 Lytho assets in the polling window; narrow the lookback or filters")
        fresh = await self._filter_unseen(items, lambda row:
            str(row["id"]) + (":" + row["modificationDate"] if updated else ""))
        return {"assets": fresh, "asset_count": len(fresh), "operation": config.operation}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_asset", "on_updated_asset"}:
            return bool(output.get("asset_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        assets = output.get("assets") if isinstance(output, dict) else None
        if assets is None:
            return super().resolve_agent_event(output)
        if not assets:
            return None
        action = "updated" if output.get("operation") == "on_updated_asset" else "new"
        lines = [f"- {row.get('name') or row.get('fileName') or 'Asset'} (asset ID {row['id']}); "
                 f"created by {row.get('createdBy') or 'unknown'}; modified {row.get('modificationDate') or 'unknown'}; "
                 f"{row.get('description') or ''}" for row in assets[:10]]
        return {"text": f"Lytho DAM: {len(assets)} {action} asset(s) in the connected tenant.\n" + "\n".join(lines),
                "conversation_key": None}

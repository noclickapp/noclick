"""Air workspace API: https://developer.air.inc/openapi/airapi.yaml (1.0.0).

Lists preserve Air's cursor. Polls traverse their full scope before recording a
baseline, bounded to 20 pages. API keys cannot discover workspaces (OAuth only).
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.air.inc"


class AirAPIKeyCredential(BaseModel):
    credential_type: Literal["air_api_key"] = Field("air_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})
    workspace_id: str = Field(..., min_length=1, title="Workspace ID")
    model_config = ConfigDict(title="Air API Key", json_schema_extra={
        "x-credential-url": "https://developer.air.inc/docs/getting-started",
        "x-credential-instructions": "Contact your Air account manager for API access, then paste your API key and workspace ID.",
    })

    @field_validator("api_key", "workspace_id")
    @classmethod
    def header_value(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter a nonempty value without control characters")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    group: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


PAGE = ("limit", "cursor")
OPERATIONS = {
    "list_assets": Operation("GET", "/v1/assets", "Assets", query=(*PAGE, "parentBoardId", "search", "tag")),
    "get_asset": Operation("GET", "/v1/assets/{assetId}", "Assets", ("assetId",)),
    "list_asset_versions": Operation("GET", "/v1/assets/{assetId}/versions", "Assets", ("assetId",)),
    "get_asset_version": Operation("GET", "/v1/assets/{assetId}/versions/{versionId}", "Assets", ("assetId", "versionId")),
    "update_asset_version": Operation("PATCH", "/v1/assets/{assetId}/versions/{versionId}", "Assets", ("assetId", "versionId"), body=("title", "description")),
    "add_version_tag": Operation("POST", "/v1/assets/{assetId}/versions/{versionId}/tags", "Assets", ("assetId", "versionId", "id"), body=("id",)),
    "remove_version_tag": Operation("DELETE", "/v1/assets/{assetId}/versions/{versionId}/tags/{tagId}", "Assets", ("assetId", "versionId", "tagId")),
    "list_boards": Operation("GET", "/v1/boards", "Boards", query=(*PAGE, "name", "parentBoardId", "libraryId")),
    "get_board": Operation("GET", "/v1/boards/{boardId}", "Boards", ("boardId",)),
    "create_board": Operation("POST", "/v1/boards", "Boards", ("title",), body=("title", "description", "parentBoardId", "libraryId")),
    "update_board": Operation("PATCH", "/v1/boards/{boardId}", "Boards", ("boardId",), body=("title", "description", "parentBoardId")),
    "delete_board": Operation("DELETE", "/v1/boards/{boardId}", "Boards", ("boardId",)),
    "add_board_assets": Operation("POST", "/v1/boards/{boardId}/assets", "Boards", ("boardId", "assetIds"), body=("assetIds",)),
    "remove_board_asset": Operation("DELETE", "/v1/boards/{boardId}/assets/{assetId}", "Boards", ("boardId", "assetId")),
    "list_tags": Operation("GET", "/v1/tags", "Tags", query=(*PAGE, "name")),
    "create_tag": Operation("POST", "/v1/tags", "Tags", ("name",), body=("name",)),
    "update_tag": Operation("PATCH", "/v1/tags/{tagId}", "Tags", ("tagId", "name"), body=("name",)),
    "delete_tag": Operation("DELETE", "/v1/tags/{tagId}", "Tags", ("tagId",)),
    "import_asset": Operation("POST", "/v1/imports", "Imports", ("sourceUrl", "fileName"), body=("sourceUrl", "fileName", "description", "ext", "recordedAt", "parentBoardId", "assetId")),
    "get_import_status": Operation("GET", "/v1/imports/{importId}/status", "Imports", ("importId",)),
    "list_libraries": Operation("GET", "/v1/libraries", "Libraries", query=(*PAGE, "search")),
}
TITLES = {"assetId": "Asset ID", "versionId": "Version ID", "boardId": "Board ID", "tagId": "Tag ID", "id": "Tag ID", "importId": "Import ID", "parentBoardId": "Parent Board ID", "libraryId": "Library ID", "assetIds": "Asset IDs", "sourceUrl": "Public File URL", "fileName": "File Name", "recordedAt": "Recorded At", "ext": "File Extension"}


class AirOperationConfig(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def safe_identifier(cls, value, info):
        if info.field_name.endswith("Id") or info.field_name == "id":
            if isinstance(value, str) and value.strip() in {".", ".."}:
                raise ValueError("Enter a resource ID, not a path segment")
        return value

    @model_validator(mode="after")
    def valid_write(self):
        values = self.model_dump(exclude_none=True)
        op = values.get("operation")
        if op == "create_board" and values.get("parentBoardId") and values.get("libraryId"):
            raise ValueError("Choose a parent board or a library, not both")
        if op in {"update_board", "update_asset_version"} and not any(k in self.model_fields_set for k in OPERATIONS[op].body):
            raise ValueError("Provide at least one property to update")
        return self


def _field(name, required):
    kind = list[str] if name == "assetIds" else int if name == "limit" else str
    bounds = {"ge": 1, "le": 500} if kind is int else {"min_length": 1}
    return (kind if required else Optional[kind], Field(... if required else None, title=TITLES.get(name, name.title()), **bounds))


def _config(name, spec):
    label = name.replace("_", " ").title()
    extra = {"const": name, "ui:hidden": True, "x-category": spec.group, "x-is-trigger": False, "x-display-name": label}
    fields = {key: _field(key, key in spec.required) for key in sorted(set(spec.required + spec.query + spec.body))}
    return create_model("Air" + name.title().replace("_", "") + "Config", __base__=AirOperationConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, description="Deleting a board also deletes assets contained only in it or its descendants." if name == "delete_board" else label, json_schema_extra=extra)), **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({m.__name__: m for m in CONFIG_MODELS.values()})


class AirOnNewOrUpdatedAssetConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_asset"] = Field("on_new_or_updated_asset", title="On New or Updated Asset", json_schema_extra={"const": "on_new_or_updated_asset", "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Asset"})
    parentBoardId: Optional[str] = Field(None, min_length=1, title="Parent Board ID", description="Optional immediate parent board. Watches asset metadata and cover version changes returned by the list API.")


class AirOnNewOrUpdatedBoardConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_board"] = Field("on_new_or_updated_board", title="On New or Updated Board", json_schema_extra={"const": "on_new_or_updated_board", "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Board"})
    parentBoardId: Optional[str] = Field(None, min_length=1, title="Parent Board ID")


AirConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (AirOnNewOrUpdatedAssetConfig, AirOnNewOrUpdatedBoardConfig)], Field(discriminator="operation")]


class AirNodeConfig(NodeConfig[AirConfig, AirAPIKeyCredential]):
    pass


class AirNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-air"
    connection_evidence = ConnectionEvidence(operation="list_boards", noun="boards", label_keys=("title", "id"))
    edit_examples = ["Import a creative asset from a public URL", "Create an Air board", "Watch Air assets for changes", "Tag an asset version"]

    @classmethod
    def get_config_model(cls):
        return AirNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"x-api-key": credential.api_key, "x-air-workspace-id": credential.workspace_id, "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            try:
                payload = response.json()
                detail = (payload.get("message") or payload.get("error")) if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            text = str(detail or "request failed")
            for secret in (credential.api_key, credential.workspace_id):
                text = text.replace(secret, "[redacted]")
            raise ValueError(f"Air API error {response.status_code}: {text}")
        return response.json() if response.content else {"ok": True}

    async def _poll(self, credential, config):
        kind = "assets" if config.operation == "on_new_or_updated_asset" else "boards"
        params = {"limit": "500"}
        if config.parentBoardId:
            params["parentBoardId"] = config.parentBoardId
        rows, cursors, ids = [], set(), set()
        for _ in range(20):
            data = await self._request(credential, "GET", "/v1/" + kind, params=dict(params))
            page = data.get("data") if isinstance(data, dict) else None
            if not isinstance(page, list):
                raise ValueError("Air returned an invalid list")
            for row in page:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                    raise ValueError("Air returned a resource without its ID")
                if row["id"] in ids:
                    raise ValueError("Air repeated a resource across pages; retry the poll")
                ids.add(row["id"])
                rows.append(row)
            pagination = data.get("pagination")
            if not isinstance(pagination, dict) or type(pagination.get("hasMore")) is not bool:
                raise ValueError("Air returned invalid pagination")
            if not pagination["hasMore"]:
                break
            cursor = pagination.get("cursor")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Air returned a nonadvancing cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("Air poll exceeds 10,000 resources; choose a smaller parent board")
        # The asset schema omits coverVersion.updatedAt. Fingerprint the returned
        # metadata rather than inventing an undocumented timestamp field.
        fresh = await self._filter_unseen(rows, lambda row: row["id"] + ":" + hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        return {"data": fresh, "kind": kind, "event_count": len(fresh), "parent_board_id": config.parentBoardId}

    async def _filter_unseen(self, items, id_fn):
        """Track the latest full snapshot so an A -> B -> A edit fires twice.

        The generic helper retains historic IDs; content fingerprints must instead
        retire old versions. Polling is complete before this one atomic state CAS.
        """
        scope = self.schedule_poll_scope(self.config.config.model_dump())
        baseline_only = getattr(self, "_poll_baseline_only", False)

        def mutate(state):
            first = "seen_ids" not in state
            repointed = state.get("scope") is not None and state["scope"] != scope
            if baseline_only and not first and not repointed:
                return None, []
            seen = set(state.get("seen_ids", []))
            current = [id_fn(item) for item in items]
            fresh = [] if first or repointed else [item for item, key in zip(items, current) if key not in seen]
            return {"seen_ids": current, "scope": scope}, fresh

        fresh = await self._update_node_state(mutate, skip_result=[])
        self._poll_emitted_count = len(fresh)
        return fresh

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("event_count")) if config.get("operation", "").startswith("on_new_or_updated_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("kind") not in {"assets", "boards"}:
            return super().resolve_agent_event(output)
        rows = output.get("data", [])
        if not rows:
            return None
        lines = []
        for row in rows[:10]:
            if output["kind"] == "assets":
                version = row.get("coverVersion") or {}
                label = version.get("title") or version.get("fileName") or row["id"]
                content = version.get("description") or ""
            else:
                version = {}
                label = row.get("title") or row["id"]
                content = row.get("description") or ""
            lines.append(f"- {label} (id {row['id']}" + (f", version {version['id']}" if version.get("id") else "") + f"): {content}")
        where = f"board {output['parent_board_id']}" if output.get("parent_board_id") else "the connected workspace"
        return {"text": f"Air: {len(rows)} new or updated {output['kind']} in {where}.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Air API key and workspace ID")
        config, credential = self.config.config, self.config.credentials
        if isinstance(config, (AirOnNewOrUpdatedAssetConfig, AirOnNewOrUpdatedBoardConfig)):
            return await self._poll(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for name in spec.required:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {key: str(values[key]) for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        if config.operation == "update_board" and "parentBoardId" in config.model_fields_set and config.parentBoardId is None:
            body["parentBoardId"] = None
        return await self._request(credential, spec.method, path, params=params or None, body=body if spec.body else None)

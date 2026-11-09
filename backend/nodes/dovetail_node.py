"""Dovetail Public API workflow node.

Uses the current data and docs resources rather than the deprecated notes and
insights aliases. Dovetail's personal API tokens expire after 30 days.
https://developers.dovetail.com/docs/introduction
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


API_BASE = "https://dovetail.com/api"


class DovetailAPICredential(BaseModel):
    """Personal API token from Dovetail account settings."""

    credential_type: Literal["dovetail_api_key"] = Field(
        "dovetail_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Personal API token",
        description="Dovetail personal API token (starts with api.; expires after 30 days).",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Dovetail Personal API Token",
        json_schema_extra={"x-credential-url": "https://dovetail.com/settings/user/account",
                           "x-credential-instructions": "Create a personal API token in Dovetail account settings. Tokens expire after 30 days; replace the token here when it expires."}
    )


def _field(annotation: Any, default: Any, title: str, **extra: Any) -> tuple[Any, Any]:
    return annotation, Field(default, title=title, **extra)


def _id_field(noun: str, *, dynamic: bool = True) -> tuple[Any, Any]:
    extra = {
        "x-dynamic-options": {
            "field_name": f"{noun}_id",
            "placeholder": f"Select a {noun}...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": f"Or paste a {noun} ID",
        }
    } if dynamic else {}
    return _field(str, ..., f"{noun.title()} ID", json_schema_extra=extra)


PAGE_FIELDS = {
    "limit": _field(int, 100, "Page size", ge=1, le=100),
    "cursor": _field(Optional[str], None, "Next cursor"),
}
PROJECT_ID = {"project_id": _id_field("project")}
DATA_ID = {"data_id": _id_field("data", dynamic=False)}
DOC_ID = {"doc_id": _id_field("doc", dynamic=False)}
CONTACT_ID = {"contact_id": _id_field("contact", dynamic=False)}
TAG_ID = {"tag_id": _id_field("tag", dynamic=False)}
HIGHLIGHT_ID = {"highlight_id": _id_field("highlight", dynamic=False)}
TITLE = {"title": _field(str, ..., "Title", min_length=1, max_length=200)}
OPTIONAL_TITLE = {"title": _field(Optional[str], None, "Title", min_length=1, max_length=200)}
CONTENT = {"content": _field(Optional[str], None, "Content", json_schema_extra={"ui:widget": "textarea"})}
FIELDS = {"fields": _field(Optional[list[dict[str, Any]]], None, "Custom fields")}


def _config(name: str, category: str, fields: dict[str, tuple[Any, Any]], *, creates: Optional[str] = None) -> type[BaseModel]:
    """Keep operation metadata, validation, and the generated editor in sync."""
    operation_extra: dict[str, Any] = {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-display-name": name.replace("_", " ").title(),
    }
    if creates:
        operation_extra.update({
            "x-creates-resource": True,
            "x-resource-type": creates,
            "x-resource-id-path": "data.id",
        })
    return create_model(
        "Dovetail" + "".join(part.title() for part in name.split("_")) + "Config",
        operation=(Literal[name], Field(name, title=operation_extra["x-display-name"], json_schema_extra=operation_extra)),
        **fields,
    )


# Each entry names a documented endpoint. List operations expose Dovetail's
# page[limit] and page[start_cursor] rather than silently truncating results.
_CONFIGS = [
    _config("test_authentication", "Account", {}),
    _config("list_projects", "Projects", {**PAGE_FIELDS, "title": _field(Optional[str], None, "Title filter")}),
    _config("get_project", "Projects", PROJECT_ID),
    _config("create_project", "Projects", {**TITLE, "folder_id": _field(Optional[str], None, "Folder ID"), "template_id": _field(Optional[str], None, "Template ID")}, creates="dovetail_project"),
    _config("update_project", "Projects", {**PROJECT_ID, **TITLE}),
    _config("delete_project", "Projects", PROJECT_ID),
    _config("list_data", "Data", {**PAGE_FIELDS, "project_id": _field(Optional[str], None, "Project ID"), "title": _field(Optional[str], None, "Title filter")}),
    _config("get_data", "Data", DATA_ID),
    _config("export_data", "Data", {**DATA_ID, "format": _field(Literal["markdown", "html"], "markdown", "Format")}),
    _config("create_data", "Data", {**PROJECT_ID, **OPTIONAL_TITLE, **CONTENT, **FIELDS}, creates="dovetail_data"),
    _config("update_data", "Data", {**DATA_ID, **OPTIONAL_TITLE, **FIELDS}),
    _config("delete_data", "Data", DATA_ID),
    _config("list_docs", "Docs", {**PAGE_FIELDS, "project_id": _field(Optional[str], None, "Project ID")}),
    _config("get_doc", "Docs", DOC_ID),
    _config("export_doc", "Docs", {**DOC_ID, "format": _field(Literal["markdown", "html"], "markdown", "Format")}),
    _config("create_doc", "Docs", {**TITLE, **CONTENT, "content_type": _field(Literal["html", "markdown", "text"], "markdown", "Content format"), "project_id": _field(Optional[str], None, "Project ID"), "folder_id": _field(Optional[str], None, "Folder ID"), **FIELDS}, creates="dovetail_doc"),
    _config("update_doc", "Docs", {**DOC_ID, **OPTIONAL_TITLE, **FIELDS}),
    _config("delete_doc", "Docs", DOC_ID),
    _config("list_contacts", "Contacts", PAGE_FIELDS),
    _config("get_contact", "Contacts", CONTACT_ID),
    _config("create_contact", "Contacts", {"name": _field(str, ..., "Name", min_length=1), "email": _field(str, ..., "Email"), **FIELDS}, creates="dovetail_contact"),
    _config("update_contact", "Contacts", {**CONTACT_ID, "name": _field(Optional[str], None, "Name"), "email": _field(Optional[str], None, "Email"), **FIELDS}),
    _config("delete_contact", "Contacts", CONTACT_ID),
    _config("list_tags", "Tags", {**PAGE_FIELDS, "project_id": _field(Optional[str], None, "Project ID")}),
    _config("get_tag", "Tags", TAG_ID),
    _config("list_tag_boards", "Tags", {**PAGE_FIELDS, "project_id": _field(Optional[str], None, "Project ID")}),
    _config("create_tag", "Tags", {**TITLE, "project_id": _field(Optional[str], None, "Project ID"), "tag_board_id": _field(Optional[str], None, "Tag board ID"), "group_id": _field(Optional[str], None, "Group ID")}, creates="dovetail_tag"),
    _config("list_highlights", "Highlights", {**PAGE_FIELDS, "project_id": _field(Optional[str], None, "Project ID"), "tag_id": _field(Optional[str], None, "Tag ID")}),
    _config("get_highlight", "Highlights", HIGHLIGHT_ID),
    _config("create_highlight", "Highlights", {
        "note_id": _field(str, ..., "Transcript data ID"),
        "start_time": _field(float, ..., "Start time (seconds)", ge=0),
        "end_time": _field(float, ..., "End time (seconds)", ge=0),
        "tag_ids": _field(Optional[list[str]], None, "Tag IDs"),
    }, creates="dovetail_highlight"),
    _config("search_workspace", "Search", {"query": _field(str, ..., "Query", min_length=1), "limit": _field(int, 20, "Limit", ge=1, le=100), "offset": _field(int, 0, "Offset", ge=0), "types": _field(Optional[list[str]], None, "Result types")}),
]

class DovetailOnNewDataConfig(PollTriggerConfigBase):
    """Poll for new research data metadata, without replaying existing data."""
    operation: Literal["on_new_data"] = Field("on_new_data", title="On New Data", json_schema_extra={
        "const": "on_new_data", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Data",
    })
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_id_field("project")[1].json_schema_extra)


class DovetailOnNewDocConfig(PollTriggerConfigBase):
    """Poll for new research doc metadata; export the doc to read its content."""
    operation: Literal["on_new_doc"] = Field("on_new_doc", title="On New Doc", json_schema_extra={
        "const": "on_new_doc", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Doc",
    })
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_id_field("project")[1].json_schema_extra)


class DovetailOnNewOrUpdatedHighlightConfig(PollTriggerConfigBase):
    """Detect new highlight IDs and changed updated_at values from List highlights."""
    operation: Literal["on_new_or_updated_highlight"] = Field(
        "on_new_or_updated_highlight", title="On New or Updated Highlight", json_schema_extra={
            "const": "on_new_or_updated_highlight", "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": "On New or Updated Highlight",
        })
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_id_field("project")[1].json_schema_extra)


_CONFIGS.extend([DovetailOnNewDataConfig, DovetailOnNewDocConfig, DovetailOnNewOrUpdatedHighlightConfig])

DovetailNodeConfig = Annotated[Union[tuple(_CONFIGS)], Discriminator("operation")]


class DovetailNodeFullConfig(NodeConfig[DovetailNodeConfig, DovetailAPICredential]):
    pass


def _segment(value: str) -> str:
    # Resource IDs are path segments, never caller-controlled URL paths.
    return quote(value, safe="")


def _nonempty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


async def _request(token: str, method: str, path: str, *, params: Optional[dict[str, Any]] = None, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method,
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            json=body,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # httpx's default exception includes the URL but no token. Avoid
            # forwarding provider response bodies that may contain user data.
            raise ValueError(f"Dovetail API returned HTTP {response.status_code} for {method} {path}") from exc
        return response.json() if response.content else {}


class DovetailNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Research projects, data, docs, contacts, tags, highlights and search."""

    integration_type = "automation-dovetail"

    edit_examples = [
        "List research projects and their data",
        "Create a data entry from customer feedback",
        "Search research and export a doc as Markdown",
    ]
    connection_evidence = ConnectionEvidence(
        field="project_id", noun="projects", identity_operation="test_authentication",
        identity_keys=("subdomain", "name", "workspace"),
    )

    @classmethod
    def get_config_model(cls):
        return DovetailNodeFullConfig

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        wrapper = output.get("data") if "status" in output and isinstance(output.get("data"), dict) else output
        operation = wrapper.get("operation")
        if operation not in {"on_new_data", "on_new_doc", "on_new_or_updated_highlight"}:
            return super().resolve_agent_event(output)
        items = wrapper.get("items")
        if not isinstance(items, list) or not items:
            return None
        highlight = operation == "on_new_or_updated_highlight"
        noun = "new or updated highlights" if highlight else "new data" if operation == "on_new_data" else "new docs"
        lines = [f"Dovetail: {len(items)} {noun}"]
        for item in items[:10]:
            identifier = item["id"]
            text = item.get("text") if highlight else item.get("title")
            lines.append(f"- {str(text or identifier)[:1000]} (id {identifier})")
            if highlight:
                if item.get("note_id"):
                    lines.append(f"  Data ID: {item['note_id']}")
                lines.append(f"  Updated at: {item['updated_at']}")
                tags = [tag["title"] for tag in item.get("tags", []) if isinstance(tag, dict) and tag.get("title")]
                if tags:
                    lines.append("  Tags: " + ", ".join(tags)[:1000])
            if item.get("url"):
                lines.append(f"  URL: {item['url']}")
        if len(items) > 10:
            lines.append(f"… and {len(items) - 10} more; all items are available in the trigger output.")
        action = "get_highlight highlight_id" if highlight else "export_data data_id" if operation == "on_new_data" else "export_doc doc_id"
        lines.append(f"To read the research, use {action}=<id>.")
        return {"text": "\n".join(lines), "conversation_key": None}

    async def _poll_research(self, token: str, config: PollTriggerConfigBase) -> Dict[str, Any]:
        resource = {"on_new_data": "data", "on_new_doc": "docs",
                    "on_new_or_updated_highlight": "highlights"}[config.operation]
        items = []
        cursor = None
        seen_cursors = set()
        for _ in range(20):
            params = {"page[limit]": 100}
            if config.project_id:
                params["filter[project_id]"] = config.project_id
            if cursor:
                params["page[start_cursor]"] = cursor
            result = await _request(token, "GET", f"/v1/{resource}", params=params)
            rows, page = result.get("data"), result.get("page")
            if not isinstance(rows, list) or not isinstance(page, dict) or not isinstance(page.get("has_more"), bool):
                raise ValueError("Dovetail returned an invalid research list or pagination envelope")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                    raise ValueError("Dovetail returned a research item without an ID")
                if resource == "highlights" and (not isinstance(row.get("updated_at"), str) or not row["updated_at"]):
                    raise ValueError("Dovetail returned a highlight without updated_at")
                if resource != "data" or not row.get("deleted"):
                    items.append(row)
            if not page["has_more"]:
                break
            cursor = page.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ValueError("Dovetail pagination did not advance; no poll state was changed")
            seen_cursors.add(cursor)
        else:
            raise ValueError("Dovetail polling exceeded 20 pages; choose a smaller project to monitor")
        # Only commit the seen-set after every page succeeded. The shared mixin
        # owns arm-time baselines, scope changes, concurrent state writes and dedup.
        fresh = await self._filter_unseen(items, lambda row: (
            f"{row['id']}:{row['updated_at']}" if resource == "highlights" else row["id"]))
        return {"operation": config.operation, "items": fresh, "item_count": len(fresh)}

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        if field_name != "project_id":
            return {"options": [], "next_page_token": None}
        token = credential_data.get("api_key")
        if not token:
            raise ValueError("Connect a Dovetail personal API token to load projects")
        params: dict[str, Any] = {"page[limit]": 100}
        if page_token:
            params["page[start_cursor]"] = page_token
        if search:
            params["filter[title][contains]"] = search
        result = await _request(token, "GET", "/v1/projects", params=params)
        return {
            "options": [
                {"value": row["id"], "label": row.get("title") or row["id"]}
                for row in result.get("data", []) if row.get("id")
            ],
            "next_page_token": (result.get("page") or {}).get("next_cursor"),
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, DovetailNodeFullConfig) or not self.config.credentials:
            raise ValueError("Dovetail configuration and personal API token are required")
        token = self.config.credentials.api_key
        config = self.config.config
        operation = config.operation
        if isinstance(config, (DovetailOnNewDataConfig, DovetailOnNewDocConfig, DovetailOnNewOrUpdatedHighlightConfig)):
            return await self._poll_research(token, config)
        values = config.model_dump(exclude_none=True, exclude={"operation"})

        if operation == "test_authentication":
            return await _request(token, "GET", "/v1/token/info")
        if operation == "search_workspace":
            options = {"query": values["query"]}
            if values.get("types"):
                options["types"] = values["types"]
            return await _request(token, "POST", "/v2/search", body={
                "options": options, "limit": values["limit"], "offset": values["offset"],
            })
        if operation == "list_tag_boards":
            params: dict[str, Any] = {"page[limit]": values["limit"]}
            if values.get("cursor"):
                params["page[start_cursor]"] = values["cursor"]
            if values.get("project_id"):
                params["filter[project_id]"] = values["project_id"]
            return await _request(token, "GET", "/v1/tags/boards", params=params)
        if operation == "create_highlight" and values["end_time"] <= values["start_time"]:
            raise ValueError("Highlight end time must be after start time")

        resource = next((name for name in ("project", "data", "doc", "contact", "tag", "highlight") if operation.endswith(name) or operation.endswith(name + "s")), None)
        if not resource:
            raise ValueError(f"Unsupported Dovetail operation: {operation}")
        plural = {"project": "projects", "data": "data", "doc": "docs", "contact": "contacts", "tag": "tags", "highlight": "highlights"}[resource]
        collection = f"/v1/{plural}"
        identifier = values.pop(f"{resource}_id", None)

        if operation.startswith("list_"):
            if operation == "list_highlights" and values.get("project_id") and values.get("tag_id"):
                raise ValueError("Filter highlights by project or tag, not both")
            params: dict[str, Any] = {"page[limit]": values.pop("limit", 100)}
            cursor = values.pop("cursor", None)
            if cursor:
                params["page[start_cursor]"] = cursor
            for key, value in values.items():
                if value is not None:
                    params[f"filter[{key}][contains]" if key == "title" else f"filter[{key}]"] = value
            return await _request(token, "GET", collection, params=params)

        path = f"{collection}/{_segment(identifier)}" if identifier else collection
        if operation.startswith("export_"):
            return await _request(token, "GET", f"{path}/export/{values['format']}")
        if operation.startswith("get_"):
            return await _request(token, "GET", path)
        if operation.startswith("delete_"):
            return await _request(token, "DELETE", path)
        if operation.startswith("create_"):
            if operation == "create_doc" and values.get("project_id") and values.get("folder_id"):
                raise ValueError("Choose a project or folder for the doc, not both")
            return await _request(token, "POST", collection, body=_nonempty(values))
        if operation.startswith("update_"):
            if not values:
                raise ValueError("Provide at least one field to update")
            return await _request(token, "PATCH", path, body=_nonempty(values))
        raise ValueError(f"Unsupported Dovetail operation: {operation}")

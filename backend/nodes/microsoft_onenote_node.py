"""Microsoft OneNote notebooks, sections, and pages via delegated Graph OAuth.

The operation catalog is deliberately restricted to documented ``/me/onenote``
routes. IDs are encoded as path segments; a workflow cannot supply an arbitrary
Graph URL or use this node to call another service with its bearer token.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft_onenote import ONENOTE_SCOPES

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0/me/onenote"


class OneNoteOAuthCredential(BaseModel):
    credential_type: Literal["microsoft_oauth"] = Field(
        default="microsoft_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str
    refresh_token: str
    expires_at: str
    email: str

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Microsoft OneNote OAuth",
            "x-credential-type": "oauth",
            "x-oauth-provider": "microsoft",
            "x-oauth-scopes": [
                "https://graph.microsoft.com/Notes.ReadWrite",
                "https://graph.microsoft.com/User.Read",
                "offline_access",
            ],
        }
    )


@dataclass(frozen=True)
class Operation:
    title: str
    category: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""


# Graph v1.0 OneNote resource methods. Content APIs intentionally use a
# separate payload type from JSON metadata APIs.
OPERATIONS: dict[str, Operation] = {
    "list_notebooks": Operation(
        "List Notebooks", "Notebook", "GET", "/notebooks", ("top",)
    ),
    "get_notebook": Operation(
        "Get Notebook", "Notebook", "GET", "/notebooks/{notebook_id}", ("notebook_id",)
    ),
    "create_notebook": Operation(
        "Create Notebook", "Notebook", "POST", "/notebooks", ("display_name",), "name"
    ),
    "list_notebook_sections": Operation(
        "List Notebook Sections",
        "Section",
        "GET",
        "/notebooks/{notebook_id}/sections",
        ("notebook_id", "top"),
    ),
    "list_sections": Operation(
        "List Sections", "Section", "GET", "/sections", ("top",)
    ),
    "get_section": Operation(
        "Get Section", "Section", "GET", "/sections/{section_id}", ("section_id",)
    ),
    "create_section": Operation(
        "Create Section",
        "Section",
        "POST",
        "/notebooks/{notebook_id}/sections",
        ("notebook_id", "display_name"),
        "name",
    ),
    "list_section_groups": Operation(
        "List Section Groups", "Section Group", "GET", "/sectionGroups", ("top",)
    ),
    "get_section_group": Operation(
        "Get Section Group",
        "Section Group",
        "GET",
        "/sectionGroups/{section_group_id}",
        ("section_group_id",),
    ),
    "create_section_group": Operation(
        "Create Section Group",
        "Section Group",
        "POST",
        "/notebooks/{notebook_id}/sectionGroups",
        ("notebook_id", "display_name"),
        "name",
    ),
    "list_pages": Operation("List Pages", "Page", "GET", "/pages", ("top",)),
    "list_section_pages": Operation(
        "List Section Pages",
        "Page",
        "GET",
        "/sections/{section_id}/pages",
        ("section_id", "top"),
    ),
    "get_page": Operation("Get Page", "Page", "GET", "/pages/{page_id}", ("page_id",)),
    "get_page_content": Operation(
        "Get Page Content",
        "Page",
        "GET",
        "/pages/{page_id}/content",
        ("page_id",),
        "html_response",
    ),
    "get_page_preview": Operation(
        "Get Page Preview", "Page", "GET", "/pages/{page_id}/preview", ("page_id",)
    ),
    "create_page": Operation(
        "Create Page",
        "Page",
        "POST",
        "/sections/{section_id}/pages",
        ("section_id", "title", "body_html"),
        "html_page",
    ),
    "append_page_content": Operation(
        "Append Page Content",
        "Page",
        "PATCH",
        "/pages/{page_id}/content",
        ("page_id", "content_html"),
        "append",
    ),
    "replace_page_content": Operation(
        "Replace Page Content",
        "Page",
        "PATCH",
        "/pages/{page_id}/content",
        ("page_id", "target_id", "content_html"),
        "replace",
    ),
    "delete_page": Operation(
        "Delete Page", "Page", "DELETE", "/pages/{page_id}", ("page_id",)
    ),
}

FIELD_DEFINITIONS: dict[str, tuple[type, str, str]] = {
    "notebook_id": (str, "Notebook ID", "OneNote notebook ID"),
    "section_id": (str, "Section ID", "OneNote section ID"),
    "section_group_id": (str, "Section Group ID", "OneNote section group ID"),
    "page_id": (str, "Page ID", "OneNote page ID"),
    "display_name": (str, "Name", "Name for the new notebook, section, or group"),
    "title": (str, "Page Title", "Title of the new page"),
    "body_html": (str, "Body HTML", "HTML content for the new page"),
    "content_html": (str, "Content HTML", "Well-formed HTML to append or replace"),
    "target_id": (str, "Element ID", "Generated ID or data-id from Get Page Content"),
    "top": (int, "Limit", "Maximum number of results (1–100)"),
}


def _config_model(slug: str, operation: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[slug],
            Field(
                default=slug,
                title=operation.title,
                json_schema_extra={
                    "ui:hidden": True,
                    "const": slug,
                    "x-category": operation.category,
                    "x-is-trigger": False,
                    "x-display-name": operation.title,
                },
            ),
        ),
    }
    for key in operation.fields:
        kind, title, description = FIELD_DEFINITIONS[key]
        if key == "top":
            fields[key] = (
                int,
                Field(default=25, ge=1, le=100, title=title, description=description),
            )
        else:
            fields[key] = (
                kind,
                Field(..., min_length=1, title=title, description=description),
            )
    name = "OneNote" + "".join(part.title() for part in slug.split("_")) + "Config"
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


CONFIG_MODELS = {slug: _config_model(slug, spec) for slug, spec in OPERATIONS.items()}
OneNoteOperationConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class OneNoteNodeConfig(NodeConfig[OneNoteOperationConfig, OneNoteOAuthCredential]):
    pass


class OneNoteNode(WorkflowNode):
    """Execute account-scoped Microsoft Graph OneNote actions."""

    integration_type = "automation-microsoft-onenote"
    borrowed_credential_types = frozenset({"microsoft_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = ONENOTE_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_notebooks", noun="notebooks"
    )
    edit_examples = [
        "List my OneNote notebooks and sections",
        "Create a project notes page in a section",
        "Append a meeting summary to a OneNote page",
        "Read the HTML of a page for summarization",
    ]

    @classmethod
    def get_config_model(cls):
        return OneNoteNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        node_config = self.config
        if not isinstance(node_config, OneNoteNodeConfig):
            raise ValueError("OneNote configuration is required")
        credential = node_config.credentials
        if not credential:
            raise ValueError("Connect a Microsoft account to use OneNote")

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token

        cred_dict = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="microsoft",
            caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, cred_dict[key])
        config = node_config.config
        slug = config.operation
        spec = OPERATIONS[slug]
        values = config.model_dump(exclude={"operation"})
        values = {key: self._resolve(value, inputs) for key, value in values.items()}

        path = spec.path
        for key in ("notebook_id", "section_id", "section_group_id", "page_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        params = {"$top": values["top"]} if "top" in values else None
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if spec.body == "name":
            request_kwargs["json"] = {"displayName": values["display_name"]}
        elif spec.body == "html_page":
            page_html = (
                "<!DOCTYPE html><html><head><title>"
                + html.escape(values["title"])
                + "</title></head><body>"
                + values["body_html"]
                + "</body></html>"
            )
            headers["Content-Type"] = "text/html"
            request_kwargs["content"] = page_html.encode("utf-8")
        elif spec.body in ("append", "replace"):
            request_kwargs["json"] = [
                {
                    "target": "body" if spec.body == "append" else values["target_id"],
                    "action": "append" if spec.body == "append" else "replace",
                    "content": values["content_html"],
                }
            ]
        if spec.body == "html_response":
            headers["Accept"] = "text/html"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                spec.method, GRAPH_ROOT + path, **request_kwargs
            )
        if response.is_error:
            try:
                error = response.json().get("error", {})
                message = (
                    error.get("message") if isinstance(error, dict) else str(error)
                )
            except (ValueError, AttributeError):
                message = response.text[:300]
            raise ValueError(
                f"OneNote API error ({response.status_code}): {message or response.reason_phrase}"
            )

        result: dict[str, Any] = {
            "type": "onenote",
            "operation": slug,
            "status": "success",
        }
        if spec.body == "html_response":
            result["html"] = response.text
        elif response.content:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("value"), list):
                result["items"] = data["value"]
                result["count"] = len(data["value"])
                if data.get("@odata.nextLink"):
                    result["next_link"] = data["@odata.nextLink"]
            else:
                result["data"] = data
        if slug == "delete_page":
            result["page_id"] = values["page_id"]
        logger.info("OneNote %s succeeded for node %s", slug, self.node_id)
        return result

    @staticmethod
    def _resolve(value: Any, inputs: dict[str, Any]) -> Any:
        """Resolve simple upstream placeholders without changing non-string fields."""
        if not isinstance(value, str):
            return value
        for node_id, output in inputs.items():
            if isinstance(output, dict):
                for field, field_value in output.items():
                    value = value.replace(
                        "{{" + node_id + "." + field + "}}", str(field_value)
                    )
        return value

"""Nutshell CRM actions using its official REST API and Basic authentication."""

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.nutshell_operations import OPERATIONS


API_BASE = "https://app.nutshell.com/rest"
PATH_VARIABLE_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


class NutshellApiKeyCredential(BaseModel):
    """An API key tied to a Nutshell user account."""

    credential_type: Literal["nutshell_api_key"] = Field(
        "nutshell_api_key", json_schema_extra={"ui:hidden": True}
    )
    email: str = Field(..., title="Nutshell user email")
    api_key: str = Field(
        ..., title="Nutshell API key", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(
        title="Nutshell API Key",
        json_schema_extra={
            "x-credential-url": "https://app.nutshell.com/setup/api-key",
            "x-credential-instructions": (
                "Create an API key under Setup → API keys. Enter the email address "
                "of the Nutshell user who owns the key. Nutshell uses the email as "
                "the HTTP Basic username and the API key as its password."
            ),
        }
    )


def _field_name(variable: str) -> str:
    return "path_" + re.sub(r"[^a-zA-Z0-9]+", "_", variable).strip("_").lower()


def _make_config(name: str, op: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in PATH_VARIABLE_RE.findall(op["path"]):
        fields[_field_name(variable)] = (
            str,
            Field(
                ..., title=variable, description=f"Nutshell {variable} for this action."
            ),
        )
    query_names = ", ".join(op["query_parameters"])
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Query parameters JSON",
            description=(
                f"Optional URL query parameters. Documented names: {query_names or 'none'}. "
                "Nested filter objects use bracketed query keys."
            )[:900],
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ),
    )
    if op["body_required"]:
        fields["body_json"] = (
            str,
            Field(
                ...,
                title="Request body JSON",
                description=(
                    "The full Nutshell request body from the linked API reference. "
                    "PATCH updates use a JSON Patch array."
                ),
                json_schema_extra={
                    "ui:widget": "code_editor",
                    "x-code-language": "json",
                },
            ),
        )
    elif op["method"] in {"POST", "PUT", "PATCH"}:
        fields["body_json"] = (
            Optional[str],
            Field(
                None,
                title="Request body JSON",
                description="Optional JSON body from the linked Nutshell API reference.",
                json_schema_extra={
                    "ui:widget": "code_editor",
                    "x-code-language": "json",
                },
            ),
        )
    return create_model(
        "Nutshell" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=op["label"],
                description=(op["description"][:700] + f" API reference: {op['docs']}"),
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op["category"],
                    "x-is-trigger": False,
                    "x-display-name": op["label"],
                    "x-operation-docs-url": op["docs"],
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
NutshellConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class NutshellNodeConfig(NodeConfig[NutshellConfig, NutshellApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_value(raw: str, field: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc


def _query_params(raw: Optional[str]) -> list[tuple[str, Any]]:
    if not raw:
        return []
    values = _json_value(raw, "Query parameters")
    if not isinstance(values, dict):
        raise ValueError("Query parameters must be a JSON object")
    params: list[tuple[str, Any]] = []

    def add(key: str, value: Any, depth: int = 0) -> None:
        if not key or depth > 4:
            raise ValueError(
                "Query parameter keys must be nonempty and at most 4 levels deep"
            )
        if isinstance(value, dict):
            for child, child_value in value.items():
                if not isinstance(child, str) or not child:
                    raise ValueError(
                        "Query parameter object keys must be nonempty strings"
                    )
                add(f"{key}[{child}]", child_value, depth + 1)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    raise ValueError(
                        "Query parameter arrays must contain scalar values"
                    )
                params.append((key, item))
        elif value is not None:
            params.append((key, value))

    for key, value in values.items():
        if not isinstance(key, str):
            raise ValueError("Query parameter keys must be strings")
        add(key, value)
    return params


class NutshellNode(WorkflowNode):
    """Run a documented Nutshell REST action."""

    integration_type = "automation-nutshell"

    connection_evidence = ConnectionEvidence(
        operation="list_accounts",
        operation_arguments={},
        noun="accounts",
        proves="account",
    )
    edit_examples = [
        "Find Nutshell contacts",
        "Create a Nutshell lead",
        "Update a Nutshell account",
        "List Nutshell tasks",
    ]

    @classmethod
    def get_config_model(cls):
        return NutshellNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, NutshellNodeConfig):
            raise ValueError("Nutshell configuration required")
        credential = self.config.credentials
        if (
            credential is None
            or not credential.email.strip()
            or not credential.api_key.strip()
        ):
            raise ValueError("Connect a Nutshell user email and API key")

        config = self.config.config
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op["path"]
        for variable in PATH_VARIABLE_RE.findall(path):
            value = values.pop(_field_name(variable))
            if not value:
                raise ValueError(f"Nutshell {variable} is required")
            path = path.replace("{" + variable + "}", quote(str(value), safe=""))
        if "{" in path or "}" in path:
            raise ValueError("Unsupported Nutshell API path template")

        params = _query_params(values.pop("query_json", None))
        body_raw = values.pop("body_json", None)
        body = _json_value(body_raw, "Request body") if body_raw else None
        if op["body_required"] and body is None:
            raise ValueError("Request body JSON is required")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = op["content_type"]
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"],
                API_BASE + path,
                auth=httpx.BasicAuth(credential.email, credential.api_key),
                headers=headers,
                params=params or None,
                json=body,
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.is_error or response.is_redirect:
            raise ValueError(
                f"Nutshell API error {response.status_code}: {response.text[:350]}"
            )
        if not response.content:
            data: Any = {"ok": True}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        if isinstance(data, list):
            data = {
                "items": [
                    item if isinstance(item, dict) else {"value": item} for item in data
                ]
            }
        return {
            "status": "success",
            "operation": config.operation,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {"api_request": elapsed_ms},
        }

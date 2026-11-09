"""Teamwork.com projects, tasks, people, tags, comments, and time tracking.

The operation catalog is pinned to Teamwork's official v3 and v1 OpenAPI
specifications. V1 remains necessary for project, task-list, and milestone
writes that have no v3 equivalent.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from jsonschema import Draft4Validator, validators
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from nodes.scopes.teamwork import TEAMWORK_SCOPES
from nodes.teamwork_operations import BODY_SCHEMAS, OPERATIONS


# Swagger's `any` is not a JSON Schema type. Its description documents
# string/number/boolean/string[] values and null to clear a custom field.
_BODY_VALIDATOR = validators.extend(
    Draft4Validator,
    type_checker=Draft4Validator.TYPE_CHECKER.redefine(
        "any",
        lambda checker, value: (
            value is None
            or isinstance(value, (str, int, float, bool))
            or (
                isinstance(value, list) and all(isinstance(item, str) for item in value)
            )
        ),
    ),
)


def _required_body_shape(schema: dict[str, Any]) -> dict[str, Any]:
    """Describe the required JSON envelope; optional controls remain accepted.

    The full provider schema below still validates every supplied field. Showing
    only mandatory fields gives agents a usable starting shape without filling
    optional controls, assignments, notifications or time-of-day settings.
    """
    result = {key: value for key, value in schema.items() if key != "properties"}
    if "properties" in schema:
        result["properties"] = {
            key: _required_body_shape(value)
            for key, value in schema["properties"].items()
            if key in schema.get("required", [])
        }
    if "items" in schema:
        result["items"] = _required_body_shape(schema["items"])
    return result


class TeamworkAPIKeyCredential(BaseModel):
    credential_type: Literal["teamwork_api_key"] = Field(
        "teamwork_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API key", json_schema_extra={"ui:widget": "password"}
    )
    site_url: str = Field(
        ...,
        title="Teamwork site URL",
        description="For example https://yourcompany.teamwork.com",
    )

    model_config = ConfigDict(
        title="Teamwork API Key",
        json_schema_extra={
            "x-credential-url": "https://apidocs.teamwork.com/guides/teamwork/authentication",
            "x-credential-instructions": "In Teamwork, open your avatar → Edit my details → API & Mobile. Copy your API key and your Teamwork site URL.",
        },
    )


class TeamworkOAuthCredential(BaseModel):
    credential_type: Literal["teamwork_oauth"] = Field(
        "teamwork_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    installation: dict[str, Any] = Field(
        ..., description="Installation returned by Teamwork sign-in"
    )

    model_config = ConfigDict(
        title="Teamwork OAuth",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "teamwork",
            "x-oauth-scopes": sorted(TEAMWORK_SCOPES.declared_scopes()),
            "x-credential-url": "https://apidocs.teamwork.com/guides/teamwork/app-login-flow",
        },
    )


TeamworkCredential = Union[TeamworkOAuthCredential, TeamworkAPIKeyCredential]


def _path_field(name: str) -> str:
    return "path_" + re.sub(r"[^a-zA-Z0-9]+", "_", name).lower()


def _make_config(name: str, op: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in re.findall(r"\{([^}]+)\}", op["path"]):
        fields[_path_field(variable)] = (
            str,
            Field(
                ...,
                title=variable,
                description=f"Teamwork {variable} for this operation.",
            ),
        )
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Query parameters (JSON)",
            description="Optional JSON object of Teamwork API filters, pagination, or search parameters.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ),
    )
    if op["body"]:
        fields["body_json"] = (
            str,
            Field(
                ...,
                title="Request body (JSON)",
                description="Full JSON body in Teamwork's documented request shape. See the operation in Teamwork's API reference.",
                json_schema_extra={
                    "ui:widget": "code_editor",
                    "x-code-language": "json",
                    **(
                        {
                            "contentMediaType": "application/json",
                            "contentSchema": _required_body_shape(BODY_SCHEMAS[name]),
                        }
                        if name in BODY_SCHEMAS
                        else {}
                    ),
                },
            ),
        )
    return create_model(
        "Teamwork" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=op["label"],
                description=op["description"],
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op["category"],
                    "x-is-trigger": False,
                    "x-display-name": op["label"],
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
# Events: https://apidocs.teamwork.com/guides/teamwork/sample-webhook-payloads
TRIGGER_EVENTS = {
    "on_project_created": ("PROJECT.CREATED", "project", "New Project"),
    "on_tasklist_created": ("TASKLIST.CREATED", "taskList", "New Task List"),
    "on_tasklist_updated": ("TASKLIST.UPDATED", "taskList", "Updated Task List"),
    "on_time_created": ("TIME.CREATED", "time", "New Time Entry"),
    "on_time_updated": ("TIME.UPDATED", "time", "Updated Time Entry"),
}
for name, (event, resource, label) in TRIGGER_EVENTS.items():
    CONFIG_MODELS[name] = create_model(
        "Teamwork" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=WebhookTriggerConfigBase,
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=label,
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": "Triggers",
                    "x-is-trigger": True,
                    "x-display-name": label,
                },
            ),
        ),
        webhook_url=(
            Optional[str],
            Field(
                None,
                title="Webhook URL",
                description="Registered automatically. Requires a paid Teamwork plan and site administrator access.",
                json_schema_extra={
                    "ui:widget": "webhook",
                    "ui:copyable": True,
                    "ui:loadValue": True,
                },
            ),
        ),
    )
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
TeamworkConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class TeamworkNodeConfig(NodeConfig[TeamworkConfig, TeamworkCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_object(raw: str, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _site_base(raw: str) -> str:
    """Keep credentials from turning a workflow node into an arbitrary HTTP client."""
    parsed = urlsplit(raw.strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not (host == "teamwork.com" or host.endswith(".teamwork.com"))
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Teamwork site must be an HTTPS *.teamwork.com origin")
    return f"https://{host}"


class TeamworkNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-teamwork"
    credential_provider_labels = {"teamwork": "Teamwork Account"}
    scope_registry = TEAMWORK_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_current_user", noun="Teamwork account"
    )
    edit_examples = [
        "Create a task in Teamwork",
        "List my Teamwork projects",
        "Log time on a Teamwork task",
        "Add a comment to a Teamwork task",
    ]

    @classmethod
    def get_config_model(cls):
        return TeamworkNodeConfig

    @staticmethod
    def _authorization(credential):
        if credential.get("credential_type") == "teamwork_api_key":
            base = _site_base(credential["site_url"])
            token = base64.b64encode(
                (credential["api_key"] + ":password").encode()
            ).decode()
            return base, f"Basic {token}"
        return (
            _site_base(credential["installation"]["apiEndPoint"]),
            f"Bearer {credential['access_token']}",
        )

    @classmethod
    async def _webhook_request(cls, credential, method, path, body=None):
        base, authorization = cls._authorization(credential)
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                method,
                base + path,
                headers={"Authorization": authorization, "Accept": "application/json"},
                json=body,
            )
        if response.is_error or response.is_redirect:
            raise ValueError(f"Teamwork webhook API error {response.status_code}")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        # Registration: https://apidocs.teamwork.com/docs/teamwork/v1/webhooks/post-webhooks-json
        # Token: https://apidocs.teamwork.com/guides/teamwork/setting-up-webhooks
        event = TRIGGER_EVENTS[config["operation"]][0]
        secret = secrets.token_hex(32)
        data = await cls._webhook_request(
            credential,
            "POST",
            "/webhooks.json",
            {
                "webhook": {
                    "event": event,
                    "url": webhook_url,
                    "status": "ACTIVE",
                    "version": "2",
                    "contentType": "application/json",
                    "token": secret,
                }
            },
        )
        if not data.get("id"):
            raise ValueError("Teamwork did not return a webhook ID")
        return {"external_webhook_id": str(data["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = config.get("external_webhook_id")
        if credential and webhook_id:
            await cls._webhook_request(
                credential,
                "DELETE",
                f"/webhooks/{quote(str(webhook_id), safe='')}.json",
            )

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # HMAC-SHA256 over raw body, hex encoded; no timestamp or prefix.
        secret = config.get("signing_secret")
        signature = next(
            (
                value
                for key, value in headers.items()
                if key.lower() == "x-projects-signature"
            ),
            "",
        )
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        headers = payload.get("_webhook", {}).get("headers", {})
        event = next(
            (
                value
                for key, value in headers.items()
                if key.lower() == "x-projects-event"
            ),
            "",
        )
        expected = TRIGGER_EVENTS.get(config.get("operation"))
        return bool(expected and event.upper() == expected[0])

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if config.get("operation") in TRIGGER_EVENTS:
            return {
                "status": "success",
                "operation": config["operation"],
                "data": payload,
            }
        return None

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        if operation not in TRIGGER_EVENTS:
            return super().resolve_agent_event(output)
        event, resource, label = TRIGGER_EVENTS[operation]
        payload = output["data"]
        actor = payload["eventCreator"]
        record = payload[resource]
        person = " ".join(filter(None, (actor.get("firstName"), actor.get("lastName"))))
        resource_id = record["id"]
        content = record.get("description") or ""
        name = (
            record.get("name")
            if resource != "time"
            else f"{record['hours']}h {record['minutes']}m"
        )
        project_id = record.get("projectId") if resource != "project" else resource_id
        lines = [
            f"Teamwork {label}: {name or resource_id}",
            f"By {person or actor['id']} (user ID {actor['id']})",
            f"{resource} ID: {resource_id}; project ID: {project_id}",
        ]
        if resource == "time":
            lines.append(
                f"Task ID: {record['taskId']}; user ID: {record['userId']}; date: {record['date']}"
            )
        if content:
            lines.append(str(content))
        return {
            "text": "\n".join(lines),
            "title": f"{label}: {name or resource_id}",
            "conversation_key": f"{resource}:{resource_id}",
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, TeamworkNodeConfig):
            raise ValueError("Teamwork configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Teamwork credentials")
        config = self.config.config
        self.scope_registry.require(config.operation)
        if config.operation in TRIGGER_EVENTS:
            payload = self.node_data.get("config", {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, config.model_dump())
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op["path"]
        for variable in re.findall(r"\{([^}]+)\}", path):
            value = values.pop(_path_field(variable))
            if not value:
                raise ValueError(f"Teamwork {variable} is required")
            path = path.replace("{" + variable + "}", quote(str(value), safe=""))
        query_raw = values.pop("query_json", None)
        query = _json_object(query_raw, "Query parameters") if query_raw else None
        body_raw = values.pop("body_json", None)
        request = {}
        if body_raw is not None:
            body = _json_object(body_raw, "Request body")
            if config.operation in BODY_SCHEMAS:
                error = next(
                    _BODY_VALIDATOR(BODY_SCHEMAS[config.operation]).iter_errors(body),
                    None,
                )
                if error is not None:
                    raise ValueError(f"Teamwork request body: {error.message}")
            request["json"] = body

        if isinstance(credential, TeamworkAPIKeyCredential):
            base = _site_base(credential.site_url)
            basic = base64.b64encode(
                (credential.api_key + ":password").encode()
            ).decode()
            authorization = f"Basic {basic}"
        else:
            base = _site_base(credential.installation.get("apiEndPoint", ""))
            authorization = f"Bearer {credential.access_token}"

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"],
                base + path,
                headers={"Authorization": authorization, "Accept": "application/json"},
                params=query,
                **request,
            )
        if response.is_error or response.is_redirect:
            raise ValueError(
                f"Teamwork API error {response.status_code}: {response.text[:350]}"
            )
        if not response.content:
            data: Any = {"ok": True}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        if isinstance(data, list):
            data = {"items": data}
        return {
            "status": "success",
            "operation": config.operation,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {
                "api_request": round((time.perf_counter() - started) * 1000, 2)
            },
        }

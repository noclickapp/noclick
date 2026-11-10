"""magicplan Cloud API 1.2: fixed account, team, plan and project operations.

Contract: https://api.swaggerhub.com/apis/magicplan/magicplanCloudApi/1.2
Webhook: https://magicplan.apidocumentation.com/guide/advanced-integrations/custom-export-button-integration/webhook-documentation-project-updated
"""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE = "https://cloud.magicplan.app/api/v2"
DOCS = "https://magicplan.apidocumentation.com/guide/getting-started/generating-api-credentials"


class MagicplanAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="magicplan API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "In magicplan Cloud, open API & Integrations and generate API credentials. Paste the API key and Customer ID. Both are sent only to cloud.magicplan.app."})
    credential_type: Literal["magicplan_api_key"] = Field("magicplan_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    customer_id: str = Field(..., title="Customer ID", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "customer_id", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="magicplan credential")
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("Paste the credential without whitespace or a header prefix")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


OPERATIONS = {
    'get_workspace': Operation('GET', '/workspace', (), (), ()),
    'update_workspace': Operation('PUT', '/workspace', (), (), ('name', 'description', 'formats_json', 'notify_user')),
    'list_teams': Operation('GET', '/teams', (), (), ()),
    'create_team': Operation('POST', '/teams', ('name',), (), ('name',)),
    'get_team': Operation('GET', '/teams/{team_id}', ('team_id',), (), ()),
    'update_team': Operation('PUT', '/teams/{team_id}', ('team_id', 'name'), (), ('name',)),
    'add_team_members': Operation('POST', '/teams/{team_id}/members', ('team_id', 'emails_json'), (), ('emails_json', 'acting_user')),
    'remove_team_member': Operation('DELETE', '/teams/{team_id}/members', ('team_id', 'email'), ('email', 'acting_user'), ()),
    'list_users': Operation('GET', '/workgroups/users', (), (), ()),
    'list_plans': Operation('GET', '/workgroups/plans', (), ('page', 'plan_sort', 'direction', 'id', 'user_email', 'name', 'creation_date', 'update_date'), ()),
    'get_plan': Operation('GET', '/plans/get/{plan_id}', ('plan_id',), ('floor_svg_dimensions', 'room_svg_dimensions', 'floor_svg_show_annotations', 'room_svg_show_annotations'), ()),
    'get_plan_statistics': Operation('GET', '/plans/statistics/{plan_id}', ('plan_id',), (), ()),
    'get_plan_forms': Operation('GET', '/plans/forms/{plan_id}', ('plan_id',), (), ()),
    'list_plan_files': Operation('GET', '/plans/{plan_id}/files', ('plan_id',), ('modified_since', 'modified_until', 'include_photos', 'format_json'), ()),
    'reassign_plan_owner': Operation('PUT', '/plans/{plan_id}/owner', ('plan_id', 'user_id'), (), ('user_id', 'notify_user_flag', 'email_message', 'acting_user_id', 'target_team_id')),
    'export_plan': Operation('POST', '/plans/{plan_id}/custom-export', ('plan_id',), ('acting_user',), ()),
    'list_projects': Operation('GET', '/projects', (), ('page', 'page_size', 'project_sort', 'direction', 'email', 'name'), ()),
    'create_project': Operation('POST', '/projects', ('name', 'email'), (), ('name', 'email', 'description', 'team_id', 'external_reference_id')),
    'get_project': Operation('GET', '/projects/{project_id}', ('project_id',), (), ()),
    'update_project': Operation('PUT', '/projects/{project_id}', ('project_id',), (), ('name', 'description', 'acting_user')),
    'archive_project': Operation('PUT', '/projects/{project_id}/archive', ('project_id',), (), ('acting_user',)),
    'list_project_files': Operation('GET', '/projects/{project_id}/files', ('project_id',), ('acting_user', 'page', 'page_size'), ()),
}


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_fields(self):
        for name, value in self.model_dump().items():
            if value is None:
                continue
            if name.endswith("_json"):
                try:
                    decoded = json.loads(value)
                except (ValueError, TypeError):
                    raise ValueError(f"{name} must be a JSON array") from None
                if not isinstance(decoded, list) or not all(isinstance(item, str) and item for item in decoded):
                    raise ValueError(f"{name} must contain nonempty strings")
                allowed = {"formats_json": {"csv", "dxf", "fml", "ifc", "jpg", "mp", "obj", "pdf", "png", "svg", "usdz", "xls", "xml"},
                    "format_json": {"pdf", "jpg", "svg", "png", "usdz", "xls", "csv", "ifc", "dxf", "fml", "xml", "mp"}}.get(name)
                if allowed and not set(decoded) <= allowed:
                    raise ValueError(f"{name} contains an unsupported file format")
            if name in {"user_id", "acting_user_id", "target_team_id", "team_id"}:
                try:
                    UUID(value)
                except ValueError:
                    raise ValueError(f"{name} must be a UUID") from None
            if name in {"email", "user_email", "acting_user"} and ("@" not in value or any(char.isspace() for char in value)):
                raise ValueError(f"{name} must be an email address")
            if name.endswith("_id") and (not value.strip() or value in {".", ".."} or any(char in value for char in "/?#\\")):
                raise ValueError(f"{name} must be a single resource ID")
            if name in {"creation_date", "update_date", "modified_since", "modified_until"}:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError(f"{name} must be an ISO date or date-time") from None
        if getattr(self, "notify_user_flag", False) and not getattr(self, "email_message", None):
            raise ValueError("Email message is required when notifying the new plan owner")
        if self.operation == "update_project" and not any(getattr(self, key, None) is not None for key in ("name", "description")):
            raise ValueError("Provide a project name or description to update")
        if self.operation == "update_workspace" and not any(getattr(self, key, None) is not None for key in ("name", "description", "formats_json", "notify_user")):
            raise ValueError("Provide a workspace field to update")
        return self


def _field(name, required):
    types = {"page": int, "page_size": int, "notify_user": bool, "notify_user_flag": bool,
        "include_photos": bool, "floor_svg_show_annotations": bool, "room_svg_show_annotations": bool,
        "direction": Literal["asc", "desc"],
        "plan_sort": Literal["Plans.name", "Plans.update_date", "Plans.creation_date"],
        "project_sort": Literal["Projects.name", "Projects.user_created", "Projects.user_modified"],
        "floor_svg_dimensions": Literal["none", "detailed"], "room_svg_dimensions": Literal["none", "detailed"]}
    kind = types.get(name, str)
    args = {"title": name.removesuffix("_json").replace("_", " ").title()}
    if name in {"page", "page_size"}:
        args["ge"] = 1
        if name == "page_size": args["le"] = 50
    if kind is str:
        args.update(min_length=1, max_length=10000)
    if name.endswith("_json"):
        args.update(description="JSON array of strings", json_schema_extra={"ui:widget": "textarea"})
    return (kind if required else Optional[kind], Field(... if required else None, **args))


def _model(name, spec):
    fields = set(spec.required + spec.query + spec.body)
    category = "Workspace" if "workspace" in name or name == "list_users" else "Teams" if "team" in name else "Plans" if "plan" in name and "project" not in name else "Projects"
    return create_model("Magicplan" + "".join(part.title() for part in name.split("_")) + "Config", __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title(), "x-category": category, "x-is-trigger": False})),
        **{key: _field(key, key in spec.required) for key in sorted(fields)})


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class MagicplanOnProjectExportedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_project_exported"] = Field("on_project_exported", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Project Exported", "x-category": "Triggers", "x-is-trigger": True})
    replace_webhook_url: Optional[str] = Field(None, title="Existing webhook URL to replace", description="Optional: paste the exact current workspace webhook URL to explicitly replace it while this trigger is active. NoClick restores it on disconnect.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="One custom-export webhook per workspace.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


MagicplanConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (MagicplanOnProjectExportedConfig,)], Discriminator("operation")]


class MagicplanNodeConfig(NodeConfig[MagicplanConfig, MagicplanAPIKeyCredential]):
    pass


class MagicplanNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-magicplan"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", label_keys=("name", "id"))
    edit_examples = ["Create a magicplan project", "Export this floor plan", "Watch for project exports"]

    @classmethod
    def get_config_model(cls):
        return MagicplanNodeConfig

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None):
        cred = MagicplanAPIKeyCredential.model_validate(credential)
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={"key": cred.api_key, "customer": cred.customer_id, "Accept": "application/json"}, params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                detail = error.get("errors") or error.get("error") or error.get("message") if isinstance(error, dict) else None
            except ValueError:
                detail = None
            detail = detail if isinstance(detail, str) else json.dumps(detail) if detail else "Request failed"
            for secret in (cred.api_key, cred.customer_id):
                detail = detail.replace(secret, "[redacted]")
            raise ValueError(f"magicplan API returned HTTP {response.status_code}: {detail[:2000]}")
        if not response.content:
            return {"status_code": response.status_code}
        try:
            result = response.json()
        except ValueError:
            raise ValueError("magicplan returned an invalid JSON response") from None
        if not isinstance(result, (dict, list)):
            raise ValueError("magicplan returned an unexpected response")
        if isinstance(result, dict) and (result.get("errors") or result.get("error")):
            raise ValueError("magicplan reported an API error")
        return result

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a magicplan API key and Customer ID")
        op = self.config.config
        credential = self.config.credentials.model_dump()
        if op.operation == "on_project_exported":
            payload = self.node_data.get("config", {}).get("_triggerPayload", inputs)
            return self.resolve_trigger_payload(payload, {"operation": op.operation}) or {"event": "project.exported", "data": {}}
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in spec.required:
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        def wire(keys):
            result = {}
            for key in keys:
                if key in values:
                    target = "sort" if key in {"plan_sort", "project_sort"} else key.removesuffix("_json")
                    result[target] = json.loads(values[key]) if key.endswith("_json") else values[key]
            return result
        params, body = wire(spec.query), wire(spec.body)
        result = await self._request(credential, spec.method, path, params=params or None,
            body=body if spec.body else None)
        output = {"status": "success", "operation": op.operation, "data": result}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        workspace = await cls._request(credential, "GET", "/workspace")
        current = workspace.get("webhook_url")
        if current and current != webhook_url and current != config.get("replace_webhook_url"):
            raise ValueError("This magicplan workspace already has a webhook; paste its exact URL in Existing webhook URL to replace to approve replacing it")
        if current != webhook_url:
            await cls._request(credential, "PUT", "/workspace", body={"webhook_url": webhook_url})
        previous = config.get("replace_webhook_url") if current == webhook_url else current
        registration = json.dumps({"url": webhook_url, "previous": previous}, sort_keys=True)
        return {"external_webhook_id": registration, "signing_secret": credential["api_key"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        registration = config.get("external_webhook_id")
        if not credential or not registration:
            raise ValueError("magicplan webhook registration details are missing")
        record = json.loads(registration)
        workspace = await cls._request(credential, "GET", "/workspace")
        if workspace.get("webhook_url") == record["url"]:
            await cls._request(credential, "PUT", "/workspace", body={"webhook_url": record["previous"]})

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"replace_webhook_url": (config or {}).get("replace_webhook_url")}

    @staticmethod
    def _decode_form(body):
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=1000)
        if any(len(value) != 1 for value in values.values()):
            raise ValueError("Duplicate magicplan webhook fields")
        return {key: value[0] for key, value in values.items()}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        try:
            content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "")
            if content_type.split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
                return False
            data = cls._decode_form(body)
            supplied = data.get("key")
            return isinstance(supplied, str) and hmac.compare_digest(supplied.encode(), secret.encode())
        except (ValueError, UnicodeError, AttributeError):
            return False

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if config.get("operation") != "on_project_exported":
            return None
        # Generic webhook routes put non-JSON form bodies in `raw`.
        if isinstance(payload, dict) and "raw" in payload:
            payload = cls._decode_form(payload["raw"].encode())
        if not isinstance(payload, dict) or not all(payload.get(key) for key in ("email", "title", "planid", "project_id")):
            return None
        # The key authenticates delivery; never forward it into workflow or agent output.
        data = {key: value for key, value in payload.items() if key not in {"key", "_webhook"}}
        return {"event": "project.exported", "data": data}

    @classmethod
    async def transform_trigger_payload(cls, payload, config, *, pool, workflow_id, node_id):
        # Strip the body credential before the workflow captures its trigger input.
        output = cls.resolve_trigger_payload(payload, config)
        return output["data"] if output is not None else {}

    @classmethod
    def webhook_ack_response(cls):
        return {"content": "<MagicPlanService><status>0</status></MagicPlanService>", "media_type": "application/xml"}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("event") == "project.exported":
            data = output.get("data", {})
            if not data: return None
            return {"text": f"magicplan: {data.get('email')} exported {data.get('title')} (project {data.get('project_id')}, plan {data.get('planid')}).\n" + json.dumps(data, ensure_ascii=False),
                "conversation_key": str(data.get("project_id"))}
        return super().resolve_agent_event(output)

"""Runscope API v1.0.0 operations and environment completion callbacks.

Contract: Runscope/runscope-api-examples, schemas/runscope-swagger-v2.json.
Personal tokens: https://help.blazemeter.com/apidocs/api-monitoring/authentication.htm
Callbacks: https://help.blazemeter.com/docs/guide/api-monitoring-notifications-overview.html
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.runscope import RUNSCOPE_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.runscope.com"


class RunscopeTokenCredential(BaseModel):
    model_config = ConfigDict(title="Runscope Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.runscope.com/applications",
            "x-credential-instructions": "In Runscope Applications, create an application and copy its Personal Access Token. Paste that token here. Your own account is authorized automatically. NoClick sends it as a Bearer token. The token must allow the reads and writes you select.",
        })
    credential_type: Literal["runscope_api_token"] = Field("runscope_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") or info.field_name == "bucket_key":
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value)):
                raise ValueError("Use the resource ID, not a URL")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    payload: str | None = None


OPERATIONS = {
    "get_account": Operation("GET", "/account", "Account"),
    "list_team_people": Operation("GET", "/teams/{team_id}/people", "Account"),
    "list_team_integrations": Operation("GET", "/teams/{team_id}/integrations", "Account"),
    "list_team_agents": Operation("GET", "/teams/{team_id}/agents", "Account"),
    "list_buckets": Operation("GET", "/buckets", "Buckets"),
    "get_bucket": Operation("GET", "/buckets/{bucket_key}", "Buckets"),
    "create_bucket": Operation("POST", "/buckets", "Buckets", "bucket"),
    "delete_bucket": Operation("DELETE", "/buckets/{bucket_key}", "Buckets"),
    "list_tests": Operation("GET", "/buckets/{bucket_key}/tests", "Tests"),
    "get_test": Operation("GET", "/buckets/{bucket_key}/tests/{test_id}", "Tests"),
    "create_test": Operation("POST", "/buckets/{bucket_key}/tests", "Tests", "test"),
    "update_test": Operation("PUT", "/buckets/{bucket_key}/tests/{test_id}", "Tests", "test"),
    "delete_test": Operation("DELETE", "/buckets/{bucket_key}/tests/{test_id}", "Tests"),
    "list_steps": Operation("GET", "/buckets/{bucket_key}/tests/{test_id}/steps", "Steps"),
    "create_step": Operation("POST", "/buckets/{bucket_key}/tests/{test_id}/steps", "Steps", "step"),
    "update_step": Operation("PUT", "/buckets/{bucket_key}/tests/{test_id}/steps/{step_id}", "Steps", "step"),
    "delete_step": Operation("DELETE", "/buckets/{bucket_key}/tests/{test_id}/steps/{step_id}", "Steps"),
    "list_test_environments": Operation("GET", "/buckets/{bucket_key}/tests/{test_id}/environments", "Environments"),
    "create_test_environment": Operation("POST", "/buckets/{bucket_key}/tests/{test_id}/environments", "Environments", "environment"),
    "update_test_environment": Operation("PUT", "/buckets/{bucket_key}/tests/{test_id}/environments/{environment_id}", "Environments", "environment"),
    "list_shared_environments": Operation("GET", "/buckets/{bucket_key}/environments", "Environments"),
    "create_shared_environment": Operation("POST", "/buckets/{bucket_key}/environments", "Environments", "environment"),
    "update_shared_environment": Operation("PUT", "/buckets/{bucket_key}/environments/{environment_id}", "Environments", "environment"),
    "get_test_metrics": Operation("GET", "/buckets/{bucket_key}/tests/{test_id}/metrics", "Tests"),
}


def config_model(name, op):
    fields = {key: (str, Field(..., title=key.replace("_", " ").title(), min_length=1))
              for key in re.findall(r"{([^}]+)}", op.path)}
    if op.payload == "bucket":
        fields.update(name=(str, Field(..., min_length=1, title="Bucket name")),
                      team_id=(str, Field(..., min_length=1, title="Team ID")))
    elif op.payload:
        fields["payload_json"] = (str, Field(..., title=f"{op.payload.title()} JSON",
            description="Complete documented resource body. For environment updates, supply the full current configuration with your changes.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model("Runscope" + "".join(s.title() for s in name.split("_")), __base__=Input,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True,
            "x-display-name": name.replace("_", " ").title(), "x-category": op.category, "x-is-trigger": False})), **fields)


MODELS = {name: config_model(name, op) for name, op in OPERATIONS.items()}
globals().update({m.__name__: m for m in MODELS.values()})


class RunscopeOnTestCompleted(WebhookTriggerConfigBase):
    operation: Literal["on_test_completed"] = Field("on_test_completed", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Test Completed", "x-category": "Triggers", "x-is-trigger": True})
    bucket_key: str = Field(..., min_length=1, title="Bucket key")
    test_id: str | None = Field(None, title="Test ID filter", description="Optional: receive only this test. Leave empty for every test using the shared environment.")
    environment_id: str = Field(..., min_length=1, title="Environment ID",
        description="Adds this callback to the chosen shared environment while retaining its other settings. Tests using or inheriting this environment notify this trigger. Avoid concurrent environment edits during activation.")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})


RunscopeConfig = Annotated[Union[tuple(MODELS.values()) + (RunscopeOnTestCompleted,)], Field(discriminator="operation")]


class RunscopeNodeConfig(NodeConfig[RunscopeConfig, RunscopeTokenCredential]):
    pass


def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Use a Runscope resource ID")
    return quote(value, safe="")


class RunscopeNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-runscope"
    webhook_signing_secret_not_issued = True
    scope_registry = RUNSCOPE_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_buckets", noun="buckets", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return RunscopeNodeConfig

    @staticmethod
    async def _request(token, method, path, *, body=None, params=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, json=body, params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = None
            try:
                payload = response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                detail = error.get("message") if isinstance(error, dict) else error
            except ValueError:
                pass
            # Preserve the provider's rejection text for connection evidence,
            # without echoing the token or a complete environment response.
            message = detail.replace(token, "[redacted]")[:500] if isinstance(detail, str) else "request failed"
            raise ValueError(f"Runscope API HTTP {response.status_code}: {message}")
        if response.status_code == 204 and method == "DELETE":
            return {"deleted": True}
        if not response.content:
            raise ValueError("Runscope returned an empty response where JSON was expected")
        result = response.json()
        if isinstance(result, dict) and result.get("error"):
            raise ValueError("Runscope API returned an error envelope")
        return result

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Runscope personal access token")
        op = self.config.config
        if op.operation == "on_test_completed":
            raise ValueError("This operation runs when Runscope sends a completion callback")
        self.scope_registry.require(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = re.sub(r"{([^}]+)}", lambda m: segment(values[m[1]]), spec.path)
        body, params = None, None
        if spec.payload == "bucket":
            # Current provider docs use query parameters; the pinned legacy
            # Swagger incorrectly describes a NewBucket JSON body.
            # https://help.blazemeter.com/apidocs/api-monitoring/buckets_create.htm
            params = {"name": op.name, "team_uuid": op.team_id}
        elif spec.payload:
            try:
                body = json.loads(op.payload_json)
            except (ValueError, TypeError):
                raise ValueError("Resource JSON must contain a JSON object") from None
            if not isinstance(body, dict):
                raise ValueError("Resource JSON must contain an object")
            required = "step_type" if spec.payload == "step" else "name"
            if not isinstance(body.get(required), str) or not body[required].strip():
                raise ValueError(f"Resource JSON requires {required}")
        data = await self._request(credential.api_token, spec.method, path, body=body, params=params)
        return {"status": "success", "operation": op.operation, "data": data.get("data", data) if isinstance(data, dict) else data}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: config.get(key) for key in ("bucket_key", "test_id", "environment_id")}

    @classmethod
    async def _change_callback(cls, credential, config, callback, *, remove=False):
        token = RunscopeTokenCredential.model_validate(credential).api_token
        base = "/buckets/" + segment(config.get("bucket_key")) + "/environments"
        result = await cls._request(token, "GET", base)
        rows = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ValueError("Runscope environment list is invalid")
        env = next((row for row in rows if isinstance(row, dict) and row.get("id") == config.get("environment_id")), None)
        if env is None:
            raise ValueError("The selected test environment was not found")
        hooks = env.get("webhooks")
        if hooks is None:
            hooks = []
        if not isinstance(hooks, list) or not all(isinstance(url, str) for url in hooks):
            raise ValueError("Runscope did not return the environment callback list")
        if not isinstance(env.get("name"), str):
            raise ValueError("Runscope environment name is missing")
        updated = [url for url in hooks if url != callback] if remove else list(dict.fromkeys([*hooks, callback]))
        if updated == hooks:
            return
        # PUT replaces the configuration: preserve every returned setting, including
        # fields added by the provider, rather than reconstructing a lossy subset.
        body = {key: value for key, value in env.items() if key not in {"id", "test_id", "exported_at", "version"}}
        body["webhooks"] = updated
        await cls._request(token, "PUT", base + "/" + segment(config.get("environment_id")), body=body)

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        await cls._change_callback(credential, config, webhook_url)
        return {"external_webhook_id": webhook_url}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        callback = config.get("external_webhook_id")
        if callback:
            await cls._change_callback(credential, config, callback, remove=True)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Standard environment callback notifications have no signature mechanism.
        # https://help.blazemeter.com/docs/guide/api-monitoring-notifications-overview.html
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return ((not config.get("test_id") or payload.get("test_id") == config["test_id"]) and
                payload.get("result") in {"pass", "fail"})

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"event": "test.completed", "data": {key: value for key, value in payload.items() if key != "_webhook"}}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("event") != "test.completed":
            return None
        data = output["data"]
        requests = data.get("requests") or []
        details = "\n".join(
            f"- {row.get('method')} {row.get('url')}: {row.get('result')} (HTTP {row.get('response_status_code')})"
            for row in requests[:10] if isinstance(row, dict))
        return {"text": f"Runscope: {data.get('test_name')} {data.get('result')} in {data.get('environment_name')} "
            f"for {data.get('team_name')} / {data.get('bucket_name')}. "
            f"Test {data.get('test_id')}; run {data.get('test_run_id')}. {data.get('test_run_url')}\n{details}",
            "conversation_key": data.get("test_id")}

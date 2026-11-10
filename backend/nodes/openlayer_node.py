"""Openlayer projects, evaluations and inference data.

REST operations follow the pinned Openlayer OpenAPI v1.0. Webhook lifecycle,
events and Standard Webhooks signatures follow the provider's published docs:
https://openlayer.com/docs/security/webhooks/manage-webhooks
https://openlayer.com/docs/security/webhooks/events
https://openlayer.com/docs/security/webhooks/verify-signatures
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.openlayer.com/v1"
EVENTS = ("test.created", "test.updated", "test.deleted", "tests.result.updated")
TASK_TYPES = Literal["llm-base", "tabular-classification", "tabular-regression", "text-classification"]
TEST_TYPES = Literal["integrity", "consistency", "performance", "fairness", "robustness"]
RESULT_STATUS = Literal["running", "passing", "failing", "skipped", "error"]


class OpenlayerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Openlayer API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://openlayer.com/docs/workspace-and-projects/find-your-api-key",
        "x-credential-instructions": "In Openlayer, open your user menu, choose API Keys, then Create API key. Copy the key and paste it here. Webhook triggers require a workspace admin's key. NoClick checks the connection by listing your projects.",
    })
    credential_type: Literal["openlayer_api_key"] = Field("openlayer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_json(self):
        inference_id = getattr(self, "inference_id", None)
        if inference_id is not None and (inference_id in {".", ".."} or any(c in inference_id for c in "/\\")
                or any(ord(c) < 32 or ord(c) == 127 for c in inference_id)):
            raise ValueError("Use a single inference ID without path separators or controls")
        for name in type(self).model_fields:
            if name.endswith("_json") and (raw := getattr(self, name)) is not None:
                try:
                    value = json.loads(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"{name} must contain valid JSON") from None
                if name == "rows_json":
                    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
                        raise ValueError("Rows JSON must be a nonempty array of objects")
                elif not isinstance(value, dict):
                    raise ValueError(f"{name} must contain a JSON object")
                elif name == "row_json" and not 1 <= len(value) <= 100:
                    raise ValueError("A row update needs between 1 and 100 properties")
        start, end = getattr(self, "start_timestamp", None), getattr(self, "end_timestamp", None)
        if start is not None and end is not None and start >= end:
            raise ValueError("End timestamp must be after start timestamp")
        return self


def text(title, *, required=False, maximum=None):
    return (str if required else str | None, Field(... if required else None, title=title, min_length=1, max_length=maximum))


def identifier(title):
    return (UUID, Field(..., title=title))


def json_text(title, *, required=False, description=""):
    return (str if required else str | None, Field(... if required else None, title=title, description=description,
        json_schema_extra={"ui:widget": "code_editor", "ui:options": {"language": "json"}}))


PAGE = {"page": (int, Field(1, ge=1, title="Page")), "per_page": (int, Field(25, ge=1, le=100, title="Page size"))}
PROJECT = {"project_id": identifier("Project ID")}
VERSION = {"project_version_id": identifier("Project commit ID")}
PIPELINE = {"inference_pipeline_id": identifier("Inference pipeline ID")}
ROW = {**PIPELINE, "inference_id": text("Inference ID", required=True, maximum=1000)}
TEST = {"test_id": identifier("Test ID")}
RESULT_FILTERS = {"test_type": (TEST_TYPES | None, Field(None, title="Test type")),
                  "result_status": (RESULT_STATUS | None, Field(None, title="Result status"))}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[tuple[str, str], ...] = ()
    body: tuple[tuple[str, str], ...] = ()


PAGINATION = (("page", "page"), ("per_page", "perPage"))
RESULT_QUERY = PAGINATION + (("test_type", "type"), ("result_status", "status"))
OPERATIONS = {
    "list_projects": Operation("List Projects", "Projects", "GET", "/projects", {
        **PAGE, "name": text("Project name"), "task_type": (TASK_TYPES | None, Field(None, title="Task type"))},
        PAGINATION + (("name", "name"), ("task_type", "taskType"))),
    "create_project": Operation("Create Project", "Projects", "POST", "/projects", {
        "name": text("Project name", required=True, maximum=64),
        "task_type": (TASK_TYPES, Field(..., title="Task type")),
        "description": text("Description", maximum=280)},
        body=(("name", "name"), ("task_type", "taskType"), ("description", "description"))),
    "update_project": Operation("Update Project", "Projects", "PATCH", "/projects/{project_id}", {
        **PROJECT, "name": text("Project name", maximum=64), "description": text("Description", maximum=280),
        "purpose": text("Purpose"), "model_developer": text("Model developer"),
        "data_retention_days": (int | None, Field(None, ge=3, title="Data retention days"))},
        body=(("name", "name"), ("description", "description"), ("purpose", "purpose"),
              ("model_developer", "modelDeveloper"), ("data_retention_days", "dataRetentionDays"))),
    "delete_project": Operation("Delete Project", "Projects", "DELETE", "/projects/{project_id}", PROJECT),
    "list_commits": Operation("List Project Commits", "Development", "GET", "/projects/{project_id}/versions", {**PROJECT, **PAGE}, PAGINATION),
    "create_commit": Operation("Create Project Commit", "Development", "POST", "/projects/{project_id}/versions", {
        **PROJECT, "storage_uri": text("Uploaded bundle storage URI", required=True),
        "commit_message": text("Commit message", required=True)},
        body=(("storage_uri", "storageUri"), ("commit_message", "commit.message"))),
    "get_commit": Operation("Get Project Commit", "Development", "GET", "/versions/{project_version_id}", VERSION),
    "list_commit_test_results": Operation("List Commit Test Results", "Development", "GET", "/versions/{project_version_id}/results", {
        **VERSION, **PAGE, **RESULT_FILTERS}, RESULT_QUERY),
    "list_inference_pipelines": Operation("List Inference Pipelines", "Monitoring", "GET", "/projects/{project_id}/inference-pipelines", {
        **PROJECT, **PAGE, "name": text("Pipeline name")}, PAGINATION + (("name", "name"),)),
    "create_inference_pipeline": Operation("Create Inference Pipeline", "Monitoring", "POST", "/projects/{project_id}/inference-pipelines", {
        **PROJECT, "name": text("Pipeline name", required=True, maximum=100),
        "description": (str, Field("", title="Description", max_length=500))},
        body=(("name", "name"), ("description", "description"))),
    "get_inference_pipeline": Operation("Get Inference Pipeline", "Monitoring", "GET", "/inference-pipelines/{inference_pipeline_id}", PIPELINE),
    "update_inference_pipeline": Operation("Update Inference Pipeline", "Monitoring", "PUT", "/inference-pipelines/{inference_pipeline_id}", {
        **PIPELINE, "name": text("Pipeline name", maximum=100), "description": text("Description", maximum=500),
        "reference_dataset_uri": text("Reference dataset storage URI", maximum=1000)},
        body=(("name", "name"), ("description", "description"), ("reference_dataset_uri", "referenceDatasetUri"))),
    "delete_inference_pipeline": Operation("Delete Inference Pipeline", "Monitoring", "DELETE", "/inference-pipelines/{inference_pipeline_id}", PIPELINE),
    "publish_inferences": Operation("Publish Inferences", "Monitoring", "POST", "/inference-pipelines/{inference_pipeline_id}/data-stream", {
        **PIPELINE, "rows_json": json_text("Rows JSON", required=True, description="Array of inference records with input and output columns."),
        "stream_config_json": json_text("Stream configuration JSON", required=True, description="Column mapping for the project's task type, as documented by Openlayer.")},
        body=(("rows_json", "rows"), ("stream_config_json", "config"))),
    "list_rows": Operation("List Inference Rows", "Inference Data", "POST", "/inference-pipelines/{inference_pipeline_id}/rows", {
        **PIPELINE, **PAGE, "filter_json": json_text("Dataset filter JSON"), "sort_column": text("Sort column"),
        "ascending": (bool | None, Field(None, title="Ascending"))},
        PAGINATION + (("sort_column", "sortColumn"), ("ascending", "asc")), (("filter_json", ""),)),
    "get_row": Operation("Get Inference Row", "Inference Data", "GET", "/inference-pipelines/{inference_pipeline_id}/rows/{inference_id}", ROW),
    "update_row": Operation("Update Inference Row", "Inference Data", "PUT", "/inference-pipelines/{inference_pipeline_id}/rows", {
        **ROW, "row_json": json_text("Row changes JSON", required=True), "stream_config_json": json_text("Column configuration JSON")},
        (("inference_id", "inferenceId"),), (("row_json", "row"), ("stream_config_json", "config"))),
    "delete_row": Operation("Delete Inference Row", "Inference Data", "DELETE", "/inference-pipelines/{inference_pipeline_id}/rows/{inference_id}", ROW),
    "list_tests": Operation("List Tests", "Tests", "GET", "/projects/{project_id}/tests", {
        **PROJECT, **PAGE, "test_type": (TEST_TYPES | None, Field(None, title="Test type")),
        "include_archived": (bool | None, Field(None, title="Include archived"))},
        PAGINATION + (("test_type", "type"), ("include_archived", "includeArchived"))),
    "evaluate_test": Operation("Evaluate Test", "Tests", "POST", "/tests/{test_id}/evaluate", {
        **TEST, "start_timestamp": (int, Field(..., title="Start Unix timestamp")), "end_timestamp": (int, Field(..., title="End Unix timestamp")),
        "inference_pipeline_id": (UUID | None, Field(None, title="Inference pipeline ID")),
        "overwrite_results": (bool, Field(False, title="Overwrite existing results"))},
        body=(("start_timestamp", "startTimestamp"), ("end_timestamp", "endTimestamp"),
              ("inference_pipeline_id", "inferencePipelineId"), ("overwrite_results", "overwriteResults"))),
    "list_test_results": Operation("List Test Results", "Tests", "GET", "/tests/{test_id}/results", {
        **TEST, **PAGE, "start_timestamp": (int | None, Field(None, title="Start Unix timestamp")),
        "end_timestamp": (int | None, Field(None, title="End Unix timestamp")),
        "inference_pipeline_id": (UUID | None, Field(None, title="Inference pipeline ID"))},
        PAGINATION + (("start_timestamp", "startTimestamp"), ("end_timestamp", "endTimestamp"), ("inference_pipeline_id", "inferencePipelineId"))),
    "list_pipeline_test_results": Operation("List Pipeline Test Results", "Tests", "GET", "/inference-pipelines/{inference_pipeline_id}/results", {
        **PIPELINE, **PAGE, **RESULT_FILTERS}, RESULT_QUERY),
}


def _make_config(name, spec):
    return create_model("Openlayer" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=_OperationConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label, "x-category": spec.category, "x-is-trigger": False})), **spec.fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class OpenlayerOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Openlayer Event", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Openlayer Event", "x-category": "Triggers", "x-is-trigger": True})
    workspace_id: UUID = Field(..., title="Workspace ID", description="Workspace UUID from Openlayer workspace settings. An admin's key is required to register webhooks.")
    event_type: Literal[*EVENTS] = Field("tests.result.updated", title="Event type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


OpenlayerConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (OpenlayerOnEventConfig,)], Field(discriminator="operation")]


class OpenlayerNodeConfig(NodeConfig[OpenlayerConfig, OpenlayerAPIKeyCredential]):
    pass


class OpenlayerNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-openlayer"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects")
    edit_examples = ["Publish inference data to Openlayer", "Evaluate an Openlayer test", "Alert when an Openlayer test suite finishes", "Create an Openlayer project"]

    @classmethod
    def get_config_model(cls):
        return OpenlayerNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if response.is_error:
            try:
                data = response.json()
                detail = data.get("message") or data.get("error") if isinstance(data, dict) else None
            except ValueError:
                detail = None
            detail = str(detail or "Request failed").replace(token, "[redacted]")
            raise ValueError(f"Openlayer API error {response.status_code}: {detail}")
        if not response.content:
            return {"success": True}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Openlayer returned an unexpected JSON response")
        return data

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = OpenlayerOnEventConfig.model_validate({**config, "operation": "on_event"})
        token = OpenlayerAPIKeyCredential.model_validate(credential).api_key
        data = await cls._request(token, "POST", f"/workspaces/{op.workspace_id}/webhooks", body={
            "url": webhook_url, "eventTypes": [op.event_type], "description": f"NoClick {node_id}"[:500]})
        if not data.get("id") or not data.get("secret"):
            raise ValueError("Openlayer did not return a webhook ID and signing secret")
        return {"external_webhook_id": str(data["id"]), "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = config.get("external_webhook_id")
        if not webhook_id or not credential:
            return
        workspace = str(UUID(str(config["workspace_id"])))
        token = OpenlayerAPIKeyCredential.model_validate(credential).api_key
        await cls._request(token, "DELETE", f"/workspaces/{workspace}/webhooks/{quote(str(webhook_id), safe='')}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"workspace_id": config.get("workspace_id"), "event_type": config.get("event_type", "tests.result.updated")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        headers = {key.lower(): value for key, value in headers.items()}
        message_id, timestamp = headers.get("webhook-id"), headers.get("webhook-timestamp")
        if (not isinstance(secret, str) or not secret or not message_id or not timestamp
                or not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 20):
            return False
        if abs(time.time() - int(timestamp)) > 300:
            return False
        try:
            key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
            if not key:
                return False
            message = message_id.encode() + b"." + timestamp.encode() + b"." + body
            expected = base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()
        except (ValueError, TypeError, binascii.Error):
            return False
        return any(part.startswith("v1,") and hmac.compare_digest(part[3:].encode(), expected.encode())
                   for part in headers.get("webhook-signature", "").split())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == config.get("event_type", "tests.result.updated")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"type": payload["type"], "timestamp": payload["timestamp"], "data": payload["data"]}

    @classmethod
    def resolve_agent_event(cls, output):
        kind = output.get("type")
        if kind not in EVENTS:
            return super().resolve_agent_event(output)
        data = output["data"]
        lines = [f"Openlayer {kind} at {output['timestamp']}"]
        if kind == "tests.result.updated":
            tests = data["tests"]
            lines.append(f"Project {tests['projectId']}: {tests['passing']}/{tests['total']} passing, {tests['failing']} failing, {tests['skipped']} skipped, {tests['running']} running.")
            if tests["projectVersionId"]:
                lines.append(f"Commit ID: {tests['projectVersionId']}.")
            if tests["inferencePipelineId"]:
                lines.append(f"Inference pipeline ID: {tests['inferencePipelineId']}.")
            lines.append("Use list_commit_test_results or list_pipeline_test_results with these IDs to inspect failures.")
            conversation_key = str(tests["projectId"])
        else:
            test = data["test"]
            lines.append(f"Test ID: {test['id']}.")
            if kind != "test.deleted":
                lines.append(f"{test['name']} ({test['type']}, {test['subtype']}).")
            if kind == "test.created":
                lines.append(f"Created by {test['creatorId']}; origin commit {test['originProjectVersionId']}. {test['description']}")
            conversation_key = str(test["id"])
        return {"text": "\n".join(lines), "conversation_key": conversation_key}

    async def execute(self, inputs):
        if not isinstance(self.config, OpenlayerNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Openlayer API key")
        op = self.config.config
        if isinstance(op, OpenlayerOnEventConfig):
            raise ValueError("This trigger waits for a signed Openlayer delivery")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        for name, value in values.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {wire: values[name] for name, wire in spec.query if name in values}
        body = {}
        for name, wire in spec.body:
            if name not in values:
                continue
            value = json.loads(values[name]) if name.endswith("_json") else values[name]
            if not wire:
                body.update(value)
            elif "." in wire:
                parent, child = wire.split(".")
                body.setdefault(parent, {})[child] = value
            else:
                body[wire] = value
        return await self._request(self.config.credentials.api_key, spec.method, path, params=params,
            body=body if spec.method in {"POST", "PUT", "PATCH"} else None)

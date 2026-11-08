"""Future AGI annotation API. Contract: https://docs.futureagi.com/openapi.json.

Request fields and Bearer API-key authentication follow the provider's API reference at
https://docs.futureagi.com/docs/api/annotations/labels/create-label.
List operations return one page, preserving the provider's pagination metadata.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.futureagi.com"


class FutureagiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Futureagi API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.futureagi.com/dashboard/keys",
            "x-credential-instructions": "Paste the API key from Future AGI Settings → API Keys. It is sent as a Bearer token, as in the published API request examples."})
    credential_type: Literal["futureagi_api_key"] = Field("futureagi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without a header prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resource(Input):
    id: str = Field(..., title="Resource ID", min_length=1, max_length=128, description="The label, score, or queue UUID.")

    @field_validator("id")
    @classmethod
    def safe_id(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a single resource ID without URL characters")
        return value


class Page(Input):
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(20, ge=1, le=100, title="Results Per Page")


class LabelFields(Input):
    name: str | None = Field(None, min_length=1, title="Name")
    description: str | None = Field(None, title="Description")
    settings: dict | None = Field(None, title="Label Settings", description='Type-specific JSON, for example {"no_of_stars": 5}.')
    allow_notes: bool | None = Field(None, title="Allow Notes")


class ListLabels(Page):
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})
    type: Literal["text", "categorical", "numeric", "star", "thumbs_up_down"] | None = None
    search: str | None = None
    project_id: str | None = None
    dataset: str | None = None
    include_usage_count: bool | None = None


class GetLabel(Resource):
    operation: Literal["get_label"] = Field("get_label", json_schema_extra={"ui:hidden": True})


class CreateLabel(LabelFields):
    operation: Literal["create_label"] = Field("create_label", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Name")
    type: Literal["text", "categorical", "numeric", "star", "thumbs_up_down"] = Field(..., title="Label Type")
    project: str | None = None


class UpdateLabel(Resource, LabelFields):
    operation: Literal["update_label"] = Field("update_label", json_schema_extra={"ui:hidden": True})


class DeleteLabel(Resource):
    operation: Literal["delete_label"] = Field("delete_label", description="Soft-delete a label; restore_label can recover it.", json_schema_extra={"ui:hidden": True})


class RestoreLabel(Resource):
    operation: Literal["restore_label"] = Field("restore_label", json_schema_extra={"ui:hidden": True})


class ListScores(Page):
    operation: Literal["list_scores"] = Field("list_scores", json_schema_extra={"ui:hidden": True})
    source_type: Literal["trace", "span", "generation", "session"] | None = None
    source_id: str | None = None
    label_id: str | None = None
    annotator_id: str | None = None


class Source(Input):
    source_type: Literal["trace", "span", "generation", "session"] = Field(..., title="Source Type")
    source_id: str = Field(..., min_length=1, title="Source UUID")


class GetScoresForSource(Source):
    operation: Literal["get_scores_for_source"] = Field("get_scores_for_source", json_schema_extra={"ui:hidden": True})
    label_id: str | None = None
    annotator_id: str | None = None


class Score(Input):
    label_id: str = Field(..., min_length=1, title="Label UUID")
    value: dict = Field(..., title="Score Value", description='JSON matching the label type, for example {"rating": 5}.')
    score_source: Literal["human", "automation", "sdk"] = "human"


class CreateScore(Source, Score):
    operation: Literal["create_score"] = Field("create_score", description="May automatically complete an associated queue item when all required labels are scored.", json_schema_extra={"ui:hidden": True})
    notes: str | None = None


class BulkCreateScores(Source):
    operation: Literal["bulk_create_scores"] = Field("bulk_create_scores", description="Create multiple scores for one source; inspect returned errors for partial failures.", json_schema_extra={"ui:hidden": True})
    scores: list[Score] = Field(..., min_length=1, title="Scores")
    notes: str | None = None


class DeleteScore(Resource):
    operation: Literal["delete_score"] = Field("delete_score", description="Soft-delete a score and its legacy annotation. Requires creator or organization admin permissions.", json_schema_extra={"ui:hidden": True})


class QueueFields(Input):
    name: str | None = Field(None, min_length=1, title="Queue Name")
    description: str | None = None
    instructions: str | None = None
    assignment_strategy: Literal["manual", "round_robin", "load_balanced"] | None = None
    annotations_required: int | None = Field(None, ge=1)
    reservation_timeout_minutes: int | None = Field(None, ge=1)
    requires_review: bool | None = None
    auto_assign: bool | None = None
    label_ids: list[str] | None = Field(None, description="Labels to attach; updates replace the existing set.")
    annotator_ids: list[str] | None = Field(None, description="Annotators to assign; updates replace the existing set.")
    annotator_roles: dict[str, Literal["annotator", "manager", "reviewer"]] | None = None


class ListQueues(Page):
    operation: Literal["list_queues"] = Field("list_queues", json_schema_extra={"ui:hidden": True})
    status: str | None = None
    search: str | None = None
    include_counts: bool | None = None


class GetQueue(Resource):
    operation: Literal["get_queue"] = Field("get_queue", json_schema_extra={"ui:hidden": True})


class CreateQueue(QueueFields):
    operation: Literal["create_queue"] = Field("create_queue", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Queue Name")
    status: Literal["draft", "active", "paused"] | None = None
    project_id: str | None = None
    dataset_id: str | None = None
    agent_definition_id: str | None = None


class UpdateQueue(Resource, QueueFields):
    operation: Literal["update_queue"] = Field("update_queue", json_schema_extra={"ui:hidden": True})


class DeleteQueue(Resource):
    operation: Literal["delete_queue"] = Field("delete_queue", description="Soft-delete an annotation queue.", json_schema_extra={"ui:hidden": True})


FutureagiConfig = Annotated[Union[ListLabels, GetLabel, CreateLabel, UpdateLabel, DeleteLabel,
    RestoreLabel, ListScores, GetScoresForSource, CreateScore, BulkCreateScores, DeleteScore,
    ListQueues, GetQueue, CreateQueue, UpdateQueue, DeleteQueue], Field(discriminator="operation")]


class FutureagiFullConfig(NodeConfig[FutureagiConfig, FutureagiAPIKeyCredential]):
    pass


# Exactly one provider operation per native operation; no request URL input.
ROUTES = {
    "list_labels": ("GET", "/model-hub/annotations-labels/"),
    "get_label": ("GET", "/model-hub/annotations-labels/{id}/"),
    "create_label": ("POST", "/model-hub/annotations-labels/"),
    "update_label": ("PUT", "/model-hub/annotations-labels/{id}/"),
    "delete_label": ("DELETE", "/model-hub/annotations-labels/{id}/"),
    "restore_label": ("POST", "/model-hub/annotations-labels/{id}/restore/"),
    "list_scores": ("GET", "/model-hub/scores/"),
    "get_scores_for_source": ("GET", "/model-hub/scores/for-source/"),
    "create_score": ("POST", "/model-hub/scores/"),
    "bulk_create_scores": ("POST", "/model-hub/scores/bulk/"),
    "delete_score": ("DELETE", "/model-hub/scores/{id}/"),
    "list_queues": ("GET", "/model-hub/annotation-queues/"),
    "get_queue": ("GET", "/model-hub/annotation-queues/{id}/"),
    "create_queue": ("POST", "/model-hub/annotation-queues/"),
    "update_queue": ("PUT", "/model-hub/annotation-queues/{id}/"),
    "delete_queue": ("DELETE", "/model-hub/annotation-queues/{id}/"),
}


class FutureagiNode(WorkflowNode):
    integration_type = "automation-futureagi"
    connection_evidence = ConnectionEvidence(noun="annotation queues", operation="list_queues")

    @classmethod
    def get_config_model(cls):
        return FutureagiFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Futureagi API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(exclude={"operation", "id"}, exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", config.id)
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}} if method == "GET" else ({"json": payload} if payload else {})
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.api_key,
                    "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Retain provider rejection text for the shared connection verdict.
            message = response.text
            for secret in (credential.api_key,):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"Futureagi HTTP {response.status_code}: {message[:2000]}")
        if response.status_code == 204 or not response.content:
            return {"status": "success", "data": None}
        body = response.json()
        if isinstance(body, dict) and (body.get("error") or body.get("success") is False):
            raise ValueError(f"Futureagi: {body.get('error') or body.get('message') or 'Request rejected'}")
        return {"status": "success", "data": body}

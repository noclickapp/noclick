"""Ashby ATS operations using its versioned, Basic-authenticated RPC API.

Ashby does not offer a customer OAuth grant for this API. Keys are created by
an Ashby administrator and scoped to endpoint read/write permissions.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_URL = "https://api.ashbyhq.com"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class AshbyApiKeyCredential(BaseModel):
    credential_type: Literal["ashby_api_key"] = Field("ashby_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    class Config:
        json_schema_extra = {"x-credential-url": "https://app.ashbyhq.com/admin/api/credentials"}


# Field types: s = text, i = integer, b = checkbox, j = JSON object/array.
# A trailing ! marks a required field. The names and RPC methods come from
# Ashby's published OpenAPI definitions (v2026-01-01).
OPERATION_SPECS: dict[str, tuple[str, str, str, str]] = {
    "get_api_key_info": ("apiKey.info", "Get API Key Info", "Account", ""),
    "list_candidates": ("candidate.list", "List Candidates", "Candidates", "cursor:s limit:i syncToken:s createdAfter:i createdBefore:i"),
    "get_candidate": ("candidate.info", "Get Candidate", "Candidates", "id:s!"),
    "search_candidates": ("candidate.search", "Search Candidates", "Candidates", "email:s name:s limit:i"),
    "create_candidate": ("candidate.create", "Create Candidate", "Candidates", "name:s! email:s phoneNumber:s linkedInUrl:s githubUrl:s website:s sourceId:s creditedToUserId:s"),
    "update_candidate": ("candidate.update", "Update Candidate", "Candidates", "candidateId:s! name:s email:s phoneNumber:s linkedInUrl:s githubUrl:s websiteUrl:s alternateEmail:s sourceId:s creditedToUserId:s sendNotifications:b"),
    "add_candidate_tag": ("candidate.addTag", "Add Candidate Tag", "Candidates", "candidateId:s! tagId:s!"),
    "remove_candidate_tag": ("candidate.removeTag", "Remove Candidate Tag", "Candidates", "candidateId:s! tagId:s!"),
    "create_candidate_note": ("candidate.createNote", "Create Candidate Note", "Candidates", "candidateId:s! note:s! sendNotifications:b isPrivate:b"),
    "list_candidate_notes": ("candidate.listNotes", "List Candidate Notes", "Candidates", "candidateId:s! cursor:s syncToken:s limit:i"),
    "list_candidate_tags": ("candidateTag.list", "List Candidate Tags", "Candidates", "includeArchived:b cursor:s limit:i syncToken:s"),
    "list_applications": ("application.list", "List Applications", "Applications", "cursor:s limit:i syncToken:s status:s jobId:s createdAfter:i createdBefore:i"),
    "get_application": ("application.info", "Get Application", "Applications", "applicationId:s!"),
    "create_application": ("application.create", "Create Application", "Applications", "candidateId:s! jobId:s! interviewPlanId:s interviewStageId:s sourceId:s creditedToUserId:s"),
    "update_application": ("application.update", "Update Application", "Applications", "applicationId:s! sourceId:s creditedToUserId:s sendNotifications:b"),
    "change_application_stage": ("application.changeStage", "Change Application Stage", "Applications", "applicationId:s! interviewStageId:s! archiveReasonId:s"),
    "list_jobs": ("job.list", "List Jobs", "Jobs", "cursor:s limit:i syncToken:s status:j createdAfter:i"),
    "get_job": ("job.info", "Get Job", "Jobs", "id:s!"),
    "search_jobs": ("job.search", "Search Jobs", "Jobs", "title:s requisitionId:s limit:i"),
    "create_job": ("job.create", "Create Job", "Jobs", "title:s! teamId:s! locationId:s! defaultInterviewPlanId:s jobTemplateId:s employmentType:s brandId:s"),
    "update_job": ("job.update", "Update Job", "Jobs", "jobId:s! title:s teamId:s locationId:s defaultInterviewPlanId:s employmentType:s customRequisitionId:s"),
    "set_job_status": ("job.setStatus", "Set Job Status", "Jobs", "jobId:s! status:s! closeReasonId:s"),
    "list_job_postings": ("jobPosting.list", "List Job Postings", "Job Postings", "location:s department:s listedOnly:b includeUnpublishedJobPostings:b jobBoardId:s"),
    "get_job_posting": ("jobPosting.info", "Get Job Posting", "Job Postings", "jobPostingId:s! jobBoardId:s includeUnpublishedJobPostings:b"),
    "create_job_posting": ("jobPosting.create", "Create Job Posting", "Job Postings", "jobId:s! title:s description:j workplaceType:s status:s isListed:b locationId:s applicationFormDefinitionId:s"),
    "set_job_posting_status": ("jobPosting.setStatus", "Set Job Posting Status", "Job Postings", "jobPostingId:s! status:s!"),
    "list_departments": ("department.list", "List Departments", "Organization", "includeArchived:b cursor:s limit:i syncToken:s"),
    "list_locations": ("location.list", "List Locations", "Organization", "includeArchived:b includeLocationHierarchy:b cursor:s limit:i syncToken:s"),
    "list_users": ("user.list", "List Users", "Organization", "includeDeactivated:b cursor:s limit:i syncToken:s"),
}


def _make_config(name: str, label: str, category: str, fields: str) -> type[BaseModel]:
    definitions: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[name],
            Field(name, title=label, json_schema_extra={
                "const": name, "ui:hidden": True, "x-category": category,
                "x-is-trigger": False, "x-display-name": label,
            }),
        )
    }
    for token in fields.split():
        field_name, kind = token.split(":")
        required = kind.endswith("!")
        kind = kind.rstrip("!")
        value_type = {"s": str, "i": int, "b": bool, "j": str}[kind]
        if not required:
            value_type = value_type | None
        title = re.sub(r"(?<!^)(?=[A-Z])", " ", field_name).replace("Id", " ID").title()
        extra = JSON_EDITOR if kind == "j" else None
        if field_name in {"candidateId", "jobId", "teamId", "locationId", "tagId"}:
            extra = {"x-dynamic-options": {
                "field_name": field_name, "placeholder": f"Select {title.lower()}...",
                "searchable": True, "allow_custom": True,
            }}
        definitions[field_name] = (
            value_type,
            Field(... if required else None, title=title,
                  json_schema_extra=extra),
        )
    class_name = "Ashby" + "".join(part.title() for part in name.split("_")) + "Config"
    return create_model(class_name, __module__=__name__, **definitions)


CONFIG_MODELS = {
    name: _make_config(name, label, category, fields)
    for name, (_, label, category, fields) in OPERATION_SPECS.items()
}
AshbyConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class AshbyNodeConfig(NodeConfig[AshbyConfig, AshbyApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _request_body(config: BaseModel, spec: str) -> dict[str, Any]:
    body = config.model_dump(exclude={"operation"}, exclude_none=True)
    for token in spec.split():
        key, kind = token.split(":")
        if kind.rstrip("!") != "j" or key not in body:
            continue
        try:
            body[key] = json.loads(body[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be valid JSON") from exc
        if not isinstance(body[key], (dict, list)):
            raise ValueError(f"{key} must be a JSON object or array")
    return body


class AshbyNode(WorkflowNode):
    integration_type = "automation-ashby"
    credential_provider_labels = {"ashby": "Ashby Account"}
    auto_select_credential = False
    connection_evidence = ConnectionEvidence(
        operation="list_jobs", noun="jobs", identity_operation="get_api_key_info",
    )
    edit_examples = [
        "Find candidates in Ashby", "Create an Ashby candidate",
        "Move an Ashby application to another stage", "List open Ashby jobs",
    ]

    @classmethod
    def get_config_model(cls):
        return AshbyNodeConfig

    @staticmethod
    async def _request(credential: AshbyApiKeyCredential, method: str, body: dict[str, Any]):
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{API_URL}/{method}", json=body,
                auth=httpx.BasicAuth(credential.api_key, ""),
                headers={"Accept": "application/json; version=1"},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"Ashby API returned non-JSON response ({response.status_code})") from exc
        if response.is_error or not payload.get("success"):
            detail = payload.get("errors") or payload.get("error") or payload.get("message") or "request failed"
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
            raise ValueError(f"Ashby API error {response.status_code}: {detail}")
        return payload

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict[str, Any],
        context: dict[str, Any] | None = None, page_token: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        source = {
            "candidateId": ("candidate.list", "name"),
            "jobId": ("job.list", "title"),
            "teamId": ("department.list", "name"),
            "locationId": ("location.list", "name"),
            "tagId": ("candidateTag.list", "title"),
        }.get(field_name)
        if not source:
            return []
        credential = AshbyApiKeyCredential.model_validate(credential_data)
        method, label_key = source
        request = {"cursor": page_token or "start", "limit": 100}
        payload = await cls._request(credential, method, request)
        rows = payload.get("results") or []
        if search:
            rows = [row for row in rows if search.lower() in str(row.get(label_key, "")).lower()]
        return [{"value": row["id"], "label": row.get(label_key) or row["id"]}
                for row in rows if isinstance(row, dict) and row.get("id")]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, AshbyNodeConfig):
            raise ValueError("Ashby configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Ashby API key")
        op = self.config.config
        method, _, _, spec = OPERATION_SPECS[op.operation]
        body = _request_body(op, spec)
        payload = await self._request(credential, method, body)
        return {"status": "success", "operation": op.operation, "data": payload}

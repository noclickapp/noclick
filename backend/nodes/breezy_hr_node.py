"""Breezy HR v3 recruiting operations using a pasted personal access token.

Each operation makes one documented API request. Lists expose explicit page
controls; writes are never retried automatically. Stage changes may run provider
actions and publishing a position makes it public.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.breezy.hr/v3"
TYPE = "breezy_hr_api_token"


class BreezyHRTokenCredential(BaseModel):
    model_config = ConfigDict(title="Breezy HR API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.breezy.hr/reference/authorization",
            "x-credential-instructions": "Paste an existing Breezy HR personal access token (PAT). NoClick sends it only to api.breezy.hr. Access follows the token owner's company membership and permissions. Listing your companies verifies the connection; write permissions are checked by Breezy when an operation runs."})
    credential_type: Literal["breezy_hr_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the token, without an Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_path(cls, value, info):
        if value is not None and info.field_name in {"company_id", "position_id", "candidate_id", "pipeline_id"}:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Use a single Breezy resource ID")
        return value


class _Company(_Input):
    company_id: str = Field(..., min_length=1, max_length=128, description="Company ID from List Companies")


class _Position(_Company):
    position_id: str = Field(..., min_length=1, max_length=128, description="Position ID from List Positions")


class _Candidate(_Position):
    candidate_id: str = Field(..., min_length=1, max_length=128, description="Candidate ID from List Candidates")


class _Page(_Input):
    page_size: int | None = Field(None, ge=1, le=50, description="Omit for all results. Set to request one page.")
    page: int | None = Field(None, ge=1, description="1-based page number, requires page size")
    sort: str | None = Field(None, max_length=128)

    @model_validator(mode="after")
    def paging(self):
        if self.page is not None and self.page_size is None:
            raise ValueError("Set page size when selecting a page")
        return self


class Location(_Input):
    country: str = Field(..., pattern="^[A-Z]{2}$", description="ISO country code, such as US")
    state: str | None = Field(None, max_length=128)
    city: str | None = Field(None, max_length=256)
    is_remote: bool | None = None


class _CandidateFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=500)
    email_address: str | None = Field(None, max_length=320)
    phone_number: str | None = Field(None, max_length=128)
    address: str | None = Field(None, max_length=2000)
    summary: str | None = Field(None, max_length=100000)
    cover_letter: str | None = Field(None, max_length=100000)
    tags: list[str] | None = Field(None, max_length=100)


class _PositionFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=100000)
    type: Literal["fullTime", "partTime", "contract", "temporary", "other"] | None = None
    department: str | None = Field(None, max_length=256, description="Configured department name")
    category: str | None = Field(None, max_length=128)
    pipeline_id: str | None = Field(None, max_length=128)
    tags: list[str] | None = Field(None, max_length=100)


class BreezyGetUser(_Input):
    """Get user in Breezy HR."""
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})


class BreezyListCompanies(_Input):
    """List companies in Breezy HR."""
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True})


class BreezyGetCompany(_Company):
    """Get company in Breezy HR."""
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})


class BreezyListDepartments(_Company):
    """List departments in Breezy HR."""
    operation: Literal["list_departments"] = Field("list_departments", title="List Departments", json_schema_extra={"ui:hidden": True})


class BreezyListPipelines(_Company):
    """List pipelines in Breezy HR."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", title="List Pipelines", json_schema_extra={"ui:hidden": True})


class BreezyGetPipeline(_Company):
    """Get pipeline in Breezy HR."""
    operation: Literal["get_pipeline"] = Field("get_pipeline", title="Get Pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: str = Field(..., description="Pipeline ID, default or default_pool")


class BreezyListPositions(_Company, _Page):
    """List positions in Breezy HR."""
    operation: Literal["list_positions"] = Field("list_positions", title="List Positions", json_schema_extra={"ui:hidden": True})
    state: Literal["published", "draft", "archived", "closed", "pending"] | None = None


class BreezyGetPosition(_Position):
    """Get position in Breezy HR."""
    operation: Literal["get_position"] = Field("get_position", title="Get Position", json_schema_extra={"ui:hidden": True})


class BreezyCreatePosition(_Company, _PositionFields):
    """Create position in Breezy HR."""
    operation: Literal["create_position"] = Field("create_position", title="Create Position", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=100000)
    type: Literal["fullTime", "partTime", "contract", "temporary", "other"]
    location: Location


class BreezyUpdatePosition(_Position, _PositionFields):
    """Update position in Breezy HR."""
    operation: Literal["update_position"] = Field("update_position", title="Update Position", json_schema_extra={"ui:hidden": True})


class BreezySetPositionState(_Position):
    """Set position state in Breezy HR."""
    operation: Literal["set_position_state"] = Field("set_position_state", title="Set Position State", json_schema_extra={"ui:hidden": True})
    state: Literal["published", "draft", "archived", "closed"] = Field(..., description="Publishing makes the position public; Breezy approval and plan rules apply")


class BreezyGetPositionTeam(_Position):
    """Get position team in Breezy HR."""
    operation: Literal["get_position_team"] = Field("get_position_team", title="Get Position Team", json_schema_extra={"ui:hidden": True})


class BreezySearchCandidates(_Company):
    """Search candidates in Breezy HR."""
    operation: Literal["search_candidates"] = Field("search_candidates", title="Search Candidates", json_schema_extra={"ui:hidden": True})
    email_address: str = Field(..., min_length=3, max_length=320, description="Exact candidate email address")


class BreezyListCandidates(_Position, _Page):
    """List candidates in Breezy HR."""
    operation: Literal["list_candidates"] = Field("list_candidates", title="List Candidates", json_schema_extra={"ui:hidden": True})
    stage_id: str | None = Field(None, pattern="^[A-Za-z0-9_-]{1,64}$")


class BreezyAddCandidate(_Position, _CandidateFields):
    """Add candidate in Breezy HR."""
    operation: Literal["add_candidate"] = Field("add_candidate", title="Add Candidate", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    source: str | None = Field(None, max_length=500)
    origin: Literal["sourced", "applied"] = Field("sourced", description="Applied can email the candidate and always runs stage actions; required application fields still apply")
    stage_actions_enabled: bool = Field(False, description="Run add-stage actions for sourced candidates")

    @model_validator(mode="after")
    def applied_email(self):
        if self.origin == "applied" and not self.email_address:
            raise ValueError("Applied candidates need an email address")
        return self


class BreezyGetCandidate(_Candidate):
    """Get candidate in Breezy HR."""
    operation: Literal["get_candidate"] = Field("get_candidate", title="Get Candidate", json_schema_extra={"ui:hidden": True})


class BreezyUpdateCandidate(_Candidate, _CandidateFields):
    """Update candidate in Breezy HR."""
    operation: Literal["update_candidate"] = Field("update_candidate", title="Update Candidate", json_schema_extra={"ui:hidden": True})
    source: str | None = Field(None, max_length=500)
    headline: str | None = Field(None, max_length=1000)


class BreezySetCandidateStage(_Candidate):
    """Set candidate stage in Breezy HR."""
    operation: Literal["set_candidate_stage"] = Field("set_candidate_stage", title="Set Candidate Stage", json_schema_extra={"ui:hidden": True})
    stage_id: str = Field(..., pattern="^[A-Za-z0-9_-]{1,64}$", description="Stage ID from a pipeline. Moves fire webhooks and configured stage actions, including hiring/onboarding.")


class BreezyGetCandidateStream(_Candidate):
    """Get candidate stream in Breezy HR."""
    operation: Literal["get_candidate_stream"] = Field("get_candidate_stream", title="Get Candidate Stream", json_schema_extra={"ui:hidden": True})
    skip: int = Field(0, ge=0, le=10000, description="Offset in 50-record pages. A first_activity entry marks the final page.")


class BreezyPostCandidateNote(_Candidate):
    """Post candidate note in Breezy HR."""
    operation: Literal["post_candidate_note"] = Field("post_candidate_note", title="Post Candidate Note", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=100000, description="Internal team note; not sent to the candidate")


Operation = Annotated[Union[BreezyGetUser, BreezyListCompanies, BreezyGetCompany, BreezyListDepartments, BreezyListPipelines, BreezyGetPipeline, BreezyListPositions, BreezyGetPosition, BreezyCreatePosition, BreezyUpdatePosition, BreezySetPositionState, BreezyGetPositionTeam, BreezySearchCandidates, BreezyListCandidates, BreezyAddCandidate, BreezyGetCandidate, BreezyUpdateCandidate, BreezySetCandidateStage, BreezyGetCandidateStream, BreezyPostCandidateNote], Field(discriminator="operation")]


class BreezyHRConfig(NodeConfig[Operation, BreezyHRTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_user': {'method': 'GET', 'path': '/user'},
 'list_companies': {'method': 'GET', 'path': '/companies'},
 'get_company': {'method': 'GET', 'path': '/company/{company_id}'},
 'list_departments': {'method': 'GET', 'path': '/company/{company_id}/departments'},
 'list_pipelines': {'method': 'GET', 'path': '/company/{company_id}/pipelines'},
 'get_pipeline': {'method': 'GET', 'path': '/company/{company_id}/pipeline/{pipeline_id}'},
 'list_positions': {'method': 'GET',
                    'path': '/company/{company_id}/positions',
                    'query': ['state', 'page_size', 'page', 'sort']},
 'get_position': {'method': 'GET', 'path': '/company/{company_id}/position/{position_id}'},
 'create_position': {'method': 'POST',
                     'path': '/company/{company_id}/positions',
                     'body': ['name',
                              'description',
                              'type',
                              'location',
                              'department',
                              'category',
                              'pipeline_id',
                              'tags']},
 'update_position': {'method': 'PUT',
                     'path': '/company/{company_id}/position/{position_id}',
                     'body': ['name',
                              'description',
                              'type',
                              'department',
                              'category',
                              'pipeline_id',
                              'tags']},
 'set_position_state': {'method': 'PUT',
                        'path': '/company/{company_id}/position/{position_id}/state',
                        'body': ['state'],
                        'status': 204},
 'get_position_team': {'method': 'GET',
                       'path': '/company/{company_id}/position/{position_id}/team'},
 'search_candidates': {'method': 'GET',
                       'path': '/company/{company_id}/candidates/search',
                       'query': ['email_address']},
 'list_candidates': {'method': 'GET',
                     'path': '/company/{company_id}/position/{position_id}/candidates',
                     'query': ['page_size', 'page', 'sort', 'stage_id']},
 'add_candidate': {'method': 'POST',
                   'path': '/company/{company_id}/position/{position_id}/candidates',
                   'body': ['name',
                            'email_address',
                            'phone_number',
                            'address',
                            'summary',
                            'cover_letter',
                            'tags',
                            'source',
                            'origin'],
                   'query': ['stage_actions_enabled']},
 'get_candidate': {'method': 'GET',
                   'path': '/company/{company_id}/position/{position_id}/candidate/{candidate_id}'},
 'update_candidate': {'method': 'PUT',
                      'path': '/company/{company_id}/position/{position_id}/candidate/{candidate_id}',
                      'body': ['name',
                               'email_address',
                               'phone_number',
                               'address',
                               'summary',
                               'cover_letter',
                               'tags',
                               'source',
                               'headline']},
 'set_candidate_stage': {'method': 'PUT',
                         'path': '/company/{company_id}/position/{position_id}/candidate/{candidate_id}/stage',
                         'body': ['stage_id'],
                         'status': 204},
 'get_candidate_stream': {'method': 'GET',
                          'path': '/company/{company_id}/position/{position_id}/candidate/{candidate_id}/stream',
                          'query': ['skip']},
 'post_candidate_note': {'method': 'POST',
                         'path': '/company/{company_id}/position/{position_id}/candidate/{candidate_id}/stream',
                         'body': ['body']}}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class BreezyHRNode(WorkflowNode):
    integration_type = "automation-breezy-hr"
    connection_evidence = ConnectionEvidence(noun="companies", operation="list_companies", identity_operation="get_user", label_keys=("name", "friendly_id", "_id"))

    @classmethod
    def get_config_model(cls):
        return BreezyHRConfig

    @classmethod
    def parse_config(cls, config_data):
        return BreezyHRConfig.model_validate(runtime_config_view(config_data, BreezyHRConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Breezy HR API token")
        cfg = self.config.config.model_dump(exclude_none=True)
        operation = cfg["operation"]
        route = ROUTES[operation]
        method = route["method"]
        token = self.config.credentials.api_token
        path = route["path"].format(**cfg)
        params = {key: str(cfg[key]).lower() if isinstance(cfg[key], bool) else cfg[key]
                  for key in route.get("query", ()) if key in cfg}
        body = {key: cfg[key] for key in route.get("body", ()) if key in cfg}
        if method != "GET" and not body:
            raise ValueError("Include at least one field to update")
        expected = route.get("status", 200)
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=30) as client:
                async with client.stream(method, BASE + path,
                        headers={"Authorization": token, "Accept": "application/json"},
                        params=params, **({"json": body} if method != "GET" else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 10 * 1024 * 1024:
                            raise ValueError("Breezy HR response exceeds 10 MB; use pagination")
                    status = response.status_code
                    if status != expected:
                        message = "Breezy HR request did not return the documented completed status"
                        try:
                            error = json.loads(raw).get("error", {})
                            if isinstance(error, dict) and isinstance(error.get("message"), str):
                                message = error["message"][:2000]
                        except (ValueError, AttributeError):
                            pass
                        output = {"status": "error" if method == "GET" or 400 <= status < 500 else "unknown",
                            "http_status": status, "message": message, "action": operation}
                        if status == 429:
                            output["retry_after"] = response.headers.get("Retry-After")
                        if method != "GET":
                            output["write_outcome"] = "partial" if status == 202 else "unverified"
                    elif expected == 204:
                        if raw.strip():
                            raise ValueError("Unexpected body for a no-content response")
                        output = {"status": "success", "action": operation, "http_status": status}
                    else:
                        data = json.loads(raw)
                        if not isinstance(data, (dict, list)) or isinstance(data, dict) and "error" in data:
                            raise ValueError("Unexpected Breezy HR response")
                        list_op = operation in {"list_companies", "list_departments", "list_positions", "get_position_team", "search_candidates", "list_candidates", "get_candidate_stream"}
                        if list_op and not isinstance(data, list):
                            raise ValueError("Expected a Breezy HR list")
                        output = {"status": "success", "action": operation,
                                  "items" if isinstance(data, list) else "data": data}
                        if operation in {"list_positions", "list_candidates"}:
                            size = cfg.get("page_size")
                            output["has_more"] = bool(size and len(data) >= size)
                            output["complete"] = not output["has_more"]
                            if output["has_more"]:
                                output["next_page"] = cfg.get("page", 1) + 1
                        elif operation == "get_candidate_stream":
                            final = not data or any(isinstance(item, dict) and item.get("first_activity") is True for item in data)
                            output["complete"] = final
                            output["has_more"] = not final and cfg["skip"] < 10000
                            if output["has_more"]:
                                output["next_skip"] = min(cfg["skip"] + 50, 10000)
        except (httpx.HTTPError, OSError, ValueError):
            output = {"status": "error" if method == "GET" else "unknown", "action": operation,
                      "message": "Breezy HR response could not be verified; inspect before retrying a write"}
        output["success"] = output["status"] == "success"
        output = _redact(output, token)
        await self.emit(output)
        return output

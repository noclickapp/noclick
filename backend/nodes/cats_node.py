"""CATS v3 recruiting operations, one documented API request per operation.

Contract: https://docs.catsone.com/openapi.yaml (1.0.0).
The published Host section specifies /v3, omitted by the OpenAPI servers URL.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import secrets
from urllib.parse import urlparse
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.catsone.com/v3"


class CatsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="CATS API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.catsone.com/#authentication",
        "x-credential-instructions": "In CATS, open Administration settings and create a v3 API key. Paste the key here without the Token prefix. Older transaction codes do not work. The key can read and change records allowed by your CATS account.",
    })
    credential_type: Literal["cats_api_key"] = Field("cats_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Token prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Config):
    page: int = Field(1, ge=1, title="Page", description="One page per run; increment to retrieve the next page.")
    per_page: int = Field(25, ge=1, le=100, title="Results per page")


class CatsAddress(_Config):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class CatsLocation(_Config):
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class CatsEmail(_Config):
    email: str = Field(..., min_length=1)
    is_primary: bool = False


class CatsPhone(_Config):
    number: str = Field(..., min_length=1)
    extension: str | None = None
    type: str | None = None


class CatsDataItem(_Config):
    id: int = Field(..., gt=0)
    type: Literal["candidate", "contact", "company", "job"]


class _Candidate(_Config):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    middle_name: str | None = None
    title: str | None = None
    address: CatsAddress | None = None
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    website: str | None = None
    current_employer: str | None = None
    key_skills: str | None = None
    notes: str | None = None
    source: str | None = None
    owner_id: int | None = Field(None, gt=0)
    is_active: bool | None = None
    is_hot: bool | None = None


class _Company(_Config):
    name: str = Field(..., min_length=1)
    owner_id: int = Field(..., gt=0)
    website: str | None = None
    phones: list[CatsPhone] | None = None
    address: CatsAddress | None = None
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    notes: str | None = None
    is_hot: bool | None = None
    key_technologies: str | None = None


class _Contact(_Config):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    owner_id: int = Field(..., gt=0)
    company_id: int = Field(..., gt=0)
    title: str | None = None
    reports_to_id: int | None = Field(None, gt=0)
    has_left_company: bool | None = None
    emails: list[CatsEmail] | None = None
    phones: list[CatsPhone] | None = None
    address: CatsAddress | None = None
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    is_hot: bool | None = None
    notes: str | None = None


class _Job(_Config):
    title: str = Field(..., min_length=1)
    location: CatsLocation = Field(..., description="Job location, using city, state and postal_code.")
    company_id: int = Field(..., gt=0)
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    department_id: int | None = Field(None, gt=0)
    recruiter_id: int | None = Field(None, gt=0)
    owner_id: int | None = Field(None, gt=0)
    is_hot: bool | None = None
    salary: str | None = None
    type: str | None = None
    openings: int | None = Field(None, ge=0)
    external_id: str | None = None
    description: str | None = None
    notes: str | None = None
    contact_id: int | None = Field(None, gt=0)


class _Task(_Config):
    assigned_to_id: int | None = Field(None, gt=0)
    description: str | None = None
    priority: int | None = Field(None, ge=1, le=5)
    date_due: str | None = Field(None, description="RFC 3339 timestamp. Omit for ASAP when creating a task.")


class CatsGetSiteConfig(_Config):
    """GET /site."""
    operation: Literal["get_site"] = Field("get_site", json_schema_extra={"ui:hidden": True})


class CatsListCandidatesConfig(_Page):
    """GET /candidates."""
    operation: Literal["list_candidates"] = Field("list_candidates", json_schema_extra={"ui:hidden": True})


class CatsGetCandidateConfig(_Config):
    """GET /candidates/{id}."""
    operation: Literal["get_candidate"] = Field("get_candidate", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., gt=0)


class CatsSearchCandidatesConfig(_Page):
    """GET /candidates/search."""
    operation: Literal["search_candidates"] = Field("search_candidates", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description="Text to search within candidates.")


class CatsCreateCandidateConfig(_Candidate):
    """POST /candidates."""
    operation: Literal["create_candidate"] = Field("create_candidate", json_schema_extra={"ui:hidden": True})
    check_duplicate: bool = Field(True, description="Refuse a duplicate instead of creating another record.")
    emails: list[CatsEmail] | None = None
    phones: list[CatsPhone] | None = None


class CatsUpdateCandidateConfig(_Candidate):
    """PUT /candidates/{id}."""
    operation: Literal["update_candidate"] = Field("update_candidate", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., gt=0)


class CatsListCompaniesConfig(_Page):
    """GET /companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class CatsGetCompanyConfig(_Config):
    """GET /companies/{id}."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0)


class CatsCreateCompanyConfig(_Company):
    """POST /companies."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    check_duplicate: bool = Field(True, description="Refuse a duplicate instead of creating another record.")


class CatsUpdateCompanyConfig(_Company):
    """PUT /companies/{id}."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., gt=0)


class CatsListContactsConfig(_Page):
    """GET /contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class CatsGetContactConfig(_Config):
    """GET /contacts/{id}."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)


class CatsCreateContactConfig(_Contact):
    """POST /contacts."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    check_duplicate: bool = Field(True, description="Refuse a duplicate instead of creating another record.")


class CatsUpdateContactConfig(_Contact):
    """PUT /contacts/{id}."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)


class CatsListJobsConfig(_Page):
    """GET /jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})


class CatsGetJobConfig(_Config):
    """GET /jobs/{id}."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class CatsCreateJobConfig(_Job):
    """POST /jobs."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    check_duplicate: bool = Field(True, description="Refuse a duplicate instead of creating another record.")
    workflow_id: int | None = Field(None, gt=0)


class CatsUpdateJobConfig(_Job):
    """PUT /jobs/{id}."""
    operation: Literal["update_job"] = Field("update_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., gt=0)


class CatsListPipelinesConfig(_Page):
    """GET /pipelines."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})


class CatsGetPipelineConfig(_Config):
    """GET /pipelines/{id}."""
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: int = Field(..., gt=0)


class CatsCreatePipelineConfig(_Config):
    """POST /pipelines."""
    operation: Literal["create_pipeline"] = Field("create_pipeline", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., gt=0)
    job_id: int = Field(..., gt=0)
    rating: int | None = Field(None, ge=0, le=5)
    create_activity: bool = Field(False, description="Also create a corresponding activity in CATS.")


class CatsListTasksConfig(_Page):
    """GET /tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})


class CatsGetTaskConfig(_Config):
    """GET /tasks/{id}."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


class CatsCreateTaskConfig(_Task):
    """POST /tasks."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    data_item: CatsDataItem | None = None


class CatsUpdateTaskConfig(_Task):
    """PUT /tasks/{id}."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)
    is_completed: bool | None = None


class _CatsWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with CATS automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class CatsOnCandidateCreatedConfig(_CatsWebhookConfig):
    operation: Literal["on_candidate_created"] = Field("on_candidate_created", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New Candidate"})


class CatsOnPipelineStatusChangedConfig(_CatsWebhookConfig):
    operation: Literal["on_pipeline_status_changed"] = Field("on_pipeline_status_changed", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "Pipeline Status Changed"})


TRIGGER_EVENTS = {"on_candidate_created": "candidate.created", "on_pipeline_status_changed": "pipeline.status_changed"}


CatsOperation = Annotated[Union[
    CatsGetSiteConfig,
    CatsListCandidatesConfig,
    CatsGetCandidateConfig,
    CatsSearchCandidatesConfig,
    CatsCreateCandidateConfig,
    CatsUpdateCandidateConfig,
    CatsListCompaniesConfig,
    CatsGetCompanyConfig,
    CatsCreateCompanyConfig,
    CatsUpdateCompanyConfig,
    CatsListContactsConfig,
    CatsGetContactConfig,
    CatsCreateContactConfig,
    CatsUpdateContactConfig,
    CatsListJobsConfig,
    CatsGetJobConfig,
    CatsCreateJobConfig,
    CatsUpdateJobConfig,
    CatsListPipelinesConfig,
    CatsGetPipelineConfig,
    CatsCreatePipelineConfig,
    CatsListTasksConfig,
    CatsGetTaskConfig,
    CatsCreateTaskConfig,
    CatsUpdateTaskConfig,
    CatsOnCandidateCreatedConfig,
    CatsOnPipelineStatusChangedConfig
], Field(discriminator="operation")]


class CatsNodeConfig(NodeConfig[CatsOperation, CatsAPIKeyCredential]):
    pass


ROUTES = {'get_site': ('GET', '/site'),
 'list_candidates': ('GET', '/candidates'),
 'get_candidate': ('GET', '/candidates/{id}'),
 'search_candidates': ('GET', '/candidates/search'),
 'create_candidate': ('POST', '/candidates'),
 'update_candidate': ('PUT', '/candidates/{id}'),
 'list_companies': ('GET', '/companies'),
 'get_company': ('GET', '/companies/{id}'),
 'create_company': ('POST', '/companies'),
 'update_company': ('PUT', '/companies/{id}'),
 'list_contacts': ('GET', '/contacts'),
 'get_contact': ('GET', '/contacts/{id}'),
 'create_contact': ('POST', '/contacts'),
 'update_contact': ('PUT', '/contacts/{id}'),
 'list_jobs': ('GET', '/jobs'),
 'get_job': ('GET', '/jobs/{id}'),
 'create_job': ('POST', '/jobs'),
 'update_job': ('PUT', '/jobs/{id}'),
 'list_pipelines': ('GET', '/pipelines'),
 'get_pipeline': ('GET', '/pipelines/{id}'),
 'create_pipeline': ('POST', '/pipelines'),
 'list_tasks': ('GET', '/tasks'),
 'get_task': ('GET', '/tasks/{id}'),
 'create_task': ('POST', '/tasks'),
 'update_task': ('PUT', '/tasks/{id}')}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
                if key.lower() not in {"password", "api_key", "api_token", "authorization"}}
    return value


class CatsNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-cats"
    connection_evidence = ConnectionEvidence(
        noun="companies", operation="list_companies", identity_operation="get_site",
        identity_keys=("subdomain",),
    )
    edit_examples = ["Create a candidate in CATS", "Find candidates by name", "Add a candidate to a job pipeline", "Complete a recruiting task"]

    @classmethod
    def get_config_model(cls):
        return CatsNodeConfig

    @classmethod
    async def _webhook_request(cls, credential, method, path, body=None):
        token = CatsAPIKeyCredential.model_validate(credential).api_key
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Token " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("CATS webhook request did not complete") from None
        if response.status_code not in ({201} if method == "POST" else {204, 404, 410}):
            raise ValueError(f"CATS webhook HTTP {response.status_code}")
        return response

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGER_EVENTS.get(config.get("operation"))
        if event is None:
            raise ValueError("Choose a CATS trigger")
        secret = secrets.token_urlsafe(32)
        response = await cls._webhook_request(credential, "POST", "/webhooks",
            {"events": [event], "target_url": webhook_url, "secret": secret})
        # Creates have no body; the documented Location identifies the resource.
        location = urlparse(response.headers.get("Location", ""))
        path = location.path.rstrip("/")
        identifier = path.rsplit("/", 1)[-1]
        if (location.netloc and (location.scheme != "https" or location.netloc != "api.catsone.com")) or not path.endswith("/webhooks/" + identifier) or not identifier.isascii() or not identifier.isdigit():
            raise ValueError("CATS did not return a webhook Location")
        return {"external_webhook_id": identifier, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if not identifier:
            return
        if not credential:
            raise ValueError("Connect CATS to remove its webhook")
        identifier = str(identifier)
        if not identifier.isascii() or not identifier.isdigit():
            raise ValueError("Invalid CATS webhook ID")
        await cls._webhook_request(credential, "DELETE", "/webhooks/" + identifier)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        lowered = {key.lower(): value for key, value in headers.items()}
        request_id = lowered.get("x-request-id")
        signature = lowered.get("x-signature")
        if not secret or not request_id or not isinstance(signature, str) or not signature.isascii():
            return False
        digest = hmac.new(secret.encode(), body + request_id.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, "HMAC-SHA256 " + digest)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = TRIGGER_EVENTS.get(config.get("operation"))
        if event is None or payload.get("event") != event:
            return False
        field = "candidate_id" if event == "candidate.created" else "pipeline_id"
        identifier = payload.get(field)
        return isinstance(identifier, int) and not isinstance(identifier, bool) and identifier > 0

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if config.get("operation") in TRIGGER_EVENTS:
            return {key: value for key, value in payload.items() if key != "_webhook"}
        return None

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        event = output.get("event")
        if event == "candidate.created":
            identifier = output.get("candidate_id")
            text = f"New candidate in CATS: candidate {identifier}. Use get_candidate with candidate_id={identifier} to read their recruiting record."
            title = f"New CATS candidate {identifier}"
            key = f"candidate:{identifier}"
        elif event == "pipeline.status_changed":
            identifier = output.get("pipeline_id")
            text = f"CATS pipeline {identifier} changed status from {output.get('previous_status_id')} to {output.get('new_status_id')}. Use get_pipeline with pipeline_id={identifier} to read the candidate and job."
            title = f"CATS pipeline {identifier} status changed"
            key = f"pipeline:{identifier}"
        else:
            return None
        # Embeds are provider-defined: preserve contents without guessing fields.
        if output.get("_embedded"):
            text += "\nRecruiting record: " + json.dumps(output["_embedded"], ensure_ascii=False)[:6000]
        if output.get("_links"):
            text += "\nCATS links: " + json.dumps(output["_links"], ensure_ascii=False)[:2000]
        return {"text": text, "title": title, "conversation_key": key}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CATS API key")
        config = self.config.config
        token = self.config.credentials.api_key
        if config.operation in TRIGGER_EVENTS:
            payload = (self.node_data.get("config") or {}).get("_triggerPayload")
            if not isinstance(payload, dict):
                raise ValueError("CATS trigger needs a webhook delivery")
            return self.resolve_trigger_payload(payload, config.model_dump())
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            resource = config.operation.split("_", 1)[1]
            route = route.replace("{id}", str(values.pop(resource + "_id")))
        params = {}
        for name in ("page", "per_page", "query", "check_duplicate", "create_activity"):
            if name in values:
                value = values.pop(name)
                params[name] = str(value).lower() if isinstance(value, bool) else value
        headers = {"Authorization": "Token " + token, "Accept": "application/json", "Content-Type": "application/json"}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params,
                                                **({"json": values} if method in {"POST", "PUT"} else {}))
        except httpx.HTTPError:
            # Never retry writes: a dropped response may still have created the record.
            raise ValueError("CATS request did not complete; check the record before retrying a write") from None
        expected = 200 if method == "GET" else 201 if method == "POST" else 204
        if response.status_code != expected:
            detail = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"CATS HTTP {response.status_code}: {detail}")
        if method != "GET":
            # Documented creates and updates have no response body; do not invent a record ID.
            result = {"success": True, "operation": config.operation, "http_status": response.status_code}
            if method == "POST" and response.headers.get("Location"):
                result["location"] = response.headers["Location"].replace(token, "[redacted]")
            return result
        try:
            data = response.json()
        except ValueError:
            raise ValueError("CATS returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError("CATS returned an unexpected response shape")
        if data.get("error") or data.get("errors"):
            raise ValueError("CATS: " + json.dumps(_redact(data, token))[:2000])
        if config.operation.startswith(("list_", "search_")):
            kind = "candidates" if config.operation == "search_candidates" else config.operation.removeprefix("list_")
            items = data.get("_embedded", {}).get(kind) if isinstance(data.get("_embedded"), dict) else None
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("CATS returned an incomplete HAL list")
            return {"items": _redact(items, token), "count": data.get("count"), "total": data.get("total"),
                    "page": config.page, "per_page": config.per_page}
        if not isinstance(data.get("id"), (int, float)) or isinstance(data.get("id"), bool):
            raise ValueError("CATS returned an incomplete record")
        return _redact(data, token)

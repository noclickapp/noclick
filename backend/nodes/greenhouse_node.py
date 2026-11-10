"""Greenhouse Harvest v3 recruiting automation.

Custom Greenhouse integrations use OAuth 2.0 client credentials. The customer
creates Harvest V3 (OAuth) credentials and grants scopes in API Credentials.
Partner authorization-code OAuth requires a Greenhouse partnership and is not
available to an unregistered public app. Harvest v1/v2 are deprecated.

API: https://harvestdocs.greenhouse.io/docs/authentication
"""

import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


API_BASE = "https://harvest.greenhouse.io/v3"
TOKEN_URL = "https://auth.greenhouse.io/token"


class GreenhouseOAuthCredential(BaseModel):
    """Customer-created Harvest v3 OAuth client, never exposed to the browser."""

    credential_type: Literal["greenhouse_oauth_client"] = Field(
        "greenhouse_oauth_client", json_schema_extra={"ui:hidden": True}
    )
    client_id: str = Field(..., title="Client ID")
    client_secret: str = Field(
        ..., title="Client Secret", json_schema_extra={"ui:widget": "password"}
    )
    sub: Optional[int] = Field(
        None, title="Acting User ID", description="Optional numeric Greenhouse Site Admin user ID. Leave blank to use the integration service user."
    )

    model_config = ConfigDict(title="Greenhouse Account", json_schema_extra={
        "x-credential-url": "https://support.greenhouse.io/hc/en-us/articles/360029266032-Harvest-API-overview",
        "x-credential-instructions": (
            "In Greenhouse API Credentials, create Harvest V3 (OAuth) credentials and grant "
            "the scopes required for the operations you use. Enter the Client ID and Client "
            "Secret. Greenhouse permits OAuth client credentials for custom integrations; "
            "one-click authorization-code login requires a Greenhouse partner app."
        ),
    })


def _operation(name: str, category: str, display: str) -> Any:
    return Field(name, title=display, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": display,
    })


class _ListConfig(BaseModel):
    per_page: int = Field(50, ge=1, le=500, title="Page Size")
    cursor: Optional[str] = Field(None, title="Next Page Cursor", description="Opaque cursor from the previous response. Other filters are ignored when set.")


class GreenhouseListCandidatesConfig(_ListConfig):
    """Find candidates by email or tag, with cursor pagination."""
    operation: Literal["list_candidates"] = _operation("list_candidates", "Candidates", "List Candidates")
    email: Optional[str] = Field(None, title="Email")
    tag: Optional[str] = Field(None, title="Tag")


class GreenhouseGetCandidateConfig(BaseModel):
    """Find one candidate by its Harvest ID."""
    operation: Literal["get_candidate"] = _operation("get_candidate", "Candidates", "Get Candidate")
    candidate_id: int = Field(..., title="Candidate ID")


class GreenhouseCreateCandidateConfig(BaseModel):
    """Create a candidate, optionally applying them to a job."""
    operation: Literal["create_candidate"] = _operation("create_candidate", "Candidates", "Create Candidate")
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    email: Optional[str] = Field(None, title="Email")
    company: Optional[str] = Field(None, title="Company")
    title: Optional[str] = Field(None, title="Job Title")
    job_id: Optional[int] = Field(None, title="Apply to Job ID", description="Optionally create the first application in the same request.")


class GreenhouseUpdateCandidateConfig(BaseModel):
    """Change a candidate's profile details."""
    operation: Literal["update_candidate"] = _operation("update_candidate", "Candidates", "Update Candidate")
    candidate_id: int = Field(..., title="Candidate ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    company: Optional[str] = Field(None, title="Company")
    title: Optional[str] = Field(None, title="Job Title")
    email: Optional[str] = Field(None, title="Email", description="Replaces all existing candidate email addresses when set.")


class GreenhouseListApplicationsConfig(_ListConfig):
    """Find applications by candidate, job, or lifecycle status."""
    operation: Literal["list_applications"] = _operation("list_applications", "Applications", "List Applications")
    candidate_id: Optional[int] = Field(None, title="Candidate ID")
    job_id: Optional[int] = Field(None, title="Job ID")
    status: Optional[Literal["active", "rejected", "hired", "converted"]] = Field(None, title="Status")


class GreenhouseGetApplicationConfig(BaseModel):
    """Find one application by its Harvest ID."""
    operation: Literal["get_application"] = _operation("get_application", "Applications", "Get Application")
    application_id: int = Field(..., title="Application ID")


class GreenhouseCreateApplicationConfig(BaseModel):
    """Apply an existing candidate to a job."""
    operation: Literal["create_application"] = _operation("create_application", "Applications", "Create Application")
    candidate_id: int = Field(..., title="Candidate ID")
    job_id: int = Field(..., title="Job ID")
    initial_stage_id: Optional[int] = Field(None, title="Initial Stage ID")


class GreenhouseMoveApplicationConfig(BaseModel):
    """Move an application to another interview stage or job."""
    operation: Literal["move_application"] = _operation("move_application", "Applications", "Move Application")
    application_id: int = Field(..., title="Application ID")
    from_stage_id: int = Field(..., title="Current Stage ID", description="Guard against a stale stage transition.")
    to_stage_id: Optional[int] = Field(None, title="New Stage ID")
    to_job_id: Optional[int] = Field(None, title="New Job ID")


class GreenhouseRejectApplicationConfig(BaseModel):
    """Reject an application with a documented reason."""
    operation: Literal["reject_application"] = _operation("reject_application", "Applications", "Reject Application")
    application_id: int = Field(..., title="Application ID")
    rejection_reason_id: int = Field(..., title="Rejection Reason ID")
    notes: Optional[str] = Field(None, title="Notes", json_schema_extra={"ui:widget": "textarea"})


class GreenhouseUnrejectApplicationConfig(BaseModel):
    """Restore a rejected application to its previous stage."""
    operation: Literal["unreject_application"] = _operation("unreject_application", "Applications", "Unreject Application")
    application_id: int = Field(..., title="Application ID")


class GreenhouseHireApplicationConfig(BaseModel):
    """Mark an application hired and close its job opening."""
    operation: Literal["hire_application"] = _operation("hire_application", "Applications", "Hire Application")
    application_id: int = Field(..., title="Application ID")
    opening_id: Optional[int] = Field(None, title="Opening ID", description="Required by Greenhouse when the job has more than one open opening.")
    start_date: Optional[str] = Field(None, title="Start Date", description="ISO 8601 date and time.", json_schema_extra={"ui:widget": "datetime"})
    close_reason_id: Optional[int] = Field(None, title="Close Reason ID")


class GreenhouseListJobsConfig(_ListConfig):
    """List job requisitions and filter by status."""
    operation: Literal["list_jobs"] = _operation("list_jobs", "Jobs", "List Jobs")
    status: Optional[str] = Field(None, title="Status")


class GreenhouseGetJobConfig(BaseModel):
    """Find one job by its Harvest ID."""
    operation: Literal["get_job"] = _operation("get_job", "Jobs", "Get Job")
    job_id: int = Field(..., title="Job ID")


class GreenhouseListJobPostsConfig(_ListConfig):
    """List candidate-facing job posts for a job or organization."""
    operation: Literal["list_job_posts"] = _operation("list_job_posts", "Jobs", "List Job Posts")
    job_id: Optional[int] = Field(None, title="Job ID")


class GreenhouseListOpeningsConfig(_ListConfig):
    """List available or filled headcount openings for a job."""
    operation: Literal["list_openings"] = _operation("list_openings", "Jobs", "List Openings")
    job_id: Optional[int] = Field(None, title="Job ID")
    open: Optional[bool] = Field(None, title="Open Only")


class GreenhouseListStagesConfig(_ListConfig):
    """List a candidate application's interview stage history."""
    operation: Literal["list_application_stages"] = _operation("list_application_stages", "Applications", "List Application Stages")
    application_id: Optional[int] = Field(None, title="Application ID", description="Filter the history to this application.")


class GreenhouseListJobInterviewStagesConfig(_ListConfig):
    """List the interview stages defined on a job's hiring plan."""
    operation: Literal["list_job_interview_stages"] = _operation("list_job_interview_stages", "Jobs", "List Job Interview Stages")
    job_id: Optional[int] = Field(None, title="Job ID", description="Find the interview stage IDs for this job.")


class GreenhouseListRejectionReasonsConfig(_ListConfig):
    """List the configured reasons available when rejecting applicants."""
    operation: Literal["list_rejection_reasons"] = _operation("list_rejection_reasons", "Applications", "List Rejection Reasons")


class GreenhouseCreateNoteConfig(BaseModel):
    """Add a note to a candidate or one of their applications."""
    operation: Literal["create_note"] = _operation("create_note", "Candidates", "Create Candidate Note")
    candidate_id: int = Field(..., title="Candidate ID")
    body: str = Field(..., min_length=1, title="Note", json_schema_extra={"ui:widget": "textarea"})
    visibility: Literal["public", "private", "admin_only"] = Field("public", title="Visibility")
    application_id: Optional[int] = Field(None, title="Application ID")


class GreenhouseListTagsConfig(_ListConfig):
    """List candidate tags defined for the organization."""
    operation: Literal["list_candidate_tags"] = _operation("list_candidate_tags", "Tags", "List Candidate Tags")


class GreenhouseCreateTagConfig(BaseModel):
    """Create a candidate tag in the organization dictionary."""
    operation: Literal["create_candidate_tag"] = _operation("create_candidate_tag", "Tags", "Create Candidate Tag")
    name: str = Field(..., min_length=1, max_length=255, title="Tag Name")


class GreenhouseApplyTagConfig(BaseModel):
    """Attach an existing candidate tag to a candidate."""
    operation: Literal["apply_candidate_tag"] = _operation("apply_candidate_tag", "Tags", "Apply Candidate Tag")
    candidate_id: int = Field(..., title="Candidate ID")
    candidate_tag_id: int = Field(..., title="Candidate Tag ID")


class GreenhouseListUsersConfig(_ListConfig):
    """List recruiters and other Greenhouse users."""
    operation: Literal["list_users"] = _operation("list_users", "Organization", "List Users")
    primary_email: Optional[str] = Field(None, title="Email")


class GreenhouseListDepartmentsConfig(_ListConfig):
    """List the organization's departments."""
    operation: Literal["list_departments"] = _operation("list_departments", "Organization", "List Departments")


class GreenhouseListSourcesConfig(_ListConfig):
    """List recruiting sources used for application attribution."""
    operation: Literal["list_sources"] = _operation("list_sources", "Organization", "List Sources")


GREENHOUSE_DELIVERY_ACTIONS = frozenset({
    'application_updated',
    'candidate_anonymized',
    'candidate_stage_change',
    'delete_application',
    'delete_candidate',
    'department_deleted',
    'hire_candidate',
    'interview_deleted',
    'job_approved',
    'job_created',
    'job_deleted',
    'job_interview_stage_deleted',
    'job_post_created',
    'job_post_deleted',
    'job_post_updated',
    'job_updated',
    'merge_candidate',
    'new_candidate_application',
    'new_prospect_application',
    'offer_approved',
    'offer_created',
    'offer_deleted',
    'offer_updated',
    'office_deleted',
    'reject_candidate',
    'scorecard_deleted',
    'unhire_candidate',
    'unreject_candidate',
    'update_candidate',
})

# Event names and payloads: https://developers.greenhouse.io/webhooks.html
GREENHOUSE_EVENTS = {
    "new_candidate_application": "Application created",
    "application_updated": "Application updated",
    "candidate_stage_change": "Candidate stage changed",
    "hire_candidate": "Candidate hired",
    "reject_candidate": "Candidate rejected",
    "update_candidate": "Candidate updated",
}


class GreenhouseOnEventConfig(WebhookTriggerConfigBase):
    """Start a workflow on a signed recruiting event (Greenhouse partners only)."""

    operation: Literal["on_event"] = Field("on_event", title="On Recruiting Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Recruiting Event",
    })
    event_type: Literal[
        "new_candidate_application", "application_updated", "candidate_stage_change",
        "hire_candidate", "reject_candidate", "update_candidate",
    ] = Field("new_candidate_application", title="Event", description=(
        "Requires a Greenhouse partner account with harvest:webhooks:create and "
        "harvest:webhooks:destroy scopes. Webhook registration is exclusive to partners."
    ))
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="Registered with Greenhouse automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


GreenhouseConfig = Annotated[Union[
    GreenhouseOnEventConfig,
    GreenhouseListCandidatesConfig, GreenhouseGetCandidateConfig,
    GreenhouseCreateCandidateConfig, GreenhouseUpdateCandidateConfig,
    GreenhouseListApplicationsConfig, GreenhouseGetApplicationConfig,
    GreenhouseCreateApplicationConfig, GreenhouseMoveApplicationConfig,
    GreenhouseRejectApplicationConfig, GreenhouseUnrejectApplicationConfig,
    GreenhouseHireApplicationConfig, GreenhouseListJobsConfig,
    GreenhouseGetJobConfig, GreenhouseListJobPostsConfig,
    GreenhouseListOpeningsConfig,
    GreenhouseListStagesConfig, GreenhouseListJobInterviewStagesConfig,
    GreenhouseListRejectionReasonsConfig,
    GreenhouseCreateNoteConfig, GreenhouseListTagsConfig,
    GreenhouseCreateTagConfig, GreenhouseApplyTagConfig,
    GreenhouseListUsersConfig, GreenhouseListDepartmentsConfig,
    GreenhouseListSourcesConfig,
], Discriminator("operation")]


class GreenhouseNodeConfig(NodeConfig[GreenhouseConfig, GreenhouseOAuthCredential]):
    pass


def _filled(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None and value != ""}


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error_description") or payload.get("error") or "Request failed")[:500]
    except ValueError:
        pass
    return f"HTTP {response.status_code}"


def _next_cursor(link: Optional[str], path: str) -> Optional[str]:
    """Extract the opaque cursor from Harvest's same-origin next-page link."""
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' not in part and "rel=next" not in part:
            continue
        if "<" not in part or ">" not in part:
            continue
        url = urlparse(part.split("<", 1)[1].split(">", 1)[0])
        if url.scheme != "https" or url.netloc != "harvest.greenhouse.io" or url.path != f"/v3{path}":
            continue
        cursor = parse_qs(url.query).get("cursor", [None])[0]
        if cursor:
            return cursor
    return None


class GreenhouseNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Core recruiting actions against Harvest v3."""

    integration_type = "automation-greenhouse"

    connection_evidence = ConnectionEvidence(
        operation="list_jobs", operation_arguments={"per_page": 5},
        noun="jobs", label_keys=("name", "title", "id"),
    )
    edit_examples = [
        "Find a candidate by email", "Create a candidate and apply them to a job",
        "Move an application to the next interview stage", "Reject an application",
        "Add a note to a candidate", "List open jobs and applicants",
    ]

    @classmethod
    def get_config_model(cls):
        return GreenhouseNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "new_candidate_application")}

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        if not credential:
            raise ValueError("Connect a Greenhouse partner account to activate this trigger")
        creds = GreenhouseOAuthCredential.model_validate(credential)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            token = await cls._token(client, creds)
            response = await client.request(
                method, f"{API_BASE}{path}", json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        if method == "DELETE" and response.status_code == 404:
            return {}
        if response.is_error:
            raise ValueError(f"Greenhouse webhook failed ({response.status_code}): {_error_message(response)}")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event_type = (config or {}).get("event_type", "new_candidate_application")
        if event_type not in GREENHOUSE_EVENTS:
            raise ValueError("Choose a supported Greenhouse recruiting event")
        secret = secrets.token_urlsafe(32)
        # POST/DELETE contracts: https://harvestdocs.greenhouse.io/reference/post_v3-webhooks
        data = await cls._webhook_request(credential, "POST", "/webhooks", body={
            "endpoint_url": webhook_url, "name": f"NoClick {node_id}",
            "event_action_type": event_type, "secret_key": secret, "max_attempts": 6,
        })
        hook_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(hook_id, int) or isinstance(hook_id, bool):
            raise ValueError("Greenhouse returned no webhook ID")
        if data.get("deactivated") is True:
            await cls._webhook_request(credential, "DELETE", f"/webhooks/{hook_id}")
            raise ValueError("Greenhouse disabled the webhook after its endpoint ping failed")
        return {"external_webhook_id": str(hook_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        hook_id = (config or {}).get("external_webhook_id")
        if hook_id is None:
            return
        if not str(hook_id).isdigit():
            raise ValueError("Greenhouse webhook ID must be numeric")
        await cls._webhook_request(credential, "DELETE", f"/webhooks/{hook_id}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Sign the original bytes, including escaped Unicode, never re-encoded JSON.
        # https://developers.greenhouse.io/webhooks.html#authentication
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "signature"), "")
        if not secret or not isinstance(signature, str) or not signature.isascii():
            return False
        expected = "sha256 " + hmac.new(str(secret).encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def handle_webhook_handshake(cls, body, headers, config=None):
        # Greenhouse pings the URL with configuration settings during registration,
        # before its signing secret has been persisted. Acknowledge non-event JSON
        # without dispatching it; all documented recruiting events still require HMAC.
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return None
        if isinstance(payload, dict) and payload.get("action") not in GREENHOUSE_DELIVERY_ACTIONS:
            return {"ok": True}
        return None

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event_type = (config or {}).get("event_type", "new_candidate_application")
        return (config or {}).get("operation") == "on_event" and payload.get("action") == event_type

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "action": "on_event", "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("data", output) if isinstance(output, dict) else {}
        if not isinstance(event, dict):
            return super().resolve_agent_event(output)
        action = event.get("action")
        if action not in GREENHOUSE_EVENTS:
            return super().resolve_agent_event(output)
        payload = event.get("payload") or {}
        if action == "update_candidate":
            application = {}
            candidate = payload.get("candidate") or {}
        else:
            application = payload.get("application") or {}
            candidate = application.get("candidate") or {}
        name = " ".join(str(candidate.get(k) or "") for k in ("first_name", "last_name")).strip()
        candidate_id = candidate.get("id")
        application_id = application.get("id")
        lines = [f"Greenhouse: {GREENHOUSE_EVENTS[action]} — {name or 'Candidate'}"]
        if candidate_id is not None:
            lines.append(f"Candidate ID: {candidate_id} (get_candidate or create_note)")
        if application_id is not None:
            lines.append(f"Application ID: {application_id} (get_application)")
            # A hire has a different documented shape: no status/current_stage.
            if action != "hire_candidate":
                if application.get("status"):
                    lines.append(f"Status: {application['status']}")
                stage = application.get("current_stage") or {}
                if stage.get("name"):
                    lines.append(f"Stage: {stage['name']} (stage ID {stage.get('id')})")
            jobs = application.get("jobs") or []
            for job in jobs:
                lines.append(f"Job: {job.get('name') or 'Job'} (job ID {job.get('id')})")
            if action == "reject_candidate":
                reason = application.get("rejection_reason") or {}
                if reason.get("name"):
                    lines.append(f"Rejection reason: {reason['name']}")
        url = candidate.get("url") if action == "update_candidate" else application.get("url")
        if url:
            lines.append(f"Greenhouse URL: {url}")
        key = f"application:{application_id}" if application_id is not None else f"candidate:{candidate_id}"
        return {"text": "\n".join(lines), "conversation_key": key, "title": f"{GREENHOUSE_EVENTS[action]}: {name}"}

    @staticmethod
    async def _token(client: httpx.AsyncClient, credential: GreenhouseOAuthCredential) -> str:
        body: Dict[str, Any] = {"grant_type": "client_credentials"}
        if credential.sub is not None:
            body["sub"] = str(credential.sub)
        response = await client.post(
            TOKEN_URL, auth=(credential.client_id, credential.client_secret),
            data=body, headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            raise ValueError(f"Greenhouse OAuth failed ({response.status_code}): {_error_message(response)}")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("Greenhouse OAuth returned no access token")
        return token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, GreenhouseNodeConfig):
            raise ValueError("Valid Greenhouse configuration is required")
        credential = self.config.credentials
        if not credential:
            raise ValueError("Greenhouse Harvest v3 OAuth client credentials are required")
        op = self.config.config
        if isinstance(op, GreenhouseOnEventConfig):
            return {"status": "success", "action": op.operation, "awaiting_event": True}
        method, path, params, body = self._request_for(op)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            token = await self._token(client, credential)
            response = await client.request(
                method, f"{API_BASE}{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if response.status_code == 401:
                token = await self._token(client, credential)
                response = await client.request(
                    method, f"{API_BASE}{path}", params=params, json=body,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        if response.status_code >= 400:
            raise ValueError(f"Greenhouse {op.operation} failed ({response.status_code}): {_error_message(response)}")
        data = response.json() if response.content else None
        if op.operation in {"get_candidate", "get_application", "get_job"} and isinstance(data, list):
            if not data:
                raise ValueError(f"Greenhouse {op.operation} found no matching record")
            data = data[0]
        result: Dict[str, Any] = {
            "status": "success", "action": op.operation, "data": data,
            "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)},
        }
        if method == "GET" and isinstance(data, list):
            result["count"] = len(data)
            next_cursor = _next_cursor(response.headers.get("link"), path)
            if next_cursor:
                result["next_cursor"] = next_cursor
        return result

    @staticmethod
    def _request_for(op: GreenhouseConfig) -> tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        name = op.operation
        if name == "list_candidates":
            return "GET", "/candidates", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "email": op.email, "tag": op.tag})), None
        if name == "get_candidate":
            return "GET", "/candidates", {"ids": op.candidate_id}, None
        if name == "create_candidate":
            body = _filled({"first_name": op.first_name, "last_name": op.last_name, "company": op.company, "title": op.title})
            if op.email:
                body["email_addresses"] = [{"value": op.email, "type": "personal"}]
            if op.job_id is not None:
                body["application"] = {"job_id": op.job_id}
            return "POST", "/candidates", None, body
        if name == "update_candidate":
            body = _filled({"first_name": op.first_name, "last_name": op.last_name, "company": op.company, "title": op.title})
            if op.email:
                body["email_addresses"] = [{"value": op.email, "type": "personal"}]
            if not body:
                raise ValueError("Set at least one candidate field to update")
            return "PATCH", f"/candidates/{op.candidate_id}", None, body
        if name == "list_applications":
            return "GET", "/applications", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "candidate_ids": op.candidate_id, "job_ids": op.job_id, "status": op.status})), None
        if name == "get_application":
            return "GET", "/applications", {"ids": op.application_id}, None
        if name == "create_application":
            return "POST", "/applications", None, _filled({"candidate_id": op.candidate_id, "job_id": op.job_id, "initial_stage_id": op.initial_stage_id})
        if name == "move_application":
            if op.to_stage_id is None and op.to_job_id is None:
                raise ValueError("Set a new stage or job for the application")
            return "POST", f"/applications/{op.application_id}/move", None, _filled({"from_stage_id": op.from_stage_id, "to_stage_id": op.to_stage_id, "to_job_id": op.to_job_id})
        if name == "reject_application":
            return "POST", f"/applications/{op.application_id}/reject", None, _filled({"rejection_reason_id": op.rejection_reason_id, "notes": op.notes})
        if name == "unreject_application":
            return "POST", f"/applications/{op.application_id}/unreject", None, None
        if name == "hire_application":
            return "POST", f"/applications/{op.application_id}/hire", None, _filled({"opening_id": op.opening_id, "start_date": op.start_date, "close_reason_id": op.close_reason_id})
        if name == "list_jobs":
            return "GET", "/jobs", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "status": op.status})), None
        if name == "get_job":
            return "GET", "/jobs", {"ids": op.job_id}, None
        if name == "list_job_posts":
            return "GET", "/job_posts", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "job_ids": op.job_id})), None
        if name == "list_openings":
            return "GET", "/openings", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "job_ids": op.job_id, "open": op.open})), None
        if name == "list_application_stages":
            return "GET", "/application_stages", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "application_ids": op.application_id})), None
        if name == "list_job_interview_stages":
            return "GET", "/job_interview_stages", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "job_ids": op.job_id})), None
        if name == "list_rejection_reasons":
            return "GET", "/rejection_reasons", ({"cursor": op.cursor} if op.cursor else {"per_page": op.per_page}), None
        if name == "create_note":
            return "POST", "/notes", None, _filled({"candidate_id": op.candidate_id, "body": op.body, "note_type": "NOTE", "visibility": op.visibility, "application_id": op.application_id})
        if name == "list_candidate_tags":
            return "GET", "/candidate_tags", ({"cursor": op.cursor} if op.cursor else {"per_page": op.per_page}), None
        if name == "create_candidate_tag":
            return "POST", "/candidate_tags", None, {"name": op.name}
        if name == "apply_candidate_tag":
            return "POST", "/applied_candidate_tags", None, {"candidate_id": op.candidate_id, "candidate_tag_id": op.candidate_tag_id}
        if name == "list_users":
            return "GET", "/users", ({"cursor": op.cursor} if op.cursor else _filled({"per_page": op.per_page, "primary_email": op.primary_email})), None
        if name == "list_departments":
            return "GET", "/departments", ({"cursor": op.cursor} if op.cursor else {"per_page": op.per_page}), None
        if name == "list_sources":
            return "GET", "/sources", ({"cursor": op.cursor} if op.cursor else {"per_page": op.per_page}), None
        raise ValueError(f"Unsupported Greenhouse operation: {name}")

"""KoboToolbox API v2 projects, submissions, validation, deployments and exports.

Contract: https://kf.kobotoolbox.org/api/v2/schema/?format=json
Token and server instructions: https://support.kobotoolbox.org/api.html
Each action issues exactly one request; export creation queues a task.
REST services deliver new submissions; edits do not send events.
"""
from __future__ import annotations

import json

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client


class KobotoolboxAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="KoboToolbox API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.kobotoolbox.org/api.html#retrieving-your-api-key",
            "x-credential-instructions": "In KoboToolbox, open Account Settings > Security > Display API Key. Paste the key and select the server where your account lives. The key can access your account's projects and data; keep it private.",
        },
    )
    credential_type: Literal["kobotoolbox_api_token"] = Field("kobotoolbox_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})
    server: Literal["https://kf.kobotoolbox.org", "https://eu.kobotoolbox.org"] = Field("https://kf.kobotoolbox.org", title="KoboToolbox server")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Token prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Project(_Input):
    project_id: str = Field(..., min_length=1, description="Project asset UID from the KoboToolbox project URL.")

    @field_validator("project_id")
    @classmethod
    def identifier(cls, value):
        if not value.isascii() or not value.isalnum():
            raise ValueError("Use the letters and digits of the project asset UID")
        return value


class _Page(_Input):
    start: int = Field(0, ge=0, description="Initial result index; use next_start from the preceding page.")
    limit: int = Field(100, ge=1, le=1000)


class _ProjectPage(_Project, _Page):
    pass


class _Submission(_Project):
    submission_id: str = Field(..., pattern=r"^[A-Za-z0-9-]+$", description="Submission integer ID or rootUuid without the uuid: prefix.")


class _Export(_Project):
    export_id: str = Field(..., pattern=r"^[A-Za-z0-9]+$", description="UID of the export task.")


class GetAccount(_Input):
    """Read the authenticated account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ListProjects(_Page):
    """List accessible projects and library assets."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description="Documented asset search query, e.g. asset_type:survey.")
    ordering: str | None = None


class GetProject(_Project):
    """Read a project asset."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class CreateProject(_Input):
    """Create a draft survey project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str = ""
    sector: str = ""
    country: str = ""
    share_metadata: bool = False


class DeleteProject(_Project):
    """Delete a project and its data permanently."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class GetFormContent(_Project):
    """Read structured form content."""
    operation: Literal["get_form_content"] = Field("get_form_content", json_schema_extra={"ui:hidden": True})


class ListSubmissions(_ProjectPage):
    """Read a page of JSON submissions."""
    operation: Literal["list_submissions"] = Field("list_submissions", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description="JSON-encoded Mongo filter query.")
    fields: str | None = Field(None, description="JSON-encoded array of field names.")
    sort: str | None = Field(None, description="JSON-encoded sort object, e.g. {\"_id\":-1}.")


class GetSubmission(_Submission):
    """Read one submission."""
    operation: Literal["get_submission"] = Field("get_submission", json_schema_extra={"ui:hidden": True})


class DeleteSubmission(_Submission):
    """Delete one submission permanently."""
    operation: Literal["delete_submission"] = Field("delete_submission", json_schema_extra={"ui:hidden": True})


class GetValidationStatus(_Submission):
    """Read the submission validation status."""
    operation: Literal["get_validation_status"] = Field("get_validation_status", json_schema_extra={"ui:hidden": True})


class SetValidationStatus(_Submission):
    """Approve, reject or hold a submission for validation."""
    operation: Literal["set_validation_status"] = Field("set_validation_status", json_schema_extra={"ui:hidden": True})
    validation_status: Literal["validation_status_approved", "validation_status_not_approved", "validation_status_on_hold"]


class ClearValidationStatus(_Submission):
    """Remove the submission validation status."""
    operation: Literal["clear_validation_status"] = Field("clear_validation_status", json_schema_extra={"ui:hidden": True})


class GetDeployment(_Project):
    """Read the form deployment."""
    operation: Literal["get_deployment"] = Field("get_deployment", json_schema_extra={"ui:hidden": True})


class DeployProject(_Project):
    """Deploy or redeploy the project form."""
    operation: Literal["deploy_project"] = Field("deploy_project", json_schema_extra={"ui:hidden": True})
    active: bool = True


class SetDeploymentActive(_Project):
    """Archive or reactivate an existing deployment."""
    operation: Literal["set_deployment_active"] = Field("set_deployment_active", json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description="False archives; true reactivates data collection.")


class ListExports(_ProjectPage):
    """List asynchronous export tasks."""
    operation: Literal["list_exports"] = Field("list_exports", json_schema_extra={"ui:hidden": True})
    ordering: str | None = None


class GetExport(_Export):
    """Read export status and the provider download URL."""
    operation: Literal["get_export"] = Field("get_export", json_schema_extra={"ui:hidden": True})


class CreateExport(_Project):
    """Queue a CSV, XLS, GeoJSON or SPSS labels export; poll Get Export for completion."""
    operation: Literal["create_export"] = Field("create_export", json_schema_extra={"ui:hidden": True})
    export_format: Literal["csv", "xls", "geojson", "spss_labels"] = "csv"
    fields_from_all_versions: bool = True
    group_sep: str = "/"
    hierarchy_in_labels: bool = True
    lang: str = "_xml"
    multiple_select: Literal["both", "summary", "details"] = "both"
    fields: list[str] = Field(default_factory=list)
    flatten: bool = True
    xls_types_as_text: bool = False
    include_media_url: bool = False


class DeleteExport(_Export):
    """Delete an export task."""
    operation: Literal["delete_export"] = Field("delete_export", json_schema_extra={"ui:hidden": True})


class OnNewSubmission(WebhookTriggerConfigBase, _Project):
    """Start when a project receives a new submission; edits do not send events."""
    operation: Literal["on_new_submission"] = Field("on_new_submission", title="New submission", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New submission",
    })
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with KoboToolbox automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


KobotoolboxConfig = Annotated[Union[OnNewSubmission, GetAccount, ListProjects, GetProject, CreateProject, DeleteProject, GetFormContent, ListSubmissions, GetSubmission, DeleteSubmission, GetValidationStatus, SetValidationStatus, ClearValidationStatus, GetDeployment, DeployProject, SetDeploymentActive, ListExports, GetExport, CreateExport, DeleteExport], Field(discriminator="operation")]


class KobotoolboxFullConfig(NodeConfig[KobotoolboxConfig, KobotoolboxAPITokenCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/me/", 200),
    "list_projects": ("GET", "/api/v2/assets/", 200),
    "get_project": ("GET", "/api/v2/assets/{project_id}/", 200),
    "create_project": ("POST", "/api/v2/assets/", 201),
    "delete_project": ("DELETE", "/api/v2/assets/{project_id}/", 204),
    "get_form_content": ("GET", "/api/v2/assets/{project_id}/content/", 200),
    "list_submissions": ("GET", "/api/v2/assets/{project_id}/data/", 200),
    "get_submission": ("GET", "/api/v2/assets/{project_id}/data/{submission_id}/", 200),
    "delete_submission": ("DELETE", "/api/v2/assets/{project_id}/data/{submission_id}/", 204),
    "get_validation_status": ("GET", "/api/v2/assets/{project_id}/data/{submission_id}/validation_status/", 200),
    "set_validation_status": ("PATCH", "/api/v2/assets/{project_id}/data/{submission_id}/validation_status/", 200),
    "clear_validation_status": ("DELETE", "/api/v2/assets/{project_id}/data/{submission_id}/validation_status/", 204),
    "get_deployment": ("GET", "/api/v2/assets/{project_id}/deployment/", 200),
    "deploy_project": ("POST", "/api/v2/assets/{project_id}/deployment/", 200),
    "set_deployment_active": ("PATCH", "/api/v2/assets/{project_id}/deployment/", 200),
    "list_exports": ("GET", "/api/v2/assets/{project_id}/exports/", 200),
    "get_export": ("GET", "/api/v2/assets/{project_id}/exports/{export_id}/", 200),
    "create_export": ("POST", "/api/v2/assets/{project_id}/exports/", 201),
    "delete_export": ("DELETE", "/api/v2/assets/{project_id}/exports/{export_id}/", 204),
}


class KobotoolboxNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-kobotoolbox"
    webhook_signing_secret_not_issued = True
    connection_evidence = ConnectionEvidence(
        noun="KoboToolbox projects", operation="list_projects", identity_operation="get_account",
    )

    @classmethod
    def get_config_model(cls):
        return KobotoolboxFullConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"project_id": (config or {}).get("project_id")}

    @staticmethod
    async def _hook_request(credential, method, path, *, body=None):
        credential = KobotoolboxAPITokenCredential.model_validate(credential or {})
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.server + path,
                headers={"Authorization": "Token " + credential.api_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        expected = 201 if method == "POST" else 204
        if response.status_code != expected:
            if method == "DELETE" and response.status_code == 404:
                return None
            raise ValueError(f"KoboToolbox REST service request failed (HTTP {response.status_code})")
        return response.json() if method == "POST" else None

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        project = _Project.model_validate({"project_id": config.get("project_id")}).project_id
        # API contract: no_auth is the default; JSON sends the complete submission.
        # https://kf.kobotoolbox.org/api/v2/docs/#tag/Survey-data-Rest-Services
        data = await cls._hook_request(credential, "POST", f"/api/v2/assets/{project}/hooks/", body={
            "name": f"NoClick {node_id}"[:255], "endpoint": webhook_url, "active": True,
            "export_type": "json", "auth_level": "no_auth", "email_notification": False,
        })
        uid = data.get("uid") if isinstance(data, dict) else None
        if not isinstance(uid, str) or not uid.isascii() or not uid.isalnum():
            raise ValueError("KoboToolbox did not return a REST service UID")
        # Keep its parent with the UID so a project edit still cleans up the old service.
        return {"external_webhook_id": f"{project}:{uid}"}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        uid = (config or {}).get("external_webhook_id")
        if not uid:
            return
        registered_project, uid = str(uid).split(":", 1)
        project = _Project.model_validate({"project_id": registered_project}).project_id
        await cls._hook_request(credential, "DELETE",
            f"/api/v2/assets/{project}/hooks/{quote(str(uid), safe='')}/")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # REST services support no_auth (default) or basic_auth, not payload signatures.
        # We register no_auth, as described in the provider's Hook API contract.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and isinstance(payload.get("_id"), int)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if (config or {}).get("operation") != "on_new_submission":
            return None
        return {"operation": "on_new_submission", "project_id": config["project_id"],
                "data": {k: v for k, v in payload.items() if k != "_webhook"}}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_new_submission":
            return super().resolve_agent_event(output)
        data = output.get("data") or {}
        if not data.get("_id"):
            return None
        project, sid = output["project_id"], data["_id"]
        who = data.get("_submitted_by") or "An anonymous respondent"
        text = (f"KoboToolbox: {who} submitted response {sid} to project {project}.\n"
                f"Received: {data.get('_submission_time') or 'time unavailable'}\n"
                f"Submission: {json.dumps(data, ensure_ascii=False, default=str)[:12000]}\n"
                f"To act: get_submission or set_validation_status with project_id={project} and submission_id={sid}.")
        return {"text": text, "conversation_key": f"{project}:{sid}", "title": f"New submission {sid}"}

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if isinstance(config, OnNewSubmission):
            payload = (self.node_data.get("config") or {}).get("_triggerPayload")
            if not payload:
                return self.no_event_output(config.operation)
            return self.resolve_trigger_payload(payload, config.model_dump())
        if credential is None:
            raise ValueError("Connect a KoboToolbox API token")
        method, template, expected_status = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {}
        if isinstance(config, _Page):
            params = {"start": config.start, "limit": config.limit}
            for field in ("q", "query", "fields", "sort", "ordering"):
                if values.get(field) is not None:
                    params[field] = values[field]
        body = None
        if isinstance(config, CreateProject):
            body = {"name": config.name, "asset_type": "survey", "settings": {
                "description": config.description, "sector": config.sector,
                "country": config.country, "share-metadata": config.share_metadata,
            }}
        elif isinstance(config, SetValidationStatus):
            body = {"validation_status.uid": config.validation_status}
        elif isinstance(config, (DeployProject, SetDeploymentActive)):
            body = {"active": config.active}
        elif isinstance(config, CreateExport):
            body = {key: values[key] for key in (
                "fields_from_all_versions", "group_sep", "hierarchy_in_labels", "lang",
                "multiple_select", "fields", "flatten", "xls_types_as_text", "include_media_url",
            )}
            body.update(type=config.export_format, submissions_id=[], query={})
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                method, credential.server + path, params=params,
                headers={"Authorization": "Token " + credential.api_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}),
            )
        if response.status_code != expected_status:
            # Preserve the provider's rejection for manual connection evidence.
            detail = f"KoboToolbox request failed (HTTP {response.status_code})"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("detail"), str):
                    detail = error["detail"].replace(credential.api_token, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": detail}
        if expected_status == 204:
            return {"operation": config.operation, "http_status": 204, "deleted": True}
        if (len(response.content) > 16_000_000
                or response.headers.get("content-type", "").split(";")[0].strip() != "application/json"):
            raise ValueError("Expected a bounded JSON response from KoboToolbox")
        data = response.json()
        if not isinstance(data, (dict, list)) or isinstance(data, dict) and any(k in data for k in ("error", "errors")):
            raise ValueError("KoboToolbox returned an unexpected response")

        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_token, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k.lower() not in {
                    "api_token", "access_token", "refresh_token", "password", "token",
                }}
            return value

        result = {"operation": config.operation, "http_status": response.status_code, "data": redact(data)}
        if isinstance(config, _Page):
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("Expected a KoboToolbox results page")
            result["items"] = redact(data["results"])
            result["count"] = data.get("count")
            result["next_start"] = config.start + len(data["results"]) if data.get("next") and data["results"] else None
        return result

"""Buildkite Pipelines REST v2 workflow integration.

The token belongs to the connected user. All paths are assembled from escaped
resource identifiers, never accepted as caller-supplied URLs.
"""

from __future__ import annotations

import json
import re
from typing import Any, Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.buildkite.com/v2"


class BuildkiteTokenCredential(BaseModel):
    credential_type: Literal["buildkite_token"] = Field(
        "buildkite_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ..., title="API access token", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(
        title="Buildkite API Token",
        json_schema_extra={
            "x-credential-url": "https://buildkite.com/user/api-access-tokens"
        }
    )


def op(name: str, category: str, *, creates: bool = False) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-display-name": name.replace("_", " ").title(),
        "x-is-trigger": False,
    }
    if creates:
        extra["x-creates-resource"] = True
    return extra


ORG_PICKER = {
    "x-dynamic-options": {
        "field_name": "organization",
        "placeholder": "Select organization...",
        "searchable": True,
        "allow_custom": True,
    }
}
PIPELINE_PICKER = {
    "x-dynamic-options": {
        "field_name": "pipeline",
        "placeholder": "Select pipeline...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": ["organization"],
    }
}


class GetUser(BaseModel):
    """Identify the connected Buildkite account."""

    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra=op("get_user", "Account")
    )


class ListOrganizations(BaseModel):
    """List organizations visible to the token."""

    operation: Literal["list_organizations"] = Field(
        "list_organizations", json_schema_extra=op("list_organizations", "Account")
    )


class OrgConfig(BaseModel):
    organization: str = Field(..., title="Organization", json_schema_extra=ORG_PICKER)


class GetOrganization(OrgConfig):
    """Get organization details."""

    operation: Literal["get_organization"] = Field(
        "get_organization", json_schema_extra=op("get_organization", "Account")
    )


class ListPipelines(OrgConfig):
    """List pipelines in an organization."""

    operation: Literal["list_pipelines"] = Field(
        "list_pipelines", json_schema_extra=op("list_pipelines", "Pipelines")
    )
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(30, ge=1, le=100, title="Items per page")


class PipelineConfig(OrgConfig):
    pipeline: str = Field(..., title="Pipeline", json_schema_extra=PIPELINE_PICKER)


class GetPipeline(PipelineConfig):
    """Get a pipeline configuration and status."""

    operation: Literal["get_pipeline"] = Field(
        "get_pipeline", json_schema_extra=op("get_pipeline", "Pipelines")
    )


class CreatePipeline(OrgConfig):
    """Create a YAML pipeline."""

    operation: Literal["create_pipeline"] = Field(
        "create_pipeline",
        json_schema_extra=op("create_pipeline", "Pipelines", creates=True),
    )
    name: str = Field(..., title="Pipeline name")
    repository: str = Field(..., title="Git repository URL")
    configuration: str = Field(
        ..., title="Pipeline YAML", json_schema_extra={"ui:widget": "textarea"}
    )
    cluster_id: Optional[str] = Field(None, title="Cluster ID")
    description: Optional[str] = Field(None, title="Description")
    provider_settings_json: Optional[str] = Field(
        None,
        title="Provider settings (JSON object)",
        description=(
            "Source provider trigger settings. For a GitHub pipeline with no "
            'automatic builds, use {"trigger_mode":"none"}. '
            "Supported properties depend on the source provider."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class UpdatePipeline(PipelineConfig):
    """Update selected pipeline properties."""

    operation: Literal["update_pipeline"] = Field(
        "update_pipeline", json_schema_extra=op("update_pipeline", "Pipelines")
    )
    name: Optional[str] = Field(None, title="New name")
    description: Optional[str] = Field(None, title="Description")
    repository: Optional[str] = Field(None, title="Git repository URL")
    configuration: Optional[str] = Field(
        None, title="Pipeline YAML", json_schema_extra={"ui:widget": "textarea"}
    )


class ArchivePipeline(PipelineConfig):
    """Archive a pipeline."""

    operation: Literal["archive_pipeline"] = Field(
        "archive_pipeline", json_schema_extra=op("archive_pipeline", "Pipelines")
    )


class UnarchivePipeline(PipelineConfig):
    """Restore an archived pipeline."""

    operation: Literal["unarchive_pipeline"] = Field(
        "unarchive_pipeline", json_schema_extra=op("unarchive_pipeline", "Pipelines")
    )


class ListBuilds(PipelineConfig):
    """List recent pipeline builds."""

    operation: Literal["list_builds"] = Field(
        "list_builds", json_schema_extra=op("list_builds", "Builds")
    )
    branch: Optional[str] = Field(None, title="Branch filter")
    state: Optional[str] = Field(None, title="State filter")
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(30, ge=1, le=100, title="Items per page")


class BuildConfig(PipelineConfig):
    build_number: int = Field(
        ...,
        ge=1,
        title="Build number",
        description="Pipeline build number, not the build UUID",
    )


class GetBuild(BuildConfig):
    """Get one build by its pipeline number."""

    operation: Literal["get_build"] = Field(
        "get_build", json_schema_extra=op("get_build", "Builds")
    )


class CreateBuild(PipelineConfig):
    """Start a new pipeline build."""

    operation: Literal["create_build"] = Field(
        "create_build", json_schema_extra=op("create_build", "Builds", creates=True)
    )
    commit: str = Field(
        ..., title="Commit SHA", description="Full Git SHA, or HEAD where supported"
    )
    branch: str = Field(..., title="Branch")
    message: Optional[str] = Field(None, title="Message")
    environment_json: Optional[str] = Field(
        None,
        title="Environment variables (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    metadata_json: Optional[str] = Field(
        None,
        title="Build metadata (JSON object)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class CancelBuild(BuildConfig):
    """Cancel a running or scheduled build."""

    operation: Literal["cancel_build"] = Field(
        "cancel_build", json_schema_extra=op("cancel_build", "Builds")
    )


class RebuildBuild(BuildConfig):
    """Rebuild an existing build with its original inputs."""

    operation: Literal["rebuild_build"] = Field(
        "rebuild_build", json_schema_extra=op("rebuild_build", "Builds", creates=True)
    )


class ListArtifacts(BuildConfig):
    """List artifacts produced by a build."""

    operation: Literal["list_artifacts"] = Field(
        "list_artifacts", json_schema_extra=op("list_artifacts", "Artifacts")
    )
    path: Optional[str] = Field(None, title="Path filter")
    state: Optional[str] = Field(None, title="State filter")


class ListAnnotations(BuildConfig):
    """List build and job annotations."""

    operation: Literal["list_annotations"] = Field(
        "list_annotations", json_schema_extra=op("list_annotations", "Annotations")
    )
    scope: Literal["build", "job", "all"] = Field("all", title="Scope")


class CreateAnnotation(BuildConfig):
    """Add or replace a Markdown build annotation."""

    operation: Literal["create_annotation"] = Field(
        "create_annotation",
        json_schema_extra=op("create_annotation", "Annotations", creates=True),
    )
    body: str = Field(
        ..., title="Markdown body", json_schema_extra={"ui:widget": "textarea"}
    )
    style: Literal["success", "info", "warning", "error"] = Field("info", title="Style")
    context: Optional[str] = Field(
        None,
        title="Context",
        description="Stable key for replacing a previous annotation",
    )


BuildkiteConfig = Annotated[
    Union[
        GetUser,
        ListOrganizations,
        GetOrganization,
        ListPipelines,
        GetPipeline,
        CreatePipeline,
        UpdatePipeline,
        ArchivePipeline,
        UnarchivePipeline,
        ListBuilds,
        GetBuild,
        CreateBuild,
        CancelBuild,
        RebuildBuild,
        ListArtifacts,
        ListAnnotations,
        CreateAnnotation,
    ],
    Discriminator("operation"),
]


class BuildkiteNodeConfig(NodeConfig[BuildkiteConfig, BuildkiteTokenCredential]):
    pass


def _segment(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Buildkite resource identifier is required")
    return quote(value.strip(), safe="")


def _json_object(value: Optional[str], label: str) -> Optional[dict[str, Any]]:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _safe_error_text(value: Any, token: str, body: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None

    def request_strings(data: Any):
        if isinstance(data, str):
            yield data
        elif isinstance(data, dict):
            for item in data.values():
                yield from request_strings(item)
        elif isinstance(data, list):
            for item in data:
                yield from request_strings(item)

    text = " ".join(value.split())
    for secret in sorted({token, *request_strings(body)}, key=len, reverse=True):
        if len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    return text[:240] or None


def _validation_errors(detail: Any, token: str, body: Any) -> list[dict[str, str]]:
    if not isinstance(detail, dict) or not isinstance(detail.get("errors"), list):
        return []
    errors: list[dict[str, str]] = []
    for item in detail["errors"]:
        if not isinstance(item, dict):
            continue
        field, code = item.get("field"), item.get("code")
        if not isinstance(field, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]{0,63}", field
        ):
            continue
        safe_code = _safe_error_text(code, token, body)
        if safe_code:
            errors.append({"field": field, "code": safe_code})
        if len(errors) == 5:
            break
    return errors


async def _request(
    token: str, method: str, path: str, *, params=None, body=None
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        try:
            response = await client.request(
                method,
                f"{API_BASE}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=body,
            )
        except httpx.RequestError as exc:
            return {
                "status": "error",
                "error": f"Buildkite request failed: {exc.__class__.__name__}",
            }
    if response.status_code >= 400 or 300 <= response.status_code < 400:
        try:
            detail = response.json()
        except ValueError:
            detail = None
        message = None
        if isinstance(detail, dict):
            message = _safe_error_text(
                detail.get("message") or detail.get("error"), token, body
            )
        result = {
            "status": "error",
            "status_code": response.status_code,
            "error": message or f"Buildkite returned HTTP {response.status_code}",
        }
        if response.status_code == 422:
            errors = _validation_errors(detail, token, body)
            if errors:
                result["validation_errors"] = errors
        return result
    if response.status_code == 204 or not response.content:
        data: Any = {"success": True}
    else:
        try:
            data = response.json()
        except ValueError:
            return {
                "status": "error",
                "status_code": response.status_code,
                "error": "Buildkite returned invalid JSON",
            }
    return {"status": "success", "status_code": response.status_code, "data": data}


class BuildkiteNode(WorkflowNode):
    """Manage Buildkite organizations, pipelines, builds, and build output."""

    integration_type = "automation-buildkite"

    edit_examples = [
        "List the latest builds for our release pipeline",
        "Start a Buildkite build for the latest main commit",
        "Cancel a stuck CI build",
        "Add a Markdown annotation with the deployment result",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_organizations",
        noun="organizations",
        identity_operation="get_user",
    )

    @classmethod
    def get_config_model(cls):
        return BuildkiteNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        token = credential_data.get("api_token")
        if not token:
            return []
        if field_name == "organization":
            result = await _request(token, "GET", "/organizations")
        elif field_name == "pipeline":
            org = (context or {}).get("organization")
            if not org:
                return []
            result = await _request(
                token,
                "GET",
                f"/organizations/{_segment(org)}/pipelines",
                params={"per_page": 100},
            )
        else:
            return []
        if result.get("status") != "success":
            return []
        rows = result.get("data")
        options = (
            [
                {"value": row["slug"], "label": row.get("name") or row["slug"]}
                for row in rows
                if isinstance(row, dict) and row.get("slug")
            ]
            if isinstance(rows, list)
            else []
        )
        if search:
            needle = search.casefold()
            options = [
                option
                for option in options
                if needle in option["value"].casefold()
                or needle in option["label"].casefold()
            ]
        return options

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(self.config, BuildkiteNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect a Buildkite API access token")
        c = self.config.config
        token = self.config.credentials.api_token
        operation = c.operation
        if operation == "get_user":
            method, path, params, body = "GET", "/user", None, None
        elif operation == "list_organizations":
            method, path, params, body = "GET", "/organizations", None, None
        else:
            org_path = f"/organizations/{_segment(c.organization)}"
            if operation == "get_organization":
                method, path, params, body = "GET", org_path, None, None
            elif operation == "list_pipelines":
                method, path, params, body = (
                    "GET",
                    org_path + "/pipelines",
                    {"page": c.page, "per_page": c.per_page},
                    None,
                )
            elif operation == "create_pipeline":
                body = c.model_dump(
                    exclude={"operation", "organization", "provider_settings_json"},
                    exclude_none=True,
                )
                provider_settings = _json_object(
                    c.provider_settings_json, "Provider settings"
                )
                if provider_settings is not None:
                    body["provider_settings"] = provider_settings
                method, path, params, body = (
                    "POST",
                    org_path + "/pipelines",
                    None,
                    body,
                )
            else:
                pipeline_path = org_path + "/pipelines/" + _segment(c.pipeline)
                if operation == "get_pipeline":
                    method, path, params, body = "GET", pipeline_path, None, None
                elif operation == "update_pipeline":
                    body = c.model_dump(
                        exclude={"operation", "organization", "pipeline"},
                        exclude_none=True,
                    )
                    if not body:
                        raise ValueError("Select at least one pipeline field to update")
                    method, path, params = "PATCH", pipeline_path, None
                elif operation in ("archive_pipeline", "unarchive_pipeline"):
                    method, path, params, body = (
                        "POST",
                        pipeline_path
                        + (
                            "/archive"
                            if operation == "archive_pipeline"
                            else "/unarchive"
                        ),
                        None,
                        None,
                    )
                elif operation == "list_builds":
                    method, path, params, body = (
                        "GET",
                        pipeline_path + "/builds",
                        {
                            "branch": c.branch,
                            "state": c.state,
                            "page": c.page,
                            "per_page": c.per_page,
                        },
                        None,
                    )
                elif operation == "create_build":
                    body = {"commit": c.commit, "branch": c.branch}
                    if c.message:
                        body["message"] = c.message
                    env = _json_object(c.environment_json, "Environment variables")
                    metadata = _json_object(c.metadata_json, "Build metadata")
                    if env is not None:
                        body["env"] = env
                    if metadata is not None:
                        body["meta_data"] = metadata
                    method, path, params = "POST", pipeline_path + "/builds", None
                else:
                    build_path = pipeline_path + "/builds/" + str(c.build_number)
                    if operation == "get_build":
                        method, path, params, body = "GET", build_path, None, None
                    elif operation in ("cancel_build", "rebuild_build"):
                        method, path, params, body = (
                            "PUT",
                            build_path
                            + (
                                "/cancel" if operation == "cancel_build" else "/rebuild"
                            ),
                            None,
                            None,
                        )
                    elif operation == "list_artifacts":
                        method, path, params, body = (
                            "GET",
                            build_path + "/artifacts",
                            {"path": c.path, "state": c.state},
                            None,
                        )
                    elif operation == "list_annotations":
                        method, path, params, body = (
                            "GET",
                            build_path + "/annotations",
                            {"scope": c.scope},
                            None,
                        )
                    elif operation == "create_annotation":
                        method, path, params, body = (
                            "POST",
                            build_path + "/annotations",
                            None,
                            c.model_dump(
                                include={"body", "style", "context"}, exclude_none=True
                            ),
                        )
                    else:
                        raise ValueError(
                            f"Unsupported Buildkite operation: {operation}"
                        )
        result = await _request(token, method, path, params=params, body=body)
        return {"operation": operation, **result}

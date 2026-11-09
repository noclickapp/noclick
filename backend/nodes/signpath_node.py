"""SignPath v1: one published operation per workflow action.

Contract: https://app.signpath.io/Api/swagger/v1/swagger.json
Token setup: https://docs.signpath.io/users#api-tokens
Transport: https://docs.signpath.io/build-system-integration#rest-api
"""
from __future__ import annotations

import re
import base64
import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.signpath.io/Api/v1"


class SignpathAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Signpath API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.signpath.io/users#api-tokens",
            "x-credential-instructions": "In SignPath, open My profile and generate an API token, or use a CI user token. Paste the token without Bearer and the organization ID from the organization page. API calls use that user's permissions; approval and administration require the corresponding roles.",
        })
    credential_type: Literal["signpath_api_token"] = Field("signpath_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=5000,
        repr=False, json_schema_extra={"ui:widget": "password"})
    organization_id: UUID = Field(..., title="Organization ID", description="Copy the organization UUID from SignPath's organization page.")

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Project(_Config):
    project_slug: str = Field(..., title="Project Slug", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class _SigningRequest(_Config):
    signing_request_id: UUID = Field(..., title="Signing Request ID")


class _Certificate(_Config):
    certificate_slug: str = Field(..., title="Certificate Slug", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class _ProjectDetails(_Config):
    name: str = Field(..., min_length=1, max_length=100, title="Name")
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$", title="New Project Slug")
    description: str | None = Field(None, max_length=5000, title="Description")
    reader_ids: list[UUID] | None = Field(None, title="Reader IDs", description="Optional list of user/group UUIDs.")
    configurator_ids: list[UUID] | None = Field(None, title="Configurator IDs", description="Optional list of user/group UUIDs.")
    repository_urls: list[str] | None = Field(None, title="Repository URLs")


class GetCurrentUser(_Config):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class GetOrganization(_Config):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"ui:hidden": True})


class ListProjects(_Config):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class CreateProject(_ProjectDetails):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True})
    artifact_configuration_xml: str = Field(..., min_length=1, title="Artifact Configuration XML", json_schema_extra={"ui:widget": "textarea"})


class EditProject(_ProjectDetails, _Project):
    operation: Literal["edit_project"] = Field("edit_project", title="Edit Project", json_schema_extra={"ui:hidden": True})


class ActivateProject(_Project):
    operation: Literal["activate_project"] = Field("activate_project", title="Activate Project", json_schema_extra={"ui:hidden": True})


class DeactivateProject(_Project):
    operation: Literal["deactivate_project"] = Field("deactivate_project", title="Deactivate Project", json_schema_extra={"ui:hidden": True})


class GetSigningPolicy(_Project):
    operation: Literal["get_signing_policy"] = Field("get_signing_policy", title="Get Signing Policy", json_schema_extra={"ui:hidden": True})
    signing_policy_slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$", title="Signing Policy Slug")
    include_pipeline_policy_content: bool = Field(False, title="Include Pipeline Policy Content")


class ListSigningRequests(_Config):
    operation: Literal["list_signing_requests"] = Field("list_signing_requests", title="List Signing Requests", json_schema_extra={"ui:hidden": True})
    submitted_before: datetime | None = Field(None, title="Submitted Before")
    submitted_after: datetime | None = Field(None, title="Submitted After", description="Filter by submission time; the result preserves SignPath pagination metadata.")
    project_slug: str | None = Field(None, max_length=100, title="Project Slug")
    artifact_configuration_slug: str | None = Field(None, max_length=100, title="Artifact Configuration Slug")
    signing_policy_slug: str | None = Field(None, max_length=100, title="Signing Policy Slug")
    certificate_slug: str | None = Field(None, max_length=100, title="Certificate Slug")
    signing_request_status: list[Literal["WaitingForArtifactUpload", "InProgress", "WaitingForApproval", "Completed", "Failed", "Denied", "Canceled"]] | None = Field(None, title="Signing Request Statuses")


class GetSigningRequest(_SigningRequest):
    operation: Literal["get_signing_request"] = Field("get_signing_request", title="Get Signing Request", json_schema_extra={"ui:hidden": True})


class GetSigningRequestStatus(_SigningRequest):
    operation: Literal["get_signing_request_status"] = Field("get_signing_request_status", title="Get Signing Request Status", json_schema_extra={"ui:hidden": True})


class SignHash(_Project):
    operation: Literal["sign_hash"] = Field("sign_hash", title="Sign Hash (RSA)", json_schema_extra={"ui:hidden": True})
    signing_policy_slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$", title="Signing Policy Slug")
    hash_base64: str = Field(..., min_length=1, max_length=100, title="Base64 Hash", description="Base64-encoded digest for an RSA hash-signing project.", json_schema_extra={"format": "byte"})
    hash_algorithm: Literal["Sha1", "Sha256", "Sha384", "Sha512"] = Field("Sha256", title="Hash Algorithm")
    padding_mode: Literal["Pkcs1", "Pss"] = Field("Pkcs1", title="RSA Padding")
    artifact_configuration_slug: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9._-]+$", title="Artifact Configuration Slug")
    description: str | None = Field(None, max_length=5000, title="Description")

    @field_validator("hash_base64")
    @classmethod
    def hash_bytes(cls, value):
        try:
            base64.b64decode(value, validate=True)
        except ValueError:
            raise ValueError("Use a Base64-encoded digest") from None
        return value


class ResubmitSigningRequest(_Config):
    operation: Literal["resubmit_signing_request"] = Field("resubmit_signing_request", title="Resubmit Signing Request", json_schema_extra={"ui:hidden": True})
    original_signing_request_id: UUID = Field(..., title="Original Signing Request ID")
    signing_policy_slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$", title="Signing Policy Slug")
    description: str | None = Field(None, max_length=5000, title="Description")
    keep_snapshotted_artifact_configuration: bool | None = Field(None, title="Keep Snapshotted Artifact Configuration")
    cancellation_timeout_in_seconds: int | None = Field(None, ge=1, le=31536000, title="Cancellation Timeout in Seconds")


class ApproveSigningRequest(_SigningRequest):
    operation: Literal["approve_signing_request"] = Field("approve_signing_request", title="Approve Signing Request", json_schema_extra={"ui:hidden": True})


class DenySigningRequest(_SigningRequest):
    operation: Literal["deny_signing_request"] = Field("deny_signing_request", title="Deny Signing Request", json_schema_extra={"ui:hidden": True})
    deny_reason: str | None = Field(None, max_length=5000, title="Denial Reason")


class CancelSigningRequest(_SigningRequest):
    operation: Literal["cancel_signing_request"] = Field("cancel_signing_request", title="Cancel Signing Request", json_schema_extra={"ui:hidden": True})


class DownloadSignedArtifact(_SigningRequest):
    operation: Literal["download_signed_artifact"] = Field("download_signed_artifact", title="Download Signed Artifact", json_schema_extra={"ui:hidden": True})


class DownloadUnsignedArtifact(_SigningRequest):
    operation: Literal["download_unsigned_artifact"] = Field("download_unsigned_artifact", title="Download Unsigned Artifact", json_schema_extra={"ui:hidden": True})


class ListCertificates(_Config):
    operation: Literal["list_certificates"] = Field("list_certificates", title="List Certificates", json_schema_extra={"ui:hidden": True})


class GetCertificate(_Certificate):
    operation: Literal["get_certificate"] = Field("get_certificate", title="Get Certificate", json_schema_extra={"ui:hidden": True})


class ListCIUsers(_Config):
    operation: Literal["list_ci_users"] = Field("list_ci_users", title="List Ci Users", json_schema_extra={"ui:hidden": True})


class ListUserGroups(_Config):
    operation: Literal["list_user_groups"] = Field("list_user_groups", title="List User Groups", json_schema_extra={"ui:hidden": True})


class ListTrustedBuildSystems(_Config):
    operation: Literal["list_trusted_build_systems"] = Field("list_trusted_build_systems", title="List Trusted Build Systems", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[
    GetCurrentUser,
    GetOrganization,
    ListProjects,
    GetProject,
    CreateProject,
    EditProject,
    ActivateProject,
    DeactivateProject,
    GetSigningPolicy,
    ListSigningRequests,
    GetSigningRequest,
    GetSigningRequestStatus,
    SignHash,
    ResubmitSigningRequest,
    ApproveSigningRequest,
    DenySigningRequest,
    CancelSigningRequest,
    DownloadSignedArtifact,
    DownloadUnsignedArtifact,
    ListCertificates,
    GetCertificate,
    ListCIUsers,
    ListUserGroups,
    ListTrustedBuildSystems,
], Field(discriminator="operation")]


class SignpathNodeConfig(NodeConfig[Operation, SignpathAPITokenCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "Users/Me", 200),
    "get_organization": ("GET", "Organization", 200),
    "list_projects": ("GET", "Projects", 200),
    "get_project": ("GET", "Projects/{project_slug}", 200),
    "create_project": ("POST", "Projects", 201),
    "edit_project": ("POST", "Projects/{project_slug}/Edit", 204),
    "activate_project": ("POST", "Projects/{project_slug}/Activate", 204),
    "deactivate_project": ("POST", "Projects/{project_slug}/Deactivate", 204),
    "get_signing_policy": ("GET", "Projects/{project_slug}/SigningPolicies/{signing_policy_slug}", 200),
    "list_signing_requests": ("GET", "SigningRequests", 200),
    "get_signing_request": ("GET", "SigningRequests/{signing_request_id}", 200),
    "get_signing_request_status": ("GET", "SigningRequests/{signing_request_id}/Status", 200),
    "sign_hash": ("POST", "SigningRequests/SignHash", 201),
    "resubmit_signing_request": ("POST", "SigningRequests/Resubmit", 201),
    "approve_signing_request": ("POST", "SigningRequests/{signing_request_id}/Approve", 204),
    "deny_signing_request": ("POST", "SigningRequests/{signing_request_id}/Deny", 204),
    "cancel_signing_request": ("POST", "SigningRequests/{signing_request_id}/Cancel", 204),
    "download_signed_artifact": ("GET", "SigningRequests/{signing_request_id}/SignedArtifact", 200),
    "download_unsigned_artifact": ("GET", "SigningRequests/{signing_request_id}/UnsignedArtifact", 200),
    "list_certificates": ("GET", "Certificates", 200),
    "get_certificate": ("GET", "Certificates/{certificate_slug}", 200),
    "list_ci_users": ("GET", "CIUsers", 200),
    "list_user_groups": ("GET", "UserGroups", 200),
    "list_trusted_build_systems": ("GET", "TrustedBuildSystems", 200),
}


def _camel(name):
    first, *rest = name.split("_")
    return first + "".join(word.title() for word in rest)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class SignpathNode(WorkflowNode):
    integration_type = "automation-signpath"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects",
        identity_operation="get_current_user", label_keys=("name", "slug", "id"))
    edit_examples = ["Sign an RSA digest with this policy", "Wait for this signing request to complete", "Download the signed artifact"]

    @classmethod
    def get_config_model(cls):
        return SignpathNodeConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SignPath API token")
        config = self.config.config
        method, route, expected = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in re.findall(r"\{([^}]+)\}", route):
            route = route.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        values = {_camel(k): v for k, v in values.items()}
        kwargs = {}
        if method == "GET":
            # httpx encodes lists as repeated query keys, as OpenAPI form/explode requires.
            kwargs["params"] = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif config.operation == "sign_hash":
            digest = values.pop("hashBase64")
            algorithm = values.pop("hashAlgorithm")
            if len(base64.b64decode(digest, validate=True)) != {"Sha1": 20, "Sha256": 32, "Sha384": 48, "Sha512": 64}[algorithm]:
                raise ValueError("Digest length does not match the selected hash algorithm")
            values["hashSigningData"] = {"hash": digest, "signatureAlgorithm": "Rsa",
                "rsaOptions": {"hashAlgorithmName": algorithm, "paddingMode": values.pop("paddingMode")}}
            kwargs["json"] = values
        elif config.operation in {"create_project", "edit_project", "resubmit_signing_request", "deny_signing_request"}:
            kwargs["json"] = values
        download = config.operation.startswith("download_")
        headers = {"Authorization": "Bearer " + credential.api_token,
            "Accept": "application/octet-stream" if download else "application/json"}
        # Fixed host and organization boundary. Never follow provider-returned URLs,
        # retry a write, or forward bearer tokens through redirects.
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE_URL + "/" + str(credential.organization_id) + "/" + route,
                                     headers=headers, **kwargs) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > (50 * 1024 * 1024 if download else 10 * 1024 * 1024):
                        raise ValueError("SignPath response exceeds the workflow size limit; inspect a write before retrying")
                if response.status_code != expected:
                    detail = "SignPath returned an unexpected status"
                    try:
                        problem = json.loads(raw)
                        if isinstance(problem, dict):
                            detail = problem.get("detail") or problem.get("title") or detail
                    except ValueError:
                        pass
                    return {"status": "error", "http_status": response.status_code,
                        "error": _redact(str(detail), credential.api_token),
                        "write_outcome": "unverified" if method != "GET" else None}
                result = {"status": "success", "operation": config.operation, "http_status": response.status_code}
                if download:
                    result["file"] = BinaryOutput(bytes(raw), response.headers.get("content-type", "application/octet-stream"),
                        "signed-artifact" if config.operation == "download_signed_artifact" else "unsigned-artifact")
                elif raw.strip():
                    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if mime != "application/json" and not mime.endswith("+json"):
                        raise ValueError("SignPath returned a non-JSON response; inspect a write before retrying")
                    payload = json.loads(raw)
                    if not isinstance(payload, (dict, list)):
                        raise ValueError("SignPath returned an unexpected JSON shape")
                    if isinstance(payload, dict) and ("error" in payload or payload.get("status") in {"error", "failed"}):
                        raise ValueError("SignPath returned an error envelope")
                    result["data"] = _redact(payload, credential.api_token)
                elif method == "GET" or config.operation == "sign_hash":
                    raise ValueError("SignPath returned an empty JSON response")
                # Location is returned for creation/resubmission without another request.
                if response.headers.get("location"):
                    result["location"] = _redact(response.headers["location"], credential.api_token)
                return result

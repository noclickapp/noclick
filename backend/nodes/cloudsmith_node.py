"""Cloudsmith repository, artifact and distribution-token automation.

Each operation sends one request to the published Cloudsmith API. Asynchronous
mutation acknowledgements are returned without claiming background completion.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.cloudsmith.io"
CREDENTIAL_TYPE = "cloudsmith_api_key"


class CloudsmithApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cloudsmith API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.cloudsmith.com/accounts-and-teams/api-key",
            "x-credential-instructions": "Paste your Cloudsmith API key from your account settings. Your account needs the repository privileges for the operations you run. NoClick sends it in X-Api-Key to api.cloudsmith.io."})
    credential_type: Literal["cloudsmith_api_key"] = Field("cloudsmith_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number. Each execution reads one page.")
    page_size: int = Field(30, ge=1, le=100, title="Page Size")


class _Owner(_Input):
    owner: str = Field(..., title="Workspace", description="Cloudsmith workspace slug.", min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")


class _Repo(_Owner):
    repo: str = Field(..., title="Repository", description="Repository slug, without the workspace.", min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")


class _Resource(_Repo):
    identifier: str = Field(..., title="Resource Identifier", description="Package or entitlement slug / permanent identifier.", min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")


class _Search(_Page):
    query: str | None = Field(None, title="Search Query", max_length=1024)


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListRepositories(_Page):
    operation: Literal["list_repositories"] = Field("list_repositories", title="List Repositories", json_schema_extra={"ui:hidden": True})


class ListWorkspaceRepositories(_Owner, _Search):
    operation: Literal["list_workspace_repositories"] = Field("list_workspace_repositories", title="List Workspace Repositories", json_schema_extra={"ui:hidden": True})


class GetRepository(_Repo):
    operation: Literal["get_repository"] = Field("get_repository", title="Get Repository", json_schema_extra={"ui:hidden": True})


class CreateRepository(_Owner):
    operation: Literal["create_repository"] = Field("create_repository", title="Create Repository", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50, pattern=r"^\w[\w \-\'\.\/()]+$")
    description: str | None = Field(None, max_length=10000)
    slug: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")
    repository_type_str: Literal["Private", "Public", "Open-Source"] = Field("Private", title="Repository Visibility")


class UpdateRepository(_Repo):
    operation: Literal["update_repository"] = Field("update_repository", title="Update Repository", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=50, pattern=r"^\w[\w \-\'\.\/()]+$")
    description: str | None = Field(None, max_length=10000)


class DeleteRepository(_Repo):
    operation: Literal["delete_repository"] = Field("delete_repository", title="Delete Repository", json_schema_extra={"ui:hidden": True})


class ListPackages(_Repo, _Search):
    operation: Literal["list_packages"] = Field("list_packages", title="List Packages", json_schema_extra={"ui:hidden": True})


class GetPackage(_Resource):
    operation: Literal["get_package"] = Field("get_package", title="Get Package", json_schema_extra={"ui:hidden": True})


class DeletePackage(_Resource):
    operation: Literal["delete_package"] = Field("delete_package", title="Delete Package", json_schema_extra={"ui:hidden": True})


class CopyPackage(_Resource):
    operation: Literal["copy_package"] = Field("copy_package", title="Copy Package", json_schema_extra={"ui:hidden": True})
    destination: str = Field(..., title="Destination Repository", min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")
    republish: bool = Field(False, description="Overwrite matching destination packages when true.")


class MovePackage(_Resource):
    operation: Literal["move_package"] = Field("move_package", title="Move Package", json_schema_extra={"ui:hidden": True})
    destination: str = Field(..., title="Destination Repository", min_length=1, max_length=255, pattern=r"^[-a-zA-Z0-9_]+$")


class GetPackageStatus(_Resource):
    operation: Literal["get_package_status"] = Field("get_package_status", title="Get Package Status", json_schema_extra={"ui:hidden": True})


class ResyncPackage(_Resource):
    operation: Literal["resync_package"] = Field("resync_package", title="Resync Package", json_schema_extra={"ui:hidden": True})


class ScanPackage(_Resource):
    operation: Literal["scan_package"] = Field("scan_package", title="Scan Package", json_schema_extra={"ui:hidden": True})


class TagPackage(_Resource):
    operation: Literal["tag_package"] = Field("tag_package", title="Tag Package", json_schema_extra={"ui:hidden": True})
    action: Literal["Add", "Clear", "Replace", "Remove"] = "Add"
    tags: list[str] = Field(default_factory=list, max_length=100, json_schema_extra={"ui:widget": "list"})

    @field_validator("tags")
    @classmethod
    def tag_lengths(cls, value):
        if any(not 1 <= len(tag) <= 255 for tag in value):
            raise ValueError("Tags must contain 1 to 255 characters")
        return value


class QuarantinePackage(_Resource):
    operation: Literal["quarantine_package"] = Field("quarantine_package", title="Quarantine Package", json_schema_extra={"ui:hidden": True})
    release: bool = Field(False, description="False quarantines the package; true releases it from quarantine.")


class ListEntitlements(_Repo, _Search):
    operation: Literal["list_entitlements"] = Field("list_entitlements", title="List Entitlements", json_schema_extra={"ui:hidden": True})


class GetEntitlement(_Resource):
    operation: Literal["get_entitlement"] = Field("get_entitlement", title="Get Entitlement", json_schema_extra={"ui:hidden": True})


class EnableEntitlement(_Resource):
    operation: Literal["enable_entitlement"] = Field("enable_entitlement", title="Enable Entitlement", json_schema_extra={"ui:hidden": True})


class DisableEntitlement(_Resource):
    operation: Literal["disable_entitlement"] = Field("disable_entitlement", title="Disable Entitlement", json_schema_extra={"ui:hidden": True})


class DeleteEntitlement(_Resource):
    operation: Literal["delete_entitlement"] = Field("delete_entitlement", title="Delete Entitlement", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetCurrentUser, ListRepositories, ListWorkspaceRepositories, GetRepository, CreateRepository, UpdateRepository, DeleteRepository, ListPackages, GetPackage, DeletePackage, CopyPackage, MovePackage, GetPackageStatus, ResyncPackage, ScanPackage, TagPackage, QuarantinePackage, ListEntitlements, GetEntitlement, EnableEntitlement, DisableEntitlement, DeleteEntitlement], Field(discriminator="operation")]


class CloudsmithNodeConfig(NodeConfig[Operation, CloudsmithApiKeyCredential]):
    pass


ROUTES = {
    "get_current_user": ('GET', '/user/self/', ()),
    "list_repositories": ('GET', '/repos/', ('page', 'page_size')),
    "list_workspace_repositories": ('GET', '/repos/{owner}/', ('page', 'page_size', 'query')),
    "get_repository": ('GET', '/repos/{owner}/{repo}/', ()),
    "create_repository": ('POST', '/repos/{owner}/', ('name', 'description', 'slug', 'repository_type_str')),
    "update_repository": ('PATCH', '/repos/{owner}/{repo}/', ('name', 'description')),
    "delete_repository": ('DELETE', '/repos/{owner}/{repo}/', ()),
    "list_packages": ('GET', '/packages/{owner}/{repo}/', ('page', 'page_size', 'query')),
    "get_package": ('GET', '/packages/{owner}/{repo}/{identifier}/', ()),
    "delete_package": ('DELETE', '/packages/{owner}/{repo}/{identifier}/', ()),
    "copy_package": ('POST', '/packages/{owner}/{repo}/{identifier}/copy/', ('destination', 'republish')),
    "move_package": ('POST', '/packages/{owner}/{repo}/{identifier}/move/', ('destination',)),
    "get_package_status": ('GET', '/packages/{owner}/{repo}/{identifier}/status/', ()),
    "resync_package": ('POST', '/packages/{owner}/{repo}/{identifier}/resync/', ()),
    "scan_package": ('POST', '/packages/{owner}/{repo}/{identifier}/scan/', ()),
    "tag_package": ('POST', '/packages/{owner}/{repo}/{identifier}/tag/', ('action', 'tags')),
    "quarantine_package": ('POST', '/packages/{owner}/{repo}/{identifier}/quarantine/', ('release',)),
    "list_entitlements": ('GET', '/entitlements/{owner}/{repo}/', ('page', 'page_size', 'query')),
    "get_entitlement": ('GET', '/entitlements/{owner}/{repo}/{identifier}/', ()),
    "enable_entitlement": ('POST', '/entitlements/{owner}/{repo}/{identifier}/enable/', ()),
    "disable_entitlement": ('POST', '/entitlements/{owner}/{repo}/{identifier}/disable/', ()),
    "delete_entitlement": ('DELETE', '/entitlements/{owner}/{repo}/{identifier}/', ()),
}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()
                if k.lower() not in {"token", "api_key", "password", "secret"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class CloudsmithNode(WorkflowNode):
    integration_type = "automation-cloudsmith"
    connection_evidence = ConnectionEvidence(noun="Cloudsmith account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return CloudsmithNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Attach a Cloudsmith API key credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Cloudsmith API key")
        config = self.config.config
        credential = self.config.credentials
        method, template, fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        payload = {k: values[k] for k in fields if k in values}
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if fields else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection words for the connect seam, without secrets.
            message = "Cloudsmith request failed"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str):
                    message = _redact(detail, credential.api_key)[:1000]
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"Cloudsmith HTTP {response.status_code}: {message}")
        body = None
        if response.content:
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected a bounded Cloudsmith JSON response")
            body = response.json()
            if not isinstance(body, (dict, list)):
                raise ValueError("Unexpected Cloudsmith response shape")
        if config.operation.startswith("list_") and not isinstance(body, list):
            raise ValueError("Expected a Cloudsmith resource list")
        if method == "GET" and not config.operation.startswith("list_") and not isinstance(body, dict):
            raise ValueError("Expected a Cloudsmith resource object")
        if config.operation == "get_current_user":
            if not isinstance(body, dict) or body.get("authenticated") is not True:
                raise ValueError("Cloudsmith did not confirm an authenticated account")
        result = {"data": _redact(body, credential.api_key), "http_status": response.status_code}
        if method != "GET":
            result["accepted"] = True
            result["background_completion_verified"] = False
        if config.operation.startswith("list_"):
            result.update(page=config.page, page_size=config.page_size)
        return result
